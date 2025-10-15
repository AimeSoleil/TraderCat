from typing import List, Optional, Dict, Any, Tuple
import math

from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

DEFAULT_WEIGHTS = {
    "fib": 0.50,  # Fibonacci level reaction / breakout (primary)
    "atr": 0.14,  # volatility filter / expansion
    "rsi": 0.10,  # momentum / avoid extremes
    "volume": 0.12,  # volume z-score confirmation
    "vwap": 0.04,  # price vs VWAP soft confirmation
    "obv": 0.04,  # OBV trend confirmation
    "macd": 0.06,  # optional momentum confirmation
}

EPS = 1e-6

class FibonacciStrategy(TradingStrategy):
    """
    Fibonacci-based weekly-option strategy (robust).

    Highlights:
    - Uses automatic swing identification (recent high/low) to generate Fibonacci retracement
    and extension levels. Signals derived from price behavior around those levels.
    - Completed-bar based decisions (no lookahead): uses completed_idx = -2 for confirmations.
    - Robust volume z-score computation with MAD fallback.
    - ATR percentile filtering to avoid low-volatility noise.
    - VWAP/OBV soft confirmations where available from provider.
    - All provider attribute access uses single-attribute _safe_get; _safe_get built on top.
    - Presets included via make_fib_weekly_presets().
    """

    def __init__(
        self,
        data_provider,
        swing_lookback: int = 30,
        fib_levels: Optional[List[float]] = None,
        rsi_period: int = 7,
        atr_period: int = 14,
        volume_window: int = 30,
        volume_zscore_threshold: float = 1.8,
        atr_percentile_filter: float = 0.4,
        atr_percentile_window: int = 60,
        confirmation_threshold: float = 0.58,
        weights: Optional[Dict[str, float]] = None,
        macd_params: Optional[Dict[str, int]] = None,
        min_swing_range_pct: float = 0.02,
    ):
        self.provider = data_provider

        # Swing and Fibonacci params
        self.swing_lookback = int(max(5, swing_lookback))
        self.fib_levels = fib_levels or [
            0.236,
            0.382,
            0.5,
            0.618,
            1.0,
            1.272,
            1.618,
            2.0,
        ]
        self.min_swing_range_pct = float(min_swing_range_pct)

        # Other indicators
        self.rsi_period = int(rsi_period)
        self.atr_period = int(atr_period)
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}

        # Volume / ATR filters
        self.volume_window = int(max(5, volume_window))
        self.volume_zscore_threshold = float(volume_zscore_threshold)
        self.atr_percentile_filter = float(atr_percentile_filter)
        self.atr_percentile_window = int(max(20, atr_percentile_window))

        # Scoring threshold and weights
        self.confirmation_threshold = float(confirmation_threshold)
        merged = DEFAULT_WEIGHTS.copy()
        if weights:
            merged.update(weights)
        self.weights = self._normalize_weights(merged)

    # -------------------------
    # Helpers (safe access & stats)
    # -------------------------
    def _normalize_weights(self, w: Dict[str, float]) -> Dict[str, float]:
        total = sum(float(v) for v in w.values()) or 1.0
        return {k: float(v) / total for k, v in w.items()}

    def _safe_get(self, series, idx: int, attr: str, default=None):
        """
        Single-attribute safe getter only (per requirement).
        Returns getattr(series[idx], attr, default) or default on error.
        """
        try:
            node = series[idx]
        except Exception:
            return default
        return getattr(node, attr, default)

    def _volume_zscore(
        self, recent_volumes: List[float], latest_volume: float
    ) -> float:
        if not recent_volumes:
            return 0.0
        n = len(recent_volumes)
        mean = sum(recent_volumes) / n
        var = sum((v - mean) ** 2 for v in recent_volumes) / n
        std = math.sqrt(var)
        if std < 1e-9:
            # MAD-based robust estimate fallback
            sorted_vals = sorted(recent_volumes)
            med = sorted_vals[n // 2]
            mad = sum(abs(v - med) for v in recent_volumes) / n
            robust_std = max(mad * 1.4826, 1e-9)
            return (latest_volume - med) / robust_std
        return (latest_volume - mean) / std

    def _build_atr_list(self, atr_series, lookback_bars: int) -> List[float]:
        available = len(atr_series) if atr_series else 0
        take = min(available, lookback_bars)
        hist: List[float] = []
        for i in range(1, take + 1):
            val = self._safe_get(atr_series, -i, f"ATRr_{self.atr_period}", None)
            if val is None:
                val = self._safe_get(atr_series, -i, "value", None)
            hist.append(float(val or 0.0))
        return hist

    def _percentile(self, data: List[float], q: float) -> float:
        if not data:
            return 0.0
        s = sorted(data)
        idx = (len(s) - 1) * max(0.0, min(1.0, q))
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return s[lo]
        frac = idx - lo
        return s[lo] * (1 - frac) + s[hi] * frac

    # -------------------------
    # Swing detection & Fib computation
    # -------------------------
    def _find_recent_swing(self, candles: list) -> Optional[Tuple[float, float]]:
        """
        Automatic simple swing high/low finder in the last swing_lookback bars.
        Returns (swing_low, swing_high) where swing_low < swing_high.
        Returns None if swing is too small or insufficient data.
        Approach: use min and max over lookback window excluding last forming bar.
        """
        if not candles or len(candles) < self.swing_lookback + 2:
            return None
        # Use completed bars (exclude latest forming bar)
        window = candles[-(self.swing_lookback + 1) : -1]
        lows = [self._safe_get(window, i, "low", None) for i in range(len(window))]
        highs = [self._safe_get(window, i, "high", None) for i in range(len(window))]
        lows = [v for v in lows if v is not None]
        highs = [v for v in highs if v is not None]
        if not lows or not highs:
            return None
        swing_low = min(lows)
        swing_high = max(highs)
        if swing_high <= swing_low:
            return None
        # require minimum swing range relative to price to avoid trivial swings
        if (swing_high - swing_low) / max(
            abs(swing_low), 1.0
        ) < self.min_swing_range_pct:
            return None
        return (swing_low, swing_high)

    def _fib_levels_from_swing(self, low: float, high: float) -> Dict[float, float]:
        """
        Return mapping level->price for configured fib_levels.
        For retracements: price = high - level*(high - low) for levels <= 1.0
        For extensions (level > 1.0): price = high + (level - 1)*(high - low) when trend up,
        and symmetric for down-trend.
        We'll return both retracements and extensions using the interpretation that
        base swing is low->high (up swing).
        """
        span = high - low
        mapping: Dict[float, float] = {}
        for lvl in self.fib_levels:
            price = high - lvl * span
            mapping[round(lvl, 6)] = price
        return mapping

    # -------------------------
    # Public API
    # -------------------------
    def get_name(self) -> str:
        return "Fibonacci Weekly (fib primary)"

    def get_lookback_window(self) -> int:
        core = max(
            self.swing_lookback,
            self.atr_period,
            self.rsi_period,
            self.volume_window,
            self.atr_percentile_window,
        )
        return max(120, core + 20)

    # -------------------------
    # Main signal generation
    # -------------------------
    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        current_date = candles[-1].date if candles else None

        # Data sufficiency
        if not self.provider or len(candles) < self.get_lookback_window() + 1:
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="Insufficient data",
                details={},
            )

        # Indicators from provider
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        try:
            macd = self.provider.get_indicator("macd", candles, self.macd_params)
        except Exception:
            macd = None
        try:
            vwap = self.provider.get_indicator("vwap", candles, {})
        except Exception:
            vwap = None
        try:
            obv = self.provider.get_indicator("obv", candles, {})
        except Exception:
            obv = None

        # basic checks
        if not all([rsi, atr]) or len(rsi) < 3 or len(atr) < 3:
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="Indicator data unavailable",
                details={},
            )

        # Identify swing and compute fib levels
        swing = self._find_recent_swing(candles)
        if not swing:
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="No valid swing found",
                details={},
            )
        swing_low, swing_high = swing
        fib_map = self._fib_levels_from_swing(
            swing_low, swing_high
        )  # mapping level->price

        # completed bar indices
        completed_idx = -2
        prior_idx = -3

        completed_close = self._safe_get(candles, completed_idx, "close", None)
        latest_close = self._safe_get(candles, -1, "close", None)
        latest_volume = self._safe_get(candles, -1, "volume", 0.0)

        # ATR history and current
        atr_hist = self._build_atr_list(atr, lookback_bars=self.atr_percentile_window)
        cur_atr = self._safe_get(atr, completed_idx, f"ATRr_{self.atr_period}", None)
        if cur_atr is None:
            cur_atr = self._safe_get(atr, completed_idx, "value", None)
        atr_percentile_value = (
            self._percentile(atr_hist, self.atr_percentile_filter) if atr_hist else 0.0
        )
        atr_vol_ok = (
            cur_atr is not None and atr_hist and cur_atr > atr_percentile_value + EPS
        )

        # RSI (completed)
        curr_rsi = self._safe_get(
            rsi, completed_idx, f"close_RSI_{self.rsi_period}", None
        ) or self._safe_get(rsi, completed_idx, "value", None)

        # Volume spike (completed vols)
        completed_vols = [
            self._safe_get(candles, -i, "volume", 0.0)
            for i in range(2, self.volume_window + 2)
        ]
        completed_vols = [v for v in completed_vols if v is not None]
        vol_z = self._volume_zscore(completed_vols, latest_volume or 0.0)
        vol_spike = vol_z > self.volume_zscore_threshold

        # MACD confirmations (optional)
        macd_confirm_up = macd_confirm_down = False
        if macd and len(macd) >= 3:
            name_val = f'close_MACD_{self.macd_params["fast"]}_{self.macd_params["slow"]}_{self.macd_params["signal"]}'
            name_sig = f'close_MACDs_{self.macd_params["fast"]}_{self.macd_params["slow"]}_{self.macd_params["signal"]}'
            mv_prev = self._safe_get(
                macd, completed_idx, name_val, None
            )
            ms_prev = self._safe_get(
                macd, completed_idx, name_sig, None
            )
            mv_prior = self._safe_get(
                macd, prior_idx, name_val, None
            )
            ms_prior = self._safe_get(
                macd, prior_idx, name_val, None
            )
            if None not in (mv_prior, ms_prior, mv_prev, ms_prev):
                macd_confirm_up = (mv_prior <= ms_prior + EPS) and (
                    mv_prev > ms_prev + EPS
                )
                macd_confirm_down = (mv_prior >= ms_prior - EPS) and (
                    mv_prev < ms_prev - EPS
                )

        # VWAP / OBV (soft)
        vwap_price = None
        if vwap:
            vwap_price = self._safe_get(
                vwap, completed_idx, "VWAP_D", None
            )
        obv_trend_up = obv_trend_down = None
        if obv and len(obv) >= 3:
            obv_curr = self._safe_get(obv, completed_idx, "OBV", None)
            obv_prev = self._safe_get(obv, prior_idx, "OBV", None)
            if obv_curr is not None and obv_prev is not None:
                obv_trend_up = obv_curr > obv_prev + EPS
                obv_trend_down = obv_curr < obv_prev - EPS

        # Build scorer
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)

        # Determine nearest fib levels around current price
        # We consider retracements 0.236-0.618 as support/resistance zones and extensions >1 as targets/breakouts
        # Find nearest retracement level price above and below completed_close
        levels_sorted = sorted(
            fib_map.items(), key=lambda x: x[0]
        )  # list of (level, price) ascending by level
        # prepare a list of (level, price) values
        level_prices = [(lvl, price) for lvl, price in levels_sorted]

        # Helper to find closest level above/below
        def _nearest_levels(price: float, level_prices_list: List[Tuple[float, float]]):
            above = None
            below = None
            for lvl, p in level_prices_list:
                if price is None:
                    break
                if p >= price:
                    if above is None:
                        above = (lvl, p)
                if p <= price:
                    below = (lvl, p)
            return below, above

        below_lvl, above_lvl = _nearest_levels(completed_close, level_prices)

        # Signal logic
        signal = "hold"
        confidence = 0.0
        reasons: List[str] = []

        # Candidate: bounce off retracement (support) -> bullish
        if below_lvl and below_lvl[0] in (0.236, 0.382, 0.5, 0.618):
            lvl, lvl_price = below_lvl
            # price near level within a small tolerance (e.g., 0.3% of price) and candle action (completed_close > level_price)
            tol = max(abs(lvl_price) * 0.003, 1e-6)
            bounced = (
                completed_close is not None
                and completed_close >= lvl_price - tol
                and completed_close <= lvl_price + tol
            )
            # confirm bounce with volume or RSI or ATR
            if bounced:
                scorer.add(
                    True,
                    f"Price at fib retrace {lvl}",
                    weight=self.weights.get("fib", 0.0),
                )
                scorer.add(
                    atr_vol_ok,
                    "ATR above percentile",
                    weight=self.weights.get("atr", 0.0),
                )
                scorer.add(
                    curr_rsi is not None and curr_rsi > 50 + EPS,
                    "RSI > 50",
                    weight=self.weights.get("rsi", 0.0),
                )
                scorer.add(
                    vol_spike, "Volume spike", weight=self.weights.get("volume", 0.0)
                )
                scorer.add(
                    macd_confirm_up,
                    "MACD confirms",
                    weight=self.weights.get("macd", 0.0),
                )
                if vwap_price is not None:
                    scorer.add(
                        (completed_close or 0.0) >= vwap_price - EPS,
                        "Price >= VWAP",
                        weight=self.weights.get("vwap", 0.0),
                    )
                if obv_trend_up is not None:
                    scorer.add(
                        obv_trend_up,
                        "OBV trending up",
                        weight=self.weights.get("obv", 0.0),
                    )
                signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Candidate: rejection at retracement or extension (resistance) -> bearish
        if signal == "hold" and above_lvl and above_lvl[0] in (0.382, 0.5, 0.618, 1.0):
            lvl, lvl_price = above_lvl
            tol = max(abs(lvl_price) * 0.003, 1e-6)
            rejected = (
                completed_close is not None
                and completed_close <= lvl_price + tol
                and completed_close >= lvl_price - tol
            )
            if rejected:
                scorer.add(
                    True,
                    f"Price at fib resistance {lvl}",
                    weight=self.weights.get("fib", 0.0),
                )
                scorer.add(
                    atr_vol_ok,
                    "ATR above percentile",
                    weight=self.weights.get("atr", 0.0),
                )
                scorer.add(
                    curr_rsi is not None and curr_rsi < 50 - EPS,
                    "RSI < 50",
                    weight=self.weights.get("rsi", 0.0),
                )
                scorer.add(
                    vol_spike, "Volume spike", weight=self.weights.get("volume", 0.0)
                )
                scorer.add(
                    macd_confirm_down,
                    "MACD confirms",
                    weight=self.weights.get("macd", 0.0),
                )
                if vwap_price is not None:
                    scorer.add(
                        (completed_close or 0.0) <= vwap_price + EPS,
                        "Price <= VWAP",
                        weight=self.weights.get("vwap", 0.0),
                    )
                if obv_trend_down is not None:
                    scorer.add(
                        obv_trend_down,
                        "OBV trending down",
                        weight=self.weights.get("obv", 0.0),
                    )
                s, c, r = scorer.evaluate(direction="bearish")
                # prioritize bearish if score suffices
                if s == "bearish":
                    signal, confidence, reasons = s, c, r

        # Candidate: extension breakout (trend continuation) -> bullish if price breaks extension >1 and volume/ATR support
        if signal == "hold":
            # check extensions (levels > 1.0)
            extensions = [(lvl, price) for lvl, price in level_prices if lvl > 1.0]
            for lvl, price in extensions:
                if completed_close is not None and completed_close > price + max(
                    abs(price) * 0.002, 1e-6
                ):
                    # breakout beyond extension
                    scorer.add(
                        True,
                        f"Fib extension breakout {lvl}",
                        weight=self.weights.get("fib", 0.0),
                    )
                    scorer.add(
                        atr_vol_ok,
                        "ATR above percentile",
                        weight=self.weights.get("atr", 0.0),
                    )
                    scorer.add(
                        curr_rsi is not None and curr_rsi > 50 + EPS,
                        "RSI > 50",
                        weight=self.weights.get("rsi", 0.0),
                    )
                    scorer.add(
                        vol_spike,
                        "Volume spike",
                        weight=self.weights.get("volume", 0.0),
                    )
                    scorer.add(
                        macd_confirm_up,
                        "MACD confirms",
                        weight=self.weights.get("macd", 0.0),
                    )
                    if vwap_price is not None:
                        scorer.add(
                            (completed_close or 0.0) >= vwap_price - EPS,
                            "Price >= VWAP",
                            weight=self.weights.get("vwap", 0.0),
                        )
                    if obv_trend_up is not None:
                        scorer.add(
                            obv_trend_up,
                            "OBV trending up",
                            weight=self.weights.get("obv", 0.0),
                        )
                    s, c, r = scorer.evaluate(direction="bullish")
                    if s == "bullish":
                        signal, confidence, reasons = s, c, r
                        break

        # Candidate: extreme expansion (price beyond extension with very high vol_z or RSI) -> consider mean-reversion sell (bearish)
        if signal == "hold":
            extreme = False
            for lvl, price in reversed(level_prices):
                if (
                    lvl >= 1.272
                    and completed_close is not None
                    and completed_close > price + max(abs(price) * 0.01, 1e-6)
                ):
                    if vol_z > 2.0 or (curr_rsi is not None and curr_rsi > 80):
                        extreme = True
                        break
            if extreme:
                scorer.add(
                    True,
                    "Extreme beyond fib extension",
                    weight=self.weights.get("fib", 0.0),
                )
                scorer.add(
                    not atr_vol_ok,
                    "ATR check (prefer volatile)",
                    weight=self.weights.get("atr", 0.0),
                )
                scorer.add(
                    curr_rsi is not None and curr_rsi > 50,
                    "RSI extreme",
                    weight=self.weights.get("rsi", 0.0),
                )
                scorer.add(
                    vol_spike, "Volume extreme", weight=self.weights.get("volume", 0.0)
                )
                s, c, r = scorer.evaluate(direction="bearish")
                if s == "bearish":
                    signal, confidence, reasons = s, c, r

        # If still hold, return hold
        if signal == "hold":
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="No fib-confirmed signal",
                details={
                    "swing_low": swing_low,
                    "swing_high": swing_high,
                    "fib_map": fib_map,
                },
            )

        # Attach details
        details: Dict[str, Any] = {
            "swing_low": swing_low,
            "swing_high": swing_high,
            "fib_map": fib_map,
            "completed_close": completed_close,
            "latest_close": latest_close,
            "curr_rsi": curr_rsi,
            "atr_current": cur_atr,
            "atr_percentile_value": (
                round(atr_percentile_value, 12) if atr_hist else None
            ),
            "atr_vol_ok": atr_vol_ok,
            "volume": latest_volume,
            "vol_zscore": round(vol_z, 3),
            "vol_spike": vol_spike,
            "macd_up": macd_confirm_up,
            "macd_down": macd_confirm_down,
            "vwap": vwap_price,
            "obv_trend_up": obv_trend_up,
            "obv_trend_down": obv_trend_down,
            "confidence": round(confidence, 3),
            "reasons": reasons,
        }

        return SignalModel(
            date=current_date,
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            confidence=round(confidence, 3),
            reason="; ".join(reasons),
            details=details,
        )


