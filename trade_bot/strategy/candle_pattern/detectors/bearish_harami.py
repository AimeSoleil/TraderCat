from typing import Optional
from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class BearishHaramiDetector(DoubleCandlePatternDetector):
    """
    Bearish Harami (2-candle) - Production Grade:
        - Candle 1: Large Bullish.
        - Candle 2: Small Bearish (or Doji), contained within Candle 1's body.
        - [Fix] Now supports Harami Cross (body2=0).
        - [Fix] Robust inside-body logic.
    """
    def __init__(
        self,
        *,
        # Direction requirements
        require_first_bullish: bool = True,
        require_second_bearish: bool = True,

        # "Inside" semantics
        strict_body_inside: bool = True,      # Body 2 inside Body 1
        strict_wick_inside: bool = False,     # High2/Low2 inside High1/Low1
        inside_tolerance: float = 1e-9,       

        # Size constraints
        max_body2_ratio_vs_body1: float = 0.50,   
        require_small_body2: bool = True,         

        # Volume Logic
        require_volume_contraction: bool = False, 

        # Doji-avoidance / Range checks
        min_body_ratio1: Optional[float] = None,  
        max_body_ratio2: Optional[float] = None,  

        # Hygiene
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR constraints
        min_body1_vs_atr: Optional[float] = None, 
        max_body2_vs_atr: Optional[float] = None, 
        
        # Upper Wick Filter (New)
        max_upper_wick_ratio2: Optional[float] = None,
    ):
        self.defaults = dict(
            require_first_bullish=require_first_bullish,
            require_second_bearish=require_second_bearish,
            strict_body_inside=strict_body_inside,
            strict_wick_inside=strict_wick_inside,
            inside_tolerance=inside_tolerance,
            max_body2_ratio_vs_body1=max_body2_ratio_vs_body1,
            require_small_body2=require_small_body2,
            require_volume_contraction=require_volume_contraction,
            min_body_ratio1=min_body_ratio1,
            max_body_ratio2=max_body_ratio2,
            min_range=min_range,
            float_tolerance=float_tolerance,
            min_body1_vs_atr=min_body1_vs_atr,
            max_body2_vs_atr=max_body2_vs_atr,
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

        # 1. Directions
        first_bullish = c1 > o1
        second_bearish = c2 < o2
        
        if p["require_first_bullish"] and not first_bullish:
            return PatternResult(is_pattern=False)
        
        if p["require_second_bearish"]:
            # [Fix] Allow Doji (Harami Cross) even if strict bearish is requested
            # Usually Harami Cross is c2 <= o2 (Bearish or Neutral)
            if not (c2 <= o2): 
                return PatternResult(is_pattern=False)

        # 2. Bodies
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        
        # Only reject if body1 is zero. Allow body2 to be zero.
        if body1 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # 3. Inside Body Check (Robust)
        # Calculate boundaries regardless of candle color
        top1, bottom1 = max(o1, c1), min(o1, c1)
        top2, bottom2 = max(o2, c2), min(o2, c2)

        if p["strict_body_inside"]:
            body_inside = (top2 <= top1 * (1 + p["float_tolerance"])) and \
                          (bottom2 >= bottom1 * (1 - p["float_tolerance"]))
        else:
            tol = body1 * p["inside_tolerance"]
            body_inside = (top2 <= (top1 + tol)) and \
                          (bottom2 >= (bottom1 - tol))

        if not body_inside:
            return PatternResult(is_pattern=False)

        # 4. Inside Wick Check
        wick_inside = True
        if p["strict_wick_inside"]:
            if all(x is not None for x in (h1, l1, h2, l2)):
                wick_inside = (h2 <= h1) and (l2 >= l1)
            else:
                wick_inside = False
        if not wick_inside:
            return PatternResult(is_pattern=False)

        # 5. Relative Size
        strength_ok = True
        if p["require_small_body2"]:
            strength_ok = body2 <= (body1 * p["max_body2_ratio_vs_body1"] * (1 + p["float_tolerance"]))

        # 6. Volume Contraction
        vol_ok = True
        if p["require_volume_contraction"]:
            if v1 is not None and v2 is not None:
                vol_ok = v2 < v1
            else:
                vol_ok = False

        # 7. Range & Ratio Checks
        def valid_range(h, l): return (h is not None and l is not None and h >= l)
        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        ranges_required = (p["min_body_ratio1"] is not None and price_range1 is None) or \
                          (p["max_body_ratio2"] is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False)

        body_ratio1_ok = True
        if p["min_body_ratio1"] is not None and price_range1:
            body_ratio1_ok = (body1 / price_range1) >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))

        body_ratio2_ok = True
        if p["max_body_ratio2"] is not None and price_range2:
            body_ratio2_ok = (body2 / price_range2) <= (p["max_body_ratio2"] * (1 + p["float_tolerance"]))

        # 8. ATR Checks
        atr_body1_ok = True
        atr_body2_ok = True
        if atr:
            if p["min_body1_vs_atr"]:
                atr_body1_ok = body1 >= (p["min_body1_vs_atr"] * atr)
            if p["max_body2_vs_atr"]:
                atr_body2_ok = body2 <= (p["max_body2_vs_atr"] * atr)

        # 9. Upper Wick Filter (New)
        upper_wick2_ok = True
        if p["max_upper_wick_ratio2"] is not None and h2 is not None and l2 is not None:
            upper_wick2 = h2 - max(o2, c2)
            denom = body2 if body2 > p["float_tolerance"] else p["float_tolerance"]
            upper_wick2_ok = (upper_wick2 / denom) <= p["max_upper_wick_ratio2"] * (1 + p["float_tolerance"])

        # Final Decision
        conditions = [
            strength_ok, vol_ok,
            body_ratio1_ok, body_ratio2_ok,
            atr_body1_ok, atr_body2_ok,
            upper_wick2_ok
        ]

        if not all(conditions):
            return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1,
            "body2": body2,
            "vol_contraction": (v2/v1) if (v1 and v2 and v1 > 0) else None,
            "wick_inside": wick_inside,
            "params": {**self.defaults, "atr": atr}
        }

        return PatternResult(
            is_pattern=True,
            name="Bearish Harami",
            bias="short",
            metrics=metrics
        )