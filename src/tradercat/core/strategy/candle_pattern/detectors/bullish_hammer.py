from typing import Optional, Tuple, Dict, Any
from tradercat.core.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class HammerDetector(SingleCandlePatternDetector):
    """
    Hammer (Bullish Reversal) - US Stock Optimized:
    - Shape: Small body near the top of the range.
    - Shadow: Long lower shadow (>= 2x body), little to no upper shadow.
    - Psychology: Bears pushed price down significantly, but Bulls fought back to close near the highs.
    - Context: Valid only after a downtrend (handled by Orchestrator) or Gap Down.
    """
    def __init__(
        self,
        *,
        # --- Shape Constraints ---
        # [Optimization] 0.10 (10%). 
        # We need a visible body to distinguish from a "Dragonfly Doji".
        # A Hammer has a small but real body.
        body_ratio_min: float = 0.10,                 

        # [Optimization] 2.0 (2x). 
        # The lower shadow must be at least twice the length of the body.
        # This is the definition of the pattern.
        min_lower_shadow_to_body: float = 2.0,

        # [Optimization] 0.20 (20%). 
        # Ideally 0, but in US stocks (microstructure noise), we allow a small upper wick.
        # If the upper wick is too long, it indicates selling pressure at the close (weakness).
        max_upper_shadow_to_body: float = 0.20,

        # --- Shadow Flags ---
        require_lower_shadow: bool = True,
        require_upper_shadow: bool = False,

        # --- Color / Direction ---
        # [Optimization] False (Default), but HIGHLY recommended True for strict Algo.
        # A Green Hammer (Close > Open) shows Bulls actually won the session.
        require_bullish_body: bool = False,

        # --- Close Position (Crucial) ---
        # [Optimization] 0.75 (Top 25%). 
        # The close must be in the upper quartile of the range. 
        # This ensures the Bulls are in control at the end of the period.
        require_close_upper_fraction: Optional[float] = 0.75,

        # --- Context Logic ---
        # [Optimization] False (Default). 
        # In Daily charts, a Gap Down adds massive conviction (Bear Trap).
        require_gap_down: bool = False,               

        # [Optimization] False (Default). 
        # Rejection on high volume is the gold standard for reversals.
        require_volume_increase: bool = False,

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Adaptation ---
        body_atr_alpha: float = 1.0,
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        min_lower_vs_atr: Optional[float] = None,
        max_upper_vs_atr: Optional[float] = None,
        max_body_vs_atr: Optional[float] = None,
    ):
        self.defaults = dict(
            body_ratio_min=body_ratio_min,
            min_lower_shadow_to_body=min_lower_shadow_to_body,
            max_upper_shadow_to_body=max_upper_shadow_to_body,
            require_lower_shadow=require_lower_shadow,
            require_upper_shadow=require_upper_shadow,
            require_bullish_body=require_bullish_body,
            require_close_upper_fraction=require_close_upper_fraction,
            require_gap_down=require_gap_down,
            require_volume_increase=require_volume_increase,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body_atr_alpha=body_atr_alpha,
            body_atr_bounds=body_atr_bounds,
            min_lower_vs_atr=min_lower_vs_atr,
            max_upper_vs_atr=max_upper_vs_atr,
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
        
        # Hygiene
        price_range = self.get_range(high, low)
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # Components
        body = self.get_body(open_, close)
        upper_shadow = self.get_upper_shadow(open_, high, close)
        lower_shadow = self.get_lower_shadow(open_, low, close)

        # 1. Color Check
        if p["require_bullish_body"]:
            if not self.is_bullish(open_, close):
                return PatternResult(is_pattern=False)

        # 2. Context Checks (Fail Fast)
        if p["require_gap_down"]:
            if prev_close is None or not (open_ < (prev_close * (1 - p["float_tolerance"]))):
                return PatternResult(is_pattern=False)

        if p["require_volume_increase"]:
            if volume is None or prev_vol is None or volume <= prev_vol:
                return PatternResult(is_pattern=False)

        # 3. ATR Scaling for Body
        body_ratio = body / price_range
        effective_min_body_ratio = p["body_ratio_min"]
        body_atr_scaler = 1.0

        if atr and atr > 0:
            lo, hi = p["body_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body_atr_scaler = p["body_atr_alpha"] * (atr / price_range)
            # Limit scaling
            body_atr_scaler = max(lo, min(hi, body_atr_scaler))
            effective_min_body_ratio = effective_min_body_ratio / body_atr_scaler

        # 4. Body Size Check (Adaptive)
        if body_ratio < (effective_min_body_ratio * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # 5. Shadow Ratios (The "Hammer" Shape)
        # Use a safe denominator (ref_size) to avoid div/0 if body is extremely thin (Doji-like)
        ref_size = body if body > p["min_range"] else p["min_range"]
        
        lower_to_body = lower_shadow / ref_size
        upper_to_body = upper_shadow / ref_size

        # A. Large Lower Shadow
        if lower_to_body < (p["min_lower_shadow_to_body"] * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)
            
        # B. Small Upper Shadow
        if upper_to_body > (p["max_upper_shadow_to_body"] * (1 + p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # 6. Shadow Existence (Strict Flags)
        if p["require_lower_shadow"] and lower_shadow <= p["min_range"]:
            return PatternResult(is_pattern=False)
        if p["require_upper_shadow"] and upper_shadow <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # 7. Close Position (Close near Highs)
        if p["require_close_upper_fraction"] is not None:
            # How high up in the range is the close?
            close_pos_frac = (close - low) / price_range
            if close_pos_frac < (p["require_close_upper_fraction"] * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 8. Absolute ATR Checks
        if atr and atr > 0:
            if p["min_lower_vs_atr"] and lower_shadow < (p["min_lower_vs_atr"] * atr):
                return PatternResult(is_pattern=False)
            if p["max_upper_vs_atr"] and upper_shadow > (p["max_upper_vs_atr"] * atr):
                return PatternResult(is_pattern=False)
            if p["max_body_vs_atr"] and body > (p["max_body_vs_atr"] * atr):
                return PatternResult(is_pattern=False)

        metrics = {
            "body": body, "price_range": price_range,
            "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
            "body_ratio": body_ratio,
            "upper_to_body": upper_to_body, "lower_to_body": lower_to_body,
            "effective_min_body_ratio": effective_min_body_ratio,
            "body_atr_scaler": body_atr_scaler,
            "close_upper_frac": (close - low) / price_range,
            "volume_increase": (volume / prev_vol) if (volume and prev_vol and prev_vol > 0) else None,
            "gap_down": (open_ < prev_close) if prev_close else None,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(
            is_pattern=True,
            name="Hammer",
            bias="long",  # pattern bias; in production, condition on trend/location/volume
            metrics=metrics
        )
