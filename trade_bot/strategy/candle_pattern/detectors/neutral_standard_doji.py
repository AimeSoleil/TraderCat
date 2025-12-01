
from typing import Optional, Tuple

from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class StandardDojiDetector(SingleCandlePatternDetector):
    def __init__(
        self,
        *,
        body_ratio_max: float = 0.001,               # 0.1% of range
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
            return PatternResult(False, None, None, None)

        price_range = high - low
        if price_range <= p["min_range"]:
            return PatternResult(False, None, None, None)

        body = abs(close - open_)
        upper_shadow = max(0.0, high - max(open_, close))
        lower_shadow = max(0.0, min(open_, close) - low)

        body_ratio = body / price_range
        upper_ratio = upper_shadow / price_range
        lower_ratio = lower_shadow / price_range

        # ATR-adaptive threshold
        effective_body_ratio_max = p["body_ratio_max"]
        atr_scaler = None
        if atr is not None and atr > 0.0:
            lo, hi = p["atr_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            atr_scaler = p["atr_scale_alpha"] * (atr / price_range)
            atr_scaler = max(lo, min(hi, atr_scaler))
            effective_body_ratio_max = p["body_ratio_max"] * atr_scaler

        body_ok = body_ratio <= (effective_body_ratio_max * (1 + p["float_tolerance"]))
        if atr is not None and atr > 0.0 and p["max_body_atr_ratio"]:
            body_ok = body_ok and (body <= (p["max_body_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        upper_ok = (upper_shadow > 0.0) if p["require_upper_shadow"] else True
        lower_ok = (lower_shadow > 0.0) if p["require_lower_shadow"] else True

        is_pattern = body_ok and upper_ok and lower_ok
        if not is_pattern:
            return PatternResult(False, None, None, None)

        metrics = {
            "body": body, "price_range": price_range, "body_ratio": body_ratio,
            "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
            "upper_ratio": upper_ratio, "lower_ratio": lower_ratio,
            "effective_body_ratio_max": effective_body_ratio_max,
            "atr": atr, "atr_scaler": atr_scaler,
            "body_ok": body_ok, "upper_ok": upper_ok, "lower_ok": lower_ok,
            "open": open_, "close": close, "high": high, "low": low,
            "params": self.defaults | {"atr": atr} | overrides,
        }
        return PatternResult(True, "Doji", "neutral", metrics)
