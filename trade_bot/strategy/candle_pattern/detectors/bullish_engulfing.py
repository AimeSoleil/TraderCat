
from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class BullishEngulfingDetector(DoubleCandlePatternDetector):
    def __init__(
        self,
        *,
        require_strict_overlap: bool = True,
        strength_multiplier: float = 1.2,
        decisive_close_margin_ratio: float = 0.0,
        min_body_ratio1: Optional[float] = None,
        min_body_ratio2: Optional[float] = None,
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,
        body_atr_alpha: float = 1.0,
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body1_vs_atr: Optional[float] = None,
        min_body2_vs_atr: Optional[float] = None,
    ):
        self.defaults = dict(
            require_strict_overlap=require_strict_overlap,
            strength_multiplier=strength_multiplier,
            decisive_close_margin_ratio=decisive_close_margin_ratio,
            min_body_ratio1=min_body_ratio1,
            min_body_ratio2=min_body_ratio2,
            min_range=min_range, float_tolerance=float_tolerance,
            body_atr_alpha=body_atr_alpha, body_atr_bounds=body_atr_bounds,
            max_body1_vs_atr=max_body1_vs_atr,
            min_body2_vs_atr=min_body2_vs_atr,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        *,
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}
        if any(x is None for x in (o1, c1, o2, c2)):
            return PatternResult()

        first_bearish = c1 < o1
        second_bullish = c2 > o2
        if not (first_bearish and second_bullish):
            return PatternResult()

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        if body1 <= 0 or body2 <= 0:
            return PatternResult()

        # Overlap
        if p["require_strict_overlap"]:
            engulf_ok = (o2 <= c1 * (1 + p["float_tolerance"])) and (c2 >= o1 * (1 - p["float_tolerance"]))
        else:
            engulf_ok = (o2 <= (c1 + abs(c1) * p["float_tolerance"])) and (c2 >= (o1 - abs(o1) * p["float_tolerance"]))

        strength_ok = body2 >= body1 * p["strength_multiplier"] * (1 - p["float_tolerance"])

        decisive_ok = True
        if p["decisive_close_margin_ratio"] and p["decisive_close_margin_ratio"] > 0.0:
            decisive_ok = c2 >= (o1 + body1 * p["decisive_close_margin_ratio"])

        # Optional body ratios if ranges provided
        price_range1 = None; body_ratio1 = None
        price_range2 = None; body_ratio2 = None
        ranges_ok = True

        if (h1 is not None) and (l1 is not None):
            if h1 < l1: ranges_ok = False
            else:
                price_range1 = h1 - l1
                if price_range1 <= p["min_range"]: ranges_ok = False
                else: body_ratio1 = body1 / price_range1

        if (h2 is not None) and (l2 is not None):
            if h2 < l2: ranges_ok = False
            else:
                price_range2 = h2 - l2
                if price_range2 <= p["min_range"]: ranges_ok = False
                else: body_ratio2 = body2 / price_range2

        if not ranges_ok and (p["min_body_ratio1"] is not None or p["min_body_ratio2"] is not None or atr is not None):
            return PatternResult()

        body_ratio1_ok = True
        body_ratio2_ok = True
        effective_min_body_ratio2 = p["min_body_ratio2"]

        body_atr_scaler = None
        if price_range2 is not None and p["min_body_ratio2"] is not None:
            if atr and atr > 0:
                lo, hi = p["body_atr_bounds"]
                if hi < lo: lo, hi = hi, lo
                body_atr_scaler = p["body_atr_alpha"] * (atr / price_range2)
                body_atr_scaler = max(lo, min(hi, body_atr_scaler))
                effective_min_body_ratio2 = p["min_body_ratio2"] / body_atr_scaler
            body_ratio2_ok = body_ratio2 is not None and (body_ratio2 >= (effective_min_body_ratio2 * (1 - p["float_tolerance"])))

        if price_range1 is not None and p["min_body_ratio1"] is not None:
            body_ratio1_ok = body_ratio1 is not None and (body_ratio1 >= (p["min_body_ratio1"] * (1 - p["float_tolerance"])))

        atr_body1_ok = True
        atr_body2_ok = True
        if atr and atr > 0:
            if p["max_body1_vs_atr"]:
                atr_body1_ok = body1 <= (p["max_body1_vs_atr"] * atr) * (1 + p["float_tolerance"])
            if p["min_body2_vs_atr"]:
                atr_body2_ok = body2 >= (p["min_body2_vs_atr"] * atr) * (1 - p["float_tolerance"])

        is_pattern = all([
            engulf_ok, strength_ok, decisive_ok,
            body_ratio1_ok, body_ratio2_ok,
            atr_body1_ok, atr_body2_ok
        ])
        if not is_pattern:
            return PatternResult()

        metrics = {
            "o1": o1, "c1": c1, "h1": h1, "l1": l1,
            "o2": o2, "c2": c2, "h2": h2, "l2": l2,
            "body1": body1, "body2": body2,
            "price_range1": price_range1, "price_range2": price_range2,
            "body_ratio1": body_ratio1, "body_ratio2": body_ratio2,
            "engulf_ok": engulf_ok, "strength_ok": strength_ok, "decisive_ok": decisive_ok,
            "min_body_ratio1": p["min_body_ratio1"],
            "min_body_ratio2": p["min_body_ratio2"],
            "effective_min_body_ratio2": effective_min_body_ratio2,
            "atr": atr, "body_atr_scaler": body_atr_scaler,
            "atr_body1_ok": atr_body1_ok, "atr_body2_ok": atr_body2_ok,
            "params": self.defaults | {"atr": atr} | overrides,
        }
        return PatternResult(True, "Bullish Engulfing", "bull", metrics)
