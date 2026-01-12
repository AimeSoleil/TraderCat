from typing import Optional, Tuple, Dict, Any
from tradercat.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult

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
        h1: float, l1: float,  # Mandatory per strict interface
        h2: float, l2: float,  # Mandatory per strict interface
        v1: Optional[float] = None, 
        v2: Optional[float] = None,
        *,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p: Dict[str, Any] = {**self.defaults, **overrides}

        # 1. Directions (C1 Bull, C2 Bear)
        if not (self.is_bullish(o1, c1) and not self.is_bullish(o2, c2)):
            return PatternResult(is_pattern=False)

        # Basic Calculations using Helpers
        body1 = self.get_body(o1, c1)
        body2 = self.get_body(o2, c2)
        range1 = self.get_range(h1, l1)
        range2 = self.get_range(h2, l2)

        # Hygiene
        if range1 <= p["min_range"] or range2 <= p["min_range"]:
            return PatternResult(is_pattern=False)

        # 2. Body Engulfing (Overlap)
        if p["require_strict_overlap"]:
            # Strict: Open2 > Close1 AND Close2 < Open1 (True Gap Engulf)
            engulf_ok = (o2 >= c1 * (1 + p["float_tolerance"])) and \
                        (c2 <= o1 * (1 - p["float_tolerance"]))
        else:
            # Standard: Open2 >= Close1 AND Close2 <= Open1
            engulf_ok = (o2 >= (c1 - abs(c1) * p["float_tolerance"])) and \
                        (c2 <= (o1 + abs(o1) * p["float_tolerance"]))

        if not engulf_ok:
            return PatternResult(is_pattern=False)

        # 3. Shadow Engulfing (Outer Bar)
        if p["require_shadow_engulfing"]:
            # H2 must beat H1, L2 must beat L1
            # Using strict comparison logic now that inputs are guaranteed
            if not ((h2 >= h1 * (1 - p["float_tolerance"])) and \
                    (l2 <= l1 * (1 + p["float_tolerance"]))):
                return PatternResult(is_pattern=False)

        # 4. Strength (Size Multiplier)
        if not (body2 >= body1 * p["strength_multiplier"] * (1 - p["float_tolerance"])):
            return PatternResult(is_pattern=False)

        # 5. Lower Wick Check (Rejection check)
        # Bearish candle closing near low is stronger.
        if p["max_lower_wick_ratio"] is not None:
            lower_wick2 = self.get_lower_shadow(o2, l2, c2)
            base_size = body2 if body2 > p["min_range"] else p["min_range"]
            
            if (lower_wick2 / base_size) > (p["max_lower_wick_ratio"] * (1 + p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 6. Body Ratio Checks (Noise Filtering)
        if p["min_body_ratio1"] is not None:
            if (body1 / range1) < (p["min_body_ratio1"] * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # Body Ratio 2 (ATR Adaptive)
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body2_atr_scaler = 1.0
        
        if effective_min_body_ratio2 is not None:
            if atr and atr > 0:
                lo, hi = p["body2_atr_bounds"]
                if hi < lo: lo, hi = hi, lo
                # If ATR is high relative to range, relax requirement
                raw_scaler = p["body2_atr_alpha"] * (atr / range2)
                body2_atr_scaler = max(lo, min(hi, raw_scaler))
                effective_min_body_ratio2 = effective_min_body_ratio2 / body2_atr_scaler
            
            if (body2 / range2) < (effective_min_body_ratio2 * (1 - p["float_tolerance"])):
                return PatternResult(is_pattern=False)

        # 7. ATR Absolute Checks
        if atr and atr > 0.0:
            if p["max_body1_vs_atr"] and body1 > (p["max_body1_vs_atr"] * atr):
                return PatternResult(is_pattern=False)
            if p["min_body2_vs_atr"] and body2 < (p["min_body2_vs_atr"] * atr):
                return PatternResult(is_pattern=False)

        # 8. Volume Confirmation
        if p["require_volume_increase"]:
            # Only enforce if data exists. 
            if v1 is not None and v2 is not None:
                if v2 <= v1:
                    return PatternResult(is_pattern=False)

        metrics = {
            "body1": body1, "body2": body2,
            "engulf_ok": True, 
            "volume_increase": (v2 / v1) if (v1 and v2 and v1 > 0) else None,
            "lower_wick_ratio": (self.get_lower_shadow(o2, l2, c2) / body2) if body2 > 0 else 0,
            "params": {**self.defaults, "atr": atr, **overrides},
        }
        return PatternResult(True, "Bearish Engulfing", "short", metrics)