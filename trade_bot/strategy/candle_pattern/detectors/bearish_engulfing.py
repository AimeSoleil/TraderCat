from typing import Optional, Tuple, Any
from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class BearishEngulfingDetector(DoubleCandlePatternDetector):
    """
    Bearish Engulfing (2-candle) - Production Grade:
        - Candle 1 bullish (Green) or Doji.
        - Candle 2 bearish (Red).
        - Candle 2 body engulfs Candle 1 body.
        - [New] Optional Shadow Engulfing (High/Low engulfing).
        - [Fix] Supports engulfing a Doji.
    """
    def __init__(
        self,
        *,
        # Direction requirements
        require_first_bullish: bool = True,
        require_second_bearish: bool = True,

        # Engulfing body overlap semantics
        require_strict_overlap: bool = True,        
        overlap_tolerance: float = 1e-9,            

        # Strength & decisiveness
        strength_multiplier: float = 1.1,           
        decisive_close_margin_ratio: float = 0.0,   

        # Wick Logic 
        max_lower_wick_ratio: Optional[float] = 0.4, 

        # Volume Logic 
        require_volume_increase: bool = False,      

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
        min_body2_vs_atr: Optional[float] = None,

        # [New] Stronger Signal
        require_shadow_engulfing: bool = False,
    ):
        self.defaults = dict(
            require_first_bullish=require_first_bullish,
            require_second_bearish=require_second_bearish,
            require_strict_overlap=require_strict_overlap,
            overlap_tolerance=overlap_tolerance,
            strength_multiplier=strength_multiplier,
            decisive_close_margin_ratio=decisive_close_margin_ratio,
            max_lower_wick_ratio=max_lower_wick_ratio,
            require_volume_increase=require_volume_increase,
            min_body_ratio1=min_body_ratio1,
            min_body_ratio2=min_body_ratio2,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body2_atr_alpha=body2_atr_alpha,
            body2_atr_bounds=body2_atr_bounds,
            max_body1_vs_atr=max_body1_vs_atr,
            min_body2_vs_atr=min_body2_vs_atr,
            require_shadow_engulfing=require_shadow_engulfing,
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

        # 1. Basic Data Integrity
        if any(x is None for x in (o1, c1, o2, c2)):
            return PatternResult(is_pattern=False)

        # 2. Direction Checks
        # Note: If require_first_bullish is True, Doji (c1==o1) fails. 
        # To allow Doji, set require_first_bullish=False in config or relax logic here.
        # Standard Engulfing usually implies Green then Red.
        first_bullish = c1 > o1
        second_bearish = c2 < o2
        
        if p["require_first_bullish"] and not first_bullish:
            # Allow Doji if body is negligible? 
            # For strict definition, we keep it. User can disable flag if needed.
            return PatternResult(is_pattern=False)
            
        if p["require_second_bearish"] and not second_bearish:
            return PatternResult(is_pattern=False)

        # 3. Body Calculations
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        
        # [Fix] Allow body1 to be zero (Doji). Only check body2.
        if body2 <= p["float_tolerance"]:
            return PatternResult(is_pattern=False)

        # 4. Engulfing Logic (Body)
        if p["require_strict_overlap"]:
            # Bear Open >= Bull Close AND Bear Close <= Bull Open
            engulf_ok = (o2 >= c1 * (1 - p["float_tolerance"])) and \
                        (c2 <= o1 * (1 + p["float_tolerance"]))
        else:
            engulf_ok = (o2 >= (c1 - abs(c1) * p["overlap_tolerance"])) and \
                        (c2 <= (o1 + abs(o1) * p["overlap_tolerance"]))

        # 5. Shadow Engulfing (New - Stronger)
        shadow_engulf_ok = True
        if p["require_shadow_engulfing"]:
            if all(x is not None for x in (h1, l1, h2, l2)):
                # High2 >= High1 AND Low2 <= Low1
                shadow_engulf_ok = (h2 >= h1 * (1 - p["float_tolerance"])) and \
                                   (l2 <= l1 * (1 + p["float_tolerance"]))
            else:
                shadow_engulf_ok = False

        # 6. Strength
        strength_ok = body2 >= body1 * p["strength_multiplier"] * (1 - p["float_tolerance"])

        # 7. Decisiveness
        decisive_ok = True
        if p["decisive_close_margin_ratio"] > 0.0:
            decisive_ok = c2 <= (o1 - body1 * p["decisive_close_margin_ratio"])

        # 8. Volume
        volume_ok = True
        if p["require_volume_increase"]:
            if v1 is not None and v2 is not None:
                volume_ok = v2 > v1
            else:
                volume_ok = False

        # 9. Wick Analysis
        wick_ok = True
        if p["max_lower_wick_ratio"] is not None and h2 is not None and l2 is not None:
            lower_wick = max(0.0, c2 - l2) # Safe calc
            if lower_wick > (body2 * p["max_lower_wick_ratio"]):
                wick_ok = False

        # 10. Range & Ratio Checks
        def valid_range(h, l): return (h is not None and l is not None and h >= l)
        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        ranges_required = (p["min_body_ratio1"] is not None and price_range1 is None) or \
                          (p["min_body_ratio2"] is not None and price_range2 is None)
        
        if ranges_required:
            return PatternResult(is_pattern=False)

        body_ratio1_ok = True
        if p["min_body_ratio1"] is not None and price_range1:
            body_ratio1_ok = (body1 / price_range1) >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))

        # ATR Adaptive Logic
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body2_atr_scaler = 1.0
        if price_range2 and atr and p["min_body_ratio2"]:
            raw_scaler = p["body2_atr_alpha"] * (atr / price_range2)
            lo, hi = p["body2_atr_bounds"]
            body2_atr_scaler = max(lo, min(hi, raw_scaler))
            effective_min_body_ratio2 = p["min_body_ratio2"] / body2_atr_scaler

        body_ratio2_ok = True
        if effective_min_body_ratio2 is not None and price_range2:
            body_ratio2_ok = (body2 / price_range2) >= (effective_min_body_ratio2 * (1 - p["float_tolerance"]))

        # ATR Absolute Checks
        atr_body1_ok = True
        atr_body2_ok = True
        if atr:
            if p["max_body1_vs_atr"]:
                atr_body1_ok = body1 <= (p["max_body1_vs_atr"] * atr)
            if p["min_body2_vs_atr"]:
                atr_body2_ok = body2 >= (p["min_body2_vs_atr"] * atr)

        # Final Decision
        conditions = [
            engulf_ok, shadow_engulf_ok,
            strength_ok, decisive_ok, volume_ok, wick_ok,
            body_ratio1_ok, body_ratio2_ok, atr_body1_ok, atr_body2_ok
        ]
        
        if not all(conditions):
            return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1,
            "body2": body2,
            "vol_increase": (v2/v1) if (v1 and v2 and v1 > 0) else None,
            "lower_wick_ratio": ((c2 - l2)/body2) if (l2 and body2 > 0) else 0.0,
            "atr_multiple": (body2 / atr) if (atr and atr > 0) else None,
            "params": {**self.defaults, "atr": atr, **overrides}, # Added params
        }

        return PatternResult(
            is_pattern=True,
            name="Bearish Engulfing",
            bias="short",
            metrics=metrics
        )