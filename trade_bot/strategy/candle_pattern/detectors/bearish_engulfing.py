from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class BearishEngulfingDetector(DoubleCandlePatternDetector):
    """
    Bearish Engulfing (Reversal) - US Stock Optimized:
    - Candle 1: Bullish (Must have a visible body).
    - Candle 2: Bearish, Body completely covers Candle 1 Body.
    - Logic: Bulls tried to push up (Gap Up or continuation), but Bears overwhelmed them, closing below Candle 1's open.
    - Psychology: A "Bull Trap" followed by total liquidation of the previous session's gains.
    """
    def __init__(
        self,
        *,
        # --- Overlap / Gap Logic ---
        # [Optimization] Default False. 
        # In modern markets (especially intraday), Open2 often equals Close1. 
        # Strict gap requirements (Open2 > Close1) miss too many valid signals.
        require_strict_overlap: bool = False,
        
        # --- Strength Parameters ---
        # [Optimization] 1.05 (5%). 
        # Body 2 must be at least 5% larger than Body 1. 
        # Ensures it's not just a "Matching Low" or weak engulfing.
        strength_multiplier: float = 1.05,

        # [New] Stronger Signal. 
        # If True, High2 > High1 AND Low2 < Low1. 
        # This is "Outer Bar" engulfing, much more powerful than just body engulfing.
        require_shadow_engulfing: bool = False,

        # --- Wick Logic (Rejection) ---
        # [Optimization] 0.3 (30%). 
        # The bearish candle must close near its low. 
        # If there is a long lower wick (>30%), it indicates buying pressure (weakness).
        max_lower_wick_ratio: Optional[float] = 0.3,

        # --- Volume Logic ---
        # [Optimization] Default False (Safety), but HIGHLY recommended True in config.
        # Reversals on low volume are often fakeouts.
        require_volume_increase: bool = False,

        # --- Noise Filtering (Crucial) ---
        # [Optimization] 0.15 (15%). 
        # Candle 1 must be a real bullish candle, not a Doji. 
        # Engulfing a flat line is statistically insignificant.
        min_body_ratio1: Optional[float] = 0.15,
        
        # [Optimization] 0.20 (20%). 
        # The engulfing candle itself must be significant in size.
        min_body_ratio2: Optional[float] = 0.20,

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Adaptation (Advanced) ---
        # Allows dynamic body size requirements based on volatility.
        body2_atr_alpha: float = 1.0,
        body2_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body1_vs_atr: Optional[float] = None,
        min_body2_vs_atr: Optional[float] = None,
    ):
        self.defaults = dict(
            require_strict_overlap=require_strict_overlap,
            strength_multiplier=strength_multiplier,
            require_shadow_engulfing=require_shadow_engulfing,
            max_lower_wick_ratio=max_lower_wick_ratio,
            require_volume_increase=require_volume_increase,
            min_body_ratio1=min_body_ratio1,
            min_body_ratio2=min_body_ratio2,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body2_atr_alpha=body2_atr_alpha,
            body2_atr_bounds=body2_atr_bounds,
            max_body1_vs_atr=max_body1_vs_atr,
            min_body2_vs_atr=min_body2_vs_atr,
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

        # 1. Direction Check
        first_bullish = c1 > o1
        second_bearish = c2 < o2
        if not (first_bullish and second_bearish):
            return PatternResult(is_pattern=False)

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        
        # 2. Body Engulfing (Overlap)
        if p["require_strict_overlap"]:
            # Strict: Open2 > Close1 AND Close2 < Open1
            engulf_ok = (o2 >= c1 * (1 + p["float_tolerance"])) and \
                        (c2 <= o1 * (1 - p["float_tolerance"]))
        else:
            # Standard: Open2 >= Close1 AND Close2 <= Open1
            # Allows equal opens/closes which is common in algo trading
            engulf_ok = (o2 >= (c1 - abs(c1) * p["float_tolerance"])) and \
                        (c2 <= (o1 + abs(o1) * p["float_tolerance"]))

        # 3. Shadow Engulfing (Optional - Stronger Signal)
        shadow_engulf_ok = True
        if p["require_shadow_engulfing"]:
            if all(x is not None for x in (h1, l1, h2, l2)):
                # High2 >= High1 AND Low2 <= Low1
                shadow_engulf_ok = (h2 >= h1 * (1 - p["float_tolerance"])) and \
                                   (l2 <= l1 * (1 + p["float_tolerance"]))
            else:
                shadow_engulf_ok = False

        # 4. Strength (Size Multiplier)
        strength_ok = body2 >= body1 * p["strength_multiplier"] * (1 - p["float_tolerance"])

        # 5. Lower Wick Check (Rejection check)
        lower_wick_ok = True
        if h2 is not None and l2 is not None and p["max_lower_wick_ratio"] is not None:
            lower_wick = max(0.0, c2 - l2)
            # Safe division
            denom = body2 if body2 > p["min_range"] else p["min_range"]
            lower_wick_ok = (lower_wick / denom) <= p["max_lower_wick_ratio"] * (1 + p["float_tolerance"])

        # 6. Range & Ratio Logic
        def valid_range(h, l): return (h is not None) and (l is not None) and (h >= l)
        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        # Fail only if ranges are strictly required for ratios
        ranges_required = (p["min_body_ratio1"] is not None and price_range1 is None) or \
                          (p["min_body_ratio2"] is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False)

        # Body Ratio 1 (Must be a real candle)
        body_ratio1_ok = True
        if price_range1 and p["min_body_ratio1"]:
            body_ratio1_ok = (body1 / price_range1) >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))

        # Body Ratio 2 (ATR Adaptive)
        body_ratio2_ok = True
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body2_atr_scaler = 1.0
        
        if price_range2 and p["min_body_ratio2"]:
            if atr and atr > 0:
                lo, hi = p["body2_atr_bounds"]
                if hi < lo: lo, hi = hi, lo
                # If ATR is high, we relax the body ratio requirement slightly
                raw_scaler = p["body2_atr_alpha"] * (atr / price_range2)
                body2_atr_scaler = max(lo, min(hi, raw_scaler))
                effective_min_body_ratio2 = p["min_body_ratio2"] / body2_atr_scaler
            
            body_ratio2_ok = (body2 / price_range2) >= (effective_min_body_ratio2 * (1 - p["float_tolerance"]))

        # ATR Absolute Checks
        atr_body1_ok = True
        atr_body2_ok = True
        if atr and atr > 0:
            if p["max_body1_vs_atr"]:
                atr_body1_ok = body1 <= (p["max_body1_vs_atr"] * atr) * (1 + p["float_tolerance"])
            if p["min_body2_vs_atr"]:
                atr_body2_ok = body2 >= (p["min_body2_vs_atr"] * atr) * (1 - p["float_tolerance"])

        # 7. Volume Confirmation
        volume_ok = True
        if p["require_volume_increase"]:
            volume_ok = (v1 is not None and v2 is not None and v2 > v1)

        is_pattern = all([
            engulf_ok, strength_ok,
            body_ratio1_ok, body_ratio2_ok,
            atr_body1_ok, atr_body2_ok,
            lower_wick_ok,
            volume_ok,
            shadow_engulf_ok,
        ])
        
        if not is_pattern:
            return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2,
            "engulf_ok": engulf_ok, 
            "strength_ok": strength_ok,
            "effective_min_body_ratio2": effective_min_body_ratio2,
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "lower_wick_ratio": ((c2 - l2) / body2) if (l2 and body2 > 0) else None,
            "params": {**self.defaults, "atr": atr, **overrides},
        }
        return PatternResult(True, "Bearish Engulfing", "short", metrics)