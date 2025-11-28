from typing import Optional, Tuple

from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult, TripeCandlePatternDetector


class ThreeWhiteSoldiersDetector(TripeCandlePatternDetector):
    """
    Three White Soldiers (bullish, 3-candle):
      - Three consecutive bullish candles (c > o)
      - Each close higher than the previous close
      - Bodies are strong (relative to average and/or range)
      - Optional: each open within prior real body; shadows relatively small
      - Optional: ATR-aware minimum body sizes
    """
    def __init__(
        self,
        *,
        # Core directional constraints
        require_consecutive_bullish: bool = True,
        require_higher_closes: bool = True,               # c2 > c1, c3 > c2

        # Open location constraints (textbook variant)
        require_open_within_prev_body: bool = False,      # o2 inside body1, o3 inside body2
        open_within_tolerance: float = 1e-9,

        # Body strength constraints
        min_body_vs_avg_body_ratio: float = 0.80,         # each body >= 0.8 * avg(body1..3)
        require_strong_bodies: bool = True,

        # Range-based body constraints (requires h/l if set)
        min_body_ratio_vs_range: Optional[float] = None,  # body_i / range_i >= x (e.g., 0.30)

        # Shadow constraints (optional; soldiers typically have small shadows)
        max_upper_shadow_to_body: Optional[float] = None, # upper_shadow/body <= x (e.g., 0.30)
        max_lower_shadow_to_body: Optional[float] = None, # lower_shadow/body <= x (e.g., 0.50)

        # Hygiene / numeric robustness
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,

        # ATR-aware constraints (optional)
        body_atr_alpha: float = 1.0,                      # scaler for (ATR / range_i)
        body_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        min_body_vs_atr: Optional[float] = None           # each body >= k * ATR (e.g., 0.25)
    ):
        self.defaults = dict(
            require_consecutive_bullish=require_consecutive_bullish,
            require_higher_closes=require_higher_closes,
            require_open_within_prev_body=require_open_within_prev_body,
            open_within_tolerance=open_within_tolerance,
            min_body_vs_avg_body_ratio=min_body_vs_avg_body_ratio,
            require_strong_bodies=require_strong_bodies,
            min_body_ratio_vs_range=min_body_ratio_vs_range,
            max_upper_shadow_to_body=max_upper_shadow_to_body,
            max_lower_shadow_to_body=max_lower_shadow_to_body,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body_atr_alpha=body_atr_alpha,
            body_atr_bounds=body_atr_bounds,
            min_body_vs_atr=min_body_vs_atr,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        o3: float, c3: float,
        *,
        # Optional highs/lows for ranges & shadow analysis
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        h3: Optional[float] = None, l3: Optional[float] = None,
        # Optional ATR (single value applied to all three)
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Basic hygiene
        if any(x is None for x in (o1, c1, o2, c2, o3, c3)):
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Directions
        bull1 = c1 > o1
        bull2 = c2 > o2
        bull3 = c3 > o3

        if p["require_consecutive_bullish"] and not (bull1 and bull2 and bull3):
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Bodies
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        body3 = abs(c3 - o3)
        if body1 <= 0 or body2 <= 0 or body3 <= 0:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        avg_body = (body1 + body2 + body3) / 3.0

        # Higher closes
        higher_closes_ok = True
        if p["require_higher_closes"]:
            higher_closes_ok = (c2 >= c1 * (1 + p["float_tolerance"])) and \
                               (c3 >= c2 * (1 + p["float_tolerance"]))

        # Open within previous body (optional)
        open_within_ok = True
        if p["require_open_within_prev_body"]:
            # For bullish prior candle (c1 > o1), inside means: o1 <= o2 <= c1; same for o3 inside body2
            open_within_ok = (o2 >= o1 * (1 - p["open_within_tolerance"])) and (o2 <= c1 * (1 + p["open_within_tolerance"])) and \
                             (o3 >= o2 * (1 - p["open_within_tolerance"])) and (o3 <= c2 * (1 + p["open_within_tolerance"]))

        # Optional ranges & shadows
        def valid_range(h: Optional[float], l: Optional[float]) -> bool:
            return (h is not None) and (l is not None) and (h >= l) and ((h - l) > p["min_range"])

        ranges = []
        for (h, l) in [(h1, l1), (h2, l2), (h3, l3)]:
            ranges.append((h - l) if valid_range(h, l) else None)
        price_range1, price_range2, price_range3 = ranges

        # If range-based constraints requested but ranges missing, fail safely
        if p["min_body_ratio_vs_range"] is not None and (price_range1 is None or price_range2 is None or price_range3 is None):
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # Shadows (if ranges provided)
        def shadows(open_, high, low, close):
            if high is None or low is None:
                return None, None
            upper = max(0.0, high - max(open_, close))
            lower = max(0.0, min(open_, close) - low)
            return upper, lower

        upper1, lower1 = shadows(o1, h1, l1, c1)
        upper2, lower2 = shadows(o2, h2, l2, c2)
        upper3, lower3 = shadows(o3, h3, l3, c3)

        # Ratios: body/range and shadow/body
        def ratios(body, prange, upper, lower):
            if prange is None:
                return None, None, None
            body_ratio = body / prange
            upper_to_body = (upper / body) if body > 0 else float('inf')
            lower_to_body = (lower / body) if body > 0 else float('inf')
            return body_ratio, upper_to_body, lower_to_body

        br1, ub1, lb1 = ratios(body1, price_range1, upper1, lower1)
        br2, ub2, lb2 = ratios(body2, price_range2, upper2, lower2)
        br3, ub3, lb3 = ratios(body3, price_range3, upper3, lower3)

        # Body strength vs average
        strong_vs_avg_ok = True
        if p["require_strong_bodies"]:
            strong_vs_avg_ok = (body1 >= avg_body * p["min_body_vs_avg_body_ratio"] * (1 - p["float_tolerance"])) and \
                               (body2 >= avg_body * p["min_body_vs_avg_body_ratio"] * (1 - p["float_tolerance"])) and \
                               (body3 >= avg_body * p["min_body_vs_avg_body_ratio"] * (1 - p["float_tolerance"]))

        # Body ratio vs range (ATR-adaptive optional)
        body_ratio_vs_range_ok = True
        effective_min_body_ratio_vs_range = [p["min_body_ratio_vs_range"]] * 3 if p["min_body_ratio_vs_range"] is not None else [None, None, None]
        body_atr_scalers = [None, None, None]
        if p["min_body_ratio_vs_range"] is not None:
            # ATR adaptation per candle (if atr provided and ranges valid)
            for i, (pr, br) in enumerate([(price_range1, br1), (price_range2, br2), (price_range3, br3)]):
                if pr is None or br is None:
                    body_ratio_vs_range_ok = False
                    break
                if atr is not None and atr > 0.0:
                    lo, hi = p["body_atr_bounds"]
                    if hi < lo: lo, hi = hi, lo
                    scaler = p["body_atr_alpha"] * (atr / pr)
                    scaler = max(lo, min(hi, scaler))
                    body_atr_scalers[i] = scaler
                    effective_min_body_ratio_vs_range[i] = p["min_body_ratio_vs_range"] / scaler  # tighten in high vol
                # Check
                body_ratio_vs_range_ok = body_ratio_vs_range_ok and (br >= effective_min_body_ratio_vs_range[i] * (1 - p["float_tolerance"]))

        # Shadow-to-body constraints (if provided)
        shadows_ok = True
        if p["max_upper_shadow_to_body"] is not None and ub1 is not None and ub2 is not None and ub3 is not None:
            shadows_ok = shadows_ok and (ub1 <= p["max_upper_shadow_to_body"] * (1 + p["float_tolerance"])) \
                                   and (ub2 <= p["max_upper_shadow_to_body"] * (1 + p["float_tolerance"])) \
                                   and (ub3 <= p["max_upper_shadow_to_body"] * (1 + p["float_tolerance"]))
        if p["max_lower_shadow_to_body"] is not None and lb1 is not None and lb2 is not None and lb3 is not None:
            shadows_ok = shadows_ok and (lb1 <= p["max_lower_shadow_to_body"] * (1 + p["float_tolerance"])) \
                                   and (lb2 <= p["max_lower_shadow_to_body"] * (1 + p["float_tolerance"])) \
                                   and (lb3 <= p["max_lower_shadow_to_body"] * (1 + p["float_tolerance"]))

        # ATR absolute body constraint (optional)
        atr_bodies_ok = True
        if atr is not None and atr > 0.0 and p["min_body_vs_atr"] is not None and p["min_body_vs_atr"] > 0.0:
            atr_bodies_ok = (body1 >= p["min_body_vs_atr"] * atr * (1 - p["float_tolerance"])) and \
                            (body2 >= p["min_body_vs_atr"] * atr * (1 - p["float_tolerance"])) and \
                            (body3 >= p["min_body_vs_atr"] * atr * (1 - p["float_tolerance"]))

        # Final decision
        is_pattern = all([
            (bull1 and bull2 and bull3) if p["require_consecutive_bullish"] else True,
            higher_closes_ok,
            open_within_ok,
            strong_vs_avg_ok,
            body_ratio_vs_range_ok,
            shadows_ok,
            atr_bodies_ok,
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        metrics = {
            # Bodies & directions
            "bull1": bull1, "bull2": bull2, "bull3": bull3,
            "body1": body1, "body2": body2, "body3": body3,
            "avg_body": avg_body,
            # Close progression
            "higher_closes_ok": higher_closes_ok,
            # Open location
            "open_within_ok": open_within_ok,
            # Ranges & shadows
            "price_range1": price_range1, "price_range2": price_range2, "price_range3": price_range3,
            "upper1": upper1, "lower1": lower1,
            "upper2": upper2, "lower2": lower2,
            "upper3": upper3, "lower3": lower3,
            # Ratios
            "body_ratio1": br1, "upper_to_body1": ub1, "lower_to_body1": lb1,
            "body_ratio2": br2, "upper_to_body2": ub2, "lower_to_body2": lb2,
            "body_ratio3": br3, "upper_to_body3": ub3, "lower_to_body3": lb3,
            # Effective thresholds & ATR info
            "min_body_vs_avg_body_ratio": p["min_body_vs_avg_body_ratio"],
            "effective_min_body_ratio_vs_range": effective_min_body_ratio_vs_range,
            "body_atr_scalers": body_atr_scalers,
            "atr": atr,
            # Flags
            "strong_vs_avg_ok": strong_vs_avg_ok,
            "body_ratio_vs_range_ok": body_ratio_vs_range_ok,
            "shadows_ok": shadows_ok,
            "atr_bodies_ok": atr_bodies_ok,
            # OHLC echo
            "o1": o1, "c1": c1, "h1": h1, "l1": l1,
            "o2": o2, "c2": c2, "h2": h2, "l2": l2,
            "o3": o3, "c3": c3, "h3": h3, "l3": l3,
            # Params snapshot (logging/debug)
            "params": self.defaults | {"atr": atr} | overrides,
        }

        return PatternResult(
            is_pattern=True,
            name="Three White Soldiers",
            bias="bull",
            metrics=metrics
        )

# Usage Example
# det = ThreeWhiteSoldiersDetector(
#     require_open_within_prev_body=True,      # textbook variant
#     require_strong_bodies=True,
#     min_body_vs_avg_body_ratio=0.8
# )

# # Minimal (open/close only)
# res = det.detect(
#     o1=9.8,  c1=10.3,
#     o2=10.1, c2=10.7,
#     o3=10.5, c3=11.0
# )

# # With ranges, shadow constraints, and ATR
# res2 = det.detect(
#     o1=9.8,  c1=10.3, h1=10.4, l1=9.6,
#     o2=10.1, c2=10.7, h2=10.8, l2=10.0,
#     o3=10.5, c3=11.0, h3=11.1, l3=10.4,
#     atr=0.8,
#     min_body_ratio_vs_range=0.30,           # each body >= 30% of its range
#     max_upper_shadow_to_body=0.30,          # cap upper wicks
#     max_lower_shadow_to_body=0.50,          # cap lower wicks
#     min_body_vs_atr=0.25                    # each body >= 25% ATR
# )

# Tuning Tips (Trader’s Perspective)

# Body strength: Keep min_body_vs_avg_body_ratio in the 0.7–1.0 range; higher values reduce false positives.
# Range-based ratio: min_body_ratio_vs_range around 0.25–0.40 ensures meaningful bodies (filters micro/weak prints).
# Open within previous body: require_open_within_prev_body=True gives a textbook look; relax for intraday or adjusted feeds.
# Shadows: Capping max_upper_shadow_to_body (e.g., ≤0.3) and max_lower_shadow_to_body (e.g., ≤0.5) strengthens pattern quality.
# ATR filters: Requiring min_body_vs_atr (e.g., 0.25–0.40) improves decisiveness in high volatility.
# Context & confirmation: Best edge after a downtrend, near support/swing lows/VWAP lower band/pivots, with confirmation (next bar breaks/closes above soldier 3’s high). Stops often below soldier 3’s low; ATR-based sizing recommended.
