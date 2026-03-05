from typing import Optional, Tuple, Dict, Any
from tradercat.core.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult


class PiercingPatternDetector(DoubleCandlePatternDetector):
    """
    Piercing Pattern (Bullish Reversal) - US Stock Optimized:
        - Candle 1: Long Bearish (Panic/Trend).
        - Candle 2: Bullish.
        - Logic: C2 Gaps Down (Open2 < Close1), but rallies to close above the Midpoint of C1.
        - Psychology: Bears tried to push lower at the open, but Bulls absorbed everything and pushed price deep into Bear territory.
    """
    def __init__(
        self,
        *,
        # --- Gap Logic (Crucial for Piercing) ---
        # [Optimization] True. 
        # In US Stocks, the "Gap Down" at the open is essential. 
        # Open2 must be lower than Close1.
        require_open_below_close1: bool = True,
        
        # --- Midpoint Logic (The Definition) ---
        # [Optimization] True. 
        # C2 must close above the 50% mark of C1's body. 
        # If it fails to do this, it's a bearish continuation pattern (On-Neck/In-Neck).
        require_close_above_midpoint1: bool = True,
        midpoint_margin_ratio: float = 0.0,

        # --- Pattern Distinction ---
        # [Optimization] True. 
        # If C2 closes above Open1, it becomes a "Bullish Engulfing". 
        # We keep this True to strictly separate "Piercing" from "Engulfing".
        require_close_below_open1: bool = True,

        # --- Body Strength ---
        # [Optimization] 0.20 (20%). 
        # Candle 1 must be a significant "Long Black Candle". 
        # A piercing pattern after a tiny doji is meaningless noise.
        min_body_ratio1: Optional[float] = 0.20,
        
        # [Optimization] 0.15 (15%). 
        # Candle 2 must also have a real body to show conviction.
        min_body_ratio2: Optional[float] = 0.15,

        # --- Wick Logic (Rejection) ---
        # [Optimization] 0.30 (30%). 
        # If C2 leaves a long upper wick, it means Bulls failed to hold the highs.
        max_upper_wick_ratio2: Optional[float] = 0.30,

        # --- Volume Logic ---
        # [Optimization] False (Default), but HIGHLY recommended True in config.
        # A high volume recovery confirms the "Bear Trap".
        require_volume_increase: bool = False,

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Adaptation ---
        body2_atr_alpha: float = 1.0,
        body2_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        min_body1_vs_atr: Optional[float] = None,
        min_body2_vs_atr: Optional[float] = None,
    ):
        self.defaults = dict(
            require_open_below_close1=require_open_below_close1,
            require_close_above_midpoint1=require_close_above_midpoint1,
            require_close_below_open1=require_close_below_open1,
            midpoint_margin_ratio=midpoint_margin_ratio,
            min_body_ratio1=min_body_ratio1,
            min_body_ratio2=min_body_ratio2,
            max_upper_wick_ratio2=max_upper_wick_ratio2,
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
        h1: float, l1: float,  # Mandatory
        h2: float, l2: float,  # Mandatory
        v1: Optional[float] = None, 
        v2: Optional[float] = None,
        *,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p: Dict[str, Any] = {**self.defaults, **overrides}

        # 1. Direction & Hygiene
        # C1 must be Bearish, C2 must be Bullish
        if self.is_bullish(o1, c1): return PatternResult(is_pattern=False)
        if not self.is_bullish(o2, c2): return PatternResult(is_pattern=False)

        body1 = self.get_body(o1, c1)
        body2 = self.get_body(o2, c2)
        range1 = self.get_range(h1, l1)
        range2 = self.get_range(h2, l2)

        if range1 <= p["min_range"] or range2 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # 2. Gap Logic (Open2 < Close1)
        if p["require_open_below_close1"]:
            if not (o2 <= c1 * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 3. Midpoint Logic (Close2 > Midpoint1)
        # Typically Midpoint = (Open + Close) / 2. Since C1 is Bearish, Top is Open, Bottom is Close.
        midpoint1 = (o1 + c1) / 2.0
        if p["require_close_above_midpoint1"]:
            margin = body1 * p["midpoint_margin_ratio"]
            # Close2 must be above (midpoint - margin)
            if not (c2 >= (midpoint1 - margin) * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 4. Distinction Logic (Close2 <= Open1)
        # Don't overlap completely (that would be Engulfing)
        if p["require_close_below_open1"]:
            if not (c2 <= o1 * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 5. Upper Wick Check (Weakness check)
        if p["max_upper_wick_ratio2"] is not None:
            upper_wick2 = self.get_upper_shadow(o2, h2, c2)
            safe_body2 = body2 if body2 > p["min_range"] else p["min_range"]
            if (upper_wick2 / safe_body2) > (p["max_upper_wick_ratio2"] * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 6. Range & Ratio Checks
        # Body 1 Ratio
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

        # 8. Volume Check
        if p["require_volume_increase"]:
            # Strict mode: fail if data missing
            if v1 is None or v2 is None:
                return PatternResult(is_pattern=False)
            if v2 <= v1:
                return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2,
            "midpoint1": midpoint1,
            "gap_ok": True,
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "upper_wick_ratio2": (self.get_upper_shadow(o2, h2, c2) / body2) if body2 > 0 else 0,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(
            is_pattern=True,
            name="Piercing Pattern",
            bias="long",
            metrics=metrics
        )