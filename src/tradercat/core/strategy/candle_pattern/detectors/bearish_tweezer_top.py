from typing import Optional, Dict, Any, Tuple
from tradercat.core.strategy.candle_pattern.pattern_detector import PatternResult, DoubleCandlePatternDetector

class TweezerTopDetector(DoubleCandlePatternDetector):
    """
    Tweezer Top (Bearish Reversal) - US Stock Optimized:
        - Pattern: Two candles with matching Highs (Resistance Test).
        - Candle 1: Bullish (Bulls push to High).
        - Candle 2: Bearish (Bulls try again, fail, Bears take over).
        - Logic: Double rejection at the same price level indicates a strong supply zone.
    """

    def __init__(
        self,
        *,
        # --- Similarity Controls (The Core Logic) ---
        # [Optimization] 0.05 (5%).
        # We calculate tolerance based on the Candle Range. 
        # If a stock moves $1.00, we allow the highs to differ by $0.05.
        # A fixed price difference doesn't work across different stock prices ($10 vs $1000).
        high_similarity_tolerance: float = 0.05,          
        
        # [Optimization] ATR Adaptive Scaling.
        # If volatility (ATR) is high relative to the candle range, we relax the tolerance slightly.
        # If volatility is low, we tighten it.
        tolerance_scale_alpha: float = 1.0,                
        tolerance_scale_bounds: Tuple[float, float] = (0.7, 1.5),

        # --- Candle Roles ---
        # [Optimization] True. 
        # Tweezer Top is a reversal pattern. 
        # We need an Up move (Green) followed by a Down move (Red) to confirm the shift in sentiment.
        require_bullish_first: bool = True,
        require_bearish_second: bool = True,

        # --- Body Filters ---
        # [Optimization] 0.15 (15%).
        # We want visible bodies to ensure significant trading activity.
        # Rejection with tiny dojis is less reliable than rejection with full bodies.
        min_body_ratio_first: float = 0.15,                
        min_body_ratio_second: float = 0.15,               

        # --- Shadow Logic ---
        # [Optimization] False. 
        # While long wicks are common, a "Shaved Head" (Marubozu) hitting resistance is just as valid.
        # We don't enforce shadows, we just enforce matching highs.
        require_upper_shadow_first: bool = False,          
        require_upper_shadow_second: bool = False,

        # --- Volume Logic ---
        # [Optimization] False (Default), but recommended True in config.
        # Rejection on higher volume (Vol2 > Vol1) is a stronger signal of supply entering the market.
        require_volume_increase: bool = False,             

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Hard Caps ---
        # [Optimization] 0.1 (10% of ATR).
        # This is a safety net. Even if the candles are huge (allowing for a large relative tolerance),
        # the difference in Highs should never exceed 10% of the daily ATR.
        max_high_diff_atr_ratio: Optional[float] = 0.1,   
    ):
        self.defaults = dict(
            high_similarity_tolerance=high_similarity_tolerance,
            tolerance_scale_alpha=tolerance_scale_alpha,
            tolerance_scale_bounds=tolerance_scale_bounds,
            require_bullish_first=require_bullish_first,
            require_bearish_second=require_bearish_second,
            min_body_ratio_first=min_body_ratio_first,
            min_body_ratio_second=min_body_ratio_second,
            require_upper_shadow_first=require_upper_shadow_first,
            require_upper_shadow_second=require_upper_shadow_second,
            require_volume_increase=require_volume_increase,
            min_range=min_range,
            float_tolerance=float_tolerance,
            max_high_diff_atr_ratio=max_high_diff_atr_ratio,
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

        # 1. Hygiene & Ranges
        range1 = self.get_range(h1, l1)
        range2 = self.get_range(h2, l2)
        if range1 <= p["min_range"] or range2 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # 2. Logic Check: Roles
        if p["require_bullish_first"]:
            if not self.is_bullish(o1, c1):
                return PatternResult(is_pattern=False)
        
        if p["require_bearish_second"]:
            if self.is_bullish(o2, c2):
                return PatternResult(is_pattern=False)

        # 3. Body Filters
        body1 = self.get_body(o1, c1)
        body2 = self.get_body(o2, c2)
        
        if (body1 / range1) < (p["min_body_ratio_first"] * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)
            
        if (body2 / range2) < (p["min_body_ratio_second"] * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # 4. Upper shadows (Optional)
        if p["require_upper_shadow_first"]:
            if self.get_upper_shadow(o1, h1, c1) <= p["min_range"]:
                return PatternResult(is_pattern=False)
                
        if p["require_upper_shadow_second"]:
            if self.get_upper_shadow(o2, h2, c2) <= p["min_range"]:
                return PatternResult(is_pattern=False)

        # 5. Similar Highs (The Core Logic)
        high_diff = abs(h1 - h2)
        avg_range = (range1 + range2) / 2.0
        
        # Base tolerance calculation
        tol = p["high_similarity_tolerance"] * avg_range

        # ATR scaler (Adaptive)
        atr_scaler = 1.0
        if atr is not None and atr > 0.0:
            lo, hi = p["tolerance_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            atr_scaler = p["tolerance_scale_alpha"] * (atr / avg_range)
            atr_scaler = max(lo, min(hi, atr_scaler))
            tol *= atr_scaler

        # Check: Within Tolerance
        if high_diff > (tol * (1 + p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # Check: ATR Hard Cap (Safety)
        if atr is not None and atr > 0.0 and p["max_high_diff_atr_ratio"]:
            if high_diff > (p["max_high_diff_atr_ratio"] * atr * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 6. Volume Confirmation
        if p["require_volume_increase"]:
            if v1 is not None and v2 is not None:
                if v2 <= v1:
                    return PatternResult(is_pattern=False)

        metrics: Dict[str, Any] = {
            "high_diff": high_diff,
            "tolerance": tol,
            "atr_scaler": atr_scaler,
            "vol_increase": (v2/v1) if (v1 and v2 and v1 > 0) else None,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(
            is_pattern=True, 
            name="Tweezer Top",
            bias="short",
            metrics=metrics
        )
