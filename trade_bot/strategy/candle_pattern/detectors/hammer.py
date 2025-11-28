
from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class HammerDetector(SingleCandlePatternDetector):
    def __init__(
        self,
        *,
        min_body_ratio: float = 0.10,
        min_lower_shadow_to_body: float = 2.0,
        max_upper_shadow_to_body: float = 0.20,
        require_lower_shadow: bool = True,
        require_upper_shadow: bool = False,
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,
        body_atr_alpha: float = 1.0,
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        min_lower_vs_atr: Optional[float] = None,
        max_upper_vs_atr: Optional[float] = None,
        max_body_vs_atr: Optional[float] = None,
    ):
        self.defaults = dict(
            min_body_ratio=min_body_ratio,
            min_lower_shadow_to_body=min_lower_shadow_to_body,
            max_upper_shadow_to_body=max_upper_shadow_to_body,
            require_lower_shadow=require_lower_shadow,
            require_upper_shadow=require_upper_shadow,
            min_range=min_range, float_tolerance=float_tolerance,
            body_atr_alpha=body_atr_alpha, body_atr_bounds=body_atr_bounds,
            min_lower_vs_atr=min_lower_vs_atr,
            max_upper_vs_atr=max_upper_vs_atr,
            max_body_vs_atr=max_body_vs_atr,
        )

    def detect(self, open_, high, low, close, *, atr: Optional[float] = None, **overrides) -> PatternResult:
        p = {**self.defaults, **overrides}
        if any(x is None for x in (open_, high, low, close)) or high < low:
            return PatternResult(False, None, None, None)

        price_range = high - low
        if price_range <= p["min_range"]:
            return PatternResult(False, None, None, None)

        body = abs(close - open_)
        upper_shadow = max(0.0, high - max(open_, close))
        lower_shadow = max(0.0, min(open_, close) - low)

        body_ratio = body / price_range
        upper_to_body = (upper_shadow / body) if body > 0 else float('inf')
        lower_to_body = (lower_shadow / body) if body > 0 else float('inf')

        effective_min_body_ratio = p["min_body_ratio"]
        body_atr_scaler = None
        if atr and atr > 0:
            lo, hi = p["body_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body_atr_scaler = p["body_atr_alpha"] * (atr / price_range)
            body_atr_scaler = max(lo, min(hi, body_atr_scaler))
            effective_min_body_ratio = p["min_body_ratio"] / body_atr_scaler  # tighten in high vol

        body_ok = body_ratio >= (effective_min_body_ratio * (1 - p["float_tolerance"]))
        lower_shadow_ok = lower_to_body >= (p["min_lower_shadow_to_body"] * (1 - p["float_tolerance"]))
        upper_shadow_ok = upper_to_body <= (p["max_upper_shadow_to_body"] * (1 + p["float_tolerance"]))

        if atr and p["min_lower_vs_atr"]:
            lower_shadow_ok = lower_shadow_ok and (lower_shadow >= p["min_lower_vs_atr"] * atr * (1 - p["float_tolerance"]))
        if atr and p["max_upper_vs_atr"]:
            upper_shadow_ok = upper_shadow_ok and (upper_shadow <= p["max_upper_vs_atr"] * atr * (1 + p["float_tolerance"]))
        if atr and p["max_body_vs_atr"]:
            body_ok = body_ok and (body <= p["max_body_vs_atr"] * atr * (1 + p["float_tolerance"]))

        if p["require_lower_shadow"]:
            lower_shadow_ok = lower_shadow_ok and (lower_shadow > 0.0)
        if p["require_upper_shadow"]:
            upper_shadow_ok = upper_shadow_ok and (upper_shadow > 0.0)

        is_pattern = body_ok and lower_shadow_ok and upper_shadow_ok
        if not is_pattern:
            return PatternResult(False, None, None, None)

        metrics = {
            "body": body, "price_range": price_range,
            "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
            "body_ratio": body_ratio,
            "upper_to_body": upper_to_body, "lower_to_body": lower_to_body,
            "effective_min_body_ratio": effective_min_body_ratio,
            "body_atr_scaler": body_atr_scaler,
            "atr": atr,
            "flags": {
                "body_ok": body_ok,
                "lower_shadow_ok": lower_shadow_ok,
                "upper_shadow_ok": upper_shadow_ok,
            },
            "open": open_, "close": close, "high": high, "low": low,
            "params": self.defaults | {"atr": atr} | overrides,
        }

        return PatternResult(
            is_pattern=True,
            name="Hammer",
            bias="bull",  # pattern bias; in production, condition on trend/location/volume
            metrics=metrics
        )
