from typing import List, Optional, Dict, Any
import statistics

from tradercat.core.strategy.exit_planner import ExitPlanner
from tradercat.core.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from tradercat.core.strategy.trading_strategy import TradingStrategy
from tradercat.core.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger

import logging
from tradercat.config import settings

# Set up logger
use_json = settings.log_format == "json"
logger = get_logger(__name__, level=getattr(logging, settings.log_level), use_json=use_json)

class MomentumTrendStrategy(TradingStrategy):
    """
    Momentum Trend Strategy (Production Grade).
    It follows the trend, so it needs Health ADX (Strength), 
    but NOT necessarily High Volatility (which reduces Sharpe).
    """

    def __init__(
        self,
        L: int = 63,            # Momentum Lookback (~1 Quarter)
        ema_fast: int = 13,
        ema_slow: int = 34,
        ht_ema_fast: int = 8,   # Higher Timeframe (Weekly) Fast
        ht_ema_slow: int = 21,  # Higher Timeframe (Weekly) Slow
        adx_period: int = 14,
        atr_period: int = 14,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.6,
        # [NEW] Dynamic Weights
        weights: Optional[Dict[str, float]] = None,
        data_provider: Any = None,
    ):
        self.L = int(L)
        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.ht_ema_fast = int(ht_ema_fast)
        self.ht_ema_slow = int(ht_ema_slow)
        self.adx_period = int(adx_period)
        self.atr_period = int(atr_period)
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        
        # [NEW] Dynamic Weights configuration
        default_weights = {
            "momentum": 0.35,       # The primary driver
            "trend_strength": 0.15, # ADX matters for momentum
            "daily_trend": 0.20,    # Daily structure
            "ht_trend": 0.20,       # Weekly structure
            "volume": 0.05,         # Confirmation
            "confluence": 0.05      # Bonus
        }
        self.weights = {**default_weights, **(weights or {})}
        
        self.provider = data_provider

        # Fields
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.atr_field = f"ATRr_{self.atr_period}"

    def get_name(self) -> str:
        return "MomentumTrend"

    def get_lookback_window(self) -> int:
        return (
            max(
                self.L,
                self.ema_slow,
                self.ht_ema_slow * 5, 
                self.atr_period,
                self.adx_period,
            )
            + 10
        )

    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.MOMENTUM_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.DAILY_TREND_CONFIRM,
            FactorName.HIGHER_TIMEFRAME_TREND_CONFIRM,
            FactorName.VOLUME_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

    # ---------- Helpers ----------

    def _compute_risk_adjusted_momentum(self, closes: List[float], lookback: int) -> float:
        """
        Calculates Risk-Adjusted Momentum: Total Return / Volatility
        Robust against zero-division and short data.
        """
        if len(closes) <= lookback:
            return 0.0
        
        # 1. Total Return
        start_price = closes[-lookback - 1]
        end_price = closes[-1]
        
        if start_price <= 1e-9: return 0.0 # Avoid bad data
        
        total_ret = (end_price - start_price) / start_price
        
        # 2. Volatility (Standard Deviation of daily returns)
        # Slicing is efficient in Python
        subset = closes[-lookback-1:]
        
        # Vectorized-style calculation usually better, but keeping simple loop for compatibility
        daily_rets = []
        for i in range(1, len(subset)):
            prev = subset[i-1]
            if prev > 1e-9:
                daily_rets.append((subset[i] / prev) - 1.0)
            else:
                daily_rets.append(0.0)
        
        if len(daily_rets) < 2: return 0.0
        
        try:
            vol = statistics.stdev(daily_rets)
        except Exception:
            vol = 0.0
        
        if vol < 1e-9: return 0.0
        
        # Metric: Annualized Return / Annualized Vol implies Sharpe
        # Here we use raw ratio which is sufficient for ranking
        return total_ret / vol

    def _compute_ema_manual(self, prices: List[float], period: int) -> Optional[float]:
        """Calculates the *last* EMA value manually."""
        if not prices or len(prices) < period:
            return None
        
        # Optimization: Don't re-calculate the whole series, just enough to stabilize
        # For EMA, usually 3*period is enough warm-up. 
        # But to be safe and simple, we calculate on passed window.
        
        k = 2.0 / (period + 1.0)
        ema = sum(prices[:period]) / period 
        
        for p in prices[period:]:
            ema = p * k + ema * (1 - k)
        return ema

    def _aggregate_higher_timeframe_closes(self, candles: List[Any], days: int = 5) -> List[float]:
        """
        Optimized aggregation: Only extracts Closes for weekly bars.
        We don't need High/Low/Vol for EMA calculation.
        """
        if len(candles) < days:
            return []
        
        # Efficient slicing: take every Nth element starting from end is tricky
        # Simple loop is fine for O(N)
        agg_closes = []
        
        # Align from the END of the array backwards
        # This ensures the last candle is the end of the current "week"
        total = len(candles)
        
        # Current partial week? 
        # Strategy: Just iterate normally. 
        # The 'last' bar of every 5-bar chunk is the close.
        for i in range(days-1, total, days):
            agg_closes.append(float(getattr(candles[i], "close", 0.0)))
        
        # Handling the "latest incomplete week" is complex in backtesting.
        # We stick to completed 5-day blocks or just standard sampling.
        # Alternative: Standard sampling (Index 4, 9, 14...)
        return agg_closes

    # ---------- Main Logic ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(date=None, symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="Data insufficient")

        closes = [float(getattr(c, "close")) for c in candles]
        highs = [float(getattr(c, "high")) for c in candles]
        lows = [float(getattr(c, "low")) for c in candles]
        vols = [float(getattr(c, "volume")) for c in candles]
        dates = [getattr(c, "date") for c in candles]
        curr_close = closes[-1]

        # 1. Momentum Calculation (Risk Adjusted)
        mom_score = self._compute_risk_adjusted_momentum(closes, self.L)

        # 2. Indicators
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        
        current_atr_val = atr_val_history[-1] if atr_val_history else 0.0
        current_adx_val = adx_val_history[-1] if adx_val_history else 0.0
        
        curr_ema_fast = getattr(ema_fast_series[-1], self.ema_fast_field, None)
        curr_ema_slow = getattr(ema_slow_series[-1], self.ema_slow_field, None)

        # 3. Higher Timeframe (HT) EMA
        # Using simplified aggregation for robustness
        agg_closes = self._aggregate_higher_timeframe_closes(candles, days=5)
        
        ht_fast = self._compute_ema_manual(agg_closes, self.ht_ema_fast)
        ht_slow = self._compute_ema_manual(agg_closes, self.ht_ema_slow)
        ht_ema_ok = (ht_fast is not None and ht_slow is not None)

        # 4. Trend Logic check
        # [UPDATED] Momentum needs Strong ADX, but allows Low Volatility (Grind).
        # We use ignore_volatility=True so we don't punish stable trends.
        trend_config = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=adx_val_history,
            price_history=closes,
            window=100,
            mode='trend',
            ignore_volatility=True,     # [KEY CHANGE]
            trend_quantiles=[0.5, 0.25] # Require moderate trendiness
        )
        
        # Now .signal contains strictly the ADX Strength check
        is_adx_strong = trend_config.signal

        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        
        # [UPDATED] Capture Z-Score
        _vol_res = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)
        if isinstance(_vol_res, tuple):
            vol_ok, vol_z = _vol_res
        else:
            vol_ok, vol_z = _vol_res, 0.0

        # Daily Trend Alignment
        trend_day_up = (curr_ema_fast > curr_ema_slow) if (curr_ema_fast and curr_ema_slow) else False
        trend_day_down = (curr_ema_fast < curr_ema_slow) if (curr_ema_fast and curr_ema_slow) else False
        
        # Price Location Check (Buying Pullbacks above Slow EMA vs Buying Extended)
        # Null check added
        price_above_slow = (curr_close > curr_ema_slow) if curr_ema_slow else False
        price_below_slow = (curr_close < curr_ema_slow) if curr_ema_slow else False

        # HT Trend Alignment (Fallback to Neutral if no data, not True)
        trend_ht_up = (ht_fast > ht_slow) if ht_ema_ok else False
        trend_ht_down = (ht_fast < ht_slow) if ht_ema_ok else False

        # Conditions
        # Long: Positive Mom + Daily Up + Price > Slow EMA + HT Up
        long_cond = (mom_score > 0) and trend_day_up and price_above_slow and trend_ht_up
        
        # Short: Negative Mom + Daily Down + Price < Slow EMA + HT Down
        short_cond = (mom_score < 0) and trend_day_down and price_below_slow and trend_ht_down

        # [UPDATED] Comprehensive Technical Details
        avg_vol = sum(vols[-recent_window:]) / recent_window if recent_window > 0 else 0.0
        rel_vol = (vols[-1] / avg_vol) if avg_vol > 0 else 0.0
        
        open_price = float(getattr(candles[-1], "open", 0.0))
        bar_change_pct = (curr_close - open_price) / open_price * 100 if open_price != 0 else 0.0
        atr_pct = (current_atr_val / curr_close * 100) if curr_close > 0 else 0.0
        
        ema_spread_pct = ((curr_ema_fast - curr_ema_slow) / curr_ema_slow * 100) if (curr_ema_slow and curr_ema_slow != 0.0) else 0.0
        
        ht_ema_spread_pct = 0.0
        if ht_ema_ok and ht_slow != 0:
            ht_ema_spread_pct = (ht_fast - ht_slow) / ht_slow * 100

        ohlcv: Dict[str, Any] = {
            "open": round(open_price, 2),
            "high": round(highs[-1], 2),
            "low": round(lows[-1], 2),
            "close": round(curr_close, 2),
            "volume": round(vols[-1], 0),
            f"avg_volume_{self.vol_zscore_window}": round(avg_vol, 0),
            f"rel_volume_{self.vol_zscore_window}": round(rel_vol, 2),
            f"vol_zscore_{self.vol_zscore_window}": round(vol_z or 0.0, 2),
            "bar_change_pct": round(bar_change_pct, 2),
        }

        indicators: Dict[str, Any] = {
            # Momentum Factors
            "mom_score_risk_adj": round(mom_score, 2),
            f"adx_{self.adx_period}": round(current_adx_val, 1),
            "is_adx_strong": is_adx_strong,
            
            # Daily Trend Structure
            f"ema_fast_{self.ema_fast}": round(curr_ema_fast, 2),
            f"ema_slow_{self.ema_slow}": round(curr_ema_slow, 2),
            "ema_spread_pct": round(ema_spread_pct, 2),
            "daily_trend_up": trend_day_up,
            
            # Higher Timeframe (Weekly) Structure
            f"ht_fast_{self.ht_ema_fast}": round(ht_fast, 3) if ht_fast else None,
            f"ht_slow_{self.ht_ema_slow}": round(ht_slow, 3) if ht_slow else None,
            "ht_ema_spread_pct": round(ht_ema_spread_pct, 2),
            "ht_trend_up": trend_ht_up,

            # Volatility
            f"atr_{self.atr_period}": round(current_atr_val, 2),
            "atr_pct": round(atr_pct, 2)
        }

        # 5. Scoring
        factors = [
            Factor(
                FactorName.MOMENTUM_CONFIRM, 
                f"Momentum ({mom_score:.2f})", 
                self.weights["momentum"], 
                long_cond or short_cond
            ),
            # [FIXED REFERENCE] Use isolated ADX signal
            Factor(
                FactorName.TREND_STRENGTH, 
                "ADX Strength", 
                self.weights["trend_strength"], 
                is_adx_strong
            ),
            Factor(
                FactorName.DAILY_TREND_CONFIRM, 
                "Daily EMA Alignment", 
                self.weights["daily_trend"], 
                (long_cond and trend_day_up) or (short_cond and trend_day_down)
            ),
            Factor(
                FactorName.HIGHER_TIMEFRAME_TREND_CONFIRM, 
                "Weekly EMA Alignment", 
                self.weights["ht_trend"], 
                (long_cond and trend_ht_up) or (short_cond and trend_ht_down)
            ),
            Factor(
                FactorName.VOLUME_CONFIRM, 
                "Volume", 
                self.weights["volume"], 
                vol_ok
            ),
            Factor(
                FactorName.CONFLUENCE_BONUS, 
                "Full Timeframe Confluence", 
                self.weights["confluence"], 
                (long_cond and trend_ht_up and is_adx_strong) or (short_cond and trend_ht_down and is_adx_strong)
            )
        ]

        engine = ScoringEngine(
            base_threshold=self.score_threshold, 
            required_factors=self.support_scoring_factors(),
            determined_factors=[FactorName.MOMENTUM_CONFIRM],
            # For Momentum, we are generally OK with any volatility state 
            # as long as it's not absurdly high (which Risk-Adj Mom handles).
            is_volatility_ok=True 
        )
        
        side = "long" if long_cond else "short" if short_cond else "neutral"
        result: ScoringResult = engine.compute_score(factors=factors, side=side)

        if result and result.signal != 'hold':
            planner = ExitPlanner(highs=highs, lows=lows, atr=current_atr_val, close_price=curr_close)
            plan = planner.make_exit_plan(trading_signal=result.signal)
            
            # [Optimization] Momentum Trades often use larger trailing stops
            plan['trailing_stop_active'] = True
            plan['stop_loss_mult'] = 2.0 # Looser stop for momentum
            
            indicators["plan"] = plan

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            date=dates[-1],
            confidence=round(min(1.0, result.score), 3),
            reason=" | ".join(result.reasons),
            ohlcv=ohlcv,
            indicators=indicators,
        )

