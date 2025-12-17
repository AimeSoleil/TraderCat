from typing import Optional, Tuple

from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class StandardDojiDetector(SingleCandlePatternDetector):
    """
    Standard Doji (Neutral):
    - Body is very small (or zero).
    - Shadows exist on both sides (looks like a cross '+').
    - [Fix] Allows perfect doji (body=0).
    """
    def __init__(
        self,
        *,
        body_ratio_max: float = 0.001,               # 0.1% of range (very strict by default)
        require_upper_shadow: bool = True,
        require_lower_shadow: bool = True,
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,
        atr_scale_alpha: float = 1.0,
        atr_scale_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body_atr_ratio: Optional[float] = None,
    ):
        self.defaults = dict(
            body_ratio_max=body_ratio_max,
            require_upper_shadow=require_upper_shadow,
            require_lower_shadow=require_lower_shadow,
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
        
        # [CRITICAL FIX] Removed the check that rejected body=0. 
        # A Doji body CAN and SHOULD be zero (Open == Close).

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
            atr_scaler = p["atr_scale_alpha"] * (atr / price_range)
            atr_scaler = max(lo, min(hi, atr_scaler))
            effective_body_ratio_max = p["body_ratio_max"] * atr_scaler

        # Core Doji Condition: Body is small enough
        body_ok = body_ratio <= (effective_body_ratio_max * (1 + p["float_tolerance"]))
        
        # Optional absolute ATR check
        if atr is not None and atr > 0.0 and p["max_body_atr_ratio"]:
            body_ok = body_ok and (body <= (p["max_body_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        # Shadow presence (Standard Doji usually implies a cross shape)
        upper_ok = (upper_shadow > 0.0) if p["require_upper_shadow"] else True
        lower_ok = (lower_shadow > 0.0) if p["require_lower_shadow"] else True

        is_pattern = body_ok and upper_ok and lower_ok
        
        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body": body, 
            "price_range": price_range, 
            "body_ratio": body_ratio,
            "upper_ratio": upper_ratio,   # Fix: 将未使用的变量暴露给 metrics
            "lower_ratio": lower_ratio,   # Fix: 将未使用的变量暴露给 metrics
            "effective_body_ratio_max": effective_body_ratio_max,
            "atr_scaler": atr_scaler,
            "params": self.defaults | overrides,
        }
        
        return PatternResult(
            is_pattern=True, 
            name="Doji", 
            bias="neutral", 
            metrics=metrics
        )
