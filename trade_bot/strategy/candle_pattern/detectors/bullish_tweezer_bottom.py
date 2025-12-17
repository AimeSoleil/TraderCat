from typing import Optional, Dict, Any
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, DoubleCandlePatternDetector

class TweezerBottomDetector(DoubleCandlePatternDetector):
    """
    Detects a Tweezer Bottom pattern across two consecutive candles.
    - Candle 1: Bearish.
    - Candle 2: Bullish.
    - Lows are approximately equal (Support test).
    - [Improved] Flexible shadow logic (Supports Marubozu/Shaved Bottom).
    - [New] Volume confirmation support.
    """

    def __init__(
        self,
        *,
        # Similarity controls
        low_similarity_tolerance: float = 0.001,          # 0.1% of price scale
        tolerance_scale_alpha: float = 1.0,               # ATR scaling factor
        tolerance_scale_bounds: tuple = (0.7, 1.5),

        # Candle role requirements
        require_bearish_first: bool = True,
        require_bullish_second: bool = True,

        # Body filters
        min_body_ratio_first: float = 0.10,               
        min_body_ratio_second: float = 0.10,              

        # Shadow requirements (Relaxed defaults for broader detection)
        require_lower_shadow_first: bool = False,   # False allows Shaved Bottom
        require_lower_shadow_second: bool = False,  

        # Hygiene / numeric
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # Optional hard caps using ATR
        max_low_diff_atr_ratio: Optional[float] = None,   

        # Volume requirements
        require_volume_increase: bool = False,      # Vol2 > Vol1
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
            require_volume_increase=require_volume_increase,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        *,
        h1: float, l1: float, h2: float, l2: float,     
        atr: Optional[float] = None,
        v1: Optional[float] = None, 
        v2: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Hygiene checks
        if any(x is None for x in (o1, h1, l1, c1, o2, h2, l2, c2)):
            return PatternResult(is_pattern=False)
        if h1 < l1 or h2 < l2:
            return PatternResult(is_pattern=False)

        # Candle ranges and bodies
        range1 = h1 - l1
        range2 = h2 - l2
        if range1 <= p["min_range"] or range2 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)

        lower_shadow1 = max(0.0, min(o1, c1) - l1)
        lower_shadow2 = max(0.0, min(o2, c2) - l2)

        body_ratio1 = body1 / range1
        body_ratio2 = body2 / range2

        # Role requirements
        bearish_first_ok = (c1 < o1) if p["require_bearish_first"] else True
        bullish_second_ok = (c2 > o2) if p["require_bullish_second"] else True

        # Body filters
        body_first_ok = (body_ratio1 >= p["min_body_ratio_first"] * (1 - p["float_tolerance"]))
        body_second_ok = (body_ratio2 >= p["min_body_ratio_second"] * (1 - p["float_tolerance"]))

        # Lower shadows presence
        lower_shadow_first_ok = (lower_shadow1 > 0.0) if p["require_lower_shadow_first"] else True
        lower_shadow_second_ok = (lower_shadow2 > 0.0) if p["require_lower_shadow_second"] else True

        # Similar lows (The Core)
        low_diff = abs(l1 - l2)

        # Local price scale
        avg_range = (range1 + range2) / 2.0
        price_scale = avg_range if avg_range > p["min_range"] else max(l1, l2, p["min_range"])

        tol = p["low_similarity_tolerance"] * price_scale

        # ATR scaler
        atr_scaler = 1.0
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

        # Volume Confirmation
        volume_ok = True
        if p["require_volume_increase"]:
            if v1 is not None and v2 is not None:
                volume_ok = v2 > v1
            else:
                volume_ok = False

        is_pattern = (
            bearish_first_ok and
            bullish_second_ok and
            body_first_ok and
            body_second_ok and
            lower_shadow_first_ok and
            lower_shadow_second_ok and
            lows_similar_ok and
            volume_ok
        )

        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics: Dict[str, Any] = {
            "low_diff": low_diff,
            "tolerance": tol,
            "atr_scaler": atr_scaler,
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
        }

        return PatternResult(True, "Tweezer Bottom", "long", metrics)
