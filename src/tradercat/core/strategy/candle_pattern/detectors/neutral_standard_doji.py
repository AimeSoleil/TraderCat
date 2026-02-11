from typing import Optional, Tuple, Dict, Any
from tradercat.core.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class StandardDojiDetector(SingleCandlePatternDetector):
    """
    Standard Doji (Neutral) - US Stock Optimized:
    - Shape: Looks like a plus sign '+'.
    - Body: Very small (Open ~= Close).
    - Shadows: Significant shadows on BOTH sides.
    - Distinction: Unlike Dragonfly (T) or Gravestone (⊥), the Standard Doji is centered.
    - Psychology: Total equilibrium between Bulls and Bears.
    """
    def __init__(
        self,
        *,
        # --- Body Constraints ---
        # [Optimization] Increased from 0.001 to 0.03 (3%).
        # In US stocks, a "perfect" doji (Open == Close) is rare due to noise.
        # We allow the body to be up to 3% of the total high-low range.
        body_ratio_max: float = 0.03,

        # --- Shadow Constraints (The "Cross" Shape) ---
        require_upper_shadow: bool = True,
        require_lower_shadow: bool = True,

        # [New Optimization] 0.10 (10%).
        # To be a "Standard" Doji (+), it cannot be a Dragonfly or Gravestone.
        # Both upper and lower shadows must be at least 10% of the total range.
        # This ensures the body is somewhat in the middle.
        min_shadow_ratio: float = 0.10,

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Adaptation ---
        atr_scale_alpha: float = 1.0,
        atr_scale_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body_atr_ratio: Optional[float] = None,
    ):
        self.defaults = dict(
            body_ratio_max=body_ratio_max,
            require_upper_shadow=require_upper_shadow,
            require_lower_shadow=require_lower_shadow,
            min_shadow_ratio=min_shadow_ratio,
            min_range=min_range,
            float_tolerance=float_tolerance,
            atr_scale_alpha=atr_scale_alpha,
            atr_scale_bounds=atr_scale_bounds,
            max_body_atr_ratio=max_body_atr_ratio,
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
        
        # Hygiene: Range too small
        price_range = self.get_range(high, low)
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # Components
        body = self.get_body(open_, close)
        upper_shadow = self.get_upper_shadow(open_, high, close)
        lower_shadow = self.get_lower_shadow(open_, low, close)

        body_ratio = body / price_range
        upper_ratio = upper_shadow / price_range
        lower_ratio = lower_shadow / price_range

        # ATR-adaptive threshold calculation
        effective_body_ratio_max = p["body_ratio_max"]
        atr_scaler = 1.0
        
        if atr is not None and atr > 0.0:
            lo, hi = p["atr_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            # If volatility (ATR) is high, we allow a slightly larger body for a Doji (more noise)
            atr_scaler = p["atr_scale_alpha"] * (atr / price_range)
            # Clip scaler
            atr_scaler = max(lo, min(hi, atr_scaler))
            effective_body_ratio_max = p["body_ratio_max"] * atr_scaler

        # 1. Body Size Check
        body_ok = body_ratio <= (effective_body_ratio_max * (1 + p["float_tolerance"]))
        
        # Optional absolute ATR check
        if atr is not None and atr > 0.0 and p["max_body_atr_ratio"]:
            body_ok = body_ok and (body <= (p["max_body_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        # 2. Shadow Presence Check
        if p["require_upper_shadow"] and upper_shadow <= p["min_range"]:
             return PatternResult(is_pattern=False)
        if p["require_lower_shadow"] and lower_shadow <= p["min_range"]:
             return PatternResult(is_pattern=False)

        # 3. Shadow Length Check (The "Cross" shape logic)
        # Prevents Dragonfly/Gravestone from being detected as Standard Doji
        if p["min_shadow_ratio"] > 0:
            if upper_ratio < p["min_shadow_ratio"]:
                return PatternResult(is_pattern=False)
            if lower_ratio < p["min_shadow_ratio"]:
                return PatternResult(is_pattern=False)

        is_pattern = body_ok
        
        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body": body, 
            "price_range": price_range, 
            "body_ratio": body_ratio,
            "upper_ratio": upper_ratio,
            "lower_ratio": lower_ratio,
            "effective_body_ratio_max": effective_body_ratio_max,
            "atr_scaler": atr_scaler,
            "params": {**self.defaults, "atr": atr, **overrides},
        }
        
        return PatternResult(
            is_pattern=True, 
            name="Doji", 
            bias="neutral", 
            metrics=metrics
        )
