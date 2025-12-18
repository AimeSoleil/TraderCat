from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

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
        *, 
        atr: Optional[float] = None,
        vol: Optional[float] = None, 
        prev_vol: Optional[float] = None, 
        prev_close: Optional[float] = None, 
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}
        
        # Hygiene
        if any(x is None for x in (open_, high, low, close)) or high < low:
            return PatternResult(is_pattern=False)

        price_range = high - low
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # Components
        body = abs(close - open_)
        upper_shadow = max(0.0, high - max(open_, close))
        lower_shadow = max(0.0, min(open_, close) - low)

        # Ratios
        body_ratio = body / price_range
        
        # Handle zero body (Doji) safely for ratios
        safe_body = body if body > p["float_tolerance"] else p["float_tolerance"]
        upper_to_body = upper_shadow / safe_body
        lower_to_body = lower_shadow / safe_body

        # ATR Scaling for minimum body size
        effective_min_body_ratio = p["body_ratio_min"]
        body_atr_scaler = 1.0
        if atr and atr > 0:
            lo, hi = p["body_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body_atr_scaler = p["body_atr_alpha"] * (atr / price_range)
            body_atr_scaler = max(lo, min(hi, body_atr_scaler))
            effective_min_body_ratio = p["body_ratio_min"] / body_atr_scaler

        # 1. Body Size Check
        body_ok = body_ratio >= (effective_min_body_ratio * (1 - p["float_tolerance"]))

        # 2. Shadow Ratios Check
        lower_shadow_ok = lower_to_body >= (p["min_lower_shadow_to_body"] * (1 - p["float_tolerance"]))
        upper_shadow_ok = upper_to_body <= (p["max_upper_shadow_to_body"] * (1 + p["float_tolerance"]))

        # 3. ATR Absolute Checks (Optional)
        if atr and atr > 0:
            if p["min_lower_vs_atr"]:
                lower_shadow_ok = lower_shadow_ok and (lower_shadow >= p["min_lower_vs_atr"] * atr * (1 - p["float_tolerance"]))
            if p["max_upper_vs_atr"]:
                upper_shadow_ok = upper_shadow_ok and (upper_shadow <= p["max_upper_vs_atr"] * atr * (1 + p["float_tolerance"]))
            if p["max_body_vs_atr"]:
                body_ok = body_ok and (body <= p["max_body_vs_atr"] * atr * (1 + p["float_tolerance"]))

        # 4. Shadow Presence
        if p["require_lower_shadow"]:
            lower_shadow_ok = lower_shadow_ok and (lower_shadow > 0.0)
        if p["require_upper_shadow"]:
            upper_shadow_ok = upper_shadow_ok and (upper_shadow > 0.0)

        # 5. Color Filter
        color_ok = True
        if p["require_bullish_body"]:
            if close <= open_:
                color_ok = False

        # 6. Close Position Filter (Must close near high)
        close_pos_ok = True
        if p["require_close_upper_fraction"] is not None:
            frac = (close - low) / price_range
            close_pos_ok = frac >= p["require_close_upper_fraction"] * (1 - p["float_tolerance"])

        # 7. Volume Filter
        volume_ok = True
        if p["require_volume_increase"]:
            if vol is None or prev_vol is None or vol <= prev_vol:
                volume_ok = False

        # 8. Gap Filter (Bear Trap)
        gap_ok = True
        if p["require_gap_down"]:
            if prev_close is None or open_ >= prev_close:
                gap_ok = False

        is_pattern = all([
            body_ok, 
            lower_shadow_ok, 
            upper_shadow_ok, 
            color_ok, 
            close_pos_ok, 
            volume_ok,
            gap_ok
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body": body, "price_range": price_range,
            "upper_shadow": upper_shadow, "lower_shadow": lower_shadow,
            "body_ratio": body_ratio,
            "upper_to_body": upper_to_body, "lower_to_body": lower_to_body,
            "effective_min_body_ratio": effective_min_body_ratio,
            "body_atr_scaler": body_atr_scaler,
            "close_upper_frac": (close - low) / price_range,
            "volume_increase": (vol / prev_vol) if (vol and prev_vol and prev_vol > 0) else None,
            "gap_down": (open_ < prev_close) if prev_close else None,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(
            is_pattern=True,
            name="Hammer",
            bias="long",  # pattern bias; in production, condition on trend/location/volume
            metrics=metrics
        )
