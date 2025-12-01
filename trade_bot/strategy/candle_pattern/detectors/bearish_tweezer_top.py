
from typing import Optional, Dict, Any, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, DoubleCandlePatternDetector

class TweezerTopDetector(DoubleCandlePatternDetector):
    """
    Detects a Tweezer Top pattern across two consecutive candles.

    Common definition:
        - Candle 1: Bullish (close > open)
        - Candle 2: Bearish (close < open)
        - Highs of the two candles are approximately equal (within tolerance)
        - Often occurs after an uptrend (trend check should be done externally)

    This detector provides:
        - ATR-adaptive tolerance for high similarity (optional)
        - Minimum body ratio checks to filter out tiny/noise candles
        - Optional requirement for upper shadows (upper wicks) on both candles
        - Structured metrics, hygiene checks, and keyword-only overrides

    Note:
        To align with DoubleCandlePatternDetector.detect signature, highs/lows are
        provided via keyword-only arguments: h1, l1, h2, l2.
    """

    def __init__(
        self,
        *,
        # Similarity controls
        high_similarity_tolerance: float = 0.001,          # 0.1% of local price scale
        tolerance_scale_alpha: float = 1.0,                # ATR scaling factor (if ATR is provided)
        tolerance_scale_bounds: Tuple[float, float] = (0.7, 1.5),  # clamp for ATR scaler

        # Candle role requirements
        require_bullish_first: bool = True,
        require_bearish_second: bool = True,

        # Body filters (ratios relative to each candle's own range)
        min_body_ratio_first: float = 0.10,                # First candle body >= 10% of its range
        min_body_ratio_second: float = 0.10,               # Second candle body >= 10% of its range

        # Shadow requirements (Tweezer Top typically shows upper wicks)
        require_upper_shadow_first: bool = True,
        require_upper_shadow_second: bool = True,

        # Hygiene / numeric
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # Optional hard caps using ATR
        max_high_diff_atr_ratio: Optional[float] = None,   # e.g., 0.1 → highs within 0.1 * ATR
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

            min_range=min_range,
            float_tolerance=float_tolerance,

            max_high_diff_atr_ratio=max_high_diff_atr_ratio,
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

        # Upper shadows
        upper_shadow1 = max(0.0, h1 - max(o1, c1))
        upper_shadow2 = max(0.0, h2 - max(o2, c2))

        # Body ratios
        body_ratio1 = body1 / range1 if range1 > 0 else 0.0
        body_ratio2 = body2 / range2 if range2 > 0 else 0.0

        # Role requirements
        bullish_first_ok = (c1 > o1) if p["require_bullish_first"] else True
        bearish_second_ok = (c2 < o2) if p["require_bearish_second"] else True

        # Body filters
        body_first_ok = (body_ratio1 >= p["min_body_ratio_first"] * (1 - p["float_tolerance"]))
        body_second_ok = (body_ratio2 >= p["min_body_ratio_second"] * (1 - p["float_tolerance"]))

        # Upper shadows presence (optional, commonly seen in tweezer top)
        upper_shadow_first_ok = (upper_shadow1 > 0.0) if p["require_upper_shadow_first"] else True
        upper_shadow_second_ok = (upper_shadow2 > 0.0) if p["require_upper_shadow_second"] else True

        # Similar highs with ATR-adaptive tolerance
        high_diff = abs(h1 - h2)

        # Local price scale: average of the two ranges (robust vs absolute highs)
        avg_range = (range1 + range2) / 2.0 if (range1 > 0 and range2 > 0) else max(range1, range2)
        price_scale = avg_range if avg_range > p["min_range"] else max(h1, h2, p["min_range"])

        tol = p["high_similarity_tolerance"] * price_scale  # base tolerance

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
        if atr is not None and atr > 0.0 and p["max_high_diff_atr_ratio"]:
            atr_cap_ok = (high_diff <= (p["max_high_diff_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        highs_similar_ok = (high_diff <= tol * (1 + p["float_tolerance"])) and atr_cap_ok

        is_pattern = (
            bullish_first_ok and
            bearish_second_ok and
            body_first_ok and
            body_second_ok and
            upper_shadow_first_ok and
            upper_shadow_second_ok and
            highs_similar_ok
        )

        if not is_pattern:
            return PatternResult(False, None, None, None)

        metrics: Dict[str, Any] = {
            "high_diff": high_diff,
            "tolerance": tol,
            "atr": atr,
            "atr_scaler": atr_scaler,

            "range1": range1, "range2": range2,
            "body1": body1, "body2": body2,
            "body_ratio1": body_ratio1, "body_ratio2": body_ratio2,
            "upper_shadow1": upper_shadow1, "upper_shadow2": upper_shadow2,

            "bullish_first_ok": bullish_first_ok,
            "bearish_second_ok": bearish_second_ok,
            "body_first_ok": body_first_ok,
            "body_second_ok": body_second_ok,
            "upper_shadow_first_ok": upper_shadow_first_ok,
            "upper_shadow_second_ok": upper_shadow_second_ok,
            "highs_similar_ok": highs_similar_ok,

            "o1": o1, "h1": h1, "l1": l1, "c1": c1,
            "o2": o2, "h2": h2, "l2": l2, "c2": c2,
            "params": self.defaults | {"atr": atr} | overrides,
        }

        return PatternResult(True, "Tweezer Top", "bear", metrics)
