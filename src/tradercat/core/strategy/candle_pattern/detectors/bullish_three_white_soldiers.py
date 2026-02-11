from typing import Optional, Tuple, Dict, Any
from tradercat.core.strategy.candle_pattern.pattern_detector import PatternResult, TripleCandlePatternDetector


class ThreeWhiteSoldiersDetector(TripleCandlePatternDetector):
    """
    Three White Soldiers (Bullish Reversal) - US Stock Optimized:
        - Pattern: Three consecutive long bullish candles.
        - Structure: Staircase up (Higher Highs, Higher Lows, Higher Closes).
        - Psychology: Steady buying pressure. Bulls are in total control.
        - Optimization: Enforces strong bodies and weak upper wicks to filter out "weak rallies".
    """

    def __init__(
        self,
        *,
        # --- Directional Constraints ---
        require_consecutive_bullish: bool = True,
        require_higher_closes: bool = True,
        
        # [Optimization] True. 
        # In a strong march, lows should also be moving up (Staircase pattern).
        require_higher_lows: bool = True,             

        # --- Open/Gap Logic ---
        # [Optimization] False. 
        # Textbook says "Open within previous body", but in US Stocks, 
        # a Gap Up (Open > Prev Close) indicates even stronger momentum. 
        # We disable this to capture high-momentum breakouts.
        require_open_within_prev_body: bool = False,
        open_within_tolerance: float = 1e-9,

        # --- Body Strength (Crucial) ---
        # [Optimization] 0.80. 
        # The three candles should be roughly similar in size. 
        # We don't want one huge candle followed by two tiny ones.
        min_body_vs_avg_body_ratio: float = 0.80,
        
        require_strong_bodies: bool = True,
        
        # [Optimization] True. 
        # The first soldier initiates the reversal; it must be significant.
        require_big_first_candle: bool = True,

        # --- Range-based Body Constraints ---
        # [Optimization] 0.40 (40%). 
        # This is the most important filter. 
        # It ensures the candles are "Long White Candles" (Body is >40% of total range),
        # filtering out small dojis or spinning tops drifting higher.
        min_body_ratio_vs_range: Optional[float] = 0.40,  

        # --- Shadow Constraints (Rejection) ---
        # [Optimization] 0.30 (30%). 
        # Soldiers must close near their highs. Long upper wicks indicate selling pressure.
        max_upper_shadow_to_body: Optional[float] = 0.30, 
        
        # [Optimization] None. 
        # Lower wicks matter less in a bullish march, as long as the body is strong.
        max_lower_shadow_to_body: Optional[float] = None, 

        # --- Volume Logic ---
        # [Optimization] False (Default), but True recommended in config.
        # Ideally, Volume 1 < Volume 2 < Volume 3 (Buying pressure growing).
        require_volume_increase: bool = False,  

        # --- Hygiene ---
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # --- ATR Constraints ---
        min_body_vs_atr: Optional[float] = None,

        # ATR adaptive scaling for body-vs-range check
        body_atr_alpha: float = 1.0,
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
    ):
        self.defaults = dict(
            require_consecutive_bullish=require_consecutive_bullish,
            require_higher_closes=require_higher_closes,
            require_higher_lows=require_higher_lows,
            require_open_within_prev_body=require_open_within_prev_body,
            open_within_tolerance=open_within_tolerance,
            min_body_vs_avg_body_ratio=min_body_vs_avg_body_ratio,
            require_strong_bodies=require_strong_bodies,
            require_big_first_candle=require_big_first_candle,
            min_body_ratio_vs_range=min_body_ratio_vs_range,
            max_upper_shadow_to_body=max_upper_shadow_to_body,
            max_lower_shadow_to_body=max_lower_shadow_to_body,
            require_volume_increase=require_volume_increase,
            min_range=min_range,
            float_tolerance=float_tolerance,
            min_body_vs_atr=min_body_vs_atr,
            body_atr_alpha=body_atr_alpha,
            body_atr_bounds=body_atr_bounds,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        o3: float, c3: float,
        h1: float, l1: float,  # Mandatory
        h2: float, l2: float,  # Mandatory
        h3: float, l3: float,  # Mandatory
        v1: Optional[float] = None, 
        v2: Optional[float] = None, 
        v3: Optional[float] = None,
        *,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p: Dict[str, Any] = {**self.defaults, **overrides}

        # 1) Direction (Bullish)
        if p["require_consecutive_bullish"]:
            if not (self.is_bullish(o1, c1) and self.is_bullish(o2, c2) and self.is_bullish(o3, c3)):
                return PatternResult(is_pattern=False)

        # 2) Bodies & Ranges
        body1 = self.get_body(o1, c1)
        body2 = self.get_body(o2, c2)
        body3 = self.get_body(o3, c3)
        range1 = self.get_range(h1, l1)
        range2 = self.get_range(h2, l2)
        range3 = self.get_range(h3, l3)
        
        # Hygiene
        if body1 <= p["min_range"] or body2 <= p["min_range"] or body3 <= p["min_range"]:
            return PatternResult(is_pattern=False)
            
        avg_body = (body1 + body2 + body3) / 3.0

        # 3) Staircase Logic
        if p["require_higher_closes"]:
            if not ((c2 > c1) and (c3 > c2)):
                return PatternResult(is_pattern=False)

        if p["require_higher_lows"]:
            # Strict low checks (no fallback)
            if not ((l2 > l1) and (l3 > l2)):
                return PatternResult(is_pattern=False)

        # 4) Open within previous body
        if p["require_open_within_prev_body"]:
            def is_inside(op, prev_o, prev_c):
                top, bot = max(prev_o, prev_c), min(prev_o, prev_c)
                return (op >= bot * (1 - p["open_within_tolerance"])) and \
                       (op <= top * (1 + p["open_within_tolerance"]))
            
            if not (is_inside(o2, o1, c1) and is_inside(o3, o2, c2)):
                return PatternResult(is_pattern=False)

        # 5) Body Strength consistency
        if p["require_strong_bodies"]:
            r = p["min_body_vs_avg_body_ratio"]
            if not ((body1 >= avg_body * r) and (body2 >= avg_body * r) and (body3 >= avg_body * r)):
                return PatternResult(is_pattern=False)
        
        if p["require_big_first_candle"]:
            if body1 < avg_body:
                return PatternResult(is_pattern=False)

        # 6) Volume Progression
        if p["require_volume_increase"]:
            # Strict mode: fail if data missing
            if any(v is None for v in (v1, v2, v3)):
                return PatternResult(is_pattern=False)
            # Allow slight variance (0.9), but generally increasing
            if not ((v2 >= v1 * 0.9) and (v3 >= v2 * 0.9)):
                 return PatternResult(is_pattern=False)

        # 7) Shadows and Ratio Checks (Iterative)
        candle_data = [
            (o1, c1, h1, l1, body1, range1),
            (o2, c2, h2, l2, body2, range2),
            (o3, c3, h3, l3, body3, range3)
        ]

        # Prepare ATR scaler for Body/Range check
        effective_min_body_ratio = p["min_body_ratio_vs_range"]
        if effective_min_body_ratio is not None and atr is not None and atr > 0:
            avg_range_val = (range1 + range2 + range3) / 3.0
            if avg_range_val > p["min_range"]:
                lo, hi = p["body_atr_bounds"]
                if hi < lo: lo, hi = hi, lo
                raw_scaler = p["body_atr_alpha"] * (atr / avg_range_val)
                scaler = max(lo, min(hi, raw_scaler))
                effective_min_body_ratio = effective_min_body_ratio / scaler

        # Check per soldier
        for (o, c, h, l, b, r) in candle_data:
            upper = self.get_upper_shadow(o, h, c)
            lower = self.get_lower_shadow(o, l, c)
            
            if p["max_upper_shadow_to_body"] is not None:
                if (upper / b) > p["max_upper_shadow_to_body"]: 
                    return PatternResult(is_pattern=False)
            
            if p["max_lower_shadow_to_body"] is not None:
                if (lower / b) > p["max_lower_shadow_to_body"]: 
                    return PatternResult(is_pattern=False)
            
            # Body vs Range
            if effective_min_body_ratio is not None:
                if (b / r) < (effective_min_body_ratio * (1 - p["float_tolerance"])):
                    return PatternResult(is_pattern=False)

        # 8) ATR Absolute Check
        if atr and p["min_body_vs_atr"]:
            threshold = p["min_body_vs_atr"] * atr
            if not ((body1 >= threshold) and (body2 >= threshold) and (body3 >= threshold)):
                return PatternResult(is_pattern=False)

        metrics = {
            "avg_body": avg_body,
            "higher_lows": True,
            "vol_trend": "increasing" if (v1 and v3 and v3 > v1) else "mixed",
            "effective_min_body_ratio": effective_min_body_ratio,
            "params": {**self.defaults, "atr": atr, **overrides},
        }

        return PatternResult(
            is_pattern=True,
            name="Three White Soldiers",
            bias="long",
            metrics=metrics
        )