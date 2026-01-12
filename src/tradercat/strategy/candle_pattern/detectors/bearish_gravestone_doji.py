from typing import Optional, Tuple, Dict, Any
from tradercat.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class GravestoneDojiDetector(SingleCandlePatternDetector):
    """
    Gravestone Doji (Bearish Reversal) - US Stock Optimized:
    - Shape: Inverted 'T'. Open, Close, and Low are clustered at the bottom.
    - Psychology: Bulls pushed price to a new high, but Bears forced a close near the open/low. Total rejection of highs.
    - Context: Most effective after an uptrend or a Gap Up (Bull Trap).
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
        # The upper shadow must dominate the candle (>60% of range) to show strong rejection.
        upper_shadow_min_ratio: float = 0.60,

        # [Optimization] 0.05 (5%). 
        # A true Gravestone closes at the lows. If there's a long lower wick, it's a "Spinning Top".
        lower_shadow_max_ratio: float = 0.05,

        require_upper_shadow: bool = True,
        require_lower_shadow: bool = False,
        
        # --- Context Logic (US Stock Specifics) ---
        # [Optimization] Default False for safety, but HIGHLY recommended True in Orchestrator.
        # A Gravestone is most potent when it gaps up (Bull Trap).
        require_gap_up: bool = False,       

        # [Optimization] Default False. 
        # Rejection on high volume indicates a "Blow-off Top" or "Churning".
        require_high_volume: bool = False,  

        # [Optimization] Default False. 
        # Checks if High > Prev High. Essential to filter out range-bound noise.
        require_new_high: bool = False,     

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Adaptation ---
        atr_scale_alpha: float = 1.0,
        atr_scale_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body_atr_ratio: Optional[float] = None,
        min_upper_vs_atr_ratio: Optional[float] = None,
        max_lower_vs_atr_ratio: Optional[float] = None,
    ):
        self.defaults = dict(
            body_ratio_max=body_ratio_max,
            upper_shadow_min_ratio=upper_shadow_min_ratio,
            lower_shadow_max_ratio=lower_shadow_max_ratio,
            require_upper_shadow=require_upper_shadow,
            require_lower_shadow=require_lower_shadow,
            require_gap_up=require_gap_up,
            require_high_volume=require_high_volume,
            require_new_high=require_new_high,
            min_range=min_range,
            float_tolerance=float_tolerance,
            atr_scale_alpha=atr_scale_alpha,
            atr_scale_bounds=atr_scale_bounds,
            max_body_atr_ratio=max_body_atr_ratio,
            min_upper_vs_atr_ratio=min_upper_vs_atr_ratio,
            max_lower_vs_atr_ratio=max_lower_vs_atr_ratio,
        )

    def detect(
        self, 
        open_: float, high: float, low: float, close: float, 
        volume: Optional[float] = None,
        prev_close: Optional[float] = None, 
        prev_high: Optional[float] = None,  
        prev_vol: Optional[float] = None,
        *, 
        atr: Optional[float] = None, 
        **overrides
    ) -> PatternResult:
        p: Dict[str, Any] = {**self.defaults, **overrides}

        # Basic Check: Range
        price_range = self.get_range(high, low)
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # Calculate Components using Base Class Helpers
        body = self.get_body(open_, close)
        upper_shadow = self.get_upper_shadow(open_, high, close)
        lower_shadow = self.get_lower_shadow(open_, low, close)

        body_ratio = body / price_range
        upper_ratio = upper_shadow / price_range
        lower_ratio = lower_shadow / price_range

        # ATR Scaling (Adaptive Strictness)
        # If volatility (ATR) is high, we allow slightly larger bodies (noise tolerance).
        effective_body_ratio_max = p["body_ratio_max"]
        atr_scaler = None
        if atr and atr > 0:
            lo, hi = p["atr_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            atr_scaler = p["atr_scale_alpha"] * (atr / price_range)
            atr_scaler = max(lo, min(hi, atr_scaler))
            effective_body_ratio_max = p["body_ratio_max"] * atr_scaler

        # 1. Body Check (Must be small)
        if body_ratio > (effective_body_ratio_max * (1 + p["float_tolerance"])):
            return PatternResult(is_pattern=False)
            
        if atr and p["max_body_atr_ratio"]:
            if body > ((p["max_body_atr_ratio"] * atr) * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 2. Upper Shadow Check (Must be long - The Rejection)
        if upper_ratio < (p["upper_shadow_min_ratio"] * (1 - p["float_tolerance"])):
             return PatternResult(is_pattern=False)
            
        if atr and p["min_upper_vs_atr_ratio"]:
             if upper_shadow < ((p["min_upper_vs_atr_ratio"] * atr) * (1 - p["float_tolerance"])):
                 return PatternResult(is_pattern=False)
        
        if p["require_upper_shadow"]:
            if upper_shadow <= p["min_range"]:
                return PatternResult(is_pattern=False)

        # 3. Lower Shadow Check (Must be tiny - Close near Low)
        if lower_ratio > (p["lower_shadow_max_ratio"] * (1 + p["float_tolerance"])):
            return PatternResult(is_pattern=False)
            
        if atr and p["max_lower_vs_atr_ratio"]:
            if lower_shadow > ((p["max_lower_vs_atr_ratio"] * atr) * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)
        
        if p["require_lower_shadow"]:
             # If strictly required, it must exist (even if small)
             if lower_shadow <= p["min_range"]: 
                 return PatternResult(is_pattern=False)

        # 4. Context Checks (Fail Fast)
        if p["require_gap_up"]:
            # If data is missing but requirement is strict -> Fail
            if prev_close is None:
                return PatternResult(is_pattern=False)
            if open_ <= (prev_close * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        if p["require_high_volume"]:
            # If data is missing but requirement is strict -> Fail
            if volume is None or prev_vol is None:
                return PatternResult(is_pattern=False)
            if volume <= prev_vol:
                return PatternResult(is_pattern=False)

        if p["require_new_high"]:
            if prev_high is None:
                return PatternResult(is_pattern=False)
            if high <= prev_high:
                return PatternResult(is_pattern=False)

        metrics = {
            "body": body, "price_range": price_range,
            "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
            "body_ratio": body_ratio, "upper_ratio": upper_ratio, "lower_ratio": lower_ratio,
            "effective_body_ratio_max": effective_body_ratio_max,
            "atr_scaler": atr_scaler,
            "gap_up": (open_ > prev_close) if prev_close else None,
            "vol_increase": (volume > prev_vol) if (volume and prev_vol) else None,
            "new_high": (high > prev_high) if prev_high else None,
            "params": {**self.defaults, "atr": atr, **overrides}
        }
        
        return PatternResult(
            is_pattern=True, name="Gravestone Doji", bias="short", metrics=metrics
        )
