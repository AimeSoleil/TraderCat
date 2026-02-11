from typing import Optional, Tuple, Dict, Any
from tradercat.core.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

class BullishEngulfingDetector(DoubleCandlePatternDetector):
    """
    Bullish Engulfing (Reversal) - US Stock Optimized:
    - Candle 1: Bearish (Must have a visible body).
    - Candle 2: Bullish, Body completely covers Candle 1 Body.
    - Logic: Bears were in control, but Bulls overwhelmed them completely in the next session.
    """
    def __init__(
        self,
        *,
        # --- Overlap / Gap Logic ---
        # [Optimization] Default False. 
        # In modern markets (especially intraday), Open2 often equals Close1. 
        # Strict gap requirements (Open2 < Close1) miss too many valid signals.
        require_strict_overlap: bool = False,
        
        # --- Strength Parameters ---
        # [Optimization] 1.05 (5%). 
        # Body 2 must be at least 5% larger than Body 1. 
        # 1.2 was too strict; 1.0 is too loose (could be equal size).
        strength_multiplier: float = 1.05,

        # [New] Stronger Signal. 
        # If True, High2 > High1 AND Low2 < Low1. 
        # This is "Outer Bar" engulfing, much more powerful than just body engulfing.
        require_shadow_engulfing: bool = False,

        # --- Wick Logic (Rejection) ---
        # [Optimization] 0.3 (30%). 
        # The bullish candle must close near its high. 
        # If there is a long upper wick (>30%), it indicates selling pressure at the top.
        max_upper_wick_ratio2: Optional[float] = 0.3,

        # --- Volume Logic ---
        # [Optimization] Default False (Safety), but HIGHLY recommended True in config.
        # Reversals on low volume are often fakeouts (Dead Cat Bounce).
        require_volume_increase: bool = False,

        # --- Noise Filtering (Crucial) ---
        # [Optimization] 0.15 (15%). 
        # Candle 1 must be a real bearish candle, not a Doji. 
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
        body_atr_alpha: float = 1.0,
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        max_body1_vs_atr: Optional[float] = None,
        min_body2_vs_atr: Optional[float] = None,
    ):
        self.defaults = dict(
            require_strict_overlap=require_strict_overlap,
            strength_multiplier=strength_multiplier,
            require_shadow_engulfing=require_shadow_engulfing,
            max_upper_wick_ratio2=max_upper_wick_ratio2,
            require_volume_increase=require_volume_increase,
            min_body_ratio1=min_body_ratio1,
            min_body_ratio2=min_body_ratio2,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body_atr_alpha=body_atr_alpha,
            body_atr_bounds=body_atr_bounds,
            max_body1_vs_atr=max_body1_vs_atr,
            min_body2_vs_atr=min_body2_vs_atr,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        h1: float, l1: float,  # Mandatory
        h2: float, l2: float,  # Mandatory
        v1: Optional[float] = None, 
        v2: Optional[float] = None,
        *,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p: Dict[str, Any] = {**self.defaults, **overrides}
        
        # 1. Direction Check (C1 Bearish, C2 Bullish)
        first_bearish = not self.is_bullish(o1, c1)
        second_bullish = self.is_bullish(o2, c2)
        if not (first_bearish and second_bullish):
            return PatternResult(is_pattern=False)

        # Basic Calculations
        body1 = self.get_body(o1, c1)
        body2 = self.get_body(o2, c2)
        range1 = self.get_range(h1, l1)
        range2 = self.get_range(h2, l2)
        
        # Hygiene
        if range1 <= p["min_range"] or range2 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # 2. Body Engulfing (Overlap)
        if p["require_strict_overlap"]:
            # Strict: Open2 < Close1 AND Close2 > Open1
            engulf_ok = (o2 <= c1 * (1 - p["float_tolerance"])) and \
                        (c2 >= o1 * (1 + p["float_tolerance"]))
        else:
            # Standard: Open2 <= Close1 AND Close2 >= Open1
            engulf_ok = (o2 <= (c1 + abs(c1) * p["float_tolerance"])) and \
                        (c2 >= (o1 - abs(o1) * p["float_tolerance"]))

        if not engulf_ok:
            return PatternResult(is_pattern=False)

        # 3. Shadow Engulfing (Outer Bar)
        if p["require_shadow_engulfing"]:
            # High2 >= High1 AND Low2 <= Low1
            shadow_engulf_ok = (h2 >= h1 * (1 - p["float_tolerance"])) and \
                               (l2 <= l1 * (1 + p["float_tolerance"]))
            if not shadow_engulf_ok:
                return PatternResult(is_pattern=False)

        # 4. Strength (Size Multiplier)
        if not (body2 >= body1 * p["strength_multiplier"] * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # 5. Upper Wick Check (Rejection check)
        if p["max_upper_wick_ratio2"] is not None:
            upper_wick2 = self.get_upper_shadow(o2, h2, c2)
            denom = body2 if body2 > p["min_range"] else p["min_range"]
            if (upper_wick2 / denom) > (p["max_upper_wick_ratio2"] * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 6. Range & Ratio Logic
        
        # Body Ratio 1 (Must be a real candle)
        if p["min_body_ratio1"] is not None:
            if (body1 / range1) < (p["min_body_ratio1"] * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # Body Ratio 2 (ATR Adaptive)
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body_atr_scaler = 1.0
        
        if effective_min_body_ratio2 is not None:
            if atr and atr > 0:
                lo, hi = p["body_atr_bounds"]
                if hi < lo: lo, hi = hi, lo
                # If ATR is high, relax the requirement
                raw_scaler = p["body_atr_alpha"] * (atr / range2)
                body_atr_scaler = max(lo, min(hi, raw_scaler))
                effective_min_body_ratio2 = effective_min_body_ratio2 / body_atr_scaler
            
            if (body2 / range2) < (effective_min_body_ratio2 * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # ATR Absolute Checks
        if atr and atr > 0:
            if p["max_body1_vs_atr"] and body1 > (p["max_body1_vs_atr"] * atr):
                return PatternResult(is_pattern=False)
            if p["min_body2_vs_atr"] and body2 < (p["min_body2_vs_atr"] * atr):
                return PatternResult(is_pattern=False)

        # 7. Volume Confirmation
        if p["require_volume_increase"]:
            if v1 is not None and v2 is not None:
                if v2 <= v1:
                    return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2,
            "engulf_ok": True, 
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "upper_wick_ratio2": (self.get_upper_shadow(o2, h2, c2) / body2) if body2 > 0 else 0,
            "params": {**self.defaults, "atr": atr, **overrides},
        }
        return PatternResult(True, "Bullish Engulfing", "long", metrics)
