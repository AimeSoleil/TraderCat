from typing import Optional, Dict, Any
from tradercat.core.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class BullishHaramiDetector(DoubleCandlePatternDetector):
    """
    Bullish Harami (2-candle) - US Stock Optimized:
        - Candle 1: Large Bearish (Trend continuation).
        - Candle 2: Small Bullish or Doji (Indecision), contained within Candle 1's body.
        - Logic: Momentum stall. Bears couldn't push lower, price consolidated inside previous range.
        - Note: Often an "Inside Bar" setup indicating a pause or potential reversal.
    """
    def __init__(
        self,
        *,
        # --- Direction ---
        require_first_bearish: bool = True,
        
        # [Optimization] False. 
        # We allow Dojis (Harami Cross) or very small green candles if they are strictly inside.
        # The "Inside" nature is more important than the color of the baby candle.
        require_second_bullish: bool = False,

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
        # Candle 1 must be a significant "Long Black Candle", not a doji itself.
        min_body_ratio1: Optional[float] = 0.20,  

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Constraints ---
        min_body1_vs_atr: Optional[float] = None, 
        max_body2_vs_atr: Optional[float] = None, 
    ):
        self.defaults = dict(
            require_first_bearish=require_first_bearish,
            require_second_bullish=require_second_bullish,
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
        first_bearish = not self.is_bullish(o1, c1)
        second_bullish = self.is_bullish(o2, c2)
        
        if p["require_first_bearish"] and not first_bearish:
            return PatternResult(is_pattern=False)
        
        if p["require_second_bullish"]:
            # If strict bullish required, allow Green (c2 > o2) or Doji (c2 == o2).
            # "Is Bullish" logic is typically Close > Open. Check logic if you want >=
            if not (c2 >= o2): 
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
            # Highs/Lows are now mandatory
            wick_inside_ok = (h2 <= h1 * (1 + p["float_tolerance"])) and \
                             (l2 >= l1 * (1 - p["float_tolerance"]))
        
        if not wick_inside_ok:
            return PatternResult(is_pattern=False)

        # 5. Relative Size
        if p["require_small_body2"]:
            if body2 > (body1 * p["max_body2_ratio_vs_body1"] * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 6. Volume Contraction
        if p["require_volume_contraction"]:
            # Strict verification
            if v1 is None or v2 is None:
                return PatternResult(is_pattern=False)
            if not (v2 < v1):
                return PatternResult(is_pattern=False)

        # 7. Range & Ratio Checks (Mother Candle Strength)
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
            name="Bullish Harami",
            bias="long",
            metrics=metrics
        )