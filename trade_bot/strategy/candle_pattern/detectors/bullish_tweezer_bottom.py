from typing import Optional, Dict, Any, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, DoubleCandlePatternDetector

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
        *,
        h1: float, l1: float, h2: float, l2: float,     
        atr: Optional[float] = None,
        v1: Optional[float] = None, 
        v2: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Hygiene checks
        if any(x is None for x in (o1, h1, l1, c1, o2, h2, l2, c2)):
            return PatternResult(is_pattern=False)
        if h1 < l1 or h2 < l2:
            return PatternResult(is_pattern=False)

        # Candle ranges and bodies
        range1 = h1 - l1
        range2 = h2 - l2
        if range1 <= p["min_range"] or range2 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)

        lower_shadow1 = max(0.0, min(o1, c1) - l1)
        lower_shadow2 = max(0.0, min(o2, c2) - l2)

        body_ratio1 = body1 / range1
        body_ratio2 = body2 / range2

        # 1. Role requirements
        bearish_first_ok = (c1 < o1) if p["require_bearish_first"] else True
        bullish_second_ok = (c2 > o2) if p["require_bullish_second"] else True

        # 2. Body filters
        body_first_ok = (body_ratio1 >= p["min_body_ratio_first"] * (1 - p["float_tolerance"]))
        body_second_ok = (body_ratio2 >= p["min_body_ratio_second"] * (1 - p["float_tolerance"]))

        # 3. Lower shadows presence
        lower_shadow_first_ok = (lower_shadow1 > 0.0) if p["require_lower_shadow_first"] else True
        lower_shadow_second_ok = (lower_shadow2 > 0.0) if p["require_lower_shadow_second"] else True

        # 4. Similar lows (The Core Logic)
        low_diff = abs(l1 - l2)

        # Scale tolerance based on the AVERAGE RANGE of the two candles.
        avg_range = (range1 + range2) / 2.0
        
        # Base tolerance calculation
        tol = p["low_similarity_tolerance"] * avg_range

        # ATR scaler (Adaptive)
        atr_scaler = 1.0
        if atr is not None and atr > 0.0:
            lo, hi = p["tolerance_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            # If ATR is high relative to current range, allow slightly more tolerance
            atr_scaler = p["tolerance_scale_alpha"] * (atr / avg_range)
            atr_scaler = max(lo, min(hi, atr_scaler))
            tol *= atr_scaler

        # Optional hard cap using ATR (Safety net)
        atr_cap_ok = True
        if atr is not None and atr > 0.0 and p["max_low_diff_atr_ratio"]:
            atr_cap_ok = (low_diff <= (p["max_low_diff_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        lows_similar_ok = (low_diff <= tol * (1 + p["float_tolerance"])) and atr_cap_ok

        # 5. Volume Confirmation
        volume_ok = True
        if p["require_volume_increase"]:
            if v1 is not None and v2 is not None:
                volume_ok = v2 > v1
            else:
                volume_ok = False

        # Final Decision
        conditions = [
            bearish_first_ok, bullish_second_ok,
            body_first_ok, body_second_ok,
            lower_shadow_first_ok, lower_shadow_second_ok,
            lows_similar_ok, volume_ok
        ]

        if not all(conditions):
            return PatternResult(is_pattern=False)

        metrics: Dict[str, Any] = {
            "low_diff": low_diff,
            "tolerance": tol,
            "atr_scaler": atr_scaler,
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(True, "Tweezer Bottom", "long", metrics)
