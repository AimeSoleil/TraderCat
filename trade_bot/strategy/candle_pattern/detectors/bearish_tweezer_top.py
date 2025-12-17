from typing import Optional, Dict, Any, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, DoubleCandlePatternDetector

class TweezerTopDetector(DoubleCandlePatternDetector):
    """
    Tweezer Top (bearish, 2-candle) - Production Grade:
        - Candle 1: Bullish.
        - Candle 2: Bearish.
        - Highs are approximately equal (Resistance test).
        - Supports Volume confirmation.
        - Flexible shadow logic (Supports Marubozu/Shaved Head).
    """

    def __init__(
        self,
        *,
        # Similarity controls
        high_similarity_tolerance: float = 0.001,          # 0.1% of local price scale
        tolerance_scale_alpha: float = 1.0,                # ATR scaling factor
        tolerance_scale_bounds: Tuple[float, float] = (0.7, 1.5),

        # Candle role requirements
        require_bullish_first: bool = True,
        require_bearish_second: bool = True,

        # Body filters
        min_body_ratio_first: float = 0.10,                
        min_body_ratio_second: float = 0.10,               

        # Shadow requirements (Relaxed defaults for broader detection)
        require_upper_shadow_first: bool = False,          # False allows Marubozu (Shaved Head)
        require_upper_shadow_second: bool = False,

        # Volume Logic
        require_volume_increase: bool = False,             # Vol2 > Vol1

        # Hygiene / numeric
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # Optional hard caps using ATR
        max_high_diff_atr_ratio: Optional[float] = None,   
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
            require_volume_increase=require_volume_increase,
            min_range=min_range,
            float_tolerance=float_tolerance,
            max_high_diff_atr_ratio=max_high_diff_atr_ratio,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        *,
        h1: float, l1: float, h2: float, l2: float,     
        v1: Optional[float] = None, v2: Optional[float] = None,
        atr: Optional[float] = None,
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

        # Upper shadows
        upper_shadow1 = max(0.0, h1 - max(o1, c1))
        upper_shadow2 = max(0.0, h2 - max(o2, c2))

        # Body ratios
        body_ratio1 = body1 / range1
        body_ratio2 = body2 / range2

        # 1. Role requirements
        bullish_first_ok = (c1 > o1) if p["require_bullish_first"] else True
        bearish_second_ok = (c2 < o2) if p["require_bearish_second"] else True

        # 2. Body filters
        body_first_ok = (body_ratio1 >= p["min_body_ratio_first"] * (1 - p["float_tolerance"]))
        body_second_ok = (body_ratio2 >= p["min_body_ratio_second"] * (1 - p["float_tolerance"]))

        # 3. Upper shadows presence
        upper_shadow_first_ok = (upper_shadow1 > 0.0) if p["require_upper_shadow_first"] else True
        upper_shadow_second_ok = (upper_shadow2 > 0.0) if p["require_upper_shadow_second"] else True

        # 4. Similar highs (The Core)
        high_diff = abs(h1 - h2)

        # Local price scale: average of the two ranges
        avg_range = (range1 + range2) / 2.0
        price_scale = avg_range if avg_range > p["min_range"] else max(h1, h2, p["min_range"])

        tol = p["high_similarity_tolerance"] * price_scale

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
        if atr is not None and atr > 0.0 and p["max_high_diff_atr_ratio"]:
            atr_cap_ok = (high_diff <= (p["max_high_diff_atr_ratio"] * atr) * (1 + p["float_tolerance"]))

        highs_similar_ok = (high_diff <= tol * (1 + p["float_tolerance"])) and atr_cap_ok

        # 5. Volume Confirmation
        vol_ok = True
        if p["require_volume_increase"]:
            if v1 is not None and v2 is not None:
                vol_ok = v2 > v1
            else:
                vol_ok = False

        # Final Decision
        conditions = [
            bullish_first_ok, bearish_second_ok,
            body_first_ok, body_second_ok,
            upper_shadow_first_ok, upper_shadow_second_ok,
            highs_similar_ok, vol_ok
        ]

        if not all(conditions):
            return PatternResult(is_pattern=False)

        metrics: Dict[str, Any] = {
            "high_diff": high_diff,
            "tolerance": tol,
            "atr_scaler": atr_scaler,
            "vol_increase": (v2/v1) if (v1 and v2 and v1 > 0) else None,
            "params": {**self.defaults, "atr": atr, **overrides}, # Added params
        }

        return PatternResult(
            is_pattern=True, 
            name="Tweezer Top",
            bias="short",
            metrics=metrics
        )
