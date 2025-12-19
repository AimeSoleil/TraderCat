from typing import Optional, Tuple
from tradercat.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class DarkCloudCoverDetector(DoubleCandlePatternDetector):
    """
    Dark Cloud Cover (Bearish Reversal) - US Stock Optimized:
        - Candle 1: Strong Bullish (Trend continuation).
        - Candle 2: Bearish.
        - Logic: Bulls push to new highs (Gap Up or New High), but Bears slam price down >50% into C1.
        - Distinction: Does NOT engulf C1 (Close2 > Open1).
    """
    def __init__(
        self,
        *,
        # --- Gap / Trap Logic ---
        # [Optimization] False. 
        # Strict textbook requires Open2 > Close1 (Gap). 
        # In modern algo trading (especially intraday), a "New High" (High2 > High1) 
        # is sufficient to represent the "Bull Trap" psychology.
        require_strict_gap_up: bool = False,         
        
        # --- Penetration Logic (The Core Definition) ---
        # [Optimization] True. 
        # C2 MUST close below the midpoint of C1. If not, it's a weak signal (Thrusting Pattern).
        require_close_below_midpoint1: bool = True,  
        
        # [Optimization] True. 
        # If C2 closes below Open1, it becomes "Bearish Engulfing". 
        # We keep this True to strictly separate the two patterns.
        require_close_above_o1: bool = True,         

        # --- Strength Constraints ---
        # [Optimization] 0.25 (25%). 
        # Candle 1 must be a significant "Long White Candle". 
        # A Dark Cloud Cover over a tiny doji is meaningless noise.
        min_body_ratio1: Optional[float] = 0.25,     
        
        # [Optimization] 0.20 (20%). 
        # Candle 2 must also show conviction.
        min_body_ratio2: Optional[float] = 0.20,     

        # --- Wick Logic (Rejection) ---
        # [Optimization] 0.05 (5%). 
        # Ideally, C2 has a small upper wick, showing price tried to go higher but was rejected.
        min_upper_wick_ratio_c2: Optional[float] = 0.05, 

        # --- Volume Logic ---
        # [Optimization] False (Default), but HIGHLY recommended True in config.
        # High volume on the reversal candle (C2) confirms the sell-off.
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

        # 1. Directions
        first_bullish = c1 > o1
        second_bearish = c2 < o2
        if not (first_bullish and second_bearish):
            return PatternResult(is_pattern=False)

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        if body1 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        midpoint1 = (o1 + c1) / 2.0

        # 2. Gap / Trap Logic
        trap_ok = True
        if p["require_strict_gap_up"]:
            # Textbook: Open2 > Close1
            trap_ok = o2 > c1 * (1 + p["float_tolerance"])
        else:
            # Modern: High2 > High1 (Bull Trap)
            # If we don't have high data, fallback to Open2 >= Close1
            if h1 is not None and h2 is not None:
                trap_ok = h2 > h1
            else:
                trap_ok = o2 >= c1 * (1 - p["float_tolerance"])

        # 3. Penetration Logic (Close2 < Midpoint1)
        midpoint_ok = True
        if p["require_close_below_midpoint1"]:
            midpoint_ok = c2 <= (midpoint1 * (1 + p["float_tolerance"]))

        # 4. Distinction Logic (Close2 > Open1)
        distinction_ok = True
        if p["require_close_above_o1"]:
            distinction_ok = c2 >= (o1 * (1 - p["float_tolerance"]))

        # 5. Upper Wick Check (Rejection)
        wick_ok = True
        if p["min_upper_wick_ratio_c2"] is not None and h2 is not None:
            upper_wick = h2 - max(o2, c2)
            safe_body2 = body2 if body2 > p["min_range"] else p["min_range"]
            wick_ok = (upper_wick / safe_body2) >= (p["min_upper_wick_ratio_c2"] * (1 - p["float_tolerance"]))

        # 6. Range & Ratio Checks
        def valid_range(h, l): return (h is not None) and (l is not None) and (h >= l)
        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        ranges_required = (p["min_body_ratio1"] is not None and price_range1 is None) or \
                          (p["min_body_ratio2"] is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False)

        # Body 1 Ratio
        body_ratio1_ok = True
        if p["min_body_ratio1"] is not None and price_range1:
            body_ratio1_ok = (body1 / price_range1) >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))

        # Body 2 Ratio (ATR Adaptive)
        body_ratio2_ok = True
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body2_atr_scaler = 1.0
        
        if effective_min_body_ratio2 is not None and price_range2:
            if atr and atr > 0:
                lo, hi = p["body2_atr_bounds"]
                if hi < lo: lo, hi = hi, lo
                raw_scaler = p["body2_atr_alpha"] * (atr / price_range2)
                body2_atr_scaler = max(lo, min(hi, raw_scaler))
                effective_min_body_ratio2 = effective_min_body_ratio2 / body2_atr_scaler
            
            body_ratio2_ok = (body2 / price_range2) >= (effective_min_body_ratio2 * (1 - p["float_tolerance"]))

        # 7. ATR Absolute Checks
        atr_body1_ok = True
        atr_body2_ok = True
        if atr is not None and atr > 0.0:
            if p["min_body1_vs_atr"]:
                atr_body1_ok = body1 >= (p["min_body1_vs_atr"] * atr)
            if p["min_body2_vs_atr"]:
                atr_body2_ok = body2 >= (p["min_body2_vs_atr"] * atr)

        # 8. Volume Check
        volume_ok = True
        if p["require_volume_increase"]:
            volume_ok = (v1 is not None and v2 is not None and v2 > v1)

        is_pattern = all([
            trap_ok, midpoint_ok, distinction_ok,
            body_ratio1_ok, body_ratio2_ok,
            atr_body1_ok, atr_body2_ok,
            volume_ok, wick_ok,
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2,
            "midpoint1": midpoint1,
            "trap_ok": trap_ok,
            "midpoint_ok": midpoint_ok,
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "upper_wick_ratio2": ((h2 - max(o2, c2)) / body2) if (h2 and body2 > 0) else None,
            "params": {**self.defaults, "atr": atr}
        }

        return PatternResult(
            is_pattern=True,
            name="Dark Cloud Cover",
            bias="short",
            metrics=metrics
        )