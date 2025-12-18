from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from scipy.stats import zscore
import numpy as np
import pandas as pd

from trade_bot.data.market_data_provider import MarketDataProvider
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

# Standard SPDR Select Sector ETFs (GICS)
SECTOR_ETF_LIST = {
    "Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Discretionary": "XLY",
    "Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Comms": "XLC",
}

# Safe Haven Asset (Short-term Treasury)
SAFE_HAVEN_ETF = "SHY"

class Indicators(BaseModel):
    rsi: Optional[float]
    volatility: Optional[float]
    momentum: Optional[float]
    avg_volume: Optional[float]
    volume_trend: Optional[float]
    composite_score: Optional[float] = 0.0

class SectorRotationStrategy(TradingStrategy):
    """
    Sector Rotation Strategy (Production Grade)
    - Uses Z-Score for robust ranking across sectors.
    - Implements 'Cash/Safety' switch during bear markets.
    - Risk-Adjusted Allocation (Inverse Volatility).
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
        self.weights = weights or {
            "momentum": 0.5,
            "rsi": 0.3,
            "volume_trend": 0.2,
        }
        self.provider = data_provider

        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.atr_field = f"ATRr_{self.atr_period}"

    def get_name(self) -> str:
        return "SectorRotation"

    def get_lookback_window(self) -> int:
        # Need enough data for SPY SMA200 and Sector Momentum
        return max(200, self.look_back_days + 20)

    # ---------- Helper Functions ------------
    def _detect_market_regime(self) -> Dict[str, Any]:
        """
        Detects if the broad market (SPY) is in a Bull or Bear regime.
        """
        spy_candles = self.provider.get_price_data("SPY", "1d", 210)
        if not spy_candles or len(spy_candles) < 200:
            return {"bull_regime": True, "sma200": 0} # Default to Bull if no data

        spy_closes = [float(getattr(c, "close")) for c in spy_candles]
        current_price = spy_closes[-1]
        sma200 = np.mean(spy_closes[-200:])
        
        # Bull regime if Price > SMA200
        bull_regime = current_price > sma200

        return {
            "bull_regime": bull_regime,
            "current_price": current_price,
            "sma200": sma200
        }

    def _compute_momentum(self, closes: List[float], lookback: int) -> float:
        if len(closes) < lookback:
            return 0.0
        # Simple Return
        return (closes[-1] / closes[-lookback]) - 1

    def generate_signal(self, symbol: str = None, candles: List[Any] = None) -> SignalModel:
        # Note: 'symbol' and 'candles' args are ignored here as this is a portfolio strategy
        # that fetches its own data for the sector list.
        
        etf_indicators: Dict[str, Indicators] = {}
        
        # 1. Market Regime Check
        regime = self._detect_market_regime()
        bull_regime = regime["bull_regime"]
        
        # 2. Collect Data for Sectors
        # In production, fetch these in batch if possible to reduce latency
        valid_sectors = []
        
        for sector_name, etf in SECTOR_ETF_LIST.items():
            _candles = self.provider.get_price_data(etf, interval="1d", lookback=self.get_lookback_window())
            if not _candles or len(_candles) < self.look_back_days:
                continue

            closes = [float(getattr(c, "close")) for c in _candles]
            vols = [float(getattr(c, "volume")) for c in _candles]
            price = closes[-1]
            date = getattr(_candles[-1], "date")

            # Indicators
            rsi_series = self.provider.get_indicator("rsi", _candles, {"length": self.rsi_period})
            atr_series = self.provider.get_indicator("atr", _candles, {"length": self.atr_period})
            
            curr_rsi = getattr(rsi_series[-1], self.rsi_field, 50) if rsi_series else 50
            curr_atr = getattr(atr_series[-1], self.atr_field, 0) if atr_series else 0
            
            # Normalized Volatility (ATR %)
            volatility = (curr_atr / price) if price > 0 else 0.01
            
            # Momentum
            mom = self._compute_momentum(closes, self.look_back_days)
            
            # Volume Trend (Current vs 20MA)
            avg_vol_20 = np.mean(vols[-20:]) if len(vols) >= 20 else 1
            vol_trend = vols[-1] / avg_vol_20 if avg_vol_20 > 0 else 1.0
            
            avg_vol_long = np.mean(vols[-self.look_back_days:])

            etf_indicators[etf] = Indicators(
                rsi=curr_rsi,
                volatility=volatility,
                momentum=mom,
                avg_volume=avg_vol_long,
                volume_trend=vol_trend
            )
            valid_sectors.append(etf)

        if not valid_sectors:
            return SignalModel(symbol="CASH", strategy=self.get_name(), signal="hold", reason="No data")

        # 3. Compute Scores using Z-Score (Robust Scaling)
        df = pd.DataFrame({etf: ind.model_dump() for etf, ind in etf_indicators.items()}).T
        
        # Calculate Z-scores for each factor across the sector universe
        # Handle NaNs by filling with mean or 0
        df = df.fillna(df.mean())
        
        # Z-Score normalization (Standardization)
        # Momentum: Higher is better
        z_mom = zscore(df['momentum'])
        # RSI: Higher is better (up to a point), but here we treat higher as stronger trend
        z_rsi = zscore(df['rsi'])
        # Volume Trend: Higher is better
        z_vol = zscore(df['volume_trend'])
        
        # Composite Score
        # Note: We use the weights to blend the Z-scores
        df['composite_score'] = (
            (z_mom * self.weights['momentum']) +
            (z_rsi * self.weights['rsi']) +
            (z_vol * self.weights['volume_trend'])
        )

        # 4. Filter & Select
        # Dynamic Thresholds based on Regime
        # In Bear regime, we are stricter on Volatility and Momentum
        
        min_rsi = 40 if bull_regime else 50
        max_vol = np.percentile(df['volatility'], 80) if bull_regime else np.percentile(df['volatility'], 50)
        
        # Filter
        candidates = df[
            (df['rsi'] > min_rsi) & 
            (df['volatility'] < max_vol) &
            (df['momentum'] > 0) # Absolute Momentum Filter: Must be positive
        ]
        
        top_sectors = candidates.sort_values(by='composite_score', ascending=False).head(self.num_sectors_to_select)
        
        selected_symbols = []
        allocations = {}
        
        # 5. Allocation Logic (Safety Switch)
        if top_sectors.empty:
            # BEAR MARKET SAFETY: If no sectors pass criteria (e.g. all have negative momentum),
            # switch to Safe Haven Asset.
            selected_symbols = [SAFE_HAVEN_ETF]
            allocations = {SAFE_HAVEN_ETF: 1.0}
            reason = "Bear Market / Negative Momentum: Switched to Safety (SHY)"
        else:
            selected_symbols = top_sectors.index.tolist()
            
            # Inverse Volatility Weighting
            # Lower volatility = Higher weight
            inv_vol = 1.0 / top_sectors['volatility']
            allocations = (inv_vol / inv_vol.sum()).to_dict()
            
            # Cap weights at 50% to ensure diversification
            for k, v in allocations.items():
                if v > 0.5: allocations[k] = 0.5
            
            # Re-normalize after capping (simple approximation)
            total_w = sum(allocations.values())
            allocations = {k: v/total_w for k, v in allocations.items()}
            
            reason = f"Top Sectors: {','.join(selected_symbols)} (Bull Regime: {bull_regime})"

        details = {
            "regime": "Bull" if bull_regime else "Bear",
            "spy_sma200": regime.get("sma200"),
            "allocations": allocations,
            "all_scores": df['composite_score'].to_dict()
        }

        return SignalModel(
            symbol=",".join(selected_symbols),
            strategy=self.get_name(),
            signal="rebalance",
            date=date,
            confidence=1.0,
            reason=reason,
            details=details,
        )

def make_sector_rotation_presets() -> Dict[str, Dict[str, Any]]:
    """
    Sector Rotation Strategy presets.
    """
    # ---------------- SWING (Aggressive) ----------------
    swing = {
        "look_back_days": 21,                # 1 Month Momentum
        "num_sectors_to_select": 3,
        "weights": {"momentum": 0.7, "rsi": 0.2, "volume_trend": 0.1}
    }

    # ---------------- INTERMEDIATE (Standard) ----------------
    intermediate = {
        "look_back_days": 63,                # 1 Quarter Momentum
        "num_sectors_to_select": 3,
        "weights": {"momentum": 0.5, "rsi": 0.3, "volume_trend": 0.2}
    }

    # ---------------- POSITION (Conservative) ----------------
    position = {
        "look_back_days": 126,               # 6 Months Momentum
        "num_sectors_to_select": 2,
        "weights": {"momentum": 0.4, "rsi": 0.4, "volume_trend": 0.2}
    }

    return {
        "swing": swing,
        "intermediate": intermediate,
        "position": position
    }
