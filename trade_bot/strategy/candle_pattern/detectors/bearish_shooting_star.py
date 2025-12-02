from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, SingleCandlePatternDetector


class ShootingStarDetector(SingleCandlePatternDetector):
    """
    Shooting Star (bearish, single-candle):
        - Upper shadow long (>= k × body)
        - Lower shadow short (<= k × body)
        - Body not tiny (avoid doji): body / range >= min_body_ratio
        - Typically after an uptrend (recommend external trend/location filters)
    """
    def __init__(
        self,
        *,
        # Body constraint relative to total range (doji avoidance)
        min_body_ratio: float = 0.10,               # body >= 10% of range (tune per timeframe)

        # Shadow-to-body constraints
        min_upper_shadow_to_body: float = 2.0,      # upper_shadow >= 2 × body
        max_lower_shadow_to_body: float = 0.20,     # lower_shadow <= 0.2 × body

        # Shadow presence flags
        require_upper_shadow: bool = True,
        require_lower_shadow: bool = False,         # shooting star often has near-zero lower shadow

        # Hygiene / numerical robustness
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR adaptation (optional)
        body_atr_alpha: float = 1.0,                # sensitivity for scaling min_body_ratio by ATR/range
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),  # clamp scaler

        # Optional absolute constraints vs ATR
        min_upper_vs_atr: Optional[float] = None,   # e.g., upper_shadow >= 0.30 * ATR
        max_lower_vs_atr: Optional[float] = None,   # e.g., lower_shadow <= 0.10 * ATR
        max_body_vs_atr: Optional[float] = None,    # optional cap: body <= 0.20 * ATR (if desired)
    ):
        self.defaults = dict(
            min_body_ratio=min_body_ratio,
            min_upper_shadow_to_body=min_upper_shadow_to_body,
            max_lower_shadow_to_body=max_lower_shadow_to_body,
            require_upper_shadow=require_upper_shadow,
            require_lower_shadow=require_lower_shadow,
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
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Hygiene
        if any(x is None for x in (open_, high, low, close)) or high < low:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        price_range = high - low
        if price_range <= p["min_range"]:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Magnitudes (clip shadows to non-negative)
        body = abs(close - open_)
        upper_shadow = max(0.0, high - max(open_, close))
        lower_shadow = max(0.0, min(open_, close) - low)

        # Ratios
        body_ratio = body / price_range
        upper_to_body = (upper_shadow / body) if body > 0 else float('inf')
        lower_to_body = (lower_shadow / body) if body > 0 else float('inf')

        # ATR-adaptive min body ratio (tighten doji avoidance in high vol)
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
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        metrics = {
            # Raw magnitudes
            "body": body,
            "price_range": price_range,
            "upper_shadow": upper_shadow,
            "lower_shadow": lower_shadow,
            # Ratios
            "body_ratio": body_ratio,
            "upper_to_body": upper_to_body,
            "lower_to_body": lower_to_body,
            # Effective thresholds and ATR info
            "effective_min_body_ratio": effective_min_body_ratio,
            "body_atr_scaler": body_atr_scaler,
            "atr": atr,
            # Pass/fail flags
            "body_ok": body_ok,
            "upper_shadow_ok": upper_shadow_ok,
            "lower_shadow_ok": lower_shadow_ok,
            # OHLC echo
            "open": open_,
            "close": close,
            "high": high,
            "low": low,
            # Params snapshot (for logging/debug)
            "params": self.defaults | {"atr": atr} | overrides,
        }

        return PatternResult(
            is_pattern=True,
            name="Shooting Star",
            bias="short",
            metrics=metrics
        )

# Usage Example:
# det = ShootingStarDetector(
#     min_body_ratio=0.10,
#     min_upper_shadow_to_body=2.0,
#     max_lower_shadow_to_body=0.20
# )

# # Minimal (no ATR)
# res = det.detect(open_=10.2, high=10.9, low=10.1, close=10.25)

# # ATR-aware thresholds (tighten doji avoidance and add absolute constraints)
# res2 = det.detect(
#     open_=10.2, high=10.9, low=10.1, close=10.25,
#     atr=0.8,
#     min_upper_vs_atr=0.30,   # upper shadow >= 30% ATR
#     max_lower_vs_atr=0.10,   # lower shadow <= 10% ATR
#     max_body_vs_atr=0.20     # body <= 20% ATR (optional cap)
# )

# Tuning Tips (Trader’s Perspective)

# Thresholds

# min_body_ratio: 0.07–0.12 typical (tighter for intraday to avoid micro doji).
# min_upper_shadow_to_body: 1.8–3.0 stricter settings improve signal quality.
# max_lower_shadow_to_body: 0.10–0.25 depending on how strict you want the “short lower shadow”.


# Context filters (for real edge)

# Shooting stars are most meaningful near swing highs / resistance after an uptrend.
# Combine with EMA slope, ADX, proximity to VWAP upper band / pivots / Bollinger upper band, and volume regime.


# Confirmation & Risk

# Bearish confirmation: next bar break and close below the shooting star’s low.
# Stops: commonly above the shooting star’s high; ATR-based position sizing recommended.
