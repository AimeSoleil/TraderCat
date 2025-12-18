from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, TripleCandlePatternDetector

class EveningStarDetector(TripleCandlePatternDetector):
    """
    Evening Star (bearish, 3-candle) - US Stock Optimized:
        - Candle 1: Long Bullish (Trend continuation).
        - Candle 2: Small body (Indecision/Star), gaps up from C1.
        - Candle 3: Long Bearish, gaps down from C2 (optional), closes deep into C1.
        - Logic: Exhaustion of bulls (C2) followed by strong bear attack (C3).
    """
    def __init__(
        self,
        *,
        # --- Core Shape Parameters ---
        # [Optimization] 0.3 (30%). 
        # The star (C2) should be small relative to the first candle. 
        # 0.5 is too big (looks like a normal candle).
        small_body2_ratio_vs_body1: float = 0.30,     

        # [Optimization] 0.5 (50%). 
        # C3 doesn't need to be huge (0.8), it just needs to penetrate deep enough into C1.
        min_body3_ratio_vs_body1: float = 0.50,       

        # [Optimization] True. 
        # This is the textbook definition. C3 must close below the midpoint of C1 to confirm reversal.
        require_c3_below_midpoint1: bool = True,      
        midpoint_margin_ratio: float = 0.0,           

        # --- Gap / Structure Parameters (US Stock Specific) ---
        # [Optimization] True. 
        # In US Stocks, gaps are meaningful. We expect C2 to open higher than C1 closed.
        require_gap_up_into_c2: bool = True,         
        
        # [Optimization] False. 
        # Gap down into C3 is rare even in stocks. Usually C3 opens inside C2's body or at C2's close.
        require_gap_down_into_c3: bool = False,       
        
        # [Optimization] True. 
        # The Star (C2) should be the highest point (High2 > High1 & High3).
        require_top_structure: bool = True,           
        
        lenient_overlap_tolerance: float = 1e-9,      

        # --- Indecision / Star Quality ---
        # [Optimization] 0.3 (30%). 
        # The body of the star should be small relative to its own range (wicks).
        max_body2_ratio_vs_range2: Optional[float] = 0.30,  
        
        # [Optimization] None. 
        # Removed min_shadows2_to_body as it's redundant if we check body ratio vs range.

        # --- Wick Logic (Rejection) ---
        # [Optimization] 0.3 (30%). 
        # C3 should close near its low. Long lower wick means buyers are fighting back.
        max_lower_wick_ratio_c3: Optional[float] = 0.3, 

        # --- Volume Logic ---
        # [Optimization] False (Default), but HIGHLY recommended True in config.
        # Reversals on low volume are often fakeouts.
        require_volume_increase: bool = False,          

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Adaptation ---
        body3_atr_alpha: float = 1.0,                          
        body3_atr_bounds: Tuple[float, float] = (0.7, 1.5),    
        min_body3_vs_atr: Optional[float] = None               
    ):
        self.defaults = dict(
            small_body2_ratio_vs_body1=small_body2_ratio_vs_body1,
            min_body3_ratio_vs_body1=min_body3_ratio_vs_body1,
            require_c3_below_midpoint1=require_c3_below_midpoint1,
            midpoint_margin_ratio=midpoint_margin_ratio,
            require_gap_up_into_c2=require_gap_up_into_c2,
            require_gap_down_into_c3=require_gap_down_into_c3,
            require_top_structure=require_top_structure,
            lenient_overlap_tolerance=lenient_overlap_tolerance,
            max_body2_ratio_vs_range2=max_body2_ratio_vs_range2,
            max_lower_wick_ratio_c3=max_lower_wick_ratio_c3,
            require_volume_increase=require_volume_increase,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body3_atr_alpha=body3_atr_alpha,
            body3_atr_bounds=body3_atr_bounds,
            min_body3_vs_atr=min_body3_vs_atr,
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
        v1: Optional[float] = None, v2: Optional[float] = None, v3: Optional[float] = None,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Basic hygiene
        if any(x is None for x in (o1, c1, o2, c2, o3, c3)):
            return PatternResult(is_pattern=False)

        first_bullish = c1 > o1
        third_bearish = c3 < o3
        if not (first_bullish and third_bearish):
            return PatternResult(is_pattern=False)

        # Bodies
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        body3 = abs(c3 - o3)
        
        # Strict tiny body check
        if body1 <= p["min_range"] or body3 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        midpoint1 = (o1 + c1) / 2.0

        def valid_range(h, l): return (h is not None) and (l is not None) and (h >= l)
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None
        price_range3 = (h3 - l3) if valid_range(h3, l3) else None

        # --- Core conditions ---

        # (1) Candle 2 small relative to body1
        small2_ok = body2 <= (body1 * p["small_body2_ratio_vs_body1"] * (1 + p["float_tolerance"]))

        # Optional: indecision using candle 2’s own range
        indecision2_ok = True
        if price_range2 is not None and p["max_body2_ratio_vs_range2"] is not None:
            body_ratio2_vs_range2 = body2 / price_range2
            indecision2_ok = (body_ratio2_vs_range2 <= (p["max_body2_ratio_vs_range2"] * (1 + p["float_tolerance"])))

        # (2) Candle 3 closes below midpoint of candle 1
        midpoint_ok = True
        if p["require_c3_below_midpoint1"]:
            margin = (body1 * p["midpoint_margin_ratio"]) if (p["midpoint_margin_ratio"] and p["midpoint_margin_ratio"] > 0.0) else 0.0
            midpoint_ok = c3 <= (midpoint1 - margin * (1 - p["float_tolerance"]))

        # (3) Candle 3 body strength vs body1 (ATR adaptive)
        body3_vs_body1_ok = body3 >= (body1 * p["min_body3_ratio_vs_body1"] * (1 - p["float_tolerance"]))
        body3_atr_scaler = None
        effective_min_body3_ratio = p["min_body3_ratio_vs_body1"]

        if atr is not None and atr > 0.0 and price_range3 is not None:
            lo, hi = p["body3_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body3_atr_scaler = p["body3_atr_alpha"] * (atr / price_range3)
            body3_atr_scaler = max(lo, min(hi, body3_atr_scaler))
            effective_min_body3_ratio = p["min_body3_ratio_vs_body1"] / body3_atr_scaler
            body3_vs_body1_ok = body3 >= (body1 * effective_min_body3_ratio * (1 - p["float_tolerance"]))

        atr_body3_ok = True
        if atr is not None and atr > 0.0 and p["min_body3_vs_atr"]:
            atr_body3_ok = body3 >= (p["min_body3_vs_atr"] * atr) * (1 - p["float_tolerance"])

        # (4) Gap semantics
        gap_up_ok = True
        gap_down_ok = True
        if p["require_gap_up_into_c2"]:
            # Open2 > Close1 (Standard Gap Up)
            gap_up_ok = o2 >= (c1 * (1 + p["lenient_overlap_tolerance"]))
        if p["require_gap_down_into_c3"]:
            # Open3 < Close2 (Standard Gap Down, optional)
            gap_down_ok = o3 <= (c2 * (1 - p["lenient_overlap_tolerance"]))

        # (5) Top Structure Check
        structure_ok = True
        if p["require_top_structure"]:
            if h1 is not None and h2 is not None and h3 is not None:
                structure_ok = (h2 >= h1) and (h2 >= h3)
            else:
                # Fallback to bodies if highs missing
                structure_ok = (max(o2, c2) >= max(o1, c1)) and (max(o2, c2) >= max(o3, c3))

        # (6) Volume Confirmation
        volume_ok = True
        if p["require_volume_increase"]:
            if v1 is not None and v3 is not None:
                volume_ok = v3 > v1
            else:
                volume_ok = False

        # (7) Wick Analysis (Safe calculation)
        wick_ok = True
        if p["max_lower_wick_ratio_c3"] is not None and h3 is not None and l3 is not None:
            # Bearish candle: Close is bottom of body
            lower_wick = max(0.0, c3 - l3) 
            if lower_wick > (body3 * p["max_lower_wick_ratio_c3"] * (1 + p["float_tolerance"])):
                wick_ok = False

        # Final decision
        conditions = [
            first_bullish, third_bearish,
            small2_ok, indecision2_ok,
            midpoint_ok, body3_vs_body1_ok, atr_body3_ok,
            gap_up_ok, gap_down_ok,
            structure_ok, volume_ok, wick_ok
        ]

        if not all(conditions):
            return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2, "body3": body3,
            "vol_increase": (v3/v1) if (v1 and v3 and v1 > 0) else None,
            "lower_wick_ratio_c3": ((c3 - l3)/body3) if (l3 and body3 > 0) else 0.0,
            "effective_min_body3_ratio": effective_min_body3_ratio,
            "body3_atr_scaler": body3_atr_scaler,
            "params": {**self.defaults, "atr": atr, **overrides}, # Added params
        }

        return PatternResult(
            is_pattern=True,
            name="Evening Star",
            bias="short",
            metrics=metrics
        )
