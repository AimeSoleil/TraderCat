from typing import Optional
from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class BullishHaramiDetector(DoubleCandlePatternDetector):
    """
    Bullish Harami (2-candle):
      - Candle 1: Large Bearish.
      - Candle 2: Small Bullish (or Doji), contained within Candle 1's body.
      - [Fix] Now supports Harami Cross (body2=0).
      - [Fix] Robust inside-body logic.
    """
    def __init__(
        self,
        *,
        # Direction requirements
        require_first_bearish: bool = True,
        require_second_bullish: bool = True,

        # "Inside body" semantics
        strict_inside: bool = True,           
        inside_tolerance: float = 1e-9,       

        # Size constraints
        max_body2_ratio_vs_body1: float = 0.50,   
        require_small_body2: bool = True,         

        # Doji-avoidance / Range checks
        min_body_ratio1: Optional[float] = None,  
        max_body_ratio2: Optional[float] = None,  

        # Hygiene
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR constraints
        min_body1_vs_atr: Optional[float] = None, 
        max_body2_vs_atr: Optional[float] = None, 

        # Advanced filters
        strict_wick_inside: bool = False,          
        require_volume_contraction: bool = False,  
        max_upper_wick_ratio2: Optional[float] = None,  
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
            strict_wick_inside=strict_wick_inside,
            require_volume_contraction=require_volume_contraction,
            max_upper_wick_ratio2=max_upper_wick_ratio2,
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
        if any(x is None for x in (o1, c1, o2, c2)):
            return PatternResult(is_pattern=False)

        # Directions
        first_bearish = c1 < o1
        second_bullish = c2 > o2
        if p["require_first_bearish"] and not first_bearish:
            return PatternResult(is_pattern=False)
        if p["require_second_bullish"] and not second_bullish:
            # Note: Harami Cross allows Doji, which might not be strictly "bullish" (c2 > o2)
            # if c2 == o2. If strict bullish is required, Doji fails. 
            # Usually for Harami, we allow c2 >= o2.
            if not (c2 >= o2): 
                return PatternResult(is_pattern=False)

        # Bodies
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        
        # [Fix] Only reject if body1 is zero. Allow body2 to be zero (Harami Cross).
        if body1 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # Inside-body check (Robust)
        # Calculate boundaries regardless of candle color
        top1, bottom1 = max(o1, c1), min(o1, c1)
        top2, bottom2 = max(o2, c2), min(o2, c2)

        if p["strict_inside"]:
            inside_ok = (bottom2 >= bottom1 * (1 - p["float_tolerance"])) and \
                        (top2 <= top1 * (1 + p["float_tolerance"]))
        else:
            # Lenient
            tol = body1 * p["inside_tolerance"]
            inside_ok = (bottom2 >= (bottom1 - tol)) and (top2 <= (top1 + tol))

        # Relative size constraint
        strength_ok = True
        if p["require_small_body2"]:
            strength_ok = body2 <= (body1 * p["max_body2_ratio_vs_body1"] * (1 + p["float_tolerance"]))

        # Ranges
        def valid_range(h, l): return (h is not None) and (l is not None) and (h >= l)
        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        # Fail safely if ranges required but missing
        ranges_required = (p["min_body_ratio1"] is not None and price_range1 is None) or \
                          (p["max_body_ratio2"] is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False)

        # Ratio Checks
        body_ratio1_ok = True
        if p["min_body_ratio1"] is not None and price_range1:
            body_ratio1_ok = (body1 / price_range1) >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))

        body_ratio2_ok = True
        if p["max_body_ratio2"] is not None and price_range2:
            body_ratio2_ok = (body2 / price_range2) <= (p["max_body_ratio2"] * (1 + p["float_tolerance"]))

        # ATR Checks
        atr_body1_ok = True
        atr_body2_ok = True
        if atr is not None and atr > 0.0:
            if p["min_body1_vs_atr"]:
                atr_body1_ok = body1 >= (p["min_body1_vs_atr"] * atr) * (1 - p["float_tolerance"])
            if p["max_body2_vs_atr"]:
                atr_body2_ok = body2 <= (p["max_body2_vs_atr"] * atr) * (1 + p["float_tolerance"])

        # Wick-inside
        wick_inside_ok = True
        if p["strict_wick_inside"]:
            if all(x is not None for x in (h1, l1, h2, l2)):
                wick_inside_ok = (h2 <= h1) and (l2 >= l1)
            else:
                wick_inside_ok = False
        if not wick_inside_ok:
            return PatternResult(is_pattern=False)

        # Upper Wick Filter
        upper_wick2_ok = True
        if p["max_upper_wick_ratio2"] is not None and h2 is not None and l2 is not None:
            upper_wick2 = h2 - max(o2, c2)
            # Handle zero body2 safely
            denom = body2 if body2 > p["float_tolerance"] else p["float_tolerance"]
            upper_wick2_ok = (upper_wick2 / denom) <= p["max_upper_wick_ratio2"] * (1 + p["float_tolerance"])

        # Volume Contraction
        vol_ok = True
        if p["require_volume_contraction"]:
            vol_ok = (v1 is not None and v2 is not None and v2 < v1)

        is_pattern = all([
            inside_ok,
            strength_ok,
            body_ratio1_ok,
            body_ratio2_ok,
            atr_body1_ok,
            atr_body2_ok,
            wick_inside_ok,
            upper_wick2_ok,
            vol_ok,
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2,
            "inside_ok": inside_ok,
            "strength_ok": strength_ok,
            "atr": atr,
            "params": {**self.defaults, "atr": atr, **overrides}, # [Fix] Compatible merge
            "wick_inside": wick_inside_ok,
            "volume_contraction": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "upper_wick_ratio2": ((h2 - max(o2, c2)) / body2) if (h2 and l2 and body2 > 0) else None,
        }

        return PatternResult(
            is_pattern=True,
            name="Bullish Harami",
            bias="long",  # 统一术语
            metrics=metrics
        )