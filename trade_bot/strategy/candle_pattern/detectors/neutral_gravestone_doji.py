
from typing import Optional, Tuple

from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class GravestoneDojiDetector(SingleCandlePatternDetector):
    def __init__(
        self,
        *,
        body_ratio_max: float = 0.001,
        upper_shadow_min_ratio: float = 0.5,
        lower_shadow_max_ratio: float = 0.1,
        require_upper_shadow: bool = True,
        require_lower_shadow: bool = False,
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
            min_range=min_range, float_tolerance=float_tolerance,
            atr_scale_alpha=atr_scale_alpha, atr_scale_bounds=atr_scale_bounds,
            max_body_atr_ratio=max_body_atr_ratio,
            min_upper_vs_atr_ratio=min_upper_vs_atr_ratio,
            max_lower_vs_atr_ratio=max_lower_vs_atr_ratio,
        )

    def detect(self, open_, high, low, close, *, atr: Optional[float] = None, **overrides) -> PatternResult:
        p = {**self.defaults, **overrides}
        if any(x is None for x in (open_, high, low, close)) or high < low:
            return PatternResult()

        price_range = high - low
        if price_range <= p["min_range"]:
            return PatternResult()

        body = abs(close - open_)
        upper_shadow = max(0.0, high - max(open_, close))
        lower_shadow = max(0.0, min(open_, close) - low)

        body_ratio = body / price_range
        upper_ratio = upper_shadow / price_range
        lower_ratio = lower_shadow / price_range

        effective_body_ratio_max = p["body_ratio_max"]
        atr_scaler = None
        if atr and atr > 0:
            lo, hi = p["atr_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            atr_scaler = p["atr_scale_alpha"] * (atr / price_range)
            atr_scaler = max(lo, min(hi, atr_scaler))
            effective_body_ratio_max = p["body_ratio_max"] * atr_scaler

        body_ok = body_ratio <= (effective_body_ratio_max * (1 + p["float_tolerance"]))
        if atr and p["max_body_atr_ratio"]:
            body_ok = body_ok and (body <= (p["max_body_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        upper_ok = upper_ratio >= (p["upper_shadow_min_ratio"] * (1 - p["float_tolerance"]))
        if atr and p["min_upper_vs_atr_ratio"]:
            upper_ok = upper_ok and (upper_shadow >= (p["min_upper_vs_atr_ratio"] * atr) * (1 - p["float_tolerance"]))
        if p["require_upper_shadow"]:
            upper_ok = upper_ok and (upper_shadow > 0.0)

        lower_ok = lower_ratio <= (p["lower_shadow_max_ratio"] * (1 + p["float_tolerance"]))
        if atr and p["max_lower_vs_atr_ratio"]:
            lower_ok = lower_ok and (lower_shadow <= (p["max_lower_vs_atr_ratio"] * atr) * (1 + p["float_tolerance"]))
        if p["require_lower_shadow"]:
            lower_ok = lower_ok and (lower_shadow > 0.0)

        is_pattern = body_ok and upper_ok and lower_ok
        if not is_pattern:
            return PatternResult()

        metrics = {
            "body": body, "price_range": price_range,
            "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
            "body_ratio": body_ratio, "upper_ratio": upper_ratio, "lower_ratio": lower_ratio,
            "effective_body_ratio_max": effective_body_ratio_max,
            "atr": atr, "atr_scaler": atr_scaler,
            "body_ok": body_ok, "upper_ok": upper_ok, "lower_ok": lower_ok,
            "open": open_, "close": close, "high": high, "low": low,
            "params": self.defaults | {"atr": atr} | overrides,
        }
        return PatternResult(True, "Gravestone Doji", "neutral", metrics)
