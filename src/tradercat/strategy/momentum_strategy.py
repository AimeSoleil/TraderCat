from typing import List, Optional, Dict, Any
import statistics

from tradercat.strategy.exit_planner import ExitPlanner
from tradercat.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from tradercat.strategy.trading_strategy import TradingStrategy
from tradercat.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class MomentumTrendStrategy(TradingStrategy):
    """
    Momentum Trend Strategy (Production Grade).
    
    Core Logic:
    1. Risk-Adjusted Momentum (Sharpe-like): Find smooth trends.
    2. Simulated Weekly Trend: Ensure macro alignment.
    3. Volatility Filter: Avoid choppy regimes.
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

        # 4. Trend Logic
        trend_config = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=adx_val_history,
            price_history=closes,
            window=100,
            mode='trend' # We want Strong Trends for Momentum
        )

        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, _ = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

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

        details = {
            "mom_score": round(mom_score, 4),
            "ema_fast": curr_ema_fast,
            "ema_slow": curr_ema_slow,
            "ht_fast": ht_fast,
            "ht_slow": ht_slow,
            "adx": current_adx_val,
            "atr": current_atr_val
        }

        # 5. Scoring
        factors = [
            Factor(
                FactorName.MOMENTUM_CONFIRM, 
                f"Risk-Adj Momentum ({mom_score:.2f})", 
                self.weights["momentum"], 
                long_cond or short_cond
            ),
            Factor(
                FactorName.TREND_STRENGTH, 
                "ADX Strength", 
                self.weights["trend_strength"], 
                trend_config.signal
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
                (long_cond and trend_ht_up and trend_config.signal) or (short_cond and trend_ht_down and trend_config.signal)
            )
        ]

        engine = ScoringEngine(
            base_threshold=self.score_threshold, 
            required_factors=self.support_scoring_factors(),
            determined_factors=[FactorName.MOMENTUM_CONFIRM],
            is_volatility_ok=bool(trend_config.volatility.get('signal', True))
        )
        
        side = "long" if long_cond else "short" if short_cond else "neutral"
        result: ScoringResult = engine.compute_score(factors=factors, side=side)

        if result and result.signal != 'hold':
            planner = ExitPlanner(highs=highs, lows=lows, atr=current_atr_val, close_price=curr_close)
            plan = planner.make_exit_plan(trading_signal=result.signal)
            
            # [Optimization] Momentum Trades often use larger trailing stops
            plan['trailing_stop_active'] = True
            plan['stop_loss_mult'] = 2.0 # Looser stop for momentum
            
            details.update({"plan": plan})

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            date=dates[-1],
            confidence=round(min(1.0, result.score), 3),
            reason=" | ".join(result.reasons),
            details=details,
        )

def make_momentum_presets() -> Dict[str, Dict[str, Any]]:
    """
    Returns a dictionary of all available presets for Momentum Trend Strategy.
    """
    return {
        "swing": {
            "L": 63,                           
            "ema_fast": 20,                     
            "ema_slow": 50,                    
            "ht_ema_fast": 13,                  
            "ht_ema_slow": 26,                 
            "adx_period": 14,                  
            "atr_period": 14,                  
            "vol_zscore_window": 20,           
            "vol_zscore_threshold": 1.0,       
            "score_threshold": 0.70,
            
            # [NEW] Tuned Weights
            "weights": {
                "momentum": 0.35,
                "trend_strength": 0.15,
                "daily_trend": 0.20,
                "ht_trend": 0.20,
                "volume": 0.05,
                "confluence": 0.05
            }
        },

        "position": {
            "L": 126,                          
            "ema_fast": 50,                    
            "ema_slow": 200,                   
            "ht_ema_fast": 21,                 
            "ht_ema_slow": 52,                 
            "adx_period": 14,
            "atr_period": 14,
            "vol_zscore_window": 40,           
            "vol_zscore_threshold": 1.0,       
            "score_threshold": 0.80,
            
            # [NEW] Tuned Weights
            "weights": {
                "momentum": 0.40,      
                "trend_strength": 0.10,
                "daily_trend": 0.15,
                "ht_trend": 0.25,      
                "volume": 0.05,
                "confluence": 0.05
            }
        }
    }