from typing import Optional, Tuple

from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult


class BearishEngulfingDetector(DoubleCandlePatternDetector):
    """
    Bearish Engulfing (2-candle):
      - Candle 1 bullish (c1 > o1)
      - Candle 2 bearish (c2 < o2)
      - Candle 2 body fully engulfs Candle 1 body (for bullish Candle 1: o2 >= c1 AND c2 <= o1)
      - Optional: strength requirement for body2 vs body1; ATR-aware decisiveness; doji-avoidance
    """
    def __init__(
        self,
        *,
        # Direction requirements
        require_first_bullish: bool = True,
        require_second_bearish: bool = True,

        # Engulfing body overlap semantics
        require_strict_overlap: bool = True,        # Strict: o2 >= c1 and c2 <= o1 (with tolerance)
        overlap_tolerance: float = 1e-9,            # Lenient absolute tolerance when require_strict_overlap=False

        # Strength & decisiveness
        strength_multiplier: float = 1.2,           # body2 >= body1 * multiplier
        decisive_close_margin_ratio: float = 0.0,   # optional: c2 <= o1 - (body1 * margin_ratio)

        # Doji-avoidance (range-based; requires h/l if set)
        min_body_ratio1: Optional[float] = None,    # body1 / range1 >= x  (e.g., 0.03)
        min_body_ratio2: Optional[float] = None,    # body2 / range2 >= y  (e.g., 0.05)

        # Hygiene / numeric robustness
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR-aware constraints (optional)
        body2_atr_alpha: float = 1.0,               # scaler for (ATR / range2)
        body2_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body1_vs_atr: Optional[float] = None,   # cap first body vs ATR (exclude giant bar) e.g., 0.25
        min_body2_vs_atr: Optional[float] = None    # require body2 >= k * ATR (decisive) e.g., 0.30
    ):
        self.defaults = dict(
            require_first_bullish=require_first_bullish,
            require_second_bearish=require_second_bearish,
            require_strict_overlap=require_strict_overlap,
            overlap_tolerance=overlap_tolerance,
            strength_multiplier=strength_multiplier,
            decisive_close_margin_ratio=decisive_close_margin_ratio,
            min_body_ratio1=min_body_ratio1,
            min_body_ratio2=min_body_ratio2,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body2_atr_alpha=body2_atr_alpha,
            body2_atr_bounds=body2_atr_bounds,
            max_body1_vs_atr=max_body1_vs_atr,
            min_body2_vs_atr=min_body2_vs_atr,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        *,
        # Optional highs/lows for range-based checks & ATR scaling
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        # Optional ATR
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Hygiene: require open/close
        if any(x is None for x in (o1, c1, o2, c2)):
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Directions (configurable)
        first_bullish = c1 > o1
        second_bearish = c2 < o2
        if p["require_first_bullish"] and not first_bullish:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)
        if p["require_second_bearish"] and not second_bearish:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Bodies
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        if body1 <= 0 or body2 <= 0:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Engulfing overlap check (body-based)
        if p["require_strict_overlap"]:
            engulf_ok = (o2 >= c1 * (1 - p["float_tolerance"])) and (c2 <= o1 * (1 + p["float_tolerance"]))
        else:
            # Lenient: allow tiny violations using absolute-tolerance band
            engulf_ok = (o2 >= (c1 - abs(c1) * p["overlap_tolerance"])) and \
                        (c2 <= (o1 + abs(o1) * p["overlap_tolerance"]))

        # Strength of second body vs first
        strength_ok = body2 >= body1 * p["strength_multiplier"] * (1 - p["float_tolerance"])

        # Optional decisive close: require c2 below o1 by margin of body1
        decisive_ok = True
        if p["decisive_close_margin_ratio"] and p["decisive_close_margin_ratio"] > 0.0:
            decisive_ok = c2 <= (o1 - body1 * p["decisive_close_margin_ratio"])

        # Optional ranges for ratio checks / ATR scaling
        def valid_range(h: Optional[float], l: Optional[float]) -> bool:
            return (h is not None) and (l is not None) and (h >= l) and ((h - l) > p["min_range"])

        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        # If ratio/ATR constraints requested but ranges missing, fail safely
        ranges_required = (p["min_body_ratio1"] is not None and price_range1 is None) or \
                          (p["min_body_ratio2"] is not None and price_range2 is None) or \
                          (p["min_body2_vs_atr"] is not None and atr is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Doji-avoidance via body/range ratios
        body_ratio1 = (body1 / price_range1) if price_range1 else None
        body_ratio2 = (body2 / price_range2) if price_range2 else None

        body_ratio1_ok = True
        if p["min_body_ratio1"] is not None and body_ratio1 is not None:
            body_ratio1_ok = body_ratio1 >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))

        # ATR-adaptive min body2 ratio (optional)
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body2_atr_scaler = None
        body_ratio2_ok = True
        if price_range2 is not None and p["min_body_ratio2"] is not None:
            if atr is not None and atr > 0.0:
                lo, hi = p["body2_atr_bounds"]
                if hi < lo: lo, hi = hi, lo
                body2_atr_scaler = p["body2_atr_alpha"] * (atr / price_range2)
                body2_atr_scaler = max(lo, min(hi, body2_atr_scaler))
                # Tighten min body2 requirement in high vol
                effective_min_body_ratio2 = p["min_body_ratio2"] / body2_atr_scaler
            body_ratio2_ok = body_ratio2 is not None and (body_ratio2 >= (effective_min_body_ratio2 * (1 - p["float_tolerance"])))

        # ATR absolute constraints (optional)
        atr_body1_ok = True
        atr_body2_ok = True
        if atr is not None and atr > 0.0:
            if p["max_body1_vs_atr"] is not None and p["max_body1_vs_atr"] > 0.0:
                atr_body1_ok = body1 <= (p["max_body1_vs_atr"] * atr) * (1 + p["float_tolerance"])
            if p["min_body2_vs_atr"] is not None and p["min_body2_vs_atr"] > 0.0:
                atr_body2_ok = body2 >= (p["min_body2_vs_atr"] * atr) * (1 - p["float_tolerance"])

        is_pattern = all([
            engulf_ok,
            strength_ok,
            decisive_ok,
            (first_bullish if p["require_first_bullish"] else True),
            (second_bearish if p["require_second_bearish"] else True),
            body_ratio1_ok,
            body_ratio2_ok,
            atr_body1_ok,
            atr_body2_ok,
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        metrics = {
            # Bodies & directions
            "first_bullish": first_bullish,
            "second_bearish": second_bearish,
            "body1": body1,
            "body2": body2,

            # Overlap & strength flags
            "engulf_ok": engulf_ok,
            "strength_ok": strength_ok,
            "decisive_ok": decisive_ok,
            "strength_multiplier": p["strength_multiplier"],
            "require_strict_overlap": p["require_strict_overlap"],
            "decisive_close_margin_ratio": p["decisive_close_margin_ratio"],

            # Ranges & ratios (if provided)
            "price_range1": price_range1,
            "price_range2": price_range2,
            "body_ratio1": body_ratio1,
            "body_ratio2": body_ratio2,
            "body_ratio1_ok": body_ratio1_ok,
            "body_ratio2_ok": body_ratio2_ok,
            "effective_min_body_ratio2": effective_min_body_ratio2,

            # ATR info
            "atr": atr,
            "body2_atr_scaler": body2_atr_scaler,
            "atr_body1_ok": atr_body1_ok,
            "atr_body2_ok": atr_body2_ok,

            # Echo inputs for traceability
            "o1": o1, "c1": c1, "h1": h1, "l1": l1,
            "o2": o2, "c2": c2, "h2": h2, "l2": l2,

            # Params snapshot (logging/debug)
            "params": self.defaults | {"atr": atr} | overrides,
        }

        return PatternResult(
            is_pattern=True,
            name="Bearish Engulfing",
            bias="short",
            metrics=metrics
        )