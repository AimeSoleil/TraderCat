from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

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
        *,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}
        
        # Hygiene
        if any(x is None for x in (open_, high, low, close)) or high < low:
            return PatternResult(is_pattern=False)

        price_range = high - low
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        body = abs(close - open_)
        upper_shadow = max(0.0, high - max(open_, close))
        lower_shadow = max(0.0, min(open_, close) - low)

        body_ratio = body / price_range
        upper_ratio = upper_shadow / price_range
        lower_ratio = lower_shadow / price_range

        # ATR-adaptive threshold
        effective_body_ratio_max = p["body_ratio_max"]
        atr_scaler = 1.0
        if atr is not None and atr > 0.0:
            lo, hi = p["atr_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            # If volatility is high, we allow a slightly larger body for a Doji
            atr_scaler = p["atr_scale_alpha"] * (atr / price_range)
            atr_scaler = max(lo, min(hi, atr_scaler))
            effective_body_ratio_max = p["body_ratio_max"] * atr_scaler

        # 1. Body Size Check
        body_ok = body_ratio <= (effective_body_ratio_max * (1 + p["float_tolerance"]))
        
        # Optional absolute ATR check
        if atr is not None and atr > 0.0 and p["max_body_atr_ratio"]:
            body_ok = body_ok and (body <= (p["max_body_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        # 2. Shadow Presence Check
        upper_exists = (upper_shadow > 0.0) if p["require_upper_shadow"] else True
        lower_exists = (lower_shadow > 0.0) if p["require_lower_shadow"] else True

        # 3. Shadow Length Check (Ensure "Cross" shape)
        # Prevents Dragonfly/Gravestone from being detected as Standard Doji
        shadows_length_ok = True
        if p["min_shadow_ratio"] > 0:
            shadows_length_ok = (upper_ratio >= p["min_shadow_ratio"]) and \
                                (lower_ratio >= p["min_shadow_ratio"])

        is_pattern = body_ok and upper_exists and lower_exists and shadows_length_ok
        
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
