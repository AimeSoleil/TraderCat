
from typing import Optional, Dict, Any
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, DoubleCandlePatternDetector

class TweezerBottomDetector(DoubleCandlePatternDetector):
    """
    Detects a Tweezer Bottom pattern across two consecutive candles.

    Common definition:
        - Candle 1: Bearish (close < open)
        - Candle 2: Bullish (close > open)
        - Lows of the two candles are approximately equal (within tolerance)
        - Often occurs after a downtrend (trend check should be done externally)

    This detector provides:
        - ATR-adaptive tolerance for low similarity (optional)
        - Minimum body ratio check to filter out tiny/noise candles
        - Optional requirement for actual lower shadows (lower wicks > 0)
        - Structured metrics and parameter overrides similar to StandardDojiDetector
    """

    def __init__(
        self,
        *,
        # Similarity controls
        low_similarity_tolerance: float = 0.001,          # 0.1% of price scale (relative)
        tolerance_scale_alpha: float = 1.0,               # ATR scaling factor (if ATR is provided)
        tolerance_scale_bounds: tuple = (0.7, 1.5),       # clamp for ATR scaler

        # Candle role requirements
        require_bearish_first: bool = True,
        require_bullish_second: bool = True,

        # Body filters
        min_body_ratio_first: float = 0.10,               # First candle body >= 10% of its range
        min_body_ratio_second: float = 0.10,              # Second candle body >= 10% of its range

        # Shadow requirements
        require_lower_shadow_first: bool = True,
        require_lower_shadow_second: bool = True,

        # Hygiene / numeric
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # Optional hard caps using ATR
        max_low_diff_atr_ratio: Optional[float] = None,   # e.g., 0.1 means lows within 0.1 * ATR
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
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        *,
        h1: float, l1: float, h2: float, l2: float,     # REQUIRED keyword-only highs/lows
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Hygiene checks
        if any(x is None for x in (o1, h1, l1, c1, o2, h2, l2, c2)):
            return PatternResult(False, None, None, None)
        if h1 < l1 or h2 < l2:
            return PatternResult(False, None, None, None)

        # Candle ranges and bodies
        range1 = h1 - l1
        range2 = h2 - l2
        if range1 <= p["min_range"] or range2 <= p["min_range"]:
            return PatternResult(False, None, None, None)

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)

        lower_shadow1 = max(0.0, min(o1, c1) - l1)
        lower_shadow2 = max(0.0, min(o2, c2) - l2)

        body_ratio1 = body1 / range1 if range1 > 0 else 0.0
        body_ratio2 = body2 / range2 if range2 > 0 else 0.0

        # Role requirements
        bearish_first_ok = (c1 < o1) if p["require_bearish_first"] else True
        bullish_second_ok = (c2 > o2) if p["require_bullish_second"] else True

        # Body filters
        body_first_ok = (body_ratio1 >= p["min_body_ratio_first"] * (1 - p["float_tolerance"]))
        body_second_ok = (body_ratio2 >= p["min_body_ratio_second"] * (1 - p["float_tolerance"]))

        # Lower shadows presence (optional, but common in tweezer bottom)
        lower_shadow_first_ok = (lower_shadow1 > 0.0) if p["require_lower_shadow_first"] else True
        lower_shadow_second_ok = (lower_shadow2 > 0.0) if p["require_lower_shadow_second"] else True

        # Similar lows with ATR-adaptive tolerance
        low_diff = abs(l1 - l2)

        # Base tolerance relative to price scale.
        # Using average of the two candle ranges as the local volatility scale.
        avg_range = (range1 + range2) / 2.0 if (range1 > 0 and range2 > 0) else max(range1, range2)

        # If avg_range is degenerate, fallback to avg low scale (safer than absolute price).
        price_scale = avg_range if avg_range > p["min_range"] else max(l1, l2, p["min_range"])

        tol = p["low_similarity_tolerance"] * price_scale  # base tolerance

        # ATR scaler (optional)
        atr_scaler = None
        if atr is not None and atr > 0.0:
            lo, hi = p["tolerance_scale_bounds"]
            if hi < lo: lo, hi = hi, lo
            atr_scaler = p["tolerance_scale_alpha"] * (atr / max(price_scale, p["min_range"]))
            atr_scaler = max(lo, min(hi, atr_scaler))
            tol *= atr_scaler

        # Optional hard cap using ATR
        atr_cap_ok = True
        if atr is not None and atr > 0.0 and p["max_low_diff_atr_ratio"]:
            atr_cap_ok = (low_diff <= (p["max_low_diff_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        lows_similar_ok = (low_diff <= tol * (1 + p["float_tolerance"])) and atr_cap_ok

        is_pattern = (
            bearish_first_ok and
            bullish_second_ok and
            body_first_ok and
            body_second_ok and
            lower_shadow_first_ok and
            lower_shadow_second_ok and
            lows_similar_ok
        )

        if not is_pattern:
            return PatternResult(False, None, None, None)

        metrics: Dict[str, Any] = {
            "low_diff": low_diff,
            "tolerance": tol,
            "atr": atr,
            "atr_scaler": atr_scaler,

            "range1": range1, "range2": range2,
            "body1": body1, "body2": body2,
            "body_ratio1": body_ratio1, "body_ratio2": body_ratio2,
            "lower_shadow1": lower_shadow1, "lower_shadow2": lower_shadow2,

            "bearish_first_ok": bearish_first_ok,
            "bullish_second_ok": bullish_second_ok,
            "body_first_ok": body_first_ok,
            "body_second_ok": body_second_ok,
            "lower_shadow_first_ok": lower_shadow_first_ok,
            "lower_shadow_second_ok": lower_shadow_second_ok,
            "lows_similar_ok": lows_similar_ok,

            "o1": o1, "h1": h1, "l1": l1, "c1": c1,
            "o2": o2, "h2": h2, "l2": l2, "c2": c2,
            "params": self.defaults | {"atr": atr} | overrides,
        }

        return PatternResult(True, "Tweezer Bottom", "bull", metrics)
