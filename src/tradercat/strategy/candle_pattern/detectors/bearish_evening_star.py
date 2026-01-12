from typing import Optional, Tuple, Dict, Any
from tradercat.strategy.candle_pattern.pattern_detector import TripleCandlePatternDetector, PatternResult

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
        
        # --- Wick Logic (Rejection) ---
        # [Optimization] 0.3 (30%). 
        # C3 should close near its low. Long lower wick means buyers are fighting back.
        max_lower_wick_ratio_c3: Optional[float] = 0.3, 

        # --- Volume Logic ---
        # [Optimization] False (Default), but HIGHLY recommended True in config.
        # Reversals on low volume are often fakeouts.
        require_volume_increase_c3: bool = False,          

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
            require_volume_increase_c3=require_volume_increase_c3,
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
        h1: float, l1: float,  # Mandatory
        h2: float, l2: float,  # Mandatory
        h3: float, l3: float,  # Mandatory
        v1: Optional[float] = None, 
        v2: Optional[float] = None, 
        v3: Optional[float] = None,
        *,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p: Dict[str, Any] = {**self.defaults, **overrides}

        # 1. Directions
        # C1 Bull, C3 Bear. C2 can be anything (Doji/Star).
        if not (self.is_bullish(o1, c1) and not self.is_bullish(o3, c3)):
            return PatternResult(is_pattern=False)

        # Basic Calculations
        body1 = self.get_body(o1, c1)
        body2 = self.get_body(o2, c2)
        body3 = self.get_body(o3, c3)
        range2 = self.get_range(h2, l2)
        range3 = self.get_range(h3, l3)
        
        # Hygiene
        if body1 <= p["min_range"] or body3 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        midpoint1 = (o1 + c1) / 2.0

        # --- Core conditions ---

        # (1) Candle 2 small relative to body1 (The "Star" definition)
        if body2 > (body1 * p["small_body2_ratio_vs_body1"] * (1 + p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # Optional: indecision using candle 2’s own range (Real Body is small part of total range)
        if p["max_body2_ratio_vs_range2"] is not None:
            eff_range2 = range2 if range2 > p["min_range"] else p["min_range"]
            if (body2 / eff_range2) > (p["max_body2_ratio_vs_range2"] * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # (2) Candle 3 closes below midpoint of candle 1 (Penetration)
        if p["require_c3_below_midpoint1"]:
            margin = (body1 * p["midpoint_margin_ratio"]) if (p["midpoint_margin_ratio"] and p["midpoint_margin_ratio"] > 0.0) else 0.0
            if c3 > (midpoint1 - margin * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # (3) Candle 3 body strength vs body1 (ATR adaptive)
        effective_min_body3_ratio = p["min_body3_ratio_vs_body1"]
        body3_atr_scaler = 1.0

        if atr is not None and atr > 0.0:
            lo, hi = p["body3_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            
            eff_range3 = range3 if range3 > p["min_range"] else p["min_range"]
            raw_scaler = p["body3_atr_alpha"] * (atr / eff_range3)
            body3_atr_scaler = max(lo, min(hi, raw_scaler))
            effective_min_body3_ratio = effective_min_body3_ratio / body3_atr_scaler

        if body3 < (body1 * effective_min_body3_ratio * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # Absolute ATR check
        if atr is not None and atr > 0.0 and p["min_body3_vs_atr"]:
            if body3 < (p["min_body3_vs_atr"] * atr):
                return PatternResult(is_pattern=False)

        # (4) Gap semantics
        if p["require_gap_up_into_c2"]:
            # Open2 >= Close1
            if not o2 >= (c1 * (1 - p["lenient_overlap_tolerance"])):
                return PatternResult(is_pattern=False)
                
        if p["require_gap_down_into_c3"]:
            # Open3 <= Close2
            limit_c2 = min(o2, c2) # Bottom of body C2
            if not o3 <= (limit_c2 * (1 + p["lenient_overlap_tolerance"])):
                return PatternResult(is_pattern=False)

        # (5) Top Structure Check (Strict Highs)
        if p["require_top_structure"]:
            # C2 must be the peak (High2 >= High1 & High2 >= High3)
            if not ((h2 >= h1 * (1 - p["float_tolerance"])) and (h2 >= h3 * (1 - p["float_tolerance"]))):
                return PatternResult(is_pattern=False)

        # (6) Volume Confirmation (Increase from Star)
        if p["require_volume_increase_c3"]:
            # Strict mode: fail if data missing
            if v2 is None or v3 is None:
                return PatternResult(is_pattern=False)
            if not (v3 > v2):
                return PatternResult(is_pattern=False)

        # (7) Wick Analysis (Rejection at bottom of C3)
        if p["max_lower_wick_ratio_c3"] is not None:
            lower_wick3 = self.get_lower_shadow(o3, l3, c3)
            if lower_wick3 > (body3 * p["max_lower_wick_ratio_c3"] * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2, "body3": body3,
            "midpoint1": midpoint1,
            "atr": atr,
            "volume_increase_c3": (v3/v2) if (v2 and v3 and v2 > 0) else None,
            "lower_wick_ratio_c3": (self.get_lower_shadow(o3, l3, c3)/body3) if body3 > 0 else 0.0,
            "effective_min_body3_ratio": effective_min_body3_ratio,
            "body3_atr_scaler": body3_atr_scaler,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(
            is_pattern=True,
            name="Evening Star",
            bias="short",
            metrics=metrics
        )
