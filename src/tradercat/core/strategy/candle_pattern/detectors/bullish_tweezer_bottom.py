from typing import Optional, Dict, Any, Tuple
from tradercat.core.strategy.candle_pattern.pattern_detector import PatternResult, DoubleCandlePatternDetector

class TweezerBottomDetector(DoubleCandlePatternDetector):
    """
    Tweezer Bottom (Bullish, 2-candle) - US Stock Optimized:
        - Pattern: Two candles with matching Lows (Support Test).
        - Candle 1: Bearish (Bears push to Low).
        - Candle 2: Bullish (Bears try again, fail, Bulls take over).
        - Logic: Double rejection at the same price level.
    """

    def __init__(
        self,
        *,
        # --- Similarity Controls (Crucial for Algo) ---
        # [Optimization] Changed from 0.001 to 0.05 (5%).
        # We calculate tolerance based on the Candle Range. 
        # If a stock moves $1.00, we allow the lows to differ by $0.05.
        # 0.001 was too strict for real-world noise.
        low_similarity_tolerance: float = 0.05,          
        
        # ATR scaling allows looser tolerance in high volatility
        tolerance_scale_alpha: float = 1.0,               
        tolerance_scale_bounds: Tuple[float, float] = (0.7, 1.5),

        # --- Candle Roles ---
        # [Optimization] True. 
        # Tweezer Bottom is a reversal. We need a Down move (Red) followed by an Up move (Green).
        require_bearish_first: bool = True,
        require_bullish_second: bool = True,

        # --- Body Filters ---
        # [Optimization] 0.15 (15%).
        # We want visible bodies to ensure significant trading activity.
        min_body_ratio_first: float = 0.15,               
        min_body_ratio_second: float = 0.15,              

        # --- Shadow Logic ---
        # [Optimization] False. 
        # A "Shaved Bottom" (Marubozu) hitting support is just as valid as a wick.
        require_lower_shadow_first: bool = False,   
        require_lower_shadow_second: bool = False,  

        # --- Volume Logic ---
        # [Optimization] False (Default), but recommended True in config.
        # Rejection on higher volume (Vol2 > Vol1) is a stronger signal.
        require_volume_increase: bool = False,      

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Hard Caps ---
        # [Optimization] 0.1 (10% of ATR).
        # Even if ranges are huge, the difference in Lows shouldn't exceed 10% of the daily ATR.
        max_low_diff_atr_ratio: Optional[float] = 0.1,   
    ):
        self.defaults = dict(
            low_similarity_tolerance=low_similarity_tolerance,
            tolerance_scale_alpha=tolerance_scale_alpha,
            tolerance_scale_bounds=tolerance_scale_bounds,
            require_bearish_first=require_bearish_first,
            require_bullish_second=require_bullish_second,
            min_body_ratio_first=min_body_ratio_first,
            min_body_ratio_second=min_body_ratio_second,
            require_lower_shadow_first=require_lower_shadow_first,
            require_lower_shadow_second=require_lower_shadow_second,
            min_range=min_range,
            float_tolerance=float_tolerance,
            max_low_diff_atr_ratio=max_low_diff_atr_ratio,
            require_volume_increase=require_volume_increase,
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

        # 1. Hygiene checks
        range1 = self.get_range(h1, l1)
        range2 = self.get_range(h2, l2)
        if range1 <= p["min_range"] or range2 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # 2. Logic Check: Roles
        if p["require_bearish_first"]:
            if self.is_bullish(o1, c1):
                return PatternResult(is_pattern=False)

        if p["require_bullish_second"]:
            if not self.is_bullish(o2, c2):
                return PatternResult(is_pattern=False)

        # 3. Body filters
        body1 = self.get_body(o1, c1)
        body2 = self.get_body(o2, c2)
        
        if (body1 / range1) < (p["min_body_ratio_first"] * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)
        if (body2 / range2) < (p["min_body_ratio_second"] * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # 4. Lower shadows presence (Optional)
        if p["require_lower_shadow_first"]:
            if self.get_lower_shadow(o1, l1, c1) <= p["min_range"]:
                return PatternResult(is_pattern=False)
                
        if p["require_lower_shadow_second"]:
            if self.get_lower_shadow(o2, l2, c2) <= p["min_range"]:
                return PatternResult(is_pattern=False)

        # 5. Similar Lows (The Core Logic)
        low_diff = abs(l1 - l2)
        avg_range = (range1 + range2) / 2.0
        
        # Base tolerance calculation
        tol = p["low_similarity_tolerance"] * avg_range

        # ATR scaler (Adaptive)
        atr_scaler = 1.0
        if atr is not None and atr > 0.0:
            lo, hi = p["tolerance_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            atr_scaler = p["tolerance_scale_alpha"] * (atr / avg_range)
            atr_scaler = max(lo, min(hi, atr_scaler))
            tol *= atr_scaler

        # Check: Within Tolerance
        if low_diff > (tol * (1 + p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # Check: ATR Hard Cap (Safety)
        if atr is not None and atr > 0.0 and p["max_low_diff_atr_ratio"]:
            if low_diff > (p["max_low_diff_atr_ratio"] * atr * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 6. Volume Confirmation
        if p["require_volume_increase"]:
            if v1 is not None and v2 is not None:
                if v2 <= v1:
                    return PatternResult(is_pattern=False)
            # If data missing and strict mode, could fallback or fail. Orchestrator handles availability.
            # Assuming if flag is True, we want strict confirmation.

        metrics: Dict[str, Any] = {
            "low_diff": low_diff,
            "tolerance": tol,
            "atr_scaler": atr_scaler,
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(True, "Tweezer Bottom", "long", metrics)
