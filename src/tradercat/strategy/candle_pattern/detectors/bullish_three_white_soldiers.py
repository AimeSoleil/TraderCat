from typing import Optional, Tuple
from tradercat.strategy.candle_pattern.pattern_detector import PatternResult, TripleCandlePatternDetector


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
        *,
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        h3: Optional[float] = None, l3: Optional[float] = None,
        v1: Optional[float] = None, v2: Optional[float] = None, v3: Optional[float] = None,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Basic hygiene
        if any(x is None for x in (o1, c1, o2, c2, o3, c3)):
            return PatternResult(is_pattern=False)

        # 1) Direction
        bull1, bull2, bull3 = c1 > o1, c2 > o2, c3 > o3
        if p["require_consecutive_bullish"] and not (bull1 and bull2 and bull3):
            return PatternResult(is_pattern=False)

        # 2) Bodies
        body1, body2, body3 = abs(c1 - o1), abs(c2 - o2), abs(c3 - o3)
        if body1 <= p["min_range"] or body2 <= p["min_range"] or body3 <= p["min_range"]:
            return PatternResult(is_pattern=False)
        avg_body = (body1 + body2 + body3) / 3.0

        # 3) Staircase (closes & lows)
        higher_closes_ok = True
        if p["require_higher_closes"]:
            higher_closes_ok = (c2 >= c1 * (1 + p["float_tolerance"])) and \
                               (c3 >= c2 * (1 + p["float_tolerance"]))

        higher_lows_ok = True
        if p["require_higher_lows"]:
            if all(x is not None for x in (l1, l2, l3)):
                higher_lows_ok = (l2 > l1) and (l3 > l2)
            else:
                # Fallback if lows missing
                higher_lows_ok = (o2 > o1) and (o3 > o2)

        # 4) Open within previous body (Legacy / Textbook check)
        open_within_ok = True
        if p["require_open_within_prev_body"]:
            # Strict textbook definition: Open is inside previous real body.
            def is_inside(op, prev_o, prev_c):
                top, bot = max(prev_o, prev_c), min(prev_o, prev_c)
                return (op >= bot * (1 - p["open_within_tolerance"])) and \
                       (op <= top * (1 + p["open_within_tolerance"]))
            
            open_within_ok = is_inside(o2, o1, c1) and is_inside(o3, o2, c2)

        # 5) Body strength consistency
        strong_vs_avg_ok = True
        if p["require_strong_bodies"]:
            r = p["min_body_vs_avg_body_ratio"]
            strong_vs_avg_ok = (body1 >= avg_body * r) and (body2 >= avg_body * r) and (body3 >= avg_body * r)

        # 6) Volume progression
        vol_ok = True
        if p["require_volume_increase"]:
            if all(v is not None for v in (v1, v2, v3)):
                # Allow slight variance, but generally increasing
                vol_ok = (v2 >= v1 * 0.9) and (v3 >= v2 * 0.9)
            else:
                vol_ok = False

        # 7) Range & shadows
        def valid_range(h, l): return (h is not None and l is not None) and (h >= l)
        ranges = [(h - l) if valid_range(h, l) else None for h, l in [(h1, l1), (h2, l2), (h3, l3)]]

        shadows_ok = True
        # Check each candle for shadow limits
        candle_data = [
            (o1, c1, h1, l1, body1),
            (o2, c2, h2, l2, body2),
            (o3, c3, h3, l3, body3)
        ]
        
        for (o, c, h, l, b) in candle_data:
            if h is None or l is None: continue
            if b <= p["min_range"]: 
                shadows_ok = False; break

            upper = h - max(o, c)
            lower = min(o, c) - l
            
            if p["max_upper_shadow_to_body"] is not None:
                if (upper / b) > p["max_upper_shadow_to_body"]: shadows_ok = False
            
            if p["max_lower_shadow_to_body"] is not None:
                if (lower / b) > p["max_lower_shadow_to_body"]: shadows_ok = False

        # 7b) Body vs Range (The "Long Candle" check)
        body_ratios_ok = True
        effective_min_body_ratio = p["min_body_ratio_vs_range"]
        
        # ATR Adaptive Logic
        if effective_min_body_ratio is not None and atr is not None and atr > 0:
            valid_ranges_vals = [r for r in ranges if r is not None]
            if valid_ranges_vals:
                avg_range_val = sum(valid_ranges_vals) / len(valid_ranges_vals)
                if avg_range_val > p["min_range"]:
                    lo, hi = p["body_atr_bounds"]
                    if hi < lo: lo, hi = hi, lo
                    # If ATR is high (volatile), we relax the body ratio requirement
                    raw_scaler = p["body_atr_alpha"] * (atr / avg_range_val)
                    scaler = max(lo, min(hi, raw_scaler))
                    effective_min_body_ratio = effective_min_body_ratio / scaler

        if effective_min_body_ratio is not None:
            for b, r in zip([body1, body2, body3], ranges):
                if r is None:
                    body_ratios_ok = False; break
                # Must be a solid candle, not a doji
                if (b / r) < (effective_min_body_ratio * (1 - p["float_tolerance"])):
                    body_ratios_ok = False; break

        # 8) ATR absolute check
        atr_bodies_ok = True
        if atr and p["min_body_vs_atr"]:
            threshold = p["min_body_vs_atr"] * atr
            atr_bodies_ok = (body1 >= threshold) and (body2 >= threshold) and (body3 >= threshold)

        # Final decision
        conditions = [
            higher_closes_ok, higher_lows_ok, open_within_ok,
            strong_vs_avg_ok, vol_ok,
            shadows_ok, atr_bodies_ok, body_ratios_ok
        ]
        
        if not all(conditions):
            return PatternResult(is_pattern=False)

        metrics = {
            "avg_body": avg_body,
            "higher_lows": higher_lows_ok,
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