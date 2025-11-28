
from typing import Optional

from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult


class BullishHaramiDetector(DoubleCandlePatternDetector):
    """
    Bullish Harami (2-candle):
      - Candle 1 bearish (c1 < o1)
      - Candle 2 bullish (c2 > o2)
      - Candle 2 body is inside Candle 1 body (for a bearish Candle 1, inside means: o2 >= c1 and c2 <= o1)
      - Typically appears after a downtrend (trend/location filter recommended externally)
    """
    def __init__(
        self,
        *,
        # Direction requirements
        require_first_bearish: bool = True,
        require_second_bullish: bool = True,

        # "Inside body" semantics
        strict_inside: bool = True,           # Strict inside: o2 >= c1 and c2 <= o1
        inside_tolerance: float = 1e-9,       # Lenient tolerance when strict_inside=False

        # Size constraints (relative and optional)
        max_body2_ratio_vs_body1: float = 0.50,   # body2 <= 50% of body1 (canonical small second body)
        require_small_body2: bool = True,         # enforce the small second body condition

        # Doji-avoidance (range-based; requires h/l if set)
        min_body_ratio1: Optional[float] = None,  # body1 / range1 >= x  (e.g., 0.03)
        max_body_ratio2: Optional[float] = None,  # body2 / range2 <= y  (e.g., 0.30)

        # Hygiene / numeric robustness
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR-aware absolute constraints (optional)
        min_body1_vs_atr: Optional[float] = None, # ensure body1 is not trivial vs ATR (e.g., 0.20)
        max_body2_vs_atr: Optional[float] = None, # cap body2 vs ATR to keep it "small" (e.g., 0.25)
    ):
        self.defaults = dict(
            require_first_bearish=require_first_bearish,
            require_second_bullish=require_second_bullish,
            strict_inside=strict_inside,
            inside_tolerance=inside_tolerance,
            max_body2_ratio_vs_body1=max_body2_ratio_vs_body1,
            require_small_body2=require_small_body2,
            min_body_ratio1=min_body_ratio1,
            max_body_ratio2=max_body_ratio2,
            min_range=min_range,
            float_tolerance=float_tolerance,
            min_body1_vs_atr=min_body1_vs_atr,
            max_body2_vs_atr=max_body2_vs_atr,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        *,
        # Optional highs/lows to enable range-based checks and ATR constraints
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        # Optional ATR
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Basic hygiene (open/close required)
        if any(x is None for x in (o1, c1, o2, c2)):
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Directions (configurable)
        first_bearish = c1 < o1
        second_bullish = c2 > o2
        if p["require_first_bearish"] and not first_bearish:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)
        if p["require_second_bullish"] and not second_bullish:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Bodies
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        if body1 <= 0 or body2 <= 0:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Inside-body check (Harami)
        if p["strict_inside"]:
            # For bearish candle1, the second body must be fully inside the first body
            inside_ok = (o2 >= c1 * (1 - p["float_tolerance"])) and (c2 <= o1 * (1 + p["float_tolerance"]))
        else:
            # Lenient: allow tiny violations using absolute-tolerance band
            inside_ok = (o2 >= (c1 - abs(c1) * p["inside_tolerance"])) and (c2 <= (o1 + abs(o1) * p["inside_tolerance"]))

        # Relative size constraint (small second body)
        strength_ok = True
        if p["require_small_body2"]:
            strength_ok = body2 <= (body1 * p["max_body2_ratio_vs_body1"] * (1 + p["float_tolerance"]))

        # Optional ranges for ratio checks
        def valid_range(h: Optional[float], l: Optional[float]) -> bool:
            return (h is not None) and (l is not None) and (h >= l) and ((h - l) > p["min_range"])

        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        # If ratio/ATR constraints requested but ranges/ATR missing, fail safely
        ranges_required = (p["min_body_ratio1"] is not None and price_range1 is None) or \
                          (p["max_body_ratio2"] is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Doji-avoidance via body/range ratios
        body_ratio1 = (body1 / price_range1) if price_range1 else None
        body_ratio2 = (body2 / price_range2) if price_range2 else None

        body_ratio1_ok = True
        if p["min_body_ratio1"] is not None and body_ratio1 is not None:
            body_ratio1_ok = body_ratio1 >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))

        body_ratio2_ok = True
        if p["max_body_ratio2"] is not None and body_ratio2 is not None:
            body_ratio2_ok = body_ratio2 <= (p["max_body_ratio2"] * (1 + p["float_tolerance"]))

        # ATR-aware constraints (optional)
        atr_body1_ok = True
        atr_body2_ok = True
        if atr is not None and atr > 0.0:
            if p["min_body1_vs_atr"] is not None and p["min_body1_vs_atr"] > 0.0:
                atr_body1_ok = body1 >= (p["min_body1_vs_atr"] * atr) * (1 - p["float_tolerance"])
            if p["max_body2_vs_atr"] is not None and p["max_body2_vs_atr"] > 0.0:
                atr_body2_ok = body2 <= (p["max_body2_vs_atr"] * atr) * (1 + p["float_tolerance"])

        is_pattern = all([
            inside_ok,
            strength_ok,
            (first_bearish if p["require_first_bearish"] else True),
            (second_bullish if p["require_second_bullish"] else True),
            body_ratio1_ok,
            body_ratio2_ok,
            atr_body1_ok,
            atr_body2_ok,
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        metrics = {
            # Bodies & directions
            "first_bearish": first_bearish,
            "second_bullish": second_bullish,
            "body1": body1,
            "body2": body2,

            # Inside/strength flags
            "inside_ok": inside_ok,
            "strength_ok": strength_ok,
            "max_body2_ratio_vs_body1": p["max_body2_ratio_vs_body1"],

            # Ranges & ratios (if provided)
            "price_range1": price_range1,
            "price_range2": price_range2,
            "body_ratio1": body_ratio1,
            "body_ratio2": body_ratio2,
            "body_ratio1_ok": body_ratio1_ok,
            "body_ratio2_ok": body_ratio2_ok,

            # ATR info
            "atr": atr,
            "atr_body1_ok": atr_body1_ok,
            "atr_body2_ok": atr_body2_ok,

            # Echo inputs for traceability
            "o1": o1, "c1": c1, "h1": h1, "l1": l1,
            "o2": o2, "c2": c2, "h2": h2, "l2": l2,

            # Params snapshot (for logging/debug)
            "params": self.defaults | {"atr": atr} | overrides,
        }

        return PatternResult(
            is_pattern=True,
            name="Bullish Harami",
            bias="bull",
            metrics=metrics
        )