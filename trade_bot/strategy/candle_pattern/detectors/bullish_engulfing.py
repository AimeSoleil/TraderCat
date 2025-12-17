from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class BullishEngulfingDetector(DoubleCandlePatternDetector):
    """
    Bullish Engulfing (Reversal):
    - Candle 1: Bearish.
    - Candle 2: Bullish, Body engulfs Candle 1 Body.
    - [New] Optional Shadow Engulfing (High/Low engulfing).
    """
    def __init__(
        self,
        *,
        require_strict_overlap: bool = True,
        strength_multiplier: float = 1.2,
        decisive_close_margin_ratio: float = 0.0,
        min_body_ratio1: Optional[float] = None,
        min_body_ratio2: Optional[float] = None,
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,
        body_atr_alpha: float = 1.0,
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body1_vs_atr: Optional[float] = None,
        min_body2_vs_atr: Optional[float] = None,
        require_volume_increase: bool = False,
        max_upper_wick_ratio2: Optional[float] = None,
        require_shadow_engulfing: bool = False,  # [New] Stronger signal requirement
    ):
        self.defaults = dict(
            require_strict_overlap=require_strict_overlap,
            strength_multiplier=strength_multiplier,
            decisive_close_margin_ratio=decisive_close_margin_ratio,
            min_body_ratio1=min_body_ratio1,
            min_body_ratio2=min_body_ratio2,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body_atr_alpha=body_atr_alpha,
            body_atr_bounds=body_atr_bounds,
            max_body1_vs_atr=max_body1_vs_atr,
            min_body2_vs_atr=min_body2_vs_atr,
            require_volume_increase=require_volume_increase,
            max_upper_wick_ratio2=max_upper_wick_ratio2,
            require_shadow_engulfing=require_shadow_engulfing,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        *,
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        v1: Optional[float] = None, v2: Optional[float] = None,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}
        
        # Basic Hygiene
        if any(x is None for x in (o1, c1, o2, c2)):
            return PatternResult(is_pattern=False)

        # Direction Check
        first_bearish = c1 < o1
        second_bullish = c2 > o2
        if not (first_bearish and second_bullish):
            return PatternResult(is_pattern=False)

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        
        # Note: body <= 0 check removed as direction checks implicitly ensure bodies > 0.
        # If we want to allow engulfing a Doji, we would relax 'first_bearish'.

        # 1. Body Engulfing (Overlap)
        if p["require_strict_overlap"]:
            engulf_ok = (o2 <= c1 * (1 + p["float_tolerance"])) and (c2 >= o1 * (1 - p["float_tolerance"]))
        else:
            # Loose overlap (allows equal open/close)
            engulf_ok = (o2 <= (c1 + abs(c1) * p["float_tolerance"])) and (c2 >= (o1 - abs(o1) * p["float_tolerance"]))

        # 2. Shadow Engulfing (Optional - Stronger Signal)
        shadow_engulf_ok = True
        if p["require_shadow_engulfing"]:
            if all(x is not None for x in (h1, l1, h2, l2)):
                # High2 >= High1 AND Low2 <= Low1
                shadow_engulf_ok = (h2 >= h1 * (1 - p["float_tolerance"])) and \
                                   (l2 <= l1 * (1 + p["float_tolerance"]))
            else:
                # If data missing but requirement exists, fail safe
                shadow_engulf_ok = False

        # 3. Strength & Decisiveness
        strength_ok = body2 >= body1 * p["strength_multiplier"] * (1 - p["float_tolerance"])

        decisive_ok = True
        if p["decisive_close_margin_ratio"] and p["decisive_close_margin_ratio"] > 0.0:
            decisive_ok = c2 >= (o1 + body1 * p["decisive_close_margin_ratio"])

        # 4. Upper Wick Check (Rejection check)
        upper_wick2_ok = True
        if h2 is not None and l2 is not None and p["max_upper_wick_ratio2"] is not None:
            price_range2_tmp = h2 - l2
            if price_range2_tmp > p["min_range"]:
                upper_wick2 = h2 - max(o2, c2)
                upper_wick2_ok = (upper_wick2 / body2) <= p["max_upper_wick_ratio2"] * (1 + p["float_tolerance"])

        # 5. Range & Ratio Logic
        def valid_range(h, l): return (h is not None) and (l is not None) and (h >= l)
        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        # Fail only if ranges are strictly required for ratios
        ranges_required = (p["min_body_ratio1"] is not None and price_range1 is None) or \
                          (p["min_body_ratio2"] is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False)

        # Body Ratio 1
        body_ratio1_ok = True
        if price_range1 and p["min_body_ratio1"]:
            body_ratio1_ok = (body1 / price_range1) >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))

        # Body Ratio 2 (ATR Adaptive)
        body_ratio2_ok = True
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body_atr_scaler = 1.0
        
        if price_range2 and p["min_body_ratio2"]:
            if atr and atr > 0:
                lo, hi = p["body_atr_bounds"]
                if hi < lo: lo, hi = hi, lo
                body_atr_scaler = p["body_atr_alpha"] * (atr / price_range2)
                body_atr_scaler = max(lo, min(hi, body_atr_scaler))
                effective_min_body_ratio2 = p["min_body_ratio2"] / body_atr_scaler
            
            body_ratio2_ok = (body2 / price_range2) >= (effective_min_body_ratio2 * (1 - p["float_tolerance"]))

        # ATR Absolute Checks
        atr_body1_ok = True
        atr_body2_ok = True
        if atr and atr > 0:
            if p["max_body1_vs_atr"]:
                atr_body1_ok = body1 <= (p["max_body1_vs_atr"] * atr) * (1 + p["float_tolerance"])
            if p["min_body2_vs_atr"]:
                atr_body2_ok = body2 >= (p["min_body2_vs_atr"] * atr) * (1 - p["float_tolerance"])

        # 成交量确认
        volume_ok = True
        if p["require_volume_increase"]:
            volume_ok = (v1 is not None and v2 is not None and v2 > v1)

        is_pattern = all([
            engulf_ok, strength_ok, decisive_ok,
            body_ratio1_ok, body_ratio2_ok,
            atr_body1_ok, atr_body2_ok,
            upper_wick2_ok,
            volume_ok,
            shadow_engulf_ok,  # [New] Include shadow engulfing in final check
        ])
        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "o1": o1, "c1": c1, "h1": h1, "l1": l1,
            "o2": o2, "c2": c2, "h2": h2, "l2": l2,
            "body1": body1, "body2": body2,
            "price_range1": price_range1, "price_range2": price_range2,
            "body_ratio1": body_ratio1, "body_ratio2": body_ratio2,
            "engulf_ok": engulf_ok, "strength_ok": strength_ok, "decisive_ok": decisive_ok,
            "min_body_ratio1": p["min_body_ratio1"],
            "min_body_ratio2": p["min_body_ratio2"],
            "effective_min_body_ratio2": effective_min_body_ratio2,
            "atr": atr, "body_atr_scaler": body_atr_scaler,
            "atr_body1_ok": atr_body1_ok, "atr_body2_ok": atr_body2_ok,
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "upper_wick_ratio2": ((h2 - max(o2, c2)) / body2) if (h2 and l2 and body2 > 0) else None,
            "params": self.defaults | {"atr": atr} | overrides,
        }
        return PatternResult(True, "Bullish Engulfing", "long", metrics)