# -------------------------
# Preset factory
# -------------------------
def make_fib_presets() -> Dict[str, Dict[str, Any]]:
    mid_balanced = {
        "swing_lookback": 60,
        "fib_levels": [0.236, 0.382, 0.5, 0.618, 0.786],
        "rsi_period": 14,
        "atr_period": 14,
        "volume_window": 30,
        "volume_zscore_threshold": 1.5,
        "atr_percentile_filter": 0.4,
        "atr_percentile_window": 60,
        "confirmation_threshold": 0.58,
        "weights": {
            "fibonacci": 0.50,
            "atr": 0.18,
            "rsi": 0.12,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    mid_conservative = {
        "swing_lookback": 80,
        "fib_levels": [0.382, 0.5, 0.618],
        "rsi_period": 14,
        "atr_period": 14,
        "volume_window": 40,
        "volume_zscore_threshold": 1.8,
        "atr_percentile_filter": 0.5,
        "atr_percentile_window": 80,
        "confirmation_threshold": 0.62,
        "weights": {
            "fibonacci": 0.55,
            "atr": 0.20,
            "rsi": 0.10,
            "volume": 0.08,
            "vwap": 0.03,
            "obv": 0.02,
            "macd": 0.02,
        },
    }

    mid_aggressive = {
        "swing_lookback": 40,
        "fib_levels": [0.236, 0.382, 0.5, 0.618],
        "rsi_period": 10,
        "atr_period": 10,
        "volume_window": 25,
        "volume_zscore_threshold": 1.2,
        "atr_percentile_filter": 0.35,
        "atr_percentile_window": 50,
        "confirmation_threshold": 0.54,
        "weights": {
            "fibonacci": 0.48,
            "atr": 0.20,
            "rsi": 0.12,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    short_quick = {
        "swing_lookback": 20,
        "fib_levels": [0.382, 0.5, 0.618],
        "rsi_period": 7,
        "atr_period": 7,
        "volume_window": 15,
        "volume_zscore_threshold": 1.0,
        "atr_percentile_filter": 0.3,
        "atr_percentile_window": 40,
        "confirmation_threshold": 0.52,
        "weights": {
            "fibonacci": 0.50,
            "atr": 0.20,
            "rsi": 0.10,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    short_balanced = {
        "swing_lookback": 25,
        "fib_levels": [0.236, 0.382, 0.5, 0.618],
        "rsi_period": 10,
        "atr_period": 10,
        "volume_window": 20,
        "volume_zscore_threshold": 1.2,
        "atr_percentile_filter": 0.35,
        "atr_percentile_window": 50,
        "confirmation_threshold": 0.56,
        "weights": {
            "fibonacci": 0.52,
            "atr": 0.18,
            "rsi": 0.10,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    short_conservative = {
        "swing_lookback": 30,
        "fib_levels": [0.382, 0.5, 0.618],
        "rsi_period": 12,
        "atr_period": 10,
        "volume_window": 25,
        "volume_zscore_threshold": 1.4,
        "atr_percentile_filter": 0.4,
        "atr_percentile_window": 60,
        "confirmation_threshold": 0.60,
        "weights": {
            "fibonacci": 0.55,
            "atr": 0.18,
            "rsi": 0.10,
            "volume": 0.08,
            "vwap": 0.05,
            "obv": 0.02,
            "macd": 0.02,
        },
    }

    return {
        "mid_balanced": mid_balanced,
        "mid_conservative": mid_conservative,
        "mid_aggressive": mid_aggressive,
        "short_quick": short_quick,
        "short_balanced": short_balanced,
        "short_conservative": short_conservative,
    }