def make_momentum_presets() -> Dict[str, Dict[str, Any]]:
    """
    Returns presets for Momentum Trend Strategy (OPTIONS OPTIMIZED).
    Focus: Avoiding 'Choppy Momentum' and 'Low Volatility Traps'.
    """
    return {
        "swing_momentum": {
            # ---------------- SWING MOMENTUM (High Octane) ----------------
            # Ideal Strategy: Buying Debit Spreads or Long Calls (21-45 DTE).
            # Goal: Catching the strongest quartile of stocks in an uptrend.
            # Logic: High Risk-Adjusted Momentum + Daily EMA Alignment.
            
            "L": 63,                            # Quarter Lookback
            "ema_fast": 10,                     # Faster trigger for swing
            "ema_slow": 30,                    
            "ht_ema_fast": 13,                  
            "ht_ema_slow": 26,                 
            "adx_period": 14,                  
            "atr_period": 14,                  
            "vol_zscore_window": 20,           
            "vol_zscore_threshold": 1.5,       # Require volume support for High Octane trades.
            "score_threshold": 0.70,
            
            # --- Weights (Velocity Is King) ---
            "weights": {
                "momentum": 0.40,           # Raw Risk-Adj Momentum is the primary driver.
                "trend_strength": 0.20,     # ADX needs to be high (>25).
                "daily_trend": 0.20,        # Must be aligned daily.
                "ht_trend": 0.10,           # Weekly matters less for a 2-week swing.
                "volume": 0.05,
                "confluence": 0.05
            }
        },

        "core_trend": {
            # ---------------- CORE TREND (LEAPS / 60+ DTE) ----------------
            # Ideal Strategy: LEAPS, PMCC (Poor Man's Covered Call), or Wide Spreads.
            # Goal: Portfolio anchoring positions.
            # Logic: Weekly EMA Alignment is non-negotiable.
            
            "L": 126,                           # Half-Year Lookback
            "ema_fast": 50,                    
            "ema_slow": 200,                    # The Golden Cross check
            "ht_ema_fast": 21,                 
            "ht_ema_slow": 50,                  # Strong Weekly Trend confirmation
            "adx_period": 14,
            "atr_period": 14,
            "vol_zscore_window": 60,           
            "vol_zscore_threshold": 1.0,        # Just need steady institutional flow.
            "score_threshold": 0.80,            # Very strict quality control for long-term holds.
            
            # --- Weights (Structure Is King) ---
            "weights": {
                "momentum": 0.25,           # Momentum score is less important than...
                "trend_strength": 0.15,
                "daily_trend": 0.10,
                "ht_trend": 0.40,           # ...WEEKLY TREND STRUCTURE. This is critical for LEAPS.
                "volume": 0.05,
                "confluence": 0.05
            }
        }
    }