from typing import Optional, Dict, Any
from tradercat.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class BearishHaramiDetector(DoubleCandlePatternDetector):
    """
    Bearish Harami (2-candle) - US Stock Optimized:
        - Candle 1: Large Bullish (Trend continuation).
        - Candle 2: Small Bearish or Doji (Indecision), contained within Candle 1's body.
        - Logic: Momentum stall. Bulls couldn't push higher, price consolidated inside previous range.
        - Note: Often an "Inside Bar" setup indicating a pause or potential reversal.
    """
    def __init__(
        self,
        *,
        # --- Direction ---
        require_first_bullish: bool = True,
        
        # [Optimization] False. 
        # A Harami Cross (Doji) is often neutral or slightly bullish in color but bearish in implication.
        # We allow C2 to be Green if it's tiny and inside C1.
        require_second_bearish: bool = False,

        # --- Inside Logic ---
        # [Optimization] True. 
        # The body of C2 MUST be inside the body of C1. This is the definition.
        strict_body_inside: bool = True,           
        
        # [Optimization] False. 
        # Wicks can poke out slightly (bull trap/bear trap) as long as the body is contained.
        strict_wick_inside: bool = False,          
        inside_tolerance: float = 1e-9,       

        # --- Size Constraints ---
        # [Optimization] 0.5 (50%). 
        # The baby (C2) should be at most half the size of the mother (C1).
        max_body2_ratio_vs_body1: float = 0.50,   
        require_small_body2: bool = True,         

        # --- Volume Logic ---
        # [Optimization] True. 
        # Harami represents a drop in volatility and momentum. Volume usually dries up.
        require_volume_contraction: bool = True,  

        # --- Doji / Range Checks ---
        # [Optimization] 0.2 (20%). 
        # Candle 1 must be a significant "Long White Candle", not a doji itself.
        min_body_ratio1: Optional[float] = 0.20,  

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Constraints ---
        min_body1_vs_atr: Optional[float] = None, 
        max_body2_vs_atr: Optional[float] = None, 
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
            min_range=min_range,
            float_tolerance=float_tolerance,
            min_body1_vs_atr=min_body1_vs_atr,
            max_body2_vs_atr=max_body2_vs_atr,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        h1: float, l1: float,  # Mandatory
        h2: float, l2: float,  # Mandatory
        v1: Optional[float] = None, 
        v2: Optional[float] = None,
        *,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p: Dict[str, Any] = {**self.defaults, **overrides}
        
        # 1. Directions
        first_bullish = self.is_bullish(o1, c1)
        # Note: Harami is typically bearish reversal, so C2 is often bearish, but can be Doji/Small Green
        second_bearish = not self.is_bullish(o2, c2) 
        
        if p["require_first_bullish"] and not first_bullish:
            return PatternResult(is_pattern=False)
        
        if p["require_second_bearish"]:
            if not second_bearish: # Must strictly be Red/Doji
                return PatternResult(is_pattern=False)

        # 2. Bodies & Ranges
        body1 = self.get_body(o1, c1)
        body2 = self.get_body(o2, c2)
        range1 = self.get_range(h1, l1)
        
        # Mother candle must exist
        if body1 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # 3. Inside Body Check (Robust)
        top1, bottom1 = max(o1, c1), min(o1, c1)
        top2, bottom2 = max(o2, c2), min(o2, c2)

        if p["strict_body_inside"]:
            # C2 Body strictly inside C1 Body
            inside_ok = (bottom2 >= bottom1 * (1 - p["float_tolerance"])) and \
                        (top2 <= top1 * (1 + p["float_tolerance"]))
        else:
            # Lenient
            tol = body1 * p["inside_tolerance"]
            inside_ok = (bottom2 >= (bottom1 - tol)) and (top2 <= (top1 + tol))

        if not inside_ok:
            return PatternResult(is_pattern=False)

        # 4. Inside Wick Check
        wick_inside_ok = True
        if p["strict_wick_inside"]:
            # Highs/Lows are now mandatory, so direct comparison
            wick_inside_ok = (h2 <= h1 * (1 + p["float_tolerance"])) and \
                             (l2 >= l1 * (1 - p["float_tolerance"]))
        if not wick_inside_ok:
            return PatternResult(is_pattern=False)

        # 5. Relative Size
        strength_ok = True
        if p["require_small_body2"]:
            strength_ok = body2 <= (body1 * p["max_body2_ratio_vs_body1"] * (1 + p["float_tolerance"]))
        if not strength_ok:
            return PatternResult(is_pattern=False)

        # 6. Volume Contraction
        if p["require_volume_contraction"]:
            # Strict mode: if data missing, fail. Use fail-fast.
            if v1 is None or v2 is None:
                return PatternResult(is_pattern=False)
            if not (v2 < v1):
                return PatternResult(is_pattern=False)

        # 7. Range & Ratio Checks
        if p["min_body_ratio1"] is not None:
             eff_range1 = range1 if range1 > p["min_range"] else p["min_range"]
             if (body1 / eff_range1) < (p["min_body_ratio1"] * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 8. ATR Checks
        if atr is not None and atr > 0.0:
            if p["min_body1_vs_atr"] and body1 < (p["min_body1_vs_atr"] * atr * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)
            if p["max_body2_vs_atr"] and body2 > (p["max_body2_vs_atr"] * atr * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2,
            "inside_ok": inside_ok,
            "vol_contraction": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(
            is_pattern=True,
            name="Bearish Harami",
            bias="short",
            metrics=metrics
        )