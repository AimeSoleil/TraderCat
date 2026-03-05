from typing import Optional, Tuple, Dict, Any
from tradercat.core.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector


class ShootingStarDetector(SingleCandlePatternDetector):
    """
    Shooting Star (Bearish Reversal) - US Stock Optimized:
        - Shape: Small body near the bottom of the range.
        - Shadow: Long upper shadow (>= 2x body), little to no lower shadow.
        - Psychology: Bulls pushed price to new highs (Bull Trap), but Bears slammed it back down to close near the lows.
        - Context: Valid only after an uptrend (handled by Orchestrator) or Gap Up.
    """
    def __init__(
        self,
        *,
        # --- Shape Constraints ---
        # [Optimization] 0.10 (10%). 
        # We need a visible body to distinguish from a "Gravestone Doji".
        # A Shooting Star has a small but real body.
        body_ratio_min: float = 0.10,               

        # [Optimization] 2.0 (2x). 
        # The upper shadow must be at least twice the length of the body.
        # This is the definition of the pattern (Rejection).
        min_upper_shadow_to_body: float = 2.0,      
        
        # [Optimization] 0.20 (20%). 
        # Ideally 0, but in US stocks (microstructure noise), we allow a small lower wick.
        # If the lower wick is too long, it indicates buying pressure at the close (weakness).
        max_lower_shadow_to_body: float = 0.20,     

        # --- Shadow Flags ---
        require_upper_shadow: bool = True,
        require_lower_shadow: bool = False,         

        # --- Color / Direction ---
        # [Optimization] False (Default), but HIGHLY recommended True for strict Algo.
        # A Red Shooting Star (Close < Open) shows Bears actually won the session.
        require_bearish_body: bool = False,         

        # --- Close Position (Crucial) ---
        # [Optimization] 0.25 (Bottom 25%). 
        # The close must be in the lower quartile of the range. 
        # This ensures the Bears are in control at the end of the period.
        require_close_lower_fraction: Optional[float] = 0.25,

        # --- Context Logic ---
        # [Optimization] False (Default). 
        # In Daily charts, a Gap Up adds massive conviction (Bull Trap).
        require_gap_up: bool = False,               

        # [Optimization] False (Default). 
        # Rejection on high volume is the gold standard for reversals.
        require_high_volume: bool = False,          

        # [Optimization] False (Default). 
        # A Shooting Star is ONLY valid if it occurs at a local High. 
        require_new_high: bool = False,             

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Adaptation ---
        body_atr_alpha: float = 1.0,                
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),  
        min_upper_vs_atr: Optional[float] = None,   
        max_lower_vs_atr: Optional[float] = None,   
        max_body_vs_atr: Optional[float] = None,    
    ):
        self.defaults = dict(
            body_ratio_min=body_ratio_min,
            min_upper_shadow_to_body=min_upper_shadow_to_body,
            max_lower_shadow_to_body=max_lower_shadow_to_body,
            require_upper_shadow=require_upper_shadow,
            require_lower_shadow=require_lower_shadow,
            require_bearish_body=require_bearish_body,
            require_close_lower_fraction=require_close_lower_fraction,
            require_gap_up=require_gap_up,
            require_high_volume=require_high_volume,
            require_new_high=require_new_high,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body_atr_alpha=body_atr_alpha,
            body_atr_bounds=body_atr_bounds,
            min_upper_vs_atr=min_upper_vs_atr,
            max_lower_vs_atr=max_lower_vs_atr,
            max_body_vs_atr=max_body_vs_atr,
        )

    def detect(
        self,
        open_: float, high: float, low: float, close: float,
        volume: Optional[float] = None,
        prev_close: Optional[float] = None, 
        prev_high: Optional[float] = None,  
        prev_vol: Optional[float] = None,
        *,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p: Dict[str, Any] = {**self.defaults, **overrides}

        # Hygiene: Range too small
        price_range = self.get_range(high, low)
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # Basic Calcs
        body = self.get_body(open_, close)
        upper_shadow = self.get_upper_shadow(open_, high, close)
        lower_shadow = self.get_lower_shadow(open_, low, close)

        # 1. Color Check
        if p["require_bearish_body"]:
            if self.is_bullish(open_, close): 
                return PatternResult(is_pattern=False)

        # 2. Gap Check (Context)
        if p["require_gap_up"]:
            # Fail fast if data missing in strict mode
            if prev_close is None:
                return PatternResult(is_pattern=False)
            if open_ <= (prev_close * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 3. Volume Check (Context)
        if p["require_high_volume"]:
            if volume is None or prev_vol is None:
                return PatternResult(is_pattern=False)
            if volume <= (prev_vol * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 4. New High Check (Context)
        if p["require_new_high"]:
            if prev_high is None:
                return PatternResult(is_pattern=False)
            if high <= (prev_high * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # Ratio & ATR Scaling
        body_ratio = body / price_range
        effective_min_body_ratio = p["body_ratio_min"]
        
        # ATR Adaptation for Body Min Ratio
        if atr is not None and atr > 0.0:
            lo, hi = p["body_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            # Ratio Logic:
            # If Range is tiny (Dull), ATR/Range > 1 -> Scaler > 1. 
            # We reduce min_body_ratio (allow Doji-like).
            # If Range is huge (Expansion), ATR/Range < 1 -> Scaler < 1. 
            # We increase min_body_ratio (strictly require visible body).
            body_atr_scaler = p["body_atr_alpha"] * (atr / price_range)
            body_atr_scaler = max(lo, min(hi, body_atr_scaler))
            effective_min_body_ratio = effective_min_body_ratio / body_atr_scaler

        # --- Core Shape Logic ---

        # A. Body Size (Must be visible but smallish)
        # Note: shooting star usually implies max body size implicitly via shadow ratio (2x shadow means body max 33%)
        if body_ratio < (effective_min_body_ratio * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # B. Upper Shadow (The Star tail)
        # Avoid div/0. If body is very tiny, use min_range safe-guard
        ref_size = body if body > p["min_range"] else p["min_range"]
        upper_to_body = upper_shadow / ref_size
        
        if upper_to_body < (p["min_upper_shadow_to_body"] * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)
            
        if p["require_upper_shadow"] and upper_shadow <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # C. Lower Shadow (Should be tiny)
        lower_to_body = lower_shadow / ref_size
        if lower_to_body > (p["max_lower_shadow_to_body"] * (1 + p["float_tolerance"])):
             return PatternResult(is_pattern=False)

        # D. Close Position (Close near Low)
        if p["require_close_lower_fraction"] is not None:
            # (Close - Low) / Range. If close == low, result is 0.
            close_pos_frac = (close - low) / price_range
            if close_pos_frac > (p["require_close_lower_fraction"] * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # E. Absolute ATR Constraints (Optional filters)
        if atr is not None and atr > 0.0:
            if p["min_upper_vs_atr"] and upper_shadow < (p["min_upper_vs_atr"] * atr):
                return PatternResult(is_pattern=False)
            if p["max_lower_vs_atr"] and lower_shadow > (p["max_lower_vs_atr"] * atr):
                return PatternResult(is_pattern=False)
            if p["max_body_vs_atr"] and body > (p["max_body_vs_atr"] * atr):
                return PatternResult(is_pattern=False)

        metrics = {
            "body": body,
            "upper_shadow": upper_shadow,
            "upper_to_body": upper_to_body,
            "is_bearish_body": not self.is_bullish(open_, close),
            "gap_up": (open_ > prev_close) if prev_close else None,
            "volume_spike": (volume > prev_vol) if (volume and prev_vol) else None,
            "body_ratio": body_ratio,
            "close_lower_frac": (close - low) / price_range,
            "effective_min_body_ratio": effective_min_body_ratio,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(
            is_pattern=True, name="Shooting Star", bias="short", metrics=metrics
        )