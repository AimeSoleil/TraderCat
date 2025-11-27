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

    # ---------- Helper Functions ------------
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
        _candles = candles
        for sector, etf in SECTOR_ETF_LIST.items():
            _candles = self.provider.get_price_data(etf, interval="1d", lookback=self.get_lookback_window())
            closes = [float(getattr(c, "close")) for c in _candles]
            vols = [float(getattr(c, "volume")) for c in _candles]
            price = closes[-1]
            date = getattr(_candles[-1], "date")

            # RSI
            rsi_series = self.provider.get_indicator("rsi", _candles, {"length": self.rsi_period})
            current_rsi_val = self._extract_latest_indicator_value(rsi_series, [self.rsi_field])

            # Volatility (ATR ratio)
            atr_series = self.provider.get_indicator(
                "atr", _candles, {"length": self.atr_period}
            )
            current_atr_val = self._extract_latest_indicator_value(atr_series, [self.atr_field])
            volatility = current_atr_val / max(abs(price), EPS) if current_atr_val else None

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
                rsi=current_rsi_val,
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

def make_sector_rotation_presets() -> Dict[str, Dict[str, Any]]:
    """
    Sector Rotation Strategy presets based on algo trading best practices:
    - swing: Short-term (1–2 weeks), aggressive momentum weighting, tighter volatility filter.
    - intermediate: Medium-term (2–6 weeks), balanced parameters.
    - position: Long-term (1–3 months), conservative, stricter filters.
    """

    # ---------------- SWING ----------------
    swing = {
        "look_back_days": 30,                # Short lookback for recent momentum.
        "num_sectors_to_select": 4,          # More sectors for diversification in short-term.
        "rsi_period": 14,                    # Standard RSI.
        "atr_period": 14,                    # ATR for volatility context.
        "weights": {
            "momentum": 0.6,                 # Momentum dominates short-term rotation.
            "rsi": 0.25,                     # RSI secondary filter.
            "volume_trend": 0.15,            # Volume trend less critical for quick rotations.
        }
    }

    # ---------------- INTERMEDIATE ----------------
    intermediate = {
        "look_back_days": 60,                # Longer lookback for medium-term momentum.
        "num_sectors_to_select": 3,          # Balanced diversification.
        "rsi_period": 14,
        "atr_period": 14,
        "weights": {
            "momentum": 0.5,                 # Balanced momentum weight.
            "rsi": 0.3,                      # RSI more important for medium-term.
            "volume_trend": 0.2,             # Volume trend matters more.
        }
    }

    # ---------------- POSITION ----------------
    position = {
        "look_back_days": 90,                # Very long lookback for sustained trends.
        "num_sectors_to_select": 2,          # Fewer sectors for concentrated bets.
        "rsi_period": 14,
        "atr_period": 14,
        "weights": {
            "momentum": 0.4,                 # Momentum still important but less dominant.
            "rsi": 0.35,                     # RSI more critical for long-term positioning.
            "volume_trend": 0.25,            # Volume trend strongly considered.
        }
    }

    return {
        "swing": swing,
        "intermediate": intermediate,
        "position": position
    }
