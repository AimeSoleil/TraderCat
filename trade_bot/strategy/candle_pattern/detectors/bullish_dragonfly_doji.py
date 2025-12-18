from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class DragonflyDojiDetector(SingleCandlePatternDetector):
    """
    Dragonfly Doji (Bullish Reversal) - US Stock Optimized:
    - Shape: 'T' shape. Open, Close, and High are clustered at the top.
    - Psychology: Bears pushed price to a new low, but Bulls forced a close near the open/high. Total rejection of lows.
    - Context: Most effective after a downtrend or a Gap Down.
    """
    def __init__(
        self,
        *,
        # --- Shape Parameters ---
        # [Optimization] 0.03 (3%). 
        # In US Stocks, a "perfect" doji is rare due to noise. 
        # We allow a very small body (e.g., 3 cents on a $100 stock range).
        body_ratio_max: float = 0.03,

        # [Optimization] 0.60 (60%). 
        # The lower shadow must dominate the candle (>60% of range) to show strong rejection.
        lower_shadow_min_ratio: float = 0.60,

        # [Optimization] 0.05 (5%). 
        # A true Dragonfly closes at the highs. If there's a long upper wick, it's a "Spinning Top".
        upper_shadow_max_ratio: float = 0.05,

        require_lower_shadow: bool = True,
        require_upper_shadow: bool = False,
        
        # --- Context Logic (US Stock Specifics) ---
        # [Optimization] Default False for safety, but HIGHLY recommended True in Orchestrator.
        # A Dragonfly is most potent when it gaps down (Bear Trap).
        require_gap_down: bool = False,     

        # [Optimization] Default False. 
        # Rejection on high volume indicates "Capitulation" (Panic selling absorbed by smart money).
        require_high_volume: bool = False,  

        # [Optimization] Default False. 
        # Checks if Low < Prev Low. Essential to filter out range-bound noise.
        require_new_low: bool = False,      

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Adaptation ---
        atr_scale_alpha: float = 1.0,
        atr_scale_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body_atr_ratio: Optional[float] = None,
        min_lower_vs_atr_ratio: Optional[float] = None,
        max_upper_vs_atr_ratio: Optional[float] = None,
    ):
        self.defaults = dict(
            body_ratio_max=body_ratio_max,
            lower_shadow_min_ratio=lower_shadow_min_ratio,
            upper_shadow_max_ratio=upper_shadow_max_ratio,
            require_lower_shadow=require_lower_shadow,
            require_upper_shadow=require_upper_shadow,
            require_gap_down=require_gap_down,
            require_high_volume=require_high_volume,
            require_new_low=require_new_low,
            min_range=min_range,
            float_tolerance=float_tolerance,
            atr_scale_alpha=atr_scale_alpha,
            atr_scale_bounds=atr_scale_bounds,
            max_body_atr_ratio=max_body_atr_ratio,
            min_lower_vs_atr_ratio=min_lower_vs_atr_ratio,
            max_upper_vs_atr_ratio=max_upper_vs_atr_ratio,
        )

    def detect(
        self, 
        open_: float, high: float, low: float, close: float, 
        *, 
        atr: Optional[float] = None, 
        prev_close: Optional[float] = None, 
        prev_low: Optional[float] = None,   
        vol: Optional[float] = None,        
        prev_vol: Optional[float] = None,   
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}
        
        # Basic Data Validation
        if any(x is None for x in (open_, high, low, close)) or high < low:
            return PatternResult(is_pattern=False)

        price_range = high - low
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # Calculate Components
        body = abs(close - open_)
        upper_shadow = max(0.0, high - max(open_, close))
        lower_shadow = max(0.0, min(open_, close) - low)

        body_ratio = body / price_range
        upper_ratio = upper_shadow / price_range
        lower_ratio = lower_shadow / price_range

        # ATR Scaling (Adaptive Strictness)
        # If volatility (ATR) is high, we allow slightly larger bodies.
        effective_body_ratio_max = p["body_ratio_max"]
        atr_scaler = None
        if atr and atr > 0:
            lo, hi = p["atr_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            atr_scaler = p["atr_scale_alpha"] * (atr / price_range)
            atr_scaler = max(lo, min(hi, atr_scaler))
            effective_body_ratio_max = p["body_ratio_max"] * atr_scaler

        # 1. Body Check (Must be small)
        body_ok = body_ratio <= (effective_body_ratio_max * (1 + p["float_tolerance"]))
        if atr and p["max_body_atr_ratio"]:
            body_ok = body_ok and (body <= (p["max_body_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        # 2. Lower Shadow Check (Must be long - The Rejection)
        lower_ok = lower_ratio >= (p["lower_shadow_min_ratio"] * (1 - p["float_tolerance"]))
        if atr and p["min_lower_vs_atr_ratio"]:
            lower_ok = lower_ok and (lower_shadow >= (p["min_lower_vs_atr_ratio"] * atr) * (1 - p["float_tolerance"]))
        if p["require_lower_shadow"]:
            lower_ok = lower_ok and (lower_shadow > 0.0)

        # 3. Upper Shadow Check (Must be tiny - Close near High)
        upper_ok = upper_ratio <= (p["upper_shadow_max_ratio"] * (1 + p["float_tolerance"]))
        if atr and p["max_upper_vs_atr_ratio"]:
            upper_ok = upper_ok and (upper_shadow <= (p["max_upper_vs_atr_ratio"] * atr) * (1 + p["float_tolerance"]))
        if p["require_upper_shadow"]:
            upper_ok = upper_ok and (upper_shadow > 0.0)

        # 4. Gap Check (Bear Trap)
        gap_ok = True
        if p["require_gap_down"]:
            if prev_close is None or open_ >= (prev_close * (1 - p["float_tolerance"])):
                gap_ok = False

        # 5. Volume Check (Capitulation)
        vol_ok = True
        if p["require_high_volume"]:
            if vol is None or prev_vol is None or vol <= prev_vol:
                vol_ok = False

        # 6. New Low Check (Bottom Picking)
        new_low_ok = True
        if p["require_new_low"]:
            if prev_low is None or low >= prev_low:
                new_low_ok = False

        is_pattern = body_ok and lower_ok and upper_ok and gap_ok and vol_ok and new_low_ok

        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body": body, "price_range": price_range,
            "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
            "body_ratio": body_ratio, "upper_ratio": upper_ratio, "lower_ratio": lower_ratio,
            "effective_body_ratio_max": effective_body_ratio_max,
            "atr_scaler": atr_scaler,
            "gap_down": (open_ < prev_close) if prev_close else None,
            "vol_increase": (vol > prev_vol) if (vol and prev_vol) else None,
            "new_low": (low < prev_low) if prev_low else None,
            "params": {**self.defaults, "atr": atr, **overrides},
        }
        
        return PatternResult(
            is_pattern=True, 
            name="Dragonfly Doji", 
            bias="long",
            metrics=metrics
        )
