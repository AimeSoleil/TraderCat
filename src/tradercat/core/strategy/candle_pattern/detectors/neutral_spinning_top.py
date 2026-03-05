from typing import Optional, Tuple, Dict, Any
from tradercat.core.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class SpinningTopDetector(SingleCandlePatternDetector):
    """
    Spinning Top (Neutral / Indecision) - US Stock Optimized:
    - Shape: Small body centered in the range.
    - Shadows: Both upper and lower shadows are visible and longer than the body.
    - Psychology: Tug-of-war between bulls and bears with no clear winner. Volatility contraction.
    - Distinction: Unlike Hammer/Shooting Star, this pattern requires SYMMETRY.
    """
    def __init__(
        self,
        *,
        # --- Body Size Constraints ---
        # [Optimization] 0.30 (30%). 
        # The body must be small (less than 30% of range), showing lack of conviction.
        body_ratio_max: float = 0.30,
        
        # [Optimization] 0.05 (5%). 
        # Increased from 0.03. We need to distinguish this from a "Doji". 
        # A Spinning Top implies *some* movement, just no winner.
        body_ratio_min: float = 0.05,
        
        # --- Shadow Constraints ---
        # [Optimization] 1.0 (1x). 
        # Shadows must be at least as long as the body. 
        # If shadows are shorter than the body, it's just a "Short Candle", not a Spinning Top.
        min_upper_shadow_to_body: float = 1.0,  
        min_lower_shadow_to_body: float = 1.0,
        
        require_upper_shadow: bool = True,
        require_lower_shadow: bool = True,
        
        # --- Symmetry (Crucial for Neutrality) ---
        # [Optimization] True. 
        # In Algo trading, we must distinguish this from Hammers/Shooting Stars.
        # A Spinning Top must be roughly symmetrical (neutral).
        require_symmetry: bool = True,
        
        # [Optimization] 0.20 (20%). 
        # The difference between Upper and Lower shadow lengths should not exceed 20% of the total range.
        # E.g. If Range=1.00, |Upper - Lower| <= 0.20.
        symmetry_tolerance: float = 0.20, 

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,
        
        # --- ATR Adaptation ---
        body_atr_alpha: float = 1.0,
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body_vs_atr: Optional[float] = None,
        min_upper_vs_atr: Optional[float] = None,
        min_lower_vs_atr: Optional[float] = None,
    ):
        self.defaults = dict(
            body_ratio_max=body_ratio_max,
            body_ratio_min=body_ratio_min,
            min_upper_shadow_to_body=min_upper_shadow_to_body,
            min_lower_shadow_to_body=min_lower_shadow_to_body,
            require_upper_shadow=require_upper_shadow,
            require_lower_shadow=require_lower_shadow,
            require_symmetry=require_symmetry,
            symmetry_tolerance=symmetry_tolerance,
            min_range=min_range, 
            float_tolerance=float_tolerance,
            body_atr_alpha=body_atr_alpha, 
            body_atr_bounds=body_atr_bounds,
            max_body_vs_atr=max_body_vs_atr,
            min_upper_vs_atr=min_upper_vs_atr,
            min_lower_vs_atr=min_lower_vs_atr,
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
        
        # Hygiene
        price_range = self.get_range(high, low)
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # Components
        body = self.get_body(open_, close)
        upper_shadow = self.get_upper_shadow(open_, high, close)
        lower_shadow = self.get_lower_shadow(open_, low, close)
        body_ratio = body / price_range
        
        # ATR-adaptive body ratio bounds
        effective_max_body_ratio = p["body_ratio_max"]
        effective_min_body_ratio = p["body_ratio_min"]
        
        body_atr_scaler = 1.0
        if atr is not None and atr > 0.0:
            lo, hi = p["body_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body_atr_scaler = p["body_atr_alpha"] * (atr / price_range)
            # Clip
            body_atr_scaler = max(lo, min(hi, body_atr_scaler))
            
            # If Volatility is high, we can accept larger bodies as being "indecisive" relative to noise
            effective_max_body_ratio = p["body_ratio_max"] * body_atr_scaler
            
            # If Volatility is high, we require the minimum body to be larger to avoid noise
            effective_min_body_ratio = p["body_ratio_min"] / body_atr_scaler

        # 1. Body Size Check
        # Not too big (Spinning Top) AND Not too small (Doji)
        if body_ratio > (effective_max_body_ratio * (1 + p["float_tolerance"])):
            return PatternResult(is_pattern=False)
            
        if body_ratio < (effective_min_body_ratio * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False) # Likely a Doji

        # 2. Shadow Length Check logic
        # Use body as denom, but guard against tiny body (though min_body_ratio handles most)
        ref_size = body if body > p["min_range"] else p["min_range"]
        
        upper_to_body = upper_shadow / ref_size
        lower_to_body = lower_shadow / ref_size

        if upper_to_body < (p["min_upper_shadow_to_body"] * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)
            
        if lower_to_body < (p["min_lower_shadow_to_body"] * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # 3. Symmetry Check (Neutrality)
        if p["require_symmetry"]:
            diff = abs(upper_shadow - lower_shadow)
            # The difference in wick lengths should be small relative to the total range
            if diff > (p["symmetry_tolerance"] * price_range * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 4. ATR Absolute Checks
        if atr is not None and atr > 0.0:
            if p["max_body_vs_atr"] and body > (p["max_body_vs_atr"] * atr):
                return PatternResult(is_pattern=False)
            if p["min_upper_vs_atr"] and upper_shadow < (p["min_upper_vs_atr"] * atr):
                return PatternResult(is_pattern=False)
            if p["min_lower_vs_atr"] and lower_shadow < (p["min_lower_vs_atr"] * atr):
                return PatternResult(is_pattern=False)

        # 5. Shadow Presence (Strict)
        if p["require_upper_shadow"] and upper_shadow <= p["min_range"]:
            return PatternResult(is_pattern=False)
        if p["require_lower_shadow"] and lower_shadow <= p["min_range"]:
            return PatternResult(is_pattern=False)

        metrics = {
            "body": body, "price_range": price_range,
            "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
            "body_ratio": body_ratio,
            "upper_to_body": upper_to_body, "lower_to_body": lower_to_body,
            "shadow_diff_ratio": abs(upper_shadow - lower_shadow) / price_range,
            "effective_max_body_ratio": effective_max_body_ratio,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(
            is_pattern=True, 
            name="Spinning Top", 
            bias="neutral", 
            metrics=metrics
        )
