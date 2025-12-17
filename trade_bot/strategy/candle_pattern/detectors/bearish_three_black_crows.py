from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, TripleCandlePatternDetector


class ThreeBlackCrowsDetector(TripleCandlePatternDetector):
    """
    Three Black Crows (bearish, 3-candle) - Production Grade:
        - Three consecutive bearish candles.
        - Each close lower than previous close.
        - Each low ideally lower than previous low (staircase down).
        - First candle is significant (trend starter).
        - Optional volume progression check.
        - Optional body-vs-range ATR adaptive filter.
    """

    def __init__(
        self,
        *,
        # Directional constraints
        require_consecutive_bearish: bool = True,
        require_lower_closes: bool = True,
        require_lower_lows: bool = True,

        # Open location constraints
        require_open_within_prev_body: bool = False,
        open_within_tolerance: float = 1e-9,

        # Body strength constraints
        min_body_vs_avg_body_ratio: float = 0.80,
        require_strong_bodies: bool = True,
        require_big_first_candle: bool = True,  # First crow should stand out

        # Range-based body constraints (optional)
        min_body_ratio_vs_range: Optional[float] = None,  # e.g., 0.4 means body >= 40% of its range

        # Shadow constraints
        max_upper_shadow_to_body: Optional[float] = None,
        max_lower_shadow_to_body: Optional[float] = 0.5,  # avoid long lower wicks (buying support)

        # Volume Logic
        require_volume_increase: bool = False,  # Prefer vol3 >= vol2 >= vol1

        # Hygiene
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR-aware constraints (absolute body vs ATR)
        min_body_vs_atr: Optional[float] = None,

        # ATR adaptive scaling for body-vs-range check
        body_atr_alpha: float = 1.0,
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
    ):
        self.defaults = dict(
            require_consecutive_bearish=require_consecutive_bearish,
            require_lower_closes=require_lower_closes,
            require_lower_lows=require_lower_lows,
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
        *,
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        h3: Optional[float] = None, l3: Optional[float] = None,
        v1: Optional[float] = None, v2: Optional[float] = None, v3: Optional[float] = None,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Basic data check
        if any(x is None for x in (o1, c1, o2, c2, o3, c3)):
            return PatternResult(is_pattern=False)

        # 1) Direction
        bear1, bear2, bear3 = c1 < o1, c2 < o2, c3 < o3
        if p["require_consecutive_bearish"] and not (bear1 and bear2 and bear3):
            return PatternResult(is_pattern=False)

        # 2) Bodies
        body1, body2, body3 = abs(c1 - o1), abs(c2 - o2), abs(c3 - o3)
        if body1 <= p["float_tolerance"] or body2 <= p["float_tolerance"] or body3 <= p["float_tolerance"]:
            return PatternResult(is_pattern=False)
        avg_body = (body1 + body2 + body3) / 3.0

        # 3) Staircase (closes & lows)
        lower_closes_ok = True
        if p["require_lower_closes"]:
            lower_closes_ok = (c2 < c1) and (c3 < c2)

        lower_lows_ok = True
        if p["require_lower_lows"]:
            if all(x is not None for x in (l1, l2, l3)):
                lower_lows_ok = (l2 < l1) and (l3 < l2)
            else:
                lower_lows_ok = (c2 < c1) and (c3 < c2)

        # 4) Open within previous body (optional)
        open_within_ok = True
        if p["require_open_within_prev_body"]:
            open_within_ok = (o2 >= min(o1, c1) * (1 - p["open_within_tolerance"])) and (o2 <= max(o1, c1) * (1 + p["open_within_tolerance"])) and \
                             (o3 >= min(o2, c2) * (1 - p["open_within_tolerance"])) and (o3 <= max(o2, c2) * (1 + p["open_within_tolerance"]))

        # 5) Body strength
        strong_vs_avg_ok = True
        if p["require_strong_bodies"]:
            r = p["min_body_vs_avg_body_ratio"]
            strong_vs_avg_ok = (body1 >= avg_body * r) and (body2 >= avg_body * r) and (body3 >= avg_body * r)

        first_candle_ok = True
        if p["require_big_first_candle"]:
            first_candle_ok = body1 >= (avg_body * 1.1)

        # 6) Volume progression (optional)
        vol_ok = True
        if p["require_volume_increase"]:
            if all(v is not None for v in (v1, v2, v3)):
                vol_ok = (v2 >= v1 * 0.9) and (v3 >= v2 * 0.9)
            else:
                vol_ok = False

        # 7) Range & shadows
        def valid_range(h, l): return (h is not None and l is not None and h >= l)
        ranges = [(h - l) if valid_range(h, l) else None for h, l in [(h1, l1), (h2, l2), (h3, l3)]]

        shadows_ok = True
        for (o, c, h, l, b, max_lower, max_upper) in [
            (o1, c1, h1, l1, body1, p["max_lower_shadow_to_body"], p["max_upper_shadow_to_body"]),
            (o2, c2, h2, l2, body2, p["max_lower_shadow_to_body"], p["max_upper_shadow_to_body"]),
            (o3, c3, h3, l3, body3, p["max_lower_shadow_to_body"], p["max_upper_shadow_to_body"]),
        ]:
            if h is None or l is None:
                continue
            
            # Safe division guard
            if b <= p["float_tolerance"]:
                shadows_ok = False
                break

            upper = h - max(o, c)  # bearish: high - max(open, close)
            lower = min(o, c) - l  # bearish: min(open, close) - low
            if max_upper is not None and upper / b > max_upper:
                shadows_ok = False
            if max_lower is not None and lower / b > max_lower:
                shadows_ok = False

        # 7b) Body vs Range with ATR adaptive scaler
        body_ratios_ok = True
        effective_min_body_ratio = p["min_body_ratio_vs_range"]
        if effective_min_body_ratio is not None and atr is not None and atr > 0:
            valid_ranges_vals = [r for r in ranges if r is not None]
            if valid_ranges_vals:
                avg_range_val = sum(valid_ranges_vals) / len(valid_ranges_vals)
                if avg_range_val > p["min_range"]:
                    lo, hi = p["body_atr_bounds"]
                    if hi < lo:
                        lo, hi = hi, lo
                    raw_scaler = p["body_atr_alpha"] * (atr / avg_range_val)
                    scaler = max(lo, min(hi, raw_scaler))
                    effective_min_body_ratio = effective_min_body_ratio / scaler

        if effective_min_body_ratio is not None:
            for b, r in zip([body1, body2, body3], ranges):
                if r is None:
                    body_ratios_ok = False
                    break
                if (b / r) < (effective_min_body_ratio * (1 - p["float_tolerance"])):
                    body_ratios_ok = False
                    break

        # 8) ATR absolute check
        atr_bodies_ok = True
        if atr and p["min_body_vs_atr"]:
            threshold = p["min_body_vs_atr"] * atr
            atr_bodies_ok = (body1 >= threshold) and (body2 >= threshold) and (body3 >= threshold)

        # Final decision
        conditions = [
            lower_closes_ok, lower_lows_ok, open_within_ok,
            strong_vs_avg_ok, first_candle_ok, vol_ok,
            shadows_ok, atr_bodies_ok, body_ratios_ok
        ]
        if not all(conditions):
            return PatternResult(is_pattern=False)

        metrics = {
            "avg_body": avg_body,
            "lower_lows": lower_lows_ok,
            "vol_trend": "increasing" if (v1 and v3 and v3 > v1) else "mixed",
            "effective_min_body_ratio": effective_min_body_ratio,
            "params": {**self.defaults, "atr": atr, **overrides}, # Added params
        }

        return PatternResult(
            is_pattern=True,
            name="Three Black Crows",
            bias="short",  # unified terminology
            metrics=metrics
        )