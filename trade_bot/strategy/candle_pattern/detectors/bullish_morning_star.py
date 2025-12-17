from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, TripleCandlePatternDetector

# --- Morning Star standalone detector ---
class MorningStarDetector(TripleCandlePatternDetector):
    """
    Morning Star (bullish, 3-candle) - Production Grade:
        - Candle 1: Long Bearish.
        - Candle 2: Small body (Indecision), gaps down (optional).
        - Candle 3: Long Bullish, gaps up (optional), closes deep into C1.
        - [New] Volume and High-breakout confirmation.
    """
    def __init__(
        self,
        *,
        # Core semantics
        small_body2_ratio_vs_body1: float = 0.50,   # body2 <= body1 * 0.5
        min_body3_ratio_vs_body1: float = 0.80,     # body3 >= body1 * 0.8
        require_c3_above_midpoint1: bool = True,    # c3 >= midpoint(o1, c1)
        midpoint_margin_ratio: float = 0.0,         

        # Overlap / gaps (Stock market: True, Crypto/Forex: False)
        require_gap_down_into_c2: bool = False,     
        require_gap_up_into_c3: bool = False,       
        lenient_overlap_tolerance: float = 1e-9,    

        # Indecision checks for candle 2
        max_body2_ratio_vs_range2: Optional[float] = 0.30,  
        min_shadows2_to_body: Optional[float] = None,       

        # Hygiene
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR adaptation
        body3_atr_alpha: float = 1.0,                          
        body3_atr_bounds: Tuple[float, float] = (0.7, 1.5),    
        min_body3_vs_atr: Optional[float] = None,               

        # Optional conditions
        require_c3_above_high2: bool = False,          # c3 close > h2
        require_volume_increase_c3: bool = False,      # v3 > v2
    ):
        self.defaults = dict(
            small_body2_ratio_vs_body1=small_body2_ratio_vs_body1,
            min_body3_ratio_vs_body1=min_body3_ratio_vs_body1,
            require_c3_above_midpoint1=require_c3_above_midpoint1,
            midpoint_margin_ratio=midpoint_margin_ratio,
            require_gap_down_into_c2=require_gap_down_into_c2,
            require_gap_up_into_c3=require_gap_up_into_c3,
            lenient_overlap_tolerance=lenient_overlap_tolerance,
            max_body2_ratio_vs_range2=max_body2_ratio_vs_range2,
            min_shadows2_to_body=min_shadows2_to_body,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body3_atr_alpha=body3_atr_alpha,
            body3_atr_bounds=body3_atr_bounds,
            min_body3_vs_atr=min_body3_vs_atr,
            require_c3_above_high2=require_c3_above_high2,
            require_volume_increase_c3=require_volume_increase_c3,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        o3: float, c3: float,
        *,
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        h3: Optional[float] = None, l3: Optional[float] = None,
        atr: Optional[float] = None,
        v2: Optional[float] = None, v3: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Basic hygiene
        if any(x is None for x in (o1, c1, o2, c2, o3, c3)):
            return PatternResult(is_pattern=False)

        first_bearish = c1 < o1
        third_bullish = c3 > o3
        if not (first_bearish and third_bullish):
            return PatternResult(is_pattern=False)

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        body3 = abs(c3 - o3)
        
        # Strict tiny body check
        if body1 <= p["min_range"] or body3 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        midpoint1 = (o1 + c1) / 2.0

        def valid_range(h, l): return (h is not None) and (l is not None) and (h >= l)
        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None
        price_range3 = (h3 - l3) if valid_range(h3, l3) else None

        # Fail safely if ranges required but missing
        ranges_required = (p["max_body2_ratio_vs_range2"] is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False)

        # (1) Candle 2 small relative to body1
        small2_ok = body2 <= (body1 * p["small_body2_ratio_vs_body1"] * (1 + p["float_tolerance"]))

        # Optional: indecision using candle 2’s own range
        indecision2_ok = True
        shadows2_ok = True
        body_ratio2_vs_range2 = None
        if price_range2 is not None and p["max_body2_ratio_vs_range2"] is not None:
            body_ratio2_vs_range2 = body2 / price_range2
            indecision2_ok = (body_ratio2_vs_range2 <= (p["max_body2_ratio_vs_range2"] * (1 + p["float_tolerance"])))
            
            if p["min_shadows2_to_body"] is not None and p["min_shadows2_to_body"] > 0.0:
                upper2 = max(0.0, (h2 - max(o2, c2)))
                lower2 = max(0.0, (min(o2, c2) - l2))
                # Handle zero body case for shadow ratio
                safe_body2 = body2 if body2 > p["min_range"] else p["min_range"]
                upper2_ok = (upper2 / safe_body2) >= (p["min_shadows2_to_body"] * (1 - p["float_tolerance"]))
                lower2_ok = (lower2 / safe_body2) >= (p["min_shadows2_to_body"] * (1 - p["float_tolerance"]))
                shadows2_ok = upper2_ok and lower2_ok

        # (2) Candle 3 closes above midpoint of candle 1
        midpoint_ok = True
        if p["require_c3_above_midpoint1"]:
            margin = (body1 * p["midpoint_margin_ratio"]) if (p["midpoint_margin_ratio"] and p["midpoint_margin_ratio"] > 0.0) else 0.0
            midpoint_ok = c3 >= (midpoint1 + margin * (1 - p["float_tolerance"]))

        # (3) Candle 3 body strength vs body1 (ATR adaptive)
        body3_vs_body1_ok = body3 >= (body1 * p["min_body3_ratio_vs_body1"] * (1 - p["float_tolerance"]))
        body3_atr_scaler = None
        effective_min_body3_ratio_vs_body1 = p["min_body3_ratio_vs_body1"]

        if atr is not None and atr > 0.0 and price_range3 is not None:
            lo, hi = p["body3_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body3_atr_scaler = p["body3_atr_alpha"] * (atr / price_range3)
            body3_atr_scaler = max(lo, min(hi, body3_atr_scaler))
            effective_min_body3_ratio_vs_body1 = p["min_body3_ratio_vs_body1"] / body3_atr_scaler
            body3_vs_body1_ok = body3 >= (body1 * effective_min_body3_ratio_vs_body1 * (1 - p["float_tolerance"]))

        atr_body3_ok = True
        if atr is not None and atr > 0.0 and p["min_body3_vs_atr"]:
            atr_body3_ok = body3 >= (p["min_body3_vs_atr"] * atr) * (1 - p["float_tolerance"])

        # (4) Gap semantics
        gap_down_ok = True
        gap_up_ok = True
        if p["require_gap_down_into_c2"]:
            gap_down_ok = o2 <= (min(o1, c1) * (1 - p["lenient_overlap_tolerance"]))
        if p["require_gap_up_into_c3"]:
            gap_up_ok = o3 >= (max(o2, c2) * (1 + p["lenient_overlap_tolerance"]))

        # Optional: c3 close > h2
        close_above_high2_ok = True
        if p["require_c3_above_high2"]:
            if h2 is None:
                close_above_high2_ok = False
            else:
                close_above_high2_ok = c3 >= h2 * (1 - p["float_tolerance"])

        # Optional: Volume
        volume_ok = True
        if p["require_volume_increase_c3"]:
            volume_ok = (v2 is not None and v3 is not None and v3 > v2)

        is_pattern = all([
            first_bearish, third_bullish,
            small2_ok, indecision2_ok, shadows2_ok,
            midpoint_ok, body3_vs_body1_ok,
            gap_down_ok, gap_up_ok,
            atr_body3_ok, close_above_high2_ok, volume_ok,
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2, "body3": body3,
            "midpoint1": midpoint1,
            "price_range2": price_range2,
            "body_ratio2_vs_range2": body_ratio2_vs_range2,
            "atr": atr,
            "body3_atr_scaler": body3_atr_scaler,
            "effective_min_body3_ratio_vs_body1": effective_min_body3_ratio_vs_body1,
            "volume_increase_c3": (v3 / v2) if (v2 and v3 and v2 > 0) else None,
            "params": {**self.defaults, "atr": atr, **overrides}, # Safe merge
        }

        return PatternResult(
            is_pattern=True,
            name="Morning Star",
            bias="long",
            metrics=metrics
        )
