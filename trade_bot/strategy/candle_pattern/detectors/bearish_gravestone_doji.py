from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class GravestoneDojiDetector(SingleCandlePatternDetector):
    """
    Gravestone Doji (Bearish Reversal):
    - Open, Close, and Low are near the bottom (inverted 'T').
    - Long upper shadow (rejection of highs).
    - Bias is Bearish.
    - Supports Gap, Volume, and New High checks.
    """
    def __init__(
        self,
        *,
        body_ratio_max: float = 0.001,
        upper_shadow_min_ratio: float = 0.5,
        lower_shadow_max_ratio: float = 0.1,
        require_upper_shadow: bool = True,
        require_lower_shadow: bool = False,
        
        # Context Logic
        require_gap_up: bool = False,       # Open > Prev Close
        require_high_volume: bool = False,  # Vol > Prev Vol
        require_new_high: bool = False,     # High > Prev High (Top picking)

        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,
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
        *, 
        atr: Optional[float] = None, 
        prev_close: Optional[float] = None, 
        prev_high: Optional[float] = None,  # Added for New High check
        vol: Optional[float] = None,        
        prev_vol: Optional[float] = None,   
        **overrides
    ) -> PatternResult:
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
        upper_ratio = upper_shadow / price_range
        lower_ratio = lower_shadow / price_range

        # ATR Scaling
        effective_body_ratio_max = p["body_ratio_max"]
        atr_scaler = None
        if atr and atr > 0:
            lo, hi = p["atr_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            atr_scaler = p["atr_scale_alpha"] * (atr / price_range)
            atr_scaler = max(lo, min(hi, atr_scaler))
            effective_body_ratio_max = p["body_ratio_max"] * atr_scaler

        # 1. Body Check
        body_ok = body_ratio <= (effective_body_ratio_max * (1 + p["float_tolerance"]))
        if atr and p["max_body_atr_ratio"]:
            body_ok = body_ok and (body <= (p["max_body_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        # 2. Upper Shadow Check (Must be long)
        upper_ok = upper_ratio >= (p["upper_shadow_min_ratio"] * (1 - p["float_tolerance"]))
        if atr and p["min_upper_vs_atr_ratio"]:
            upper_ok = upper_ok and (upper_shadow >= (p["min_upper_vs_atr_ratio"] * atr) * (1 - p["float_tolerance"]))
        if p["require_upper_shadow"]:
            upper_ok = upper_ok and (upper_shadow > 0.0)

        # 3. Lower Shadow Check (Must be short/non-existent)
        lower_ok = lower_ratio <= (p["lower_shadow_max_ratio"] * (1 + p["float_tolerance"]))
        if atr and p["max_lower_vs_atr_ratio"]:
            lower_ok = lower_ok and (lower_shadow <= (p["max_lower_vs_atr_ratio"] * atr) * (1 + p["float_tolerance"]))
        if p["require_lower_shadow"]:
            lower_ok = lower_ok and (lower_shadow > 0.0)

        # 4. Gap Check
        gap_ok = True
        if p["require_gap_up"]:
            if prev_close is None or open_ <= prev_close:
                gap_ok = False

        # 5. Volume Check
        vol_ok = True
        if p["require_high_volume"]:
            if vol is None or prev_vol is None or vol <= prev_vol:
                vol_ok = False

        # 6. New High Check (New)
        new_high_ok = True
        if p["require_new_high"]:
            if prev_high is None or high <= prev_high:
                new_high_ok = False

        is_pattern = body_ok and upper_ok and lower_ok and gap_ok and vol_ok and new_high_ok
        
        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body": body, "price_range": price_range,
            "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
            "body_ratio": body_ratio, "upper_ratio": upper_ratio, "lower_ratio": lower_ratio,
            "effective_body_ratio_max": effective_body_ratio_max,
            "atr_scaler": atr_scaler,
            "gap_up": (open_ > prev_close) if prev_close else None,
            "vol_increase": (vol > prev_vol) if (vol and prev_vol) else None,
            "new_high": (high > prev_high) if prev_high else None
        }
        
        return PatternResult(
            is_pattern=True, name="Gravestone Doji", bias="short", metrics=metrics
        )
