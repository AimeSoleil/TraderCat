from datetime import date, timedelta
import traceback
import numpy as np
import pandas as pd
from openbb import obb
from tradercat.core.data.market_data_provider import MarketDataProvider
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)


class OpenBBProvider(MarketDataProvider):

    def __init__(self):
        super().__init__()
        self._chains_df_cache: dict[str, pd.DataFrame] = {}

    # ──────────────────────────────────────────────────────────────────────
    # Price Data
    # ──────────────────────────────────────────────────────────────────────

    def get_price_data(self, symbol: str, interval: str, lookback: int):
        df = obb.equity.price.historical(symbol=symbol, interval=interval, period=f"{lookback}d")
        return df.results

    def get_price_data_by_range(self, symbol: str, start_date: str, end_date: str, interval: str = '1d'):
        df = obb.equity.price.historical(symbol=symbol, start_date=start_date, end_date=end_date, interval=interval)
        return df.results

    def get_indicator(self, indicator: str, data: list, params: dict):
        func = getattr(obb.technical, indicator)
        try:
            return func(data=data, **params).results
        except Exception as e:
            logger.info(f"Error fetching indicator {indicator} with params {params}: {traceback.format_exc()}")
            return None

    # ──────────────────────────────────────────────────────────────────────
    # Options Chains — single API call, convert to DataFrame, cache
    # ──────────────────────────────────────────────────────────────────────

    def _get_chains_df(self, symbol: str) -> pd.DataFrame | None:
        """
        Fetch options chains and return as DataFrame (each row = one contract).
        Cached per symbol. Single API call.
        """
        if symbol in self._chains_df_cache:
            return self._chains_df_cache[symbol]

        try:
            result = obb.derivatives.options.chains(symbol=symbol)
            if not result or not result.results:
                logger.warning(f"No chains data for {symbol}")
                return None

            df = result.to_dataframe()
            if df is None or df.empty:
                logger.warning(f"Empty DataFrame for {symbol}")
                return None

            df = self._normalize_iv_format(df)
            self._chains_df_cache[symbol] = df
            logger.info(f"Chains DF for {symbol}: {len(df)} rows")
            return df

        except Exception as e:
            logger.error(f"Error fetching chains for {symbol}: {traceback.format_exc()}")
            return None

    @staticmethod
    def _normalize_iv_format(df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize IV to decimal format (0.265 = 26.5%).
        yfinance may return percentage (26.5), intrinio returns decimal.
        """
        if 'implied_volatility' not in df.columns:
            return df

        ivs = df['implied_volatility'].dropna()
        ivs = ivs[ivs > 0]
        if ivs.empty:
            return df

        if ivs.median() > 1.0:
            logger.info(f"IV normalization: median={ivs.median():.2f} > 1.0, dividing by 100")
            df['implied_volatility'] = df['implied_volatility'] / 100.0

        return df

    def _get_underlying_price(self, symbol: str) -> float | None:
        """Extract underlying price from chains DataFrame, fallback to quote API."""
        df = self._get_chains_df(symbol)
        if df is not None and 'underlying_price' in df.columns:
            prices = df['underlying_price'].dropna()
            prices = prices[prices > 0]
            if not prices.empty:
                return float(prices.iloc[0])

        try:
            price_data = obb.equity.price.quote(symbol=symbol)
            if price_data.results:
                r = price_data.results[0]
                return getattr(r, 'last_price', None) or getattr(r, 'prev_close', None)
        except Exception:
            pass
        return None

    def clear_cache(self):
        self._chains_df_cache.clear()

    # ──────────────────────────────────────────────────────────────────────
    # IV Surface — filter DataFrame for OTM contracts
    # ──────────────────────────────────────────────────────────────────────

    def get_iv_surface(self, symbol: str, dte_min: int = 7, dte_max: int = 365,
                       moneyness: float = 20) -> pd.DataFrame | None:
        """
        Build IV surface from chains DataFrame.
        Filters: OTM only, DTE range, moneyness %, OI > 0.
        Returns DataFrame with columns: expiration, strike, option_type, dte,
                                         implied_volatility, open_interest, volume
        """
        df = self._get_chains_df(symbol)
        if df is None or df.empty:
            return None

        underlying_price = self._get_underlying_price(symbol)
        if not underlying_price or underlying_price <= 0:
            return None

        today = date.today()
        work = df.copy()

        # Ensure DTE exists
        if 'dte' not in work.columns or work['dte'].isna().all():
            if 'expiration' in work.columns:
                work['dte'] = work['expiration'].apply(
                    lambda exp: (exp - today).days if isinstance(exp, date) else None
                )

        # Required columns
        for col in ['strike', 'option_type', 'implied_volatility', 'dte']:
            if col not in work.columns:
                logger.warning(f"Missing column '{col}' for {symbol}")
                return None

        # Filter valid rows
        work = work.dropna(subset=['strike', 'option_type', 'implied_volatility', 'dte'])
        work = work[work['implied_volatility'] > 0]
        work = work[(work['dte'] >= dte_min) & (work['dte'] <= dte_max)]

        if work.empty:
            return None

        # OTM selection
        opt_lower = work['option_type'].str.lower()
        work = work[
            ((opt_lower == 'call') & (work['strike'] > underlying_price)) |
            ((opt_lower == 'put') & (work['strike'] < underlying_price))
        ]

        if work.empty:
            return None

        # Moneyness filter
        work = work[((work['strike'] - underlying_price) / underlying_price * 100).abs() <= moneyness]

        if work.empty:
            return None

        # OI filter (relaxed if too few)
        if 'open_interest' in work.columns:
            with_oi = work[work['open_interest'] > 0]
            if len(with_oi) >= 5:
                work = with_oi

        keep_cols = ['expiration', 'strike', 'option_type', 'dte',
                     'implied_volatility', 'open_interest', 'volume']
        keep_cols = [c for c in keep_cols if c in work.columns]
        result = work[keep_cols].reset_index(drop=True)

        logger.info(
            f"{symbol} IV surface: {len(result)} OTM contracts, "
            f"DTE [{dte_min}-{dte_max}], moneyness ≤{moneyness}%, "
            f"underlying=${underlying_price:.2f}"
        )
        return result

    # ──────────────────────────────────────────────────────────────────────
    # IV30: Interpolated 30-day Constant-Maturity IV
    # ──────────────────────────────────────────────────────────────────────

    def get_iv30(self, symbol: str) -> dict | None:
        """
        Calculate IV30 — 30-day constant-maturity IV via linear interpolation.

        1. Get OTM surface (DTE 7-90)
        2. Group by DTE, compute OI-weighted IV per expiration
        3. Interpolate between bracketing expirations around DTE=30
        """
        try:
            surface = self.get_iv_surface(symbol, dte_min=7, dte_max=90, moneyness=10)
            if surface is None or surface.empty:
                surface = self.get_iv_surface(symbol, dte_min=7, dte_max=120, moneyness=20)
            if surface is None or surface.empty:
                return None

            underlying_price = self._get_underlying_price(symbol)

            # OI-weighted IV per DTE
            exp_ivs = self._oi_weighted_iv_by_dte(surface)
            if not exp_ivs:
                return None

            total_contracts = sum(n for _, _, n in exp_ivs)
            target_dte = 30

            near = [(d, iv, n) for d, iv, n in exp_ivs if d <= target_dte]
            nxt = [(d, iv, n) for d, iv, n in exp_ivs if d > target_dte]

            if near and nxt:
                near_dte, near_iv, _ = max(near, key=lambda x: x[0])
                next_dte, next_iv, _ = min(nxt, key=lambda x: x[0])
                span = next_dte - near_dte
                iv30 = near_iv + (target_dte - near_dte) / span * (next_iv - near_iv) if span > 0 else (near_iv + next_iv) / 2
                interpolation = "linear"
            else:
                closest_dte, closest_iv, _ = min(exp_ivs, key=lambda x: abs(x[0] - target_dte))
                iv30 = closest_iv
                near_dte = closest_dte if closest_dte <= target_dte else None
                near_iv = closest_iv if near_dte else None
                next_dte = closest_dte if closest_dte > target_dte else None
                next_iv = closest_iv if next_dte else None
                interpolation = "single_exp"

            logger.info(f"{symbol} IV30={iv30:.4f} ({interpolation})")

            return {
                "iv30": round(iv30, 6),
                "underlying_price": underlying_price,
                "near_dte": near_dte if interpolation == "linear" else (near_dte),
                "near_iv": round(near_iv, 6) if near_iv else None,
                "next_dte": next_dte if interpolation == "linear" else (next_dte),
                "next_iv": round(next_iv, 6) if next_iv else None,
                "interpolation": interpolation,
                "contracts_sampled": total_contracts,
            }

        except Exception as e:
            logger.error(f"Error computing IV30 for {symbol}: {traceback.format_exc()}")
            return None

    def get_current_iv(self, symbol: str) -> dict | None:
        """
        Current ATM IV: OI-weighted OTM IV from expiration closest to 30 DTE.
        """
        try:
            surface = self.get_iv_surface(symbol, dte_min=20, dte_max=60, moneyness=10)
            if surface is None or surface.empty:
                surface = self.get_iv_surface(symbol, dte_min=7, dte_max=90, moneyness=20)
            if surface is None or surface.empty:
                return None

            underlying_price = self._get_underlying_price(symbol)

            # Find DTE closest to 30
            best_dte = int(surface['dte'].map(lambda d: abs(d - 30)).idxmin())
            best_dte_val = int(surface.loc[best_dte, 'dte'])
            nearest = surface[surface['dte'] == best_dte_val]

            ivs = nearest['implied_volatility'].values
            ois = nearest['open_interest'].fillna(0).values if 'open_interest' in nearest.columns else np.zeros(len(nearest))
            total_oi = ois.sum()

            current_iv = float(np.average(ivs, weights=ois)) if total_oi > 0 else float(np.mean(ivs))

            logger.info(f"{symbol} Current IV: {current_iv:.4f} | DTE={best_dte_val} | {len(nearest)} contracts")

            return {
                "current_iv": round(current_iv, 6),
                "underlying_price": underlying_price,
                "contracts_sampled": len(nearest),
                "dte_used": best_dte_val,
                "total_oi_sampled": float(total_oi),
                "weighting": "open_interest" if total_oi > 0 else "equal",
            }

        except Exception as e:
            logger.error(f"Error getting current IV for {symbol}: {traceback.format_exc()}")
            return None

    def get_iv_term_structure(self, symbol: str) -> list[tuple[int, float]] | None:
        """
        IV term structure: OI-weighted IV at each DTE.
        Returns [(dte, avg_iv), ...] sorted ascending.
        """
        try:
            surface = self.get_iv_surface(symbol, dte_min=7, dte_max=365, moneyness=20)
            if surface is None or surface.empty:
                return None

            exp_ivs = self._oi_weighted_iv_by_dte(surface)
            if not exp_ivs:
                return None

            term = [(dte, round(iv, 6)) for dte, iv, _ in exp_ivs]

            logger.info(
                f"{symbol} Term structure: {len(term)} expirations, "
                f"DTE {term[0][0]}-{term[-1][0]}, "
                f"IV {min(iv for _, iv in term):.4f}-{max(iv for _, iv in term):.4f}"
            )
            return term

        except Exception as e:
            logger.error(f"Error getting IV term structure for {symbol}: {traceback.format_exc()}")
            return None

    @staticmethod
    def _oi_weighted_iv_by_dte(surface: pd.DataFrame) -> list[tuple[int, float, int]]:
        """
        Group surface DataFrame by DTE, compute OI-weighted avg IV per group.
        Returns [(dte, weighted_iv, num_contracts), ...] sorted by DTE.
        """
        has_oi = 'open_interest' in surface.columns
        result = []

        for dte_val, group in surface.groupby('dte'):
            ivs = group['implied_volatility'].values
            if has_oi:
                ois = group['open_interest'].fillna(0).values
                total_oi = ois.sum()
                avg_iv = float(np.average(ivs, weights=ois)) if total_oi > 0 else float(np.mean(ivs))
            else:
                avg_iv = float(np.mean(ivs))
            result.append((int(dte_val), avg_iv, len(group)))

        return sorted(result, key=lambda x: x[0])

    # ──────────────────────────────────────────────────────────────────────
    # Historical IV: RV Calibration
    # ──────────────────────────────────────────────────────────────────────

    def get_historical_iv(self, symbol: str, lookback_days: int = 252) -> list[float] | None:
        """
        Build historical IV series:
        1. Term structure from surface (10-20 points)
        2. RV calibration for dense series (~220 points)
        """
        try:
            iv_from_term = []

            term_structure = self.get_iv_term_structure(symbol)
            if term_structure and len(term_structure) >= 3:
                iv_from_term = [iv for _, iv in sorted(term_structure, key=lambda x: -x[0])]

            rv_series = self._compute_rv_series(symbol, lookback_days)

            if rv_series and len(rv_series) >= 30:
                current_iv_data = self.get_current_iv(symbol)
                current_iv = current_iv_data["current_iv"] if current_iv_data else None
                current_rv = rv_series[-1]

                if current_iv and current_rv and current_rv > 0:
                    ratio = max(0.5, min(3.0, current_iv / current_rv))
                    calibrated = [rv * ratio for rv in rv_series]
                    logger.info(f"{symbol} RV→IV calibration: ratio={ratio:.2f}, {len(calibrated)} points")
                    return calibrated
                return rv_series

            return iv_from_term if iv_from_term else None

        except Exception as e:
            logger.error(f"Error getting historical IV for {symbol}: {traceback.format_exc()}")
            return None

    def _compute_rv_series(self, symbol: str, lookback_days: int) -> list[float] | None:
        """Rolling 30-day realized volatility (annualized) from equity prices."""
        try:
            hist_data = obb.equity.price.historical(
                symbol=symbol,
                start_date=(date.today() - timedelta(days=lookback_days + 60)).isoformat(),
                end_date=date.today().isoformat(),
                interval="1d"
            )
            if not hist_data.results:
                return None

            closes = [p.close for p in hist_data.results if p.close is not None]
            if len(closes) < 60:
                return None

            log_returns = np.diff(np.log(np.array(closes, dtype=float)))

            window = 30
            rv_series = [
                float(np.std(log_returns[i - window:i], ddof=1) * np.sqrt(252))
                for i in range(window, len(log_returns) + 1)
            ]
            return rv_series if rv_series else None

        except Exception as e:
            logger.error(f"RV computation failed for {symbol}: {e}")
            return None

    # ──────────────────────────────────────────────────────────────────────
    # IV Metrics: IV30, IV Rank, IV Percentile, IV Regime
    # ──────────────────────────────────────────────────────────────────────

    def calculate_iv_metrics(self, symbol: str) -> dict | None:
        """Calculate comprehensive IV metrics."""
        try:
            iv30_data = self.get_iv30(symbol)
            iv30 = iv30_data["iv30"] if iv30_data else None

            current_iv_data = self.get_current_iv(symbol)
            if not current_iv_data and not iv30_data:
                return {
                    "symbol": symbol, "current_iv": None, "iv30": None,
                    "underlying_price": None,
                    "iv30_rank": None, "iv_rank": None, "iv_percentile": None,
                    "iv_regime": "UNAVAILABLE",
                    "recommended_structure": "debit_spread",
                    "data_quality": "UNAVAILABLE",
                }

            current_iv = current_iv_data["current_iv"] if current_iv_data else iv30
            underlying_price = (current_iv_data or iv30_data or {}).get("underlying_price")

            iv_series = self.get_historical_iv(symbol, lookback_days=365)

            if not iv_series or len(iv_series) < 5:
                primary_iv = iv30 or current_iv
                regime = self._classify_iv_regime_from_level(primary_iv)
                return {
                    "symbol": symbol,
                    "current_iv": round(current_iv, 4) if current_iv else None,
                    "iv30": round(iv30, 4) if iv30 is not None else None,
                    "underlying_price": underlying_price,
                    "iv_high_52w": None, "iv_low_52w": None,
                    "iv30_rank": None, "iv_rank": None, "iv_percentile": None,
                    "iv_regime": regime,
                    "recommended_structure": self._regime_to_structure(regime),
                    "data_quality": "CURRENT_ONLY",
                    "contracts_sampled": (current_iv_data or {}).get("contracts_sampled"),
                }

            iv_high, iv_low = max(iv_series), min(iv_series)
            iv_range = iv_high - iv_low

            iv_rank = max(0, min(100, ((current_iv - iv_low) / iv_range * 100) if iv_range > 0 else 50))
            iv30_rank = max(0, min(100, ((iv30 - iv_low) / iv_range * 100))) if iv30 is not None and iv_range > 0 else None

            ref_iv = iv30 if iv30 is not None else current_iv
            iv_percentile = sum(1 for iv in iv_series if iv < ref_iv) / len(iv_series) * 100

            rank_for_regime = iv30_rank if iv30_rank is not None else iv_rank
            iv_regime = self._classify_iv_regime(rank_for_regime, iv_percentile)

            result = {
                "symbol": symbol,
                "current_iv": round(current_iv, 4),
                "iv30": round(iv30, 4) if iv30 is not None else None,
                "underlying_price": underlying_price,
                "iv_high_52w": round(iv_high, 4),
                "iv_low_52w": round(iv_low, 4),
                "iv30_rank": round(iv30_rank, 1) if iv30_rank is not None else None,
                "iv_rank": round(iv_rank, 1),
                "iv_percentile": round(iv_percentile, 1),
                "iv_regime": iv_regime,
                "recommended_structure": self._regime_to_structure(iv_regime),
                "data_quality": "CALIBRATED" if len(iv_series) >= 30 else "TERM_STRUCTURE",
                "contracts_sampled": (current_iv_data or {}).get("contracts_sampled"),
                "historical_iv_points": len(iv_series),
                "iv30_interpolation": (iv30_data or {}).get("interpolation"),
            }

            logger.info(
                f"{symbol} IV Metrics: IV={current_iv:.1%} | IV30={iv30:.1%} | "
                f"IV30Rank={iv30_rank:.1f} | IVRank={iv_rank:.1f} | "
                f"Pctl={iv_percentile:.1f} | Regime={iv_regime}"
            )
            return result

        except Exception as e:
            logger.error(f"Error calculating IV metrics for {symbol}: {traceback.format_exc()}")
            return None

    # ──────────────────────────────────────────────────────────────────────
    # IV Classification Helpers
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _classify_iv_regime(iv_rank: float, iv_percentile: float) -> str:
        composite = iv_rank * 0.6 + iv_percentile * 0.4
        if composite >= 80: return "EXTREME"
        if composite >= 55: return "HIGH"
        if composite >= 30: return "NORMAL"
        return "LOW"

    @staticmethod
    def _classify_iv_regime_from_level(current_iv: float) -> str:
        if current_iv >= 0.60: return "EXTREME"
        if current_iv >= 0.40: return "HIGH"
        if current_iv >= 0.20: return "NORMAL"
        return "LOW"

    @staticmethod
    def _regime_to_structure(regime: str) -> str:
        return {"EXTREME": "credit_spread", "HIGH": "credit_spread",
                "NORMAL": "debit_spread", "LOW": "long_option",
                "UNAVAILABLE": "debit_spread"}.get(regime, "debit_spread")

    # ──────────────────────────────────────────────────────────────────────
    # Combined Metadata 
    # ──────────────────────────────────────────────────────────────────────

    def get_option_metadata(self, symbol: str) -> dict | None:
        """
        Notes: as tested, the options IV data from yfinance is not correct, better to use other data source.
        """
        try:
            return self.calculate_iv_metrics(symbol)
        except Exception as e:
            logger.error(f"Error getting metadata for {symbol}: {traceback.format_exc()}")
            return None


if __name__ == "__main__":
    provider = OpenBBProvider()

    print("=" * 70)
    print("AAPL — Chains DataFrame")
    print("=" * 70)
    df = provider._get_chains_df("AAPL")
    if df is not None:
        up = provider._get_underlying_price("AAPL")
        print(f"  Underlying: {up}")
        print(f"  Shape: {df.shape}")
        print(f"  Columns: {list(df.columns)}")

        if up and 'strike' in df.columns:
            df_view = df.copy()
            df_view['atm_dist'] = (df_view['strike'] - up).abs()
            cols = [c for c in ['strike', 'option_type', 'expiration', 'dte',
                                'implied_volatility', 'open_interest', 'volume', 'bid', 'ask']
                    if c in df_view.columns]
            print(df_view.sort_values('atm_dist')[cols].head(20).to_string(index=False))

        if 'implied_volatility' in df.columns:
            ivs = df['implied_volatility'].dropna()
            ivs = ivs[ivs > 0]
            if not ivs.empty:
                print(f"\n  IV: min={ivs.min():.4f} max={ivs.max():.4f} "
                    f"mean={ivs.mean():.4f} median={ivs.median():.4f}")

    print("\n" + "=" * 70)
    print("AAPL — IV Surface (DTE 20-60, moneyness 10%)")
    print("=" * 70)
    surface = provider.get_iv_surface("AAPL", dte_min=20, dte_max=60, moneyness=10)
    if surface is not None:
        print(f"  {len(surface)} OTM contracts")
        print(surface.head(10).to_string(index=False))

    print("\n" + "=" * 70)
    print("AAPL — Full IV Metrics")
    print("=" * 70)
    provider.clear_cache()
    metrics = provider.calculate_iv_metrics("AAPL")
    if metrics:
        for k, v in metrics.items():
            print(f"  {k:>25s}: {v}")

