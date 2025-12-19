from typing import Optional, Tuple
from tradercat.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector


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
        *,
        # Context for Gap/Volume checks
        prev_close: Optional[float] = None,
        prev_high: Optional[float] = None,  
        vol: Optional[float] = None,
        prev_vol: Optional[float] = None,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Hygiene
        if any(x is None for x in (open_, high, low, close)) or high < low:
            return PatternResult(is_pattern=False)

        price_range = high - low
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # Magnitudes
        body = abs(close - open_)
        upper_shadow = max(0.0, high - max(open_, close))
        lower_shadow = max(0.0, min(open_, close) - low)

        # 1. Color Check (Bearish Preference)
        if p["require_bearish_body"]:
            if close > open_: # If Green, reject
                return PatternResult(is_pattern=False)

        # 2. Gap Check (Bull Trap)
        if p["require_gap_up"]:
            if prev_close is None or open_ <= prev_close:
                return PatternResult(is_pattern=False)

        # 3. Volume Check (Supply Spike)
        if p["require_high_volume"]:
            if vol is None or prev_vol is None or vol <= prev_vol:
                return PatternResult(is_pattern=False)

        # 4. New High Check (Location Filter)
        if p["require_new_high"]:
            if prev_high is None or high <= prev_high:
                return PatternResult(is_pattern=False)

        # Ratios
        body_ratio = body / price_range
        # Handle zero body safely (though body_ratio_min usually handles this)
        safe_body = body if body > p["float_tolerance"] else p["float_tolerance"]
        upper_to_body = upper_shadow / safe_body
        lower_to_body = lower_shadow / safe_body

        # ATR-adaptive min body ratio
        effective_min_body_ratio = p["body_ratio_min"]
        body_atr_scaler = None
        if atr is not None and atr > 0.0:
            lo, hi = p["body_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body_atr_scaler = p["body_atr_alpha"] * (atr / price_range)
            body_atr_scaler = max(lo, min(hi, body_atr_scaler))
            effective_min_body_ratio = p["body_ratio_min"] / body_atr_scaler

        # --- Core Logic ---
        
        # A. Body must be visible (Not a Doji)
        body_ok = body_ratio >= (effective_min_body_ratio * (1 - p["float_tolerance"]))
        
        # B. Upper Shadow must be long (Rejection)
        upper_shadow_ok = upper_to_body >= (p["min_upper_shadow_to_body"] * (1 - p["float_tolerance"]))
        
        # C. Lower Shadow must be short (Close near lows)
        lower_shadow_ok = lower_to_body <= (p["max_lower_shadow_to_body"] * (1 + p["float_tolerance"]))

        # D. Close Position Filter (Must close near low)
        close_pos_ok = True
        if p["require_close_lower_fraction"] is not None:
            frac = (close - low) / price_range
            close_pos_ok = frac <= p["require_close_lower_fraction"] * (1 + p["float_tolerance"])

        # Optional ATR absolute constraints
        if atr is not None and atr > 0.0:
            if p["min_upper_vs_atr"] is not None and p["min_upper_vs_atr"] > 0.0:
                upper_shadow_ok = upper_shadow_ok and (upper_shadow >= (p["min_upper_vs_atr"] * atr) * (1 - p["float_tolerance"]))
            if p["max_lower_vs_atr"] is not None and p["max_lower_vs_atr"] > 0.0:
                lower_shadow_ok = lower_shadow_ok and (lower_shadow <= (p["max_lower_vs_atr"] * atr) * (1 + p["float_tolerance"]))
            if p["max_body_vs_atr"] is not None and p["max_body_vs_atr"] > 0.0:
                body_ok = body_ok and (body <= (p["max_body_vs_atr"] * atr) * (1 + p["float_tolerance"]))

        # Shadow presence requirements
        if p["require_upper_shadow"]:
            upper_shadow_ok = upper_shadow_ok and (upper_shadow > 0.0)
        if p["require_lower_shadow"]:
            lower_shadow_ok = lower_shadow_ok and (lower_shadow > 0.0)

        is_pattern = body_ok and upper_shadow_ok and lower_shadow_ok and close_pos_ok

        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body": body,
            "upper_shadow": upper_shadow,
            "upper_to_body": upper_to_body,
            "is_bearish_body": close < open_,
            "gap_up": (open_ > prev_close) if prev_close is not None else None,
            "volume_spike": (vol > prev_vol) if vol is not None and prev_vol is not None else None,
            "new_high": (high > prev_high) if prev_high is not None else None,
            "price_range": price_range,
            "lower_shadow": lower_shadow,
            "body_ratio": body_ratio,
            "lower_to_body": lower_to_body,
            "close_lower_frac": (close - low) / price_range,
            "effective_min_body_ratio": effective_min_body_ratio,
            "body_atr_scaler": body_atr_scaler,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(
            is_pattern=True,
            name="Shooting Star",
            bias="short",
            metrics=metrics
        )