from typing import List, Optional, Dict, Any, Tuple

from tradercat.strategy.exit_planner import ExitPlanner
from tradercat.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from tradercat.strategy.trading_strategy import TradingStrategy
from tradercat.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class FibonacciRetracementStrategy(TradingStrategy):
    """
    Fibonacci Retracement + Breakout Strategy (Production Grade).
    
    Logic:
    1. Identify Major Impulse (Filtered by EMA 200 Trend).
    2. Wait for price to enter "Golden Zone" (e.g. 0.382-0.618).
    3. Trigger: Must have strong confirmation (Engulfing Candle OR RSI Hook OR EMA Reclaim).
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
        # [NEW] Dynamic Weights
        weights: Optional[Dict[str, float]] = None,
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
        
        # [NEW] Dynamic Weights configuration
        default_weights = {
            "zone_trigger": 0.35,   # Price action confirmation
            "trend_match": 0.20,    # Alignment with specific EMA trend
            "adx_strength": 0.15,   # Trend strength
            "momentum": 0.15,       # RSI/MACD hook
            "volume": 0.10,         # Volume confirmation
            "confluence": 0.05      # Bonus factors
        }
        self.weights = {**default_weights, **(weights or {})}
        
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
    ) -> Tuple[float, float]:
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
        
        p1 = fib_levels.get(zone[0], 0.0)
        p2 = fib_levels.get(zone[1], 0.0)
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
        ratios = [-0.236, 0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0, 1.272, 1.618]
        levels = {}
        
        if direction == 'long':
            # Retracement from High down to Low
            for r in ratios:
                levels[r] = swing_high - (diff * r)
        else:
            # Retracement from Low up to High
            for r in ratios:
                levels[r] = swing_low + (diff * r)
                
        return levels

    # ---------- Main Logic ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:        
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(date=None, symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="insufficient data")

        # Data Extraction
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        opens = [float(c.open) for c in candles]
        closes = [float(c.close) for c in candles]
        vols = [float(c.volume) for c in candles]
        dates = [c.date for c in candles]
        curr_close = closes[-1]
        prev_close = closes[-2]

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

        # Trend Filter (EMA 9/21 cross, or similar)
        trend_up = ema_fast_val > ema_slow_val
        trend_down = ema_fast_val < ema_slow_val

        # Swings Detection (Inherited from TradingStrategy)
        slice_start = max(0, len(highs) - self.lookback_swings - 50)
        swings_highs, swings_lows = self._find_fractal_swings(
            highs[slice_start:], lows[slice_start:], self.swing_window
        )
        # Rebase indices
        swings_highs = [(i + slice_start, v) for i, v in swings_highs]
        swings_lows = [(i + slice_start, v) for i, v in swings_lows]

        # Identify Major Impulse
        impulse_type = None 
        impulse_start_val = 0.0
        impulse_end_val = 0.0
        
        last_high = swings_highs[-1] if swings_highs else None
        last_low = swings_lows[-1] if swings_lows else None
        
        if not last_high or not last_low:
            return SignalModel(date=dates[-1], symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="No swings")

        if last_high[0] > last_low[0]:
            impulse_type = 'long' # Low -> High
            impulse_start_val = last_low[1]
            impulse_end_val = last_high[1]
        else:
            impulse_type = 'short' # High -> Low
            impulse_start_val = last_high[1]
            impulse_end_val = last_low[1]

        # Calculate Fibs & Zone
        fib_levels = self._calc_fib_levels(impulse_end_val, impulse_start_val, impulse_type)
        zone_high, zone_low = self._select_fib_zone(
            fib_levels=fib_levels,
            base_fib_low=self.fib_low,
            base_fib_high=self.fib_high,
            pullback_type="auto",
            trend_strength=current_adx_val
        )

        signal_triggered = False
        trigger_reason = ""
        in_zone = zone_low <= curr_close <= zone_high
        
        # [CRITICAL FIX 2] Enhanced Trigger Logic
        # We need "Engulfing" or "RSI Hook" or "EMA Reclaim"
        
        # RSI Hook Logic
        curr_rsi = rsi_val_history[-1] if rsi_val_history else 50
        prev_rsi = rsi_val_history[-2] if len(rsi_val_history) > 1 else 50
        
        if impulse_type == 'long':
            # Bullish Case
            # 1. RSI Hook: Was oversold/low, now ticking up
            rsi_hook = (prev_rsi < 50) and (curr_rsi > prev_rsi)
            
            # 2. Engulfing / Strong Candle: Close > Prev High (stronger than just prev close)
            # Or at least Close > Open AND Close > Prev Close
            is_strong_candle = (curr_close > opens[-1]) and (curr_close > prev_close)
            is_engulfing = (curr_close > highs[-2]) and (curr_close > opens[-1])
            
            # 3. EMA Reclaim (Breakout confirmation)
            ema_reclaim = (curr_close > ema_fast_val)
            
            # Specific trigger combinations
            bounce_type = in_zone and (is_engulfing or (is_strong_candle and rsi_hook))
            breakout_type = (curr_close > zone_low) and ema_reclaim
            
            if bounce_type or breakout_type:
                signal_triggered = True
                trigger_reason = "Fib Long: Bounce/Breakout Confirmed"
                
        elif impulse_type == 'short':
            # Bearish Case
            rsi_hook = (prev_rsi > 50) and (curr_rsi < prev_rsi)
            
            is_strong_candle = (curr_close < opens[-1]) and (curr_close < prev_close)
            is_engulfing = (curr_close < lows[-2]) and (curr_close < opens[-1])
            
            ema_reclaim = (curr_close < ema_fast_val)
            
            bounce_type = in_zone and (is_engulfing or (is_strong_candle and rsi_hook))
            breakout_type = (curr_close < zone_high) and ema_reclaim
            
            if bounce_type or breakout_type:
                signal_triggered = True
                trigger_reason = "Fib Short: Bounce/Breakout Confirmed"

        # Scoring Factors
        # [UPDATED] Trend Strength Check
        # Fibonacci pullbacks naturally cause ADX to dip. 
        # We use 'trend' mode but ignore volatility (pullbacks are often quiet).
        
        trend_strength = self._check_trend_and_volatility(
            atr_val_history, 
            adx_val_history, 
            closes, 
            100, 
            mode='trend',
            ignore_volatility=True,     # [KEY CHANGE]
            trend_quantiles=[0.4, 0.2]  # Relaxed rules
        )
        
        # If trend_match (EMA) is good (calculated elsewhere), we use this relaxed ADX
        is_trend_adx_ok = trend_strength.signal

        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        # [UPDATED] Capture Z-Score for details
        vol_ok, vol_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)
        
        mom_ok = self._momentum_confirm(rsi_val_history, macd_hist_val_history, prefer=impulse_type)
        
        # Trend Direction Confirm
        trend_match = (impulse_type == 'long' and trend_up) or (impulse_type == 'short' and trend_down)

        factors = [
            Factor(FactorName.FIB_ZONE_CONFIRM, trigger_reason, self.weights["zone_trigger"], True),
            Factor(FactorName.TREND_DIRECTION_CONFIRM, "Major Trend Match", self.weights["trend_match"], trend_match),
            # We already have Trend Direction (EMA), so ADX is secondary
            Factor(
                FactorName.TREND_STRENGTH, 
                "ADX Strength", 
                self.weights["adx_strength"], 
                is_trend_adx_ok
            ),
            Factor(FactorName.MOMENTUM_CONFIRM, "Momentum Hook", self.weights["momentum"], mom_ok),
            Factor(FactorName.VOLUME_CONFIRM, "Volume", self.weights["volume"], vol_ok),
            Factor(FactorName.CONFLUENCE_BONUS, "Confluence", self.weights["confluence"], trend_match and mom_ok)
        ]

        engine = ScoringEngine(
            base_threshold=self.score_threshold,
            required_factors=self.support_scoring_factors(),
            determined_factors=[FactorName.FIB_ZONE_CONFIRM],
            # Use volatility Health signal from Pydantic model
            is_volatility_ok=trend_strength.volatility.get("signal", False)
        )
        
        result: ScoringResult = engine.compute_score(factors, side=impulse_type)

        # [UPDATED] Comprehensive Technical Details
        avg_vol = sum(vols[-recent_window:]) / recent_window if recent_window > 0 else 0.0
        rel_vol = (vols[-1] / avg_vol) if avg_vol > 0 else 0.0
        atr_pct = (current_atr_val / curr_close * 100) if curr_close > 0 else 0.0
        current_macd_hist = macd_hist_val_history[-1] if macd_hist_val_history else 0.0
        bar_change_pct = (curr_close - opens[-1]) / opens[-1] * 100 if opens[-1] != 0 else 0.0

        details: Dict[str, Any] = {
            # 基础 OHLCV 上下文
            "open": round(opens[-1], 2),
            "high": round(highs[-1], 2),
            "low": round(lows[-1], 2),
            "close": round(curr_close, 2),
            "volume": round(vols[-1], 0),
            "avg_volume": round(avg_vol, 0),
            "rel_volume": round(rel_vol, 2),
            "vol_zscore": round(vol_z if vol_z is not None else 0.0, 2),
            "bar_change_pct": round(bar_change_pct, 2),

            # 斐波那契结构数据
            "impulse_direction": impulse_type,
            "impulse_start": impulse_start_val,
            "impulse_end": impulse_end_val,
            "fib_zone_low": round(zone_low, 2),
            "fib_zone_high": round(zone_high, 2),
            
            # 趋势指标
            "ema_fast": ema_fast_val,
            "ema_slow": ema_slow_val,
            "adx": round(current_adx_val, 1),
            "trend_match": trend_match,

            # 动量与波动率
            "rsi": round(curr_rsi, 1),
            "macd_hist": round(current_macd_hist, 2),
            "atr": round(current_atr_val, 2),
            "atr_pct": round(atr_pct, 2)
        }

        # If price is above EMA Slow (e.g. 200), we act as if it's a Bull Market.
        # Ignore Short signals derived from minor pullbacks.
        is_bull_context = curr_close > ema_slow_val
        
        if is_bull_context and impulse_type == 'short':
            return SignalModel(date=dates[-1], symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="Counter-trend Short Impulse ignored", details=details)
        
        if not is_bull_context and impulse_type == 'long':
            return SignalModel(date=dates[-1], symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="Counter-trend Long Impulse ignored", details=details)

        # Impulse Strength Validation
        impulse_range = abs(impulse_end_val - impulse_start_val)
        if impulse_range < 2 * current_atr_val:
            return SignalModel(date=dates[-1], symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="Impulse too weak", details=details)

        if not signal_triggered:
            return SignalModel(date=dates[-1], symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="No trigger in zone", details=details)

        if result.signal != 'hold':
            planner = ExitPlanner(highs=highs, lows=lows, atr=current_atr_val, close_price=curr_close)
            plan = planner.make_exit_plan(trading_signal=result.signal)
            
            # [Optimization] Fib Target Extension
            # If we buy at 0.618 retracement, target is often -0.236 extension
            ext_level = fib_levels.get(-0.236, None)
            if ext_level:
                plan['take_profit'] = ext_level
                plan['take_profit_type'] = 'fib_extension_1.236'
                
            # Stop loss just below the 1.0 (start of impulse) is safest but wide
            # A tighter stop is below 0.786
            sl_level = fib_levels.get(0.786, None) # or 1.0 (swing_low/high)
            
            # Default to ExitPlanner stop unless Fib structure is clearer
            fib_stop = sl_level
            
            if fib_stop:
                if impulse_type == 'long':
                    # Use fib stop if it is tighter than ATR stop (don't risk too much), 
                    # OR if ATR stop is too tight, use fib stop?
                    # Usually: Stop below support (Fib) is structural. Stop by ATR is volatility based.
                    # We pick MIN (for long) to be safe (wider stop)? No, we pick MAX (tighter stop) for capital preservation
                    # unless it's too close.
                    # Let's trust ExitPlanner unless Fib level is structurally sensible.
                    plan['fib_stop_loss_at'] = fib_stop
                else:
                    plan['fib_stop_loss_at'] = fib_stop
                plan['fib_stop_loss_at'] = round(plan['fib_stop_loss_at'], 2)
                # We can store it in details for debugging
                details['fib_stop'] = round(fib_stop, 2)

            details["plan"] = plan

        return SignalModel(
            date=dates[-1],
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            # Ensure confidence capped at 1.0
            confidence=round(min(1.0, result.score), 3),
            reason=" | ".join(result.reasons),
            details=details
        )

def make_fibonacci_presets() -> Dict[str, Dict[str, Any]]:
    """
    Returns presets for Fibonacci Retracement Strategy (OPTIONS OPTIMIZED).
    Focus: Precision entries at key structural levels to maximize R:R for options.
    """
    return {
        "trend_pullback": {
            # ---------------- TREND PULLBACK (Delta / Swing Options) ----------------
            # Ideal Strategy: ITM Calls (Delta 0.70) or Bull Call Spreads.
            # Goal: Buying the "First Pullback" in a new trend.
            # Zone: Shallow retracement (0.382 - 0.50).
            
            "lookback_swings": 40,               
            "swing_window": 5,                   
            "fib_zone": (0.382, 0.55),           # Shallow zone. Strong trends don't dip deep.
            "ema_fast": 13,                       
            "ema_slow": 34,                      # Fast alignment check.
            "atr_period": 14,                    
            "rsi_period": 14,                    
            "macd_params": {"fast": 12, "slow": 26, "signal": 9}, 
            "adx_period": 14,                    
            "vol_zscore_window": 20,             
            "vol_zscore_threshold": 0.8,         # Pullbacks normally have LOWER volume. We don't need a surge yet.
            "score_threshold": 0.65,

            # --- Weights (Trend Integrity) ---
            "weights": {
                "zone_trigger": 0.30,       # Hit the zone?
                "trend_match": 0.30,        # Is the trend still up? (Crucial)
                "adx_strength": 0.20,       # ADX must verify the prior impulse was real.
                "momentum": 0.15,           # RSI Hook from oversold.
                "volume": 0.05,             # Volume is less relevant on the dip itself.
                "confluence": 0.00
            }
        },
    
        "golden_zone": {
            # ---------------- GOLDEN ZONE (Deep Value / LEAPS) ----------------
            # Ideal Strategy: LEAPS or Selling Put Spreads (Bullish Bias).
            # Goal: Catching the major structural low.
            # Zone: The "Golden Pocket" (0.618 - 0.786).
            
            "lookback_swings": 100,              
            "swing_window": 10,
            "fib_zone": (0.618, 0.786),          # Deep value zone. "Do or Die" level.
            "ema_fast": 50,
            "ema_slow": 200,                     # Major trend context.
            "atr_period": 14,
            "rsi_period": 14,
            "macd_params": {"fast": 12, "slow": 26, "signal": 9},
            "adx_period": 14,
            "vol_zscore_window": 50,
            "vol_zscore_threshold": 1.5,         # Need institutional buying (volume) to confirm the bottom.
            "score_threshold": 0.75,             # Strict. Buying falling knives is dangerous.
            
            # --- Weights (Structure First) ---
            "weights": {
                "zone_trigger": 0.40,       # Being IN the zone is the most important factor.
                "trend_match": 0.20,        # Still aligned with macro trend?
                "adx_strength": 0.05,       # ADX is likely low/resetting here.
                "momentum": 0.20,           # Divergence often happens here.
                "volume": 0.10,             # Capitulation volume?
                "confluence": 0.05
            }
        }
    }
