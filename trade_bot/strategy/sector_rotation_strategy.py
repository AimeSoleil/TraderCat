from tokenize import cookie_re
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from trade_bot.data.market_data_provider import MarketDataProvider
from trade_bot.strategy.trading_strategy import TradingStrategy, EPS
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger
import numpy as np
import pandas as pd

logger = get_logger(__name__)

# ETF list
SECTOR_ETF_LIST = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

class Indicators(BaseModel):
    rsi: Optional[float]
    volatility: Optional[float]
    momentum: Optional[float]
    avg_volume: Optional[float]
    volume_trend: Optional[float]
    composite_score: Optional[float]

class SectorRotationStrategy(TradingStrategy):
    """
    Sector Rotation Strategy with dynamic thresholds and market regime filter.
    """

    def __init__(
        self,
        look_back_days: int = 90,
        num_sectors_to_select: int = 3,
        rsi_period: int = 14,
        atr_period: int = 14,
        weights: Optional[Dict[str, float]] = None,
        data_provider: MarketDataProvider = None,
    ):
        self.look_back_days = look_back_days
        self.num_sectors_to_select = num_sectors_to_select
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.weights = (
            weights
            if weights
            else {
                "momentum": 0.5,
                "rsi": 0.3,
                "volume_trend": 0.2,
            }
        )
        self.provider = data_provider

        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.atr_field = f"ATRr_{self.atr_period}"

    def get_name(self) -> str:
        return "SectorRotationStrategy"

    def get_lookback_window(self) -> int:
        return self.look_back_days + self.rsi_period

    def _compute_return_L(self, closes: List[float], L: int) -> Optional[float]:
        if len(closes) <= L:
            return None
        past = closes[-L - 1]
        curr = closes[-1]
        if abs(past) < EPS:
            return None
        return curr / past - 1.0

    def _extract_latest_indicator_value(
        self, series: Optional[List[Any]], keys: List[str]
    ) -> Optional[float]:
        if not series:
            return None
        last = series[-1]
        for k in keys:
            try:
                v = (
                    getattr(last, k, None)
                    if hasattr(last, k)
                    else (last.get(k) if isinstance(last, dict) else None)
                )
            except Exception:
                v = None
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    continue
        return None

    def _normalize(self, val: float, min_val: float, max_val: float) -> float:
        if val is None or max_val <= min_val:
            return 0.0
        return (val - min_val) / (max_val - min_val)

    def _detect_market_regime(self) -> Dict[str, Any]:
        spy_candles = self.provider.get_price_data("SPY", "1d", 200)

        spy_closes = [float(getattr(c, "close")) for c in spy_candles]
        sma50 = np.mean(spy_closes[-50:])
        sma200 = np.mean(spy_closes[-200:])
        bull_regime = sma50 > sma200

        return {
            "bull_regime": bull_regime,
        }

    def generate_signal(self, symbol: str = None, candles: List[Any] = None) -> SignalModel:
        etf_indicators: Dict[str, Indicators] = {}

        # Market regime detection
        regime = self._detect_market_regime()
        bull_regime = regime["bull_regime"]

        # Collect data for all sectors
        for sector, etf in SECTOR_ETF_LIST.items():
            _candles = self.provider.get_price_data(etf, interval="1d", lookback=self.get_lookback_window())
            closes = [float(getattr(c, "close")) for c in _candles]
            vols = [float(getattr(c, "volume")) for c in _candles]
            price = closes[-1]
            date = getattr(_candles[-1], "date")

            # RSI
            rsi_series = self.provider.get_indicator(
                "rsi", _candles, {"length": self.rsi_period}
            )
            rsi_val = self._extract_latest_indicator_value(rsi_series, [self.rsi_field])

            # Volatility (ATR ratio)
            atr_series = self.provider.get_indicator(
                "atr", _candles, {"length": self.atr_period}
            )
            atr_val = self._extract_latest_indicator_value(atr_series, [self.atr_field])
            volatility = atr_val / max(abs(price), EPS) if atr_val else None

            # Momentum
            momentum = self._compute_return_L(closes, self.look_back_days)

            # Volume metrics
            avg_volume = (
                np.mean(vols[-self.look_back_days :])
                if len(vols) >= self.look_back_days
                else None
            )
            volume_trend = vols[-1] / (np.mean(vols[-20:]) if len(vols) >= 20 else 1)

            etf_indicators[etf] = Indicators(
                rsi=rsi_val,
                volatility=volatility,
                momentum=momentum,
                avg_volume=avg_volume,
                volume_trend=volume_trend,
                composite_score=None,
            )

        # Convert to DataFrame for normalization
        df = pd.DataFrame(
            {etf: ind.model_dump() for etf, ind in etf_indicators.items()}
        ).T

        # Normalize and compute composite score
        for etf, ind in etf_indicators.items():
            ind.composite_score = (
                self._normalize(
                    ind.momentum, df["momentum"].min(), df["momentum"].max()
                )
                * self.weights["momentum"]
                + self._normalize(ind.rsi, df["rsi"].min(), df["rsi"].max())
                * self.weights["rsi"]
                + self._normalize(
                    ind.volume_trend, df["volume_trend"].min(), df["volume_trend"].max()
                )
                * self.weights["volume_trend"]
            )

        # Dynamic thresholds adjusted by regime
        vol_threshold = np.percentile(
            df["volatility"].dropna(), 85 if bull_regime else 65
        )
        rsi_threshold = np.percentile(df["rsi"].dropna(), 40 if bull_regime else 60)
        volume_threshold = np.percentile(df["avg_volume"].dropna(), 25)

        # Filter and Rank sectors
        filtered = [
            (sector, etf_indicators[SECTOR_ETF_LIST[sector]])
            for sector in SECTOR_ETF_LIST
            if etf_indicators[SECTOR_ETF_LIST[sector]].rsi
            and etf_indicators[SECTOR_ETF_LIST[sector]].rsi >= rsi_threshold
            and etf_indicators[SECTOR_ETF_LIST[sector]].volatility
            and etf_indicators[SECTOR_ETF_LIST[sector]].volatility <= vol_threshold
            and etf_indicators[SECTOR_ETF_LIST[sector]].avg_volume
            and etf_indicators[SECTOR_ETF_LIST[sector]].avg_volume >= volume_threshold
        ]

        ranked = sorted(filtered, key=lambda x: x[1].composite_score or 0, reverse=True)
        top_sectors = ranked[: self.num_sectors_to_select]

        # Risk-adjusted allocation with cap
        allocations = {}
        total_inv_vol = sum(1 / (ind.volatility or 1) for _, ind in top_sectors)
        for sector, ind in top_sectors:
            weight = (1 / (ind.volatility or 1)) / total_inv_vol
            allocations[sector] = min(weight, 0.5)  # Cap at 50%

        details = {
            "dynamic_thresholds": {
                "volatility": vol_threshold,
                "rsi": rsi_threshold,
                "avg_volume": volume_threshold,
            },
            "market_regime": regime,
            "etf_indicators": {sector: ind.model_dump() for sector, ind in filtered},
            "allocations": allocations,
        }

        return SignalModel(
            symbol=",".join([SECTOR_ETF_LIST[sector] for sector, _ in top_sectors]),
            strategy=self.get_name(),
            signal="rebalance" if top_sectors else "hold",
            date=date,
            confidence=1 if top_sectors else 0,
            reason=(
                "Top sectors selected using dynamic thresholds, composite score, and market regime filter"
                if top_sectors
                else "No sectors met dynamic criteria"
            ),
            details=details,
        )

    # def backtest(self, initial_capital: float = 100000) -> Dict[str, Any]:
    #     """
    #     Backtest the strategy over a dynamic historical period based on lookback window.
    #     """
    #     lookback_window = self.get_lookback_window()
    #     logger.info(f"Backtest lookback window: {lookback_window} days")

    #     # Fetch historical data for all ETFs using get_price_data
    #     historical_data = {}
    #     for sector, etf in SECTOR_ETF_LIST.items():
    #         historical_data[etf] = self.provider.get_price_data(etf, interval="1d", lookback_days=lookback_window)

    #     # Use SPY as reference for dates
    #     spy_data = self.provider.get_price_data("SPY", interval="1d", lookback_days=lookback_window)
    #     dates = [getattr(c, "date") for c in spy_data]

    #     portfolio_value = []
    #     allocations_history = []
    #     current_allocations = {}
    #     capital = initial_capital

    #     for i, date in enumerate(dates):
    #         # Generate signal for this date
    #         candles = spy_data[:i+1]  # Pass SPY candles up to current date
    #         signal = self.generate_signal("SPY", candles)

    #         if signal.signal == "rebalance":
    #             current_allocations = signal.details["allocations"]
    #             allocations_history.append((date, current_allocations))

    #         # Compute portfolio value
    #         daily_value = 0
    #         for sector, weight in current_allocations.items():
    #             etf = SECTOR_ETF_LIST[sector]
    #             price = float(getattr(historical_data[etf][i], "close"))
    #             daily_value += capital * weight * (price / float(getattr(historical_data[etf][0], "close")))

    #         portfolio_value.append(daily_value if daily_value > 0 else capital)

    #     # Convert to DataFrame
    #     df = pd.DataFrame({"date": dates, "portfolio_value": portfolio_value})
    #     df.set_index("date", inplace=True)

    #     # Compute metrics
    #     returns = df["portfolio_value"].pct_change().dropna()
    #     cagr = (df["portfolio_value"].iloc[-1] / initial_capital) ** (252 / len(df)) - 1
    #     sharpe = returns.mean() / returns.std() * np.sqrt(252)
    #     max_drawdown = ((df["portfolio_value"] / df["portfolio_value"].cummax()) - 1).min()

    #     summary = {
    #         "CAGR": round(cagr, 4),
    #         "Sharpe Ratio": round(sharpe, 2),
    #         "Max Drawdown": round(max_drawdown, 4),
    #         "Final Value": round(df["portfolio_value"].iloc[-1], 2),
    #         "Allocations History": allocations_history,
    #         "Lookback Window": lookback_window
    #     }

    #     return {"performance": summary, "equity_curve": df}
