from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class DarkCloudCoverDetector(DoubleCandlePatternDetector):
    """
    Dark Cloud Cover (bearish, 2-candle) - Production Grade:
        - Candle 1: Bullish.
        - Candle 2: Bearish.
        - Gap Up: Candle 2 opens above Candle 1 close.
        - Penetration: Candle 2 closes below Candle 1 midpoint.
        - Not Engulfing: Candle 2 closes above Candle 1 open.
        - [New] Volume & Wick confirmation.
    """
    def __init__(
        self,
        *,
        # Direction requirements
        require_first_bullish: bool = True,
        require_second_bearish: bool = True,

        # Gap & midpoint semantics
        require_gap_up_into_c2: bool = True,         # Default True (Equities). Set False for Crypto/Forex.
        gap_tolerance: float = 1e-9,                 
        require_close_below_midpoint1: bool = True,  
        require_close_above_o1: bool = True,         # If False, it overlaps with Bearish Engulfing
        midpoint_margin_ratio: float = 0.0,          

        # Strength constraint (relative)
        min_body2_ratio_vs_body1: float = 0.80,      
        require_strong_body2: bool = True,

        # Volume Logic
        require_volume_increase: bool = False,       # Vol2 > Vol1

        # Wick Logic (Rejection)
        min_upper_wick_ratio_c2: Optional[float] = None, # e.g. 0.1 means upper wick >= 10% of body

        # Doji-avoidance
        min_body_ratio1: Optional[float] = None,     
        min_body_ratio2: Optional[float] = None,     

        # Hygiene
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR-aware constraints
        body2_atr_alpha: float = 1.0,                
        body2_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body1_vs_atr: Optional[float] = None,    
        min_body2_vs_atr: Optional[float] = None     
    ):
        self.defaults = dict(
            require_first_bullish=require_first_bullish,
            require_second_bearish=require_second_bearish,
            require_gap_up_into_c2=require_gap_up_into_c2,
            gap_tolerance=gap_tolerance,
            require_close_below_midpoint1=require_close_below_midpoint1,
            require_close_above_o1=require_close_above_o1,
            midpoint_margin_ratio=midpoint_margin_ratio,
            min_body2_ratio_vs_body1=min_body2_ratio_vs_body1,
            require_strong_body2=require_strong_body2,
            require_volume_increase=require_volume_increase,
            min_upper_wick_ratio_c2=min_upper_wick_ratio_c2,
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
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        v1: Optional[float] = None, v2: Optional[float] = None,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Hygiene
        if any(x is None for x in (o1, c1, o2, c2)):
            return PatternResult(is_pattern=False)

        # Directions
        first_bullish = c1 > o1
        second_bearish = c2 < o2
        if p["require_first_bullish"] and not first_bullish:
            return PatternResult(is_pattern=False)
        if p["require_second_bearish"] and not second_bearish:
            return PatternResult(is_pattern=False)

        # Bodies
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        # Use tolerance instead of hard 0 check
        if body1 <= p["float_tolerance"] or body2 <= p["float_tolerance"]:
            return PatternResult(is_pattern=False)

        midpoint1 = (o1 + c1) / 2.0

        # (1) Gap up into candle 2
        gap_up_ok = True
        if p["require_gap_up_into_c2"]:
            gap_up_ok = o2 >= (c1 * (1 + p["gap_tolerance"]))

        # (2) Close below midpoint of candle 1
        midpoint_ok = True
        if p["require_close_below_midpoint1"]:
            margin = body1 * p["midpoint_margin_ratio"] if p["midpoint_margin_ratio"] else 0.0
            midpoint_ok = c2 <= (midpoint1 - margin * (1 - p["float_tolerance"]))

        # (3) Close above candle 1 open (Distinguish from Engulfing)
        close_above_o1_ok = True
        if p["require_close_above_o1"]:
            close_above_o1_ok = c2 >= (o1 * (1 - p["float_tolerance"]))

        # (4) Strength
        strength_ok = True
        if p["require_strong_body2"]:
            strength_ok = body2 >= (body1 * p["min_body2_ratio_vs_body1"] * (1 - p["float_tolerance"]))

        # (5) Volume
        volume_ok = True
        if p["require_volume_increase"]:
            if v1 is not None and v2 is not None:
                volume_ok = v2 > v1
            else:
                volume_ok = False

        # (6) Upper Wick (Rejection)
        wick_ok = True
        if p["min_upper_wick_ratio_c2"] is not None and h2 is not None:
            upper_wick = h2 - max(o2, c2)
            wick_ok = (upper_wick / body2) >= p["min_upper_wick_ratio_c2"] * (1 - p["float_tolerance"])

        # Range & Ratio Checks
        def valid_range(h, l): return (h is not None) and (l is not None) and (h >= l)
        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        # [Fix] Explicitly calculate ratios here
        body_ratio1 = (body1 / price_range1) if (price_range1 and price_range1 > p["min_range"]) else None
        body_ratio2 = (body2 / price_range2) if (price_range2 and price_range2 > p["min_range"]) else None

        ranges_required = (p["min_body_ratio1"] is not None and body_ratio1 is None) or \
                          (p["min_body_ratio2"] is not None and body_ratio2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False)

        body_ratio1_ok = True
        if p["min_body_ratio1"] is not None:
            body_ratio1_ok = body_ratio1 >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))

        # ATR Adaptive Logic
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body2_atr_scaler = 1.0
        if price_range2 and atr and p["min_body_ratio2"]:
            lo, hi = p["body2_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body2_atr_scaler = p["body2_atr_alpha"] * (atr / price_range2)
            body2_atr_scaler = max(lo, min(hi, body2_atr_scaler))
            # Tighten min body2 requirement in high vol
            effective_min_body_ratio2 = p["min_body_ratio2"] / body2_atr_scaler

        body_ratio2_ok = True
        if p["min_body_ratio2"] is not None:
            body_ratio2_ok = body_ratio2 >= (effective_min_body_ratio2 * (1 - p["float_tolerance"]))

        # ATR absolute constraints (optional)
        atr_body1_ok = True
        atr_body2_ok = True
        if atr is not None and atr > 0.0:
            if p["max_body1_vs_atr"] is not None and p["max_body1_vs_atr"] > 0.0:
                atr_body1_ok = body1 <= (p["max_body1_vs_atr"] * atr) * (1 + p["float_tolerance"])
            if p["min_body2_vs_atr"] is not None and p["min_body2_vs_atr"] > 0.0:
                atr_body2_ok = body2 >= (p["min_body2_vs_atr"] * atr) * (1 - p["float_tolerance"])

        is_pattern = all([
            first_bullish,
            second_bearish,
            gap_up_ok,
            midpoint_ok,
            close_above_o1_ok,
            strength_ok,
            body_ratio1_ok,
            body_ratio2_ok,
            atr_body1_ok,
            atr_body2_ok,
            volume_ok,
            wick_ok,
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            # Bodies & directions
            "first_bullish": first_bullish,
            "second_bearish": second_bearish,
            "body1": body1, "body2": body2,
            "midpoint1": midpoint1,
            # Ranges & ratios
            "price_range1": price_range1,
            "price_range2": price_range2,
            "body_ratio1": body_ratio1,
            "body_ratio2": body_ratio2,
            "effective_min_body_ratio2": effective_min_body_ratio2,
            # Core flags
            "gap_up_ok": gap_up_ok,
            "midpoint_ok": midpoint_ok,
            "close_above_o1_ok": close_above_o1_ok,
            "strength_ok": strength_ok,
            "body_ratio1_ok": body_ratio1_ok,
            "body_ratio2_ok": body_ratio2_ok,
            "volume_ok": volume_ok,
            "wick_ok": wick_ok,
            # ATR info
            "atr": atr,
            "body2_atr_scaler": body2_atr_scaler,
            "atr_body1_ok": atr_body1_ok,
            "atr_body2_ok": atr_body2_ok,
            # Echo inputs for traceability
            "o1": o1, "c1": c1, "h1": h1, "l1": l1,
            "o2": o2, "c2": c2, "h2": h2, "l2": l2,
            # Params snapshot (logging/debug)
            "params": {**self.defaults, "atr": atr} | overrides,
        }

        return PatternResult(
            is_pattern=True,
            name="Dark Cloud Cover",
            bias="short",
            metrics=metrics
        )