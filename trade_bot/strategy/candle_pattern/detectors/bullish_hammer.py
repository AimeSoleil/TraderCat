from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector

class HammerDetector(SingleCandlePatternDetector):
    """
    Hammer (Bullish Reversal):
    - Small body near the top of the range.
    - Long lower shadow (>= 2x body).
    - Little to no upper shadow.
    - [New] Gap Down support.
    """
    def __init__(
        self,
        *,
        min_body_ratio: float = 0.01,                 # [Tweak] Lowered from 0.10 to allow near-doji hammers
        min_lower_shadow_to_body: float = 2.0,
        max_upper_shadow_to_body: float = 0.20,
        require_lower_shadow: bool = True,
        require_upper_shadow: bool = False,
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,
        body_atr_alpha: float = 1.0,
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        min_lower_vs_atr: Optional[float] = None,
        max_upper_vs_atr: Optional[float] = None,
        max_body_vs_atr: Optional[float] = None,
        require_bullish_body: bool = False,
        require_volume_increase: bool = False,
        require_close_upper_fraction: Optional[float] = None,
        require_gap_down: bool = False,               # [New] Open < Prev Close
    ):
        self.defaults = dict(
            min_body_ratio=min_body_ratio,
            min_lower_shadow_to_body=min_lower_shadow_to_body,
            max_upper_shadow_to_body=max_upper_shadow_to_body,
            require_lower_shadow=require_lower_shadow,
            require_upper_shadow=require_upper_shadow,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body_atr_alpha=body_atr_alpha,
            body_atr_bounds=body_atr_bounds,
            min_lower_vs_atr=min_lower_vs_atr,
            max_upper_vs_atr=max_upper_vs_atr,
            max_body_vs_atr=max_body_vs_atr,
            require_bullish_body=require_bullish_body,
            require_volume_increase=require_volume_increase,
            require_close_upper_fraction=require_close_upper_fraction,
            require_gap_down=require_gap_down,
        )

    def detect(
        self, 
        open_: float, high: float, low: float, close: float, 
        *, 
        atr: Optional[float] = None,
        vol: Optional[float] = None, 
        prev_vol: Optional[float] = None, 
        prev_close: Optional[float] = None, # Added for Gap
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}
        
        if any(x is None for x in (open_, high, low, close)) or high < low:
            return PatternResult(is_pattern=False)

        price_range = high - low
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False)

        body = abs(close - open_)
        upper_shadow = max(0.0, high - max(open_, close))
        lower_shadow = max(0.0, min(open_, close) - low)

        body_ratio = body / price_range
        
        # Handle zero body (Doji) safely for ratios
        safe_body = body if body > p["float_tolerance"] else p["float_tolerance"]
        upper_to_body = upper_shadow / safe_body
        lower_to_body = lower_shadow / safe_body

        # ATR Scaling for minimum body size
        effective_min_body_ratio = p["min_body_ratio"]
        body_atr_scaler = 1.0
        if atr and atr > 0:
            lo, hi = p["body_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body_atr_scaler = p["body_atr_alpha"] * (atr / price_range)
            body_atr_scaler = max(lo, min(hi, body_atr_scaler))
            effective_min_body_ratio = p["min_body_ratio"] / body_atr_scaler

        # Checks
        body_ok = body_ratio >= (effective_min_body_ratio * (1 - p["float_tolerance"]))
        lower_shadow_ok = lower_to_body >= (p["min_lower_shadow_to_body"] * (1 - p["float_tolerance"]))
        upper_shadow_ok = upper_to_body <= (p["max_upper_shadow_to_body"] * (1 + p["float_tolerance"]))

        # ATR Absolute Checks
        if atr and p["min_lower_vs_atr"]:
            lower_shadow_ok = lower_shadow_ok and (lower_shadow >= p["min_lower_vs_atr"] * atr * (1 - p["float_tolerance"]))
        if atr and p["max_upper_vs_atr"]:
            upper_shadow_ok = upper_shadow_ok and (upper_shadow <= p["max_upper_vs_atr"] * atr * (1 + p["float_tolerance"]))
        if atr and p["max_body_vs_atr"]:
            body_ok = body_ok and (body <= p["max_body_vs_atr"] * atr * (1 + p["float_tolerance"]))

        if p["require_lower_shadow"]:
            lower_shadow_ok = lower_shadow_ok and (lower_shadow > 0.0)
        if p["require_upper_shadow"]:
            upper_shadow_ok = upper_shadow_ok and (upper_shadow > 0.0)

        # Color Filter
        color_ok = True
        if p["require_bullish_body"]:
            if close <= open_:
                color_ok = False

        # Close Position Filter
        close_pos_ok = True
        if p["require_close_upper_fraction"] is not None:
            frac = (close - low) / price_range
            close_pos_ok = frac >= p["require_close_upper_fraction"] * (1 - p["float_tolerance"])

        # Volume Filter
        volume_ok = True
        if p["require_volume_increase"]:
            if vol is None or prev_vol is None or vol <= prev_vol:
                volume_ok = False

        # Gap Filter (New)
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
            "atr": atr,
            "params": {**self.defaults, "atr": atr, **overrides}, # [Fix] Compatible merge
            "close_upper_frac": (close - low) / price_range,
            "volume_increase": (vol / prev_vol) if (vol and prev_vol and prev_vol > 0) else None,
            "gap_down": (open_ < prev_close) if prev_close else None,
        }

        return PatternResult(
            is_pattern=True,
            name="Hammer",
            bias="long",  # pattern bias; in production, condition on trend/location/volume
            metrics=metrics
        )
