from typing import Optional, Tuple, Dict, Any
from tradercat.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class DarkCloudCoverDetector(DoubleCandlePatternDetector):
    """
    Dark Cloud Cover (Bearish Reversal) - Refactored for Strict Interface.
    
    Logic:
    1. Trend: Previous candle (C1) is strong bullish.
    2. Trap: Current candle (C2) opens higher or makes a new high (Bull Trap).
    3. Rejection: C2 closes deeply into C1's body (>50%).
    4. Distinction: C2 does NOT fully engulf C1 (otherwise it's Bearish Engulfing).
    """

    def __init__(
        self,
        *,
        # --- Gap / Trap Logic ---
        # [Optimization] False. 
        # Textbook definition requires Open2 > Close1 (Gap Up).
        # In modern markets (24h/electronic), gaps are rare. 
        # We accept High2 > High1 (Bull Trap) as a valid substitute if False.
        require_strict_gap_up: bool = False,         
        
        # --- Penetration Logic (Crucial) ---
        # [Optimization] True. 
        # C2 must close below the midpoint of C1. This shows Bears are winning.
        require_close_below_midpoint1: bool = True,  
        
        # --- Pattern Distinction ---
        # [Optimization] True. 
        # If C2 closes below Open1, it becomes a "Bearish Engulfing".
        # We keep this True to strictly separate "Dark Cloud" from "Engulfing".
        require_close_above_o1: bool = True,         

        # --- Body Strength ---
        # [Optimization] 0.25 (25%). 
        # Candle 1 must be a strong bullish candle ("Long White Candle").
        min_body_ratio1: Optional[float] = 0.25,     
        
        # [Optimization] 0.20 (20%). 
        # Candle 2 needs conviction.
        min_body_ratio2: Optional[float] = 0.20,     

        # --- Rejection Signals ---
        # [Optimization] 0.05 (5%). 
        # We expect SOME upper wick on C2 (rejection of highs), though not necessarily a Shooting Star.
        min_upper_wick_ratio_c2: Optional[float] = 0.05, 

        # --- Volume ---
        # [Optimization] False (Default). 
        # Rejection on high volume is a stronger signal.
        require_volume_increase: bool = False,

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Adaptation ---
        body2_atr_alpha: float = 1.0,                
        body2_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        min_body1_vs_atr: Optional[float] = None,    
        min_body2_vs_atr: Optional[float] = None     
    ):
        self.defaults = dict(
            require_strict_gap_up=require_strict_gap_up,
            require_close_below_midpoint1=require_close_below_midpoint1,
            require_close_above_o1=require_close_above_o1,
            min_body_ratio1=min_body_ratio1,
            min_body_ratio2=min_body_ratio2,
            min_upper_wick_ratio_c2=min_upper_wick_ratio_c2,
            require_volume_increase=require_volume_increase,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body2_atr_alpha=body2_atr_alpha,
            body2_atr_bounds=body2_atr_bounds,
            min_body1_vs_atr=min_body1_vs_atr,
            min_body2_vs_atr=min_body2_vs_atr,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        h1: float, l1: float,  # Now Mandatory
        h2: float, l2: float,  # Now Mandatory
        v1: Optional[float] = None, 
        v2: Optional[float] = None,
        *,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p: Dict[str, Any] = {**self.defaults, **overrides}

        # 1. Basic Direction Checks
        # C1 Bullish, C2 Bearish
        if not (self.is_bullish(o1, c1) and not self.is_bullish(o2, c2)):
            return PatternResult(is_pattern=False)

        # Calculate Basics using Base Class Helpers
        body1 = self.get_body(o1, c1)
        body2 = self.get_body(o2, c2)
        range1 = self.get_range(h1, l1)
        range2 = self.get_range(h2, l2)

        # Hygiene: Range too small to analyze
        if range1 <= p["min_range"] or range2 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # 2. Gap / Trap Logic
        # Strict: True Gap Up (Open2 > Close1)
        # Modern: Bull Trap (High2 > High1) - We now confidently use h1/h2
        trap_ok = False
        if p["require_strict_gap_up"]:
            trap_ok = o2 > c1 * (1 + p["float_tolerance"])
        else:
            trap_ok = h2 > h1 # Direct comparison enabled by strict interface

        if not trap_ok:
            return PatternResult(is_pattern=False)

        # 3. Penetration Logic (Close2 < Midpoint1)
        # Midpoint of Bull C1 is average of O and C.
        midpoint1 = (o1 + c1) / 2.0
        if p["require_close_below_midpoint1"]:
            if c2 > (midpoint1 * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 4. Distinction Logic (Close2 > Open1 - Not Engulfing)
        if p["require_close_above_o1"]:
            # If C2 closes below O1, it's engulfing. We want Close2 >= O1
            if c2 < (o1 * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 5. Upper Wick Check (Rejection via Helper)
        if p["min_upper_wick_ratio_c2"] is not None:
            upper_wick2 = self.get_upper_shadow(o2, h2, c2)
            # Prevent div/0 by using range if body is tiny, or hygiene min
            base_size = body2 if body2 > p["min_range"] else p["min_range"]
            if (upper_wick2 / base_size) < (p["min_upper_wick_ratio_c2"] * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 6. Body Ratio Checks
        if p["min_body_ratio1"] is not None:
            if (body1 / range1) < (p["min_body_ratio1"] * (1 - p["float_tolerance"])):
                 return PatternResult(is_pattern=False)

        # Body 2 Ratio (ATR Adaptive)
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body2_atr_scaler = 1.0
        
        if effective_min_body_ratio2 is not None:
            if atr and atr > 0:
                lo, hi = p["body2_atr_bounds"]
                if hi < lo: lo, hi = hi, lo
                # Normalize ATR impact: If ATR is huge vs Range, reduce requirement
                raw_scaler = p["body2_atr_alpha"] * (atr / range2)
                body2_atr_scaler = max(lo, min(hi, raw_scaler))
                effective_min_body_ratio2 = effective_min_body_ratio2 / body2_atr_scaler
            
            if (body2 / range2) < (effective_min_body_ratio2 * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 7. ATR Absolute Checks
        if atr and atr > 0.0:
            if p["min_body1_vs_atr"] and body1 < (p["min_body1_vs_atr"] * atr):
                return PatternResult(is_pattern=False)
            if p["min_body2_vs_atr"] and body2 < (p["min_body2_vs_atr"] * atr):
                return PatternResult(is_pattern=False)

        # 8. Volume Check (Optional input, strict logic)
        if p["require_volume_increase"]:
            # Only fail if data exists and condition fails
            if v1 is not None and v2 is not None:
                if v2 <= v1:
                    return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, 
            "body2": body2,
            "midpoint1": midpoint1,
            "trap_ok": trap_ok,
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "upper_wick_ratio2": (self.get_upper_shadow(o2, h2, c2) / body2) if body2 > 0 else 0,
            "params": {**self.defaults, "atr": atr, **overrides}
        }

        return PatternResult(
            is_pattern=True,
            name="Dark Cloud Cover",
            bias="short",
            metrics=metrics
        )