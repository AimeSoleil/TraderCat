from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector


class ShootingStarDetector(SingleCandlePatternDetector):
    """
    Shooting Star (bearish, single-candle) - Production Grade:
        - Upper shadow long (>= k * body).
        - Lower shadow short.
        - Body small but not tiny (distinct from Gravestone Doji).
        - [New] Color check (Bearish body preferred).
        - [New] Gap up check (vs previous close).
        - [New] Volume spike check.
        - [New] New High check.
    """
    def __init__(
        self,
        *,
        # Body constraint relative to total range (doji avoidance)
        min_body_ratio: float = 0.10,               

        # Shadow-to-body constraints
        min_upper_shadow_to_body: float = 2.0,      
        max_lower_shadow_to_body: float = 0.20,     

        # Shadow presence flags
        require_upper_shadow: bool = True,
        require_lower_shadow: bool = False,         

        # Color / Direction
        require_bearish_body: bool = False,         # Ideally True for stronger signal (Red Shooting Star)

        # Context Logic
        require_gap_up: bool = False,               # Open > Prev Close (Stronger reversal)
        require_high_volume: bool = False,          # Vol > PrevVol
        require_new_high: bool = False,             # High > Prev High (Top picking)

        # Hygiene / numerical robustness
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR adaptation (optional)
        body_atr_alpha: float = 1.0,                
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),  
        min_upper_vs_atr: Optional[float] = None,   
        max_lower_vs_atr: Optional[float] = None,   
        max_body_vs_atr: Optional[float] = None,    
    ):
        self.defaults = dict(
            min_body_ratio=min_body_ratio,
            min_upper_shadow_to_body=min_upper_shadow_to_body,
            max_lower_shadow_to_body=max_lower_shadow_to_body,
            require_upper_shadow=require_upper_shadow,
            require_lower_shadow=require_lower_shadow,
            require_bearish_body=require_bearish_body,
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
        prev_high: Optional[float] = None,  # Added for New High check
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

        # 1. Color Check
        if p["require_bearish_body"]:
            if close > open_: # Bullish
                return PatternResult(is_pattern=False)

        # 2. Gap Check
        if p["require_gap_up"]:
            if prev_close is None or open_ <= prev_close:
                return PatternResult(is_pattern=False)

        # 3. Volume Check
        if p["require_high_volume"]:
            if vol is None or prev_vol is None or vol <= prev_vol:
                return PatternResult(is_pattern=False)

        # 4. New High Check (New)
        if p["require_new_high"]:
            if prev_high is None or high <= prev_high:
                return PatternResult(is_pattern=False)

        # Ratios
        body_ratio = body / price_range
        # Handle zero body safely
        safe_body = body if body > p["float_tolerance"] else p["float_tolerance"]
        upper_to_body = upper_shadow / safe_body
        lower_to_body = lower_shadow / safe_body

        # ATR-adaptive min body ratio
        effective_min_body_ratio = p["min_body_ratio"]
        body_atr_scaler = None
        if atr is not None and atr > 0.0:
            lo, hi = p["body_atr_bounds"]
            if hi < lo: lo, hi = hi, lo
            body_atr_scaler = p["body_atr_alpha"] * (atr / price_range)
            body_atr_scaler = max(lo, min(hi, body_atr_scaler))
            effective_min_body_ratio = p["min_body_ratio"] / body_atr_scaler

        # Core conditions
        body_ok = body_ratio >= (effective_min_body_ratio * (1 - p["float_tolerance"]))
        upper_shadow_ok = upper_to_body >= (p["min_upper_shadow_to_body"] * (1 - p["float_tolerance"]))
        lower_shadow_ok = lower_to_body <= (p["max_lower_shadow_to_body"] * (1 + p["float_tolerance"]))

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

        is_pattern = body_ok and upper_shadow_ok and lower_shadow_ok

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
            # Raw magnitudes
            "price_range": price_range,
            "lower_shadow": lower_shadow,
            # Ratios
            "body_ratio": body_ratio,
            "lower_to_body": lower_to_body,
            # Effective thresholds and ATR info
            "effective_min_body_ratio": effective_min_body_ratio,
            "body_atr_scaler": body_atr_scaler,
            "atr": atr,
            # Params snapshot (for logging/debug)
            "params": {**self.defaults, "atr": atr, **overrides}, # [Fix] Compatible merge
        }

        return PatternResult(
            is_pattern=True,
            name="Shooting Star",
            bias="short",
            metrics=metrics
        )