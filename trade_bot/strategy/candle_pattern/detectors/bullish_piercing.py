from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult


class PiercingPatternDetector(DoubleCandlePatternDetector):
    """
    Piercing Pattern (bullish, 2-candle):
        - Candle 1 bearish (c1 < o1)
        - Candle 2 bullish (c2 > o2)
        - Candle 2 opens below Candle 1 close (o2 < c1)
        - Candle 2 closes above Candle 1 midpoint but below Candle 1 open
        - [Fix] Added missing logic for upper_wick2_ok and volume_ok
    """
    def __init__(
        self,
        *,
        require_strict_open_below_c1: bool = True,
        require_close_above_midpoint1: bool = True,
        require_close_below_o1: bool = True,
        midpoint_margin_ratio: float = 0.0,
        strength_multiplier_vs_body1: float = 0.80,
        min_body_ratio1: Optional[float] = None,
        min_body_ratio2: Optional[float] = None,
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,
        body2_atr_alpha: float = 1.0,
        body2_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        min_body2_vs_atr: Optional[float] = None,
        require_volume_increase: bool = False,
        max_upper_wick_ratio2: Optional[float] = None,
        min_body1_vs_atr: Optional[float] = None,
    ):
        self.defaults = dict(
            require_strict_open_below_c1=require_strict_open_below_c1,
            require_close_above_midpoint1=require_close_above_midpoint1,
            require_close_below_o1=require_close_below_o1,
            midpoint_margin_ratio=midpoint_margin_ratio,
            strength_multiplier_vs_body1=strength_multiplier_vs_body1,
            min_body_ratio1=min_body_ratio1,
            min_body_ratio2=min_body_ratio2,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body2_atr_alpha=body2_atr_alpha,
            body2_atr_bounds=body2_atr_bounds,
            min_body2_vs_atr=min_body2_vs_atr,
            require_volume_increase=require_volume_increase,
            max_upper_wick_ratio2=max_upper_wick_ratio2,
            min_body1_vs_atr=min_body1_vs_atr,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        *,
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        v1: Optional[float] = None, v2: Optional[float] = None,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Basic hygiene
        if any(x is None for x in (o1, c1, o2, c2)):
            return PatternResult(is_pattern=False)

        first_bearish = c1 < o1
        second_bullish = c2 > o2
        if not (first_bearish and second_bullish):
            return PatternResult(is_pattern=False)

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        if body1 <= p["float_tolerance"] or body2 <= p["float_tolerance"]:
            return PatternResult(is_pattern=False)

        midpoint1 = (o1 + c1) / 2.0

        # Optional ranges
        def valid_range(h, l): return (h is not None) and (l is not None) and (h >= l)
        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        # Fail safely if ranges required but missing
        ranges_required = (p["min_body_ratio1"] is not None and price_range1 is None) or \
                          (p["min_body_ratio2"] is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False)

        # --- ATR Adaptive Logic ---
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body2_atr_scaler = 1.0
        if effective_min_body_ratio2 is not None and price_range2 and atr:
            lo, hi = p["body2_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            raw_scaler = p["body2_atr_alpha"] * (atr / price_range2)
            body2_atr_scaler = max(lo, min(hi, raw_scaler))
            effective_min_body_ratio2 = effective_min_body_ratio2 / body2_atr_scaler

        # Body Ratio Checks
        body_ratio1_ok = True
        if p["min_body_ratio1"] is not None and price_range1:
            body_ratio1_ok = (body1 / price_range1) >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))

        body_ratio2_ok = True
        if effective_min_body_ratio2 is not None and price_range2:
            body_ratio2_ok = (body2 / price_range2) >= (effective_min_body_ratio2 * (1 - p["float_tolerance"]))

        # Core Pattern Logic
        open_below_c1_ok = not p["require_strict_open_below_c1"] or o2 <= c1
        midpoint_ok = not p["require_close_above_midpoint1"] or c2 >= midpoint1 + p["midpoint_margin_ratio"] * body1
        close_below_o1_ok = not p["require_close_below_o1"] or c2 <= o1
        strength_ok = not p["strength_multiplier_vs_body1"] or body2 >= p["strength_multiplier_vs_body1"] * body1

        # ATR Absolute Checks
        atr_body1_ok = True
        if atr and p["min_body1_vs_atr"]:
            atr_body1_ok = body1 >= (p["min_body1_vs_atr"] * atr) * (1 - p["float_tolerance"])

        atr_body2_ok = True
        if atr and p["min_body2_vs_atr"]:
            atr_body2_ok = body2 >= (p["min_body2_vs_atr"] * atr) * (1 - p["float_tolerance"])

        # --- [FIX] Missing Logic Calculation ---
        
        # Upper Wick Check (New)
        upper_wick2_ok = True
        if p["max_upper_wick_ratio2"] is not None:
            if h2 is not None and l2 is not None:
                upper_wick = h2 - max(o2, c2)
                # Ensure body2 is not zero (checked above, but safe practice)
                ratio = upper_wick / body2 if body2 > p["float_tolerance"] else 0.0
                if ratio > p["max_upper_wick_ratio2"] * (1 + p["float_tolerance"]):
                    upper_wick2_ok = False
            else:
                # If constraint exists but data missing, usually fail strict or pass loose. 
                # Here we assume pass if data missing unless critical.
                pass 

        # Volume Check (New)
        volume_ok = True
        if p["require_volume_increase"]:
            if v1 is not None and v2 is not None:
                volume_ok = v2 > v1
            else:
                volume_ok = False
        # ---------------------------------------

        is_pattern = all([
            first_bearish, second_bullish,
            open_below_c1_ok, midpoint_ok, close_below_o1_ok,
            strength_ok, body_ratio1_ok, body_ratio2_ok,
            atr_body1_ok, atr_body2_ok,
            upper_wick2_ok, volume_ok,
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2,
            "midpoint1": midpoint1,
            "body_ratio1": (body1 / price_range1) if price_range1 else None,
            "body_ratio2": (body2 / price_range2) if price_range2 else None,
            "atr": atr,
            "body2_atr_scaler": body2_atr_scaler,
            "effective_min_body_ratio2": effective_min_body_ratio2,
            "params": {**self.defaults, "atr": atr, **overrides}, # Safer dict merge
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "upper_wick_ratio2": ((h2 - max(o2, c2)) / body2) if (h2 and l2 and body2 > 0) else None,
        }

        return PatternResult(
            is_pattern=True,
            name="Piercing Pattern",
            bias="long",
            metrics=metrics
        )