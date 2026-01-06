from typing import List, Optional, Dict, Any, Tuple
import math
import statistics

from tradercat.strategy.strategy_presets import StrategyPreset
from tradercat.strategy.exit_planner import ExitPlanner
from tradercat.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from tradercat.strategy.trading_strategy import TradingStrategy
from tradercat.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class FibonacciRetracementStrategy(TradingStrategy):
    """
    Fibonacci Retracement + Breakout Strategy (Refactored)
    
    Key Improvements:
    - Fix: Strict direction enforcement based on impulse type (Long Impulse -> Only Long signals).
    - Fix: Removed premature 'in_zone' entry; requires confirmation (breakout or bounce).
    - Improvement: Added impulse strength validation (must be > 2 ATR).
    """

    def __init__(
        self,
        lookback_swings: int = 30,
        swing_window: int = 4,
        fib_zone: Tuple[float, float] = (0.382, 0.618),
        ema_fast: int = 13,
        ema_slow: int = 34,
        atr_period: int = 14,
        rsi_period: int = 14,
        macd_params: Optional[Dict[str, int]] = None,
        adx_period: int = 14,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.6,
        data_provider: Any = None,
    ):
        self.lookback_swings = int(lookback_swings)
        self.swing_window = max(1, int(swing_window))
        self.fib_low = float(fib_zone[0])
        self.fib_high = float(fib_zone[1])
        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.atr_period = int(atr_period)
        self.rsi_period = int(rsi_period)
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.adx_period = adx_period
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # Fields
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"

    def get_name(self) -> str:
        return "FibonacciRetracement"

    def get_lookback_window(self) -> int:
        return (
            max(
                self.lookback_swings,
                self.ema_slow,
                self.atr_period,
                (self.macd_params["slow"] or 0),
            )
            + 10
        )

    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.FIB_ZONE_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.VOLUME_CONFIRM,
            FactorName.MOMENTUM_CONFIRM,
            FactorName.TREND_DIRECTION_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

    # -------------- Helper Functions --------------
    def _select_fib_zone(
        self,
        fib_levels: Dict[float, float],
        base_fib_low=0.382,
        base_fib_high=0.618,
        pullback_type="auto",
        trend_strength=None,
    ):
        if not fib_levels:
            raise ValueError("Missing fib_levels")
        
        shallow_zone = (base_fib_low, 0.5)
        deep_zone = (0.5, base_fib_high)

        if pullback_type == "auto":
            if trend_strength and trend_strength > 25:
                zone = shallow_zone
            else:
                zone = deep_zone
        elif pullback_type == "shallow":
            zone = shallow_zone
        elif pullback_type == "deep":
            zone = deep_zone
        else:
            zone = (base_fib_low, base_fib_high)
        
        # Ensure we return High/Low values correctly regardless of trend direction
        # fib_levels dict keys are ratios.
        # For Uptrend: 0.0 is High, 1.0 is Low. Retracement 0.382 is closer to High.
        # For Downtrend: 0.0 is Low, 1.0 is High. Retracement 0.382 is closer to Low.
        # The _calc_fib_levels function handles the math, so fib_levels[0.382] is the price level.
        
        # We just need to return the price range.
        p1 = fib_levels[zone[0]]
        p2 = fib_levels[zone[1]]
        return max(p1, p2), min(p1, p2)

    def _calc_fib_levels(
        self, swing_high: float, swing_low: float, direction: str
    ) -> Dict[float, float]:
        """
        Calculate Fib levels.
        Direction 'long' (Uptrend Impulse): Low -> High. Retracement goes down from High.
        Direction 'short' (Downtrend Impulse): High -> Low. Retracement goes up from Low.
        """
        diff = abs(swing_high - swing_low)
        ratios = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
        levels = {}
        
        if direction == 'long':
            # Retracement from High down to Low
            # 0.0 is Swing High, 1.0 is Swing Low
            for r in ratios:
                levels[r] = swing_high - (diff * r)
        else:
            # Retracement from Low up to High
            # 0.0 is Swing Low, 1.0 is Swing High
            for r in ratios:
                levels[r] = swing_low + (diff * r)
                
        return levels

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        logger.info(f"🔍 Generating Fibonacci Retracement signal for {symbol}...")
        
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="insufficient data")

        # Data Extraction
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        opens = [float(c.open) for c in candles]
        closes = [float(c.close) for c in candles]
        vols = [float(c.volume) for c in candles]
        dates = [c.date for c in candles]
        curr_close = closes[-1]

        # Indicators
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params)
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        rsi_val_history = [getattr(r, self.rsi_field, None) for r in rsi_series]
        macd_hist_val_history = [getattr(m, self.macd_hist_field, None) for m in macd_series] if macd_series else []
        
        current_atr_val = atr_val_history[-1] if atr_val_history else 0.0
        current_adx_val = adx_val_history[-1] if adx_val_history else 0.0
        
        ema_fast_val = getattr(ema_fast_series[-1], self.ema_fast_field, 0)
        ema_slow_val = getattr(ema_slow_series[-1], self.ema_slow_field, 0)

        # Trend Filter
        trend_up = ema_fast_val > ema_slow_val
        trend_down = ema_fast_val < ema_slow_val

        # Swings Detection
        # Use a slice for efficiency
        slice_start = max(0, len(highs) - self.lookback_swings - 50)
        swings_highs, swings_lows = self._find_fractal_swings(
            highs[slice_start:], lows[slice_start:], self.swing_window
        )
        # Rebase indices
        swings_highs = [(i + slice_start, v) for i, v in swings_highs]
        swings_lows = [(i + slice_start, v) for i, v in swings_lows]

        # Identify Impulse
        # We need the most recent completed impulse.
        # Long Impulse: Low -> High
        # Short Impulse: High -> Low
        
        impulse_type = None # 'long' or 'short'
        impulse_start_val = 0.0
        impulse_end_val = 0.0
        
        # Find latest swing points
        last_high = swings_highs[-1] if swings_highs else None
        last_low = swings_lows[-1] if swings_lows else None
        
        if not last_high or not last_low:
            return SignalModel(date=dates[-1], symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="No swings")

        # Determine which impulse is more recent/relevant
        # If Last High index > Last Low index -> Potential Long Impulse (Low -> High)
        # If Last Low index > Last High index -> Potential Short Impulse (High -> Low)
        
        if last_high[0] > last_low[0]:
            impulse_type = 'long'
            impulse_start_val = last_low[1]
            impulse_end_val = last_high[1]
        else:
            impulse_type = 'short'
            impulse_start_val = last_high[1]
            impulse_end_val = last_low[1]

        # [Improvement] Impulse Validation
        # Impulse must be significant (> 2 * ATR)
        impulse_range = abs(impulse_end_val - impulse_start_val)
        if impulse_range < 2 * current_atr_val:
            return SignalModel(date=dates[-1], symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="Impulse too weak")

        # Calculate Fibs
        fib_levels = self._calc_fib_levels(impulse_end_val, impulse_start_val, impulse_type) # Note arg order
        
        # Select Zone
        zone_high, zone_low = self._select_fib_zone(
            fib_levels=fib_levels,
            base_fib_low=self.fib_low,
            base_fib_high=self.fib_high,
            pullback_type="auto",
            trend_strength=current_adx_val
        )

        # Logic Check
        # Long: Price retraced into zone, then breaks UP above zone_high (or bounces)
        # Short: Price retraced into zone, then breaks DOWN below zone_low (or bounces)
        
        signal_triggered = False
        trigger_reason = ""
        
        # Check if price is currently inside or just broke out of the zone in the trend direction
        in_zone = zone_low <= curr_close <= zone_high
        
        if impulse_type == 'long':
            # Retracement is downward. Zone High is 0.382 (higher price), Zone Low is 0.618 (lower price).
            # We want to buy if price stabilizes in zone and starts moving up.
            # Trigger: Price > Zone High (Breakout of shallow retracement) OR Price bounces from Zone Low
            
            # [Fix] Don't buy just because 'in_zone'. Wait for momentum up.
            # Simple trigger: Price closes above Zone High (0.382 level) after being inside/below?
            # Or Price > EMA Fast while in zone?
            
            # Let's use: Breakout of Zone High (0.382) implies retracement is over.
            # OR: Price is in zone AND Candle is Green AND RSI hooking up.
            
            # [Optimization] Breakout Confirmation
            # Instead of just Close > Zone High, we can require Close > EMA Fast (9).
            # This confirms that short-term momentum has realigned with the major trend.
            
            # breakout_confirm = curr_close > zone_high  <-- Old logic (can be too late if zone is wide)
            
            # New Logic:
            # 1. Price is above the "Deep" part of the zone (e.g. > 0.618 level in uptrend)
            # 2. Price reclaims the Fast EMA (9)
            
            breakout_confirm = (curr_close > zone_low) and (curr_close > ema_fast_val)
            
            # Bounce confirm remains useful for early entry
            bounce_confirm = in_zone and (curr_close > closes[-2]) and (curr_close > opens[-1]) # Green candle
            
            if breakout_confirm or bounce_confirm:
                signal_triggered = True
                trigger_reason = "Fib Bounce/Breakout Long"
                
        elif impulse_type == 'short':
            # Retracement is upward. Zone High is 0.618 (higher price), Zone Low is 0.382 (lower price).
            # We want to sell if price stabilizes and starts moving down.
            
            breakout_confirm = curr_close < zone_low
            bounce_confirm = in_zone and (curr_close < closes[-2])
            
            if breakout_confirm or bounce_confirm:
                signal_triggered = True
                trigger_reason = "Fib Bounce/Breakout Short"

        if not signal_triggered:
            return SignalModel(date=dates[-1], symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="No trigger in zone")

        # Scoring
        trend_strength = self._check_trend_and_volatility(
            atr_val_history, adx_val_history, closes, 100, mode='trend'
        )
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, _ = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)
        mom_ok = self._momentum_confirm(rsi_val_history, macd_hist_val_history, prefer=impulse_type)
        
        # Trend Direction Confirm: Major trend (EMA) should match Impulse
        trend_match = (impulse_type == 'long' and trend_up) or (impulse_type == 'short' and trend_down)

        factors = [
            Factor(FactorName.FIB_ZONE_CONFIRM, trigger_reason, 0.35, True),
            Factor(FactorName.TREND_DIRECTION_CONFIRM, "Major Trend Match", 0.20, trend_match),
            Factor(FactorName.TREND_STRENGTH, "ADX Strength", 0.15, trend_strength.signal),
            Factor(FactorName.MOMENTUM_CONFIRM, "Momentum Hook", 0.15, mom_ok),
            Factor(FactorName.VOLUME_CONFIRM, "Volume", 0.10, vol_ok),
            Factor(FactorName.CONFLUENCE_BONUS, "Bonus", 0.05, trend_match and mom_ok)
        ]

        engine = ScoringEngine(
            base_threshold=self.score_threshold,
            required_factors=[FactorName.FIB_ZONE_CONFIRM],
            determined_factors=[FactorName.FIB_ZONE_CONFIRM],
            is_volatility_ok=trend_strength.volatility['signal']
        )
        
        result: ScoringResult = engine.compute_score(factors, side=impulse_type)

        details = {
            "impulse": impulse_type,
            "zone": (zone_low, zone_high),
            "curr": curr_close,
            "atr": current_atr_val
        }

        if result.signal != 'hold':
            planner = ExitPlanner(highs=highs, lows=lows, atr=current_atr_val, close_price=curr_close)
            plan = planner.make_exit_plan(trading_signal=result.signal)
            details["plan"] = plan

        return SignalModel(
            date=dates[-1],
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            confidence=round(result.score, 3),
            reason=" | ".join(result.reasons),
            details=details
        )

