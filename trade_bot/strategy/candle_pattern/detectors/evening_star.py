from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, TripeCandlePatternDetector

class EveningStarDetector(TripeCandlePatternDetector):
    """
    Evening Star (bearish, 3-candle):
      - Candle 1 bullish (c1 > o1)
      - Candle 2 small body (indecision)
      - Candle 3 bearish (c3 < o3), closes below Candle 1 midpoint
      - Optional: gap up into C2 and gap down into C3 (textbook variant)
      - Optional: ATR-aware decisiveness for Candle 3
    """
    def __init__(
        self,
        *,
        # Core body-only semantics
        small_body2_ratio_vs_body1: float = 0.50,     # body2 <= body1 * 0.5
        min_body3_ratio_vs_body1: float = 0.80,       # body3 >= body1 * 0.8
        require_c3_below_midpoint1: bool = True,      # c3 <= midpoint(o1, c1)
        midpoint_margin_ratio: float = 0.0,           # extra margin below midpoint: margin = body1 * ratio

        # Overlap / gaps (common on daily equities)
        require_gap_up_into_c2: bool = False,         # gap up into candle 2: o2 > c1
        require_gap_down_into_c3: bool = False,       # gap down into candle 3: o3 < c2
        lenient_overlap_tolerance: float = 1e-9,      # tolerance used for gap checks

        # Indecision checks for candle 2 using its own range (requires h2/l2)
        max_body2_ratio_vs_range2: Optional[float] = 0.30,  # body2 <= 30% of its own range
        min_shadows2_to_body: Optional[float] = None,       # both shadows >= k * body2 (e.g., 1.0)

        # Hygiene / numerical robustness
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR adaptation (optional; requires h3/l3 for range3)
        body3_atr_alpha: float = 1.0,                          # scaler for (ATR / range3)
        body3_atr_bounds: Tuple[float, float] = (0.7, 1.5),    # clamp for scaler
        min_body3_vs_atr: Optional[float] = None               # body3 >= ratio * ATR (e.g., 0.30)
    ):
        self.defaults = dict(
            small_body2_ratio_vs_body1=small_body2_ratio_vs_body1,
            min_body3_ratio_vs_body1=min_body3_ratio_vs_body1,
            require_c3_below_midpoint1=require_c3_below_midpoint1,
            midpoint_margin_ratio=midpoint_margin_ratio,
            require_gap_up_into_c2=require_gap_up_into_c2,
            require_gap_down_into_c3=require_gap_down_into_c3,
            lenient_overlap_tolerance=lenient_overlap_tolerance,
            max_body2_ratio_vs_range2=max_body2_ratio_vs_range2,
            min_shadows2_to_body=min_shadows2_to_body,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body3_atr_alpha=body3_atr_alpha,
            body3_atr_bounds=body3_atr_bounds,
            min_body3_vs_atr=min_body3_vs_atr,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        o3: float, c3: float,
        *,
        # Optional highs/lows for ranges & ATR scaling
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        h3: Optional[float] = None, l3: Optional[float] = None,
        # Optional ATR for decisiveness of candle 3
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Basic hygiene: require open/close; candle 1 bullish, candle 3 bearish
        if any(x is None for x in (o1, c1, o2, c2, o3, c3)):
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        first_bullish = c1 > o1
        third_bearish = c3 < o3
        if not (first_bullish and third_bearish):
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Bodies (body2 can be tiny; body1 and body3 must be positive)
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        body3 = abs(c3 - o3)
        if body1 <= 0 or body3 <= 0:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        midpoint1 = (o1 + c1) / 2.0

        # Helper for range validity
        def valid_range(h: Optional[float], l: Optional[float]) -> bool:
            return (h is not None) and (l is not None) and (h >= l) and ((h - l) > p["min_range"])

        # Optional ranges for candle 2 indecision and candle 3 ATR adaptation
        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None
        price_range3 = (h3 - l3) if valid_range(h3, l3) else None

        # If caller requests ATR/range-based constraints but ranges missing/invalid, fail safely
        ranges_required = (atr is not None and price_range3 is None) or \
                          (p["max_body2_ratio_vs_range2"] is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # --- Core conditions ---

        # (1) Candle 2 small relative to body1
        small2_ok = body2 <= (body1 * p["small_body2_ratio_vs_body1"] * (1 + p["float_tolerance"]))

        # Optional: indecision using candle 2’s own range (if available) & shadow symmetry
        indecision2_ok = True
        shadows2_ok = True
        body_ratio2_vs_range2 = None
        if price_range2 is not None and p["max_body2_ratio_vs_range2"] is not None:
            body_ratio2_vs_range2 = body2 / price_range2
            indecision2_ok = (body_ratio2_vs_range2 <= (p["max_body2_ratio_vs_range2"] * (1 + p["float_tolerance"])))
            if p["min_shadows2_to_body"] is not None and p["min_shadows2_to_body"] > 0.0:
                upper2 = max(0.0, (h2 - max(o2, c2)))
                lower2 = max(0.0, (min(o2, c2) - l2))
                upper2_ok = (upper2 / body2) >= (p["min_shadows2_to_body"] * (1 - p["float_tolerance"])) if body2 > 0 else True
                lower2_ok = (lower2 / body2) >= (p["min_shadows2_to_body"] * (1 - p["float_tolerance"])) if body2 > 0 else True
                shadows2_ok = upper2_ok and lower2_ok

        # (2) Candle 3 closes below midpoint of candle 1 (optionally add margin)
        midpoint_ok = True
        if p["require_c3_below_midpoint1"]:
            margin = (body1 * p["midpoint_margin_ratio"]) if (p["midpoint_margin_ratio"] and p["midpoint_margin_ratio"] > 0.0) else 0.0
            midpoint_ok = c3 <= (midpoint1 - margin * (1 - p["float_tolerance"]))

        # (3) Candle 3 body strength vs body1 (with optional ATR adaptation)
        body3_vs_body1_ok = body3 >= (body1 * p["min_body3_ratio_vs_body1"] * (1 - p["float_tolerance"]))
        body3_atr_scaler = None
        effective_min_body3_ratio_vs_body1 = p["min_body3_ratio_vs_body1"]

        if atr is not None and atr > 0.0 and price_range3 is not None:
            lo, hi = p["body3_atr_bounds"]
            if hi < lo:
                lo, hi = hi, lo
            body3_atr_scaler = p["body3_atr_alpha"] * (atr / price_range3)
            body3_atr_scaler = max(lo, min(hi, body3_atr_scaler))
            # Tighten min body3 requirement in high vol
            effective_min_body3_ratio_vs_body1 = p["min_body3_ratio_vs_body1"] / body3_atr_scaler
            body3_vs_body1_ok = body3 >= (body1 * effective_min_body3_ratio_vs_body1 * (1 - p["float_tolerance"]))

        atr_body3_ok = True
        if atr is not None and atr > 0.0 and p["min_body3_vs_atr"] is not None and p["min_body3_vs_atr"] > 0.0:
            atr_body3_ok = body3 >= (p["min_body3_vs_atr"] * atr) * (1 - p["float_tolerance"])

        # (4) Optional gap semantics (common on daily equities)
        gap_up_ok = True
        gap_down_ok = True
        if p["require_gap_up_into_c2"]:
            # Gap up into candle 2: o2 > c1 with tolerance
            gap_up_ok = o2 >= (c1 * (1 + p["lenient_overlap_tolerance"]))
        if p["require_gap_down_into_c3"]:
            # Gap down into candle 3: o3 < c2 with tolerance
            gap_down_ok = o3 <= (c2 * (1 - p["lenient_overlap_tolerance"]))

        # Final decision
        is_pattern = all([
            first_bullish,
            third_bearish,
            small2_ok,
            indecision2_ok,
            shadows2_ok,
            midpoint_ok,
            body3_vs_body1_ok,
            gap_up_ok,
            gap_down_ok,
            atr_body3_ok,
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Metrics dict for diagnostics/backtests
        metrics = {
            # Bodies & directions
            "first_bullish": first_bullish,
            "third_bearish": third_bearish,
            "body1": body1, "body2": body2, "body3": body3,
            "midpoint1": midpoint1,
            # Ranges (if provided)
            "price_range1": price_range1,
            "price_range2": price_range2,
            "price_range3": price_range3,
            "body_ratio2_vs_range2": body_ratio2_vs_range2,
            # Core flags
            "small2_ok": small2_ok,
            "indecision2_ok": indecision2_ok,
            "shadows2_ok": shadows2_ok,
            "midpoint_ok": midpoint_ok,
            "body3_vs_body1_ok": body3_vs_body1_ok,
            "gap_up_ok": gap_up_ok,
            "gap_down_ok": gap_down_ok,
            # ATR info
            "atr": atr,
            "body3_atr_scaler": body3_atr_scaler,
            "effective_min_body3_ratio_vs_body1": effective_min_body3_ratio_vs_body1,
            "atr_body3_ok": atr_body3_ok,
            # Echo inputs (traceability)
            "o1": o1, "c1": c1, "h1": h1, "l1": l1,
            "o2": o2, "c2": c2, "h2": h2, "l2": l2,
            "o3": o3, "c3": c3, "h3": h3, "l3": l3,
            # Params snapshot (logging/debug)
            "params": self.defaults | {"atr": atr} | overrides,
        }

        return PatternResult(
            is_pattern=True,
            name="Evening Star",
            bias="bear",
            metrics=metrics
        )
