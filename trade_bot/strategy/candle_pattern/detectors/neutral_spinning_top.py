from typing import Optional, Tuple

from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class SpinningTopDetector(SingleCandlePatternDetector):
    """
    Spinning Top (Neutral):
    - Small body (but not a Doji).
    - Upper and lower shadows are present and longer than the body.
    - [Fix] Adjusted defaults to avoid mathematical impossibility.
    - [New] Symmetry check to ensure neutrality.
    """
    def __init__(
        self,
        *,
        max_body_ratio: float = 0.30,
        min_body_ratio: float = 0.03,
        
        # Adjusted from 1.5 to 1.0 to allow bodies up to 0.33 range (1+1+1=3)
        min_upper_shadow_to_body: float = 1.0,  
        min_lower_shadow_to_body: float = 1.0,
        
        require_upper_shadow: bool = True,
        require_lower_shadow: bool = True,
        
        # Symmetry: Shadows should be roughly equal for true neutrality
        require_symmetry: bool = False,
        symmetry_tolerance: float = 0.5, # |upper - lower| <= 0.5 * range (loose default)

        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,
        
        body_atr_alpha: float = 1.0,
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body_vs_atr: Optional[float] = None,
        min_upper_vs_atr: Optional[float] = None,
        min_lower_vs_atr: Optional[float] = None,
    ):
        self.defaults = dict(
            max_body_ratio=max_body_ratio,
            min_body_ratio=min_body_ratio,
            min_upper_shadow_to_body=min_upper_shadow_to_body,
            min_lower_shadow_to_body=min_lower_shadow_to_body,
            require_upper_shadow=require_upper_shadow,
            require_lower_shadow=require_lower_shadow,
            require_symmetry=require_symmetry,
            symmetry_tolerance=symmetry_tolerance,
            min_range=min_range, float_tolerance=float_tolerance,
            body_atr_alpha=body_atr_alpha, body_atr_bounds=body_atr_bounds,
            max_body_vs_atr=max_body_vs_atr,
            min_upper_vs_atr=min_upper_vs_atr,
            min_lower_vs_atr=min_lower_vs_atr,
        )

    def detect(self, open_, high, low, close, *, atr: Optional[float] = None, **overrides) -> PatternResult:
        p = {**self.defaults, **overrides}
        if any(x is None for x in (open_, high, low, close)) or high < low:
            return PatternResult(is_pattern=False)

        price_range = high - low
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        body = abs(close - open_)
        upper_shadow = max(0.0, high - max(open_, close))
        lower_shadow = max(0.0, min(open_, close) - low)

        body_ratio = body / price_range
        upper_to_body = (upper_shadow / body) if body > 0 else float('inf')
        lower_to_body = (lower_shadow / body) if body > 0 else float('inf')

        # ATR-adaptive body ratio bounds
        effective_max_body_ratio = p["max_body_ratio"]
        effective_min_body_ratio = p["min_body_ratio"]
        body_atr_scaler = 1.0
        if atr and atr > 0:
            lo, hi = p["body_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body_atr_scaler = p["body_atr_alpha"] * (atr / price_range)
            body_atr_scaler = max(lo, min(hi, body_atr_scaler))
            effective_max_body_ratio = p["max_body_ratio"] * body_atr_scaler
            effective_min_body_ratio = p["min_body_ratio"] / body_atr_scaler

        body_small_ok = body_ratio <= (effective_max_body_ratio * (1 + p["float_tolerance"]))
        body_not_too_small_ok = body_ratio >= (effective_min_body_ratio * (1 - p["float_tolerance"]))
        body_ok = body_small_ok and body_not_too_small_ok

        upper_shadow_ok = upper_to_body >= (p["min_upper_shadow_to_body"] * (1 - p["float_tolerance"]))
        lower_shadow_ok = lower_to_body >= (p["min_lower_shadow_to_body"] * (1 - p["float_tolerance"]))

        # Symmetry Check (New)
        symmetry_ok = True
        if p["require_symmetry"]:
            diff = abs(upper_shadow - lower_shadow)
            symmetry_ok = diff <= (p["symmetry_tolerance"] * price_range)

        # ATR Absolute Checks
        if atr and p["max_body_vs_atr"]:
            body_ok = body_ok and (body <= p["max_body_vs_atr"] * atr * (1 + p["float_tolerance"]))
        if atr and p["min_upper_vs_atr"]:
            upper_shadow_ok = upper_shadow_ok and (upper_shadow >= p["min_upper_vs_atr"] * atr * (1 - p["float_tolerance"]))
        if atr and p["min_lower_vs_atr"]:
            lower_shadow_ok = lower_shadow_ok and (lower_shadow >= p["min_lower_vs_atr"] * atr * (1 - p["float_tolerance"]))

        if p["require_upper_shadow"]:
            upper_shadow_ok = upper_shadow_ok and (upper_shadow > 0.0)
        if p["require_lower_shadow"]:
            lower_shadow_ok = lower_shadow_ok and (lower_shadow > 0.0)

        is_pattern = body_ok and upper_shadow_ok and lower_shadow_ok and symmetry_ok
        
        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body": body, "price_range": price_range,
            "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
            "body_ratio": body_ratio,
            "upper_to_body": upper_to_body, "lower_to_body": lower_to_body,
            "shadow_diff_ratio": abs(upper_shadow - lower_shadow) / price_range,
            "effective_max_body_ratio": effective_max_body_ratio,
            "params": self.defaults | overrides,
        }

        return PatternResult(is_pattern=True, name="Spinning Top", bias="neutral", metrics=metrics)