def make_fibonacci_presets(preset: StrategyPreset) -> Dict[str, Any]:
    """
    Fibonacci retracement strategy presets based on algo trading best practices:
    - swing: Optimized for "Buy the Dip" in established trends.
    """

    if preset == "swing":
        # ---------------- SWING TRADING (Optimized) ----------------
        return {
            # --- Swing Detection ---
            # 5 bars (1 week) is standard for identifying significant swing points.
            "lookback_swings": 40,               # Look back ~2 months to find the major impulse.
            "swing_window": 5,                   

            # --- Fib Zone ---
            # The "Golden Pocket" is between 0.5 and 0.618. 
            # But for strong trends, 0.382 is common. We keep the wide zone.
            "fib_zone": (0.382, 0.618),          

            # --- Trend Filter ---
            # Use 9/21 EMA. Price should be respecting the 21 EMA in a healthy swing trend.
            "ema_fast": 9,                       
            "ema_slow": 21,                      

            # --- Indicators ---
            "atr_period": 14,                    
            "rsi_period": 14,                    
            "macd_params": {"fast": 12, "slow": 26, "signal": 9}, 
            "adx_period": 14,                    

            # --- Volume Confirmation ---
            # The bounce from the Fib level needs volume validation.
            "vol_zscore_window": 20,             
            "vol_zscore_threshold": 1.5,         

            # --- Scoring ---
            # Set to 0.65. We need Trend + Fib Level + Bounce Confirmation.
            "score_threshold": 0.65               
        }
    
    elif preset == "position":
        return { }
    
    elif preset == "scalp":
        return { }

    else:
        raise ValueError(f"Unknown preset: {preset}")
