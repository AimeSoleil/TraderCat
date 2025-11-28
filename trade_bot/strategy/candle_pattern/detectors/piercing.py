
from typing import Optional, Tuple
from trade_bot.strategy.candle_pattern.pattern_detector import DoubleCandlePatternDetector, PatternResult


class PiercingPatternDetector(DoubleCandlePatternDetector):
    """
    Piercing Pattern (bullish, 2-candle):
      - Candle 1 bearish (c1 < o1)
      - Candle 2 bullish (c2 > o2)
      - Candle 2 opens below Candle 1 close (o2 < c1)  [gap-down semantics on daily]
      - Candle 2 closes above Candle 1 midpoint but below Candle 1 open
      - Optional: body2 strength relative to body1, doji avoidance via range ratios, ATR-aware constraints
    """
    def __init__(
        self,
        *,
        require_strict_open_below_c1: bool = True,      # require o2 <= c1 (strict)
        require_close_above_midpoint1: bool = True,     # require c2 >= midpoint(o1,c1)
        require_close_below_o1: bool = True,            # require c2 <= o1 (classic definition)
        midpoint_margin_ratio: float = 0.0,             # extra margin above midpoint: margin = body1 * ratio
        strength_multiplier_vs_body1: float = 0.80,     # body2 >= 0.8 * body1
        # Doji avoidance (requires ranges if set)
        min_body_ratio1: Optional[float] = None,        # body1 / range1 >= x  (e.g., 0.03)
        min_body_ratio2: Optional[float] = None,        # body2 / range2 >= y  (e.g., 0.05)
        # Hygiene / numeric robustness
        min_range: float = 1e-9,
        float_tolerance: float = 1e-9,
        # ATR adaptation (optional)
        body2_atr_alpha: float = 1.0,                   # scaler for (ATR / range2)
        body2_atr_bounds: Tuple[float, float] = (0.7, 1.5),
        min_body2_vs_atr: Optional[float] = None        # body2 >= ratio * ATR (e.g., 0.30)
    ):
        self.defaults = dict(
            require_strict_open_below_c1=require_strict_open_below_c1,
            require_close_above_midpoint1=require_close_above_midpoint1,
            require_close_below_o1=require_close_below_o1,
            midpoint_margin_ratio=midpoint_margin_ratio,
            strength_multiplier_vs_body1=strength_multiplier_vs_body1,
            min_body_ratio1=min_body_ratio1,
            min_body_ratio2=min_body_ratio2,
            min_range=min_range,
            float_tolerance=float_tolerance,
            body2_atr_alpha=body2_atr_alpha,
            body2_atr_bounds=body2_atr_bounds,
            min_body2_vs_atr=min_body2_vs_atr,
        )

    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        *,
        # Optional highs/lows for range-based checks and ATR scaling
        h1: Optional[float] = None, l1: Optional[float] = None,
        h2: Optional[float] = None, l2: Optional[float] = None,
        atr: Optional[float] = None,
        **overrides
    ) -> PatternResult:
        p = {**self.defaults, **overrides}

        # Basic hygiene
        if any(x is None for x in (o1, c1, o2, c2)):
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        first_bearish = c1 < o1
        second_bullish = c2 > o2
        if not (first_bearish and second_bullish):
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        if body1 <= 0 or body2 <= 0:
            # degenerate bodies -> not a valid pattern
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        midpoint1 = (o1 + c1) / 2.0

        # Optional ranges for ratio/ATR logic
        def valid_range(h: Optional[float], l: Optional[float]) -> bool:
            return (h is not None) and (l is not None) and (h >= l) and ((h - l) > p["min_range"])

        price_range1 = (h1 - l1) if valid_range(h1, l1) else None
        price_range2 = (h2 - l2) if valid_range(h2, l2) else None

        # If caller wants ratio/ATR checks but ranges invalid, fail safely
        ranges_required = (p["min_body_ratio1"] is not None and price_range1 is None) or \
                          (p["min_body_ratio2"] is not None and price_range2 is None) or \
                          (p["min_body2_vs_atr"] is not None and atr is not None and price_range2 is None)
        if ranges_required:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        # --- Core conditions ---

        # (1) Open below previous close (gap-down semantics)
        if p["require_strict_open_below_c1"]:
            open_below_c1_ok = o2 <= (c1 * (1 + p["float_tolerance"]))
        else:
            open_below_c1_ok = o2 <= (c1 + abs(c1) * p["float_tolerance"])

        # (2) Close above midpoint of candle 1 (optional margin)
        midpoint_ok = True
        if p["require_close_above_midpoint1"]:
            margin = body1 * p["midpoint_margin_ratio"] if p["midpoint_margin_ratio"] and p["midpoint_margin_ratio"] > 0.0 else 0.0
            midpoint_ok = c2 >= (midpoint1 + margin * (1 - p["float_tolerance"]))

        # (3) Close below candle 1 open (classic definition)
        close_below_o1_ok = True
        if p["require_close_below_o1"]:
            close_below_o1_ok = c2 <= (o1 * (1 + p["float_tolerance"]))

        # (4) Strength of body2 vs body1
        strength_ok = body2 >= (body1 * p["strength_multiplier_vs_body1"] * (1 - p["float_tolerance"]))

        # (5) Doji avoidance via body ratios (if ranges given)
        body_ratio1_ok = True
        body_ratio2_ok = True
        effective_min_body_ratio2 = p["min_body_ratio2"]
        body2_atr_scaler = None

        if price_range1 is not None and p["min_body_ratio1"] is not None:
            body_ratio1 = body1 / price_range1
            body_ratio1_ok = body_ratio1 >= (p["min_body_ratio1"] * (1 - p["float_tolerance"]))
        else:
            body_ratio1 = None

        if price_range2 is not None and p["min_body_ratio2"] is not None:
            body_ratio2 = body2 / price_range2
            # ATR-based adaptation for min body2 ratio
            if atr is not None and atr > 0.0:
                lo, hi = p["body2_atr_bounds"]
                if hi < lo: lo, hi = hi, lo
                body2_atr_scaler = p["body2_atr_alpha"] * (atr / price_range2)
                body2_atr_scaler = max(lo, min(hi, body2_atr_scaler))
                # Tighten min body2 requirement in high vol
                effective_min_body_ratio2 = p["min_body_ratio2"] / body2_atr_scaler
            body_ratio2_ok = body_ratio2 >= (effective_min_body_ratio2 * (1 - p["float_tolerance"]))
        else:
            body_ratio2 = None

        # (6) ATR absolute constraint for body2 (optional)
        atr_body2_ok = True
        if atr is not None and atr > 0.0 and p["min_body2_vs_atr"] is not None and p["min_body2_vs_atr"] > 0.0:
            atr_body2_ok = body2 >= (p["min_body2_vs_atr"] * atr) * (1 - p["float_tolerance"])

        is_pattern = all([
            first_bearish,
            second_bullish,
            open_below_c1_ok,
            midpoint_ok,
            close_below_o1_ok,
            strength_ok,
            body_ratio1_ok,
            body_ratio2_ok,
            atr_body2_ok,
        ])

        if not is_pattern:
            return PatternResult(is_pattern=False, name=None, bias=None, metrics=None)

        metrics = {
            # Bodies & directions
            "first_bearish": first_bearish,
            "second_bullish": second_bullish,
            "body1": body1, "body2": body2,
            "midpoint1": midpoint1,
            # Ranges & ratios
            "price_range1": price_range1,
            "price_range2": price_range2,
            "body_ratio1": (body1 / price_range1) if price_range1 else None,
            "body_ratio2": (body2 / price_range2) if price_range2 else None,
            # Core flags
            "open_below_c1_ok": open_below_c1_ok,
            "midpoint_ok": midpoint_ok,
            "close_below_o1_ok": close_below_o1_ok,
            "strength_ok": strength_ok,
            "body_ratio1_ok": body_ratio1_ok,
            "body_ratio2_ok": body_ratio2_ok,
            # ATR info
            "atr": atr,
            "body2_atr_scaler": body2_atr_scaler,
            "effective_min_body_ratio2": effective_min_body_ratio2,
            "atr_body2_ok": atr_body2_ok,
            # Echo inputs
            "o1": o1, "c1": c1, "h1": h1, "l1": l1,
            "o2": o2, "c2": c2, "h2": h2, "l2": l2,
            # Params snapshot (for logging/debug)
            "params": self.defaults | {"atr": atr} | overrides,
        }

        return PatternResult(
            is_pattern=True,
            name="Piercing Pattern",
            bias="bull",
            metrics=metrics
        )