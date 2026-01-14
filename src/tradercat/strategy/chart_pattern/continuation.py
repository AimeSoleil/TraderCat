from typing import Optional
from .base_detector import ChartPatternDetector, ChartData, PatternResult

class AscendingTriangleDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        """
        Ascending Triangle (Bullish): Flat Top + Rising Lows.
        Structure: L1 -> H1 -> L2 -> H2 (Breakout)
        """
        if len(data.pivots_high) < 2 or len(data.pivots_low) < 2:
            return None

        # Get last 2 of each
        h1, h2 = data.pivots_high[-2], data.pivots_high[-1]
        l1, l2 = data.pivots_low[-2], data.pivots_low[-1]

        # 1. Logic: Time Ordering / Recency Check
        # Ensure the pattern is compact. The first point (L1) shouldn't be ancient.
        # Also, check interleaving roughly: The last Low (L2) should be somewhat recent relative to Last High.
        # Strict interleaving (L1<H1<L2<H2) is ideal, but market noise makes it hard.
        # We ensure the whole pattern is within typically 50 bars
        latest_idx = max(h2.index, l2.index)
        earliest_idx = min(h1.index, l1.index)
        if (latest_idx - earliest_idx) > 60:
            return None  # Pattern too stretched

        # 2. Logic: Flat Top (Resistance)
        if not self._is_price_similar(h1.price, h2.price):
            return None
        resistance = (h1.price + h2.price) / 2

        # 3. Logic: Rising Lows (Support Slope)
        # Use a small epsilon or slope calculation. "1 + tol" (e.g. 1.03) is too strict for slope.
        # We just need L2 to be visibly higher than L1.
        if l2.price <= l1.price * 1.005:
            return None

        # 4. Geometry: Triangle must converge (L2 should be below Resistance)
        if l2.price >= resistance:
            return None

        # 5. Breakout
        if data.current_close > resistance:
            height = resistance - l1.price
            return PatternResult(
                name="Ascending Triangle",
                bias="long",
                stop=l2.price,
                target=resistance + height,
            )
        return None


class DescendingTriangleDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        """
        Descending Triangle (Bearish): Flat Bottom + Falling Highs.
        """
        if len(data.pivots_low) < 2 or len(data.pivots_high) < 2:
            return None

        l1, l2 = data.pivots_low[-2], data.pivots_low[-1]
        h1, h2 = data.pivots_high[-2], data.pivots_high[-1]

        # 1. Time Check
        latest_idx = max(h2.index, l2.index)
        earliest_idx = min(h1.index, l1.index)
        if (latest_idx - earliest_idx) > 60:
            return None

        # 2. Flat Bottom (Support)
        if not self._is_price_similar(l1.price, l2.price):
            return None
        support = (l1.price + l2.price) / 2

        # 3. Falling Highs
        if h2.price >= h1.price * 0.995:
            return None

        # 4. Geometry
        if h2.price <= support:
            return None

        # 5. Breakout
        if data.current_close < support:
            height = h1.price - support
            return PatternResult(
                name="Descending Triangle",
                bias="short",
                stop=h2.price,
                target=support - height,
            )
        return None


class BullFlagDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        """
        Bull Flag: Dynamic detection.
        Finds the highest point in lookback window -> That's the pole tip.
        Before tip = Pole (Impulse). After tip = Flag (Consolidation).
        """
        highs = data.highs_history
        lows = data.lows_history
        atr = data.atr

        lookback = 20
        if not highs or len(highs) < lookback or atr <= 0:
            return None

        # Slice recent data
        rec_h = highs[-lookback:]
        rec_l = lows[-lookback:]

        # 1. Find the Peak (The top of the flag pole) dynamically
        # We need the peak to be at least some bars away from start and end
        # to ensure we have a pole before it and a flag after it.
        peak_val = -1.0
        peak_idx = -1

        for i, val in enumerate(rec_h):
            if val > peak_val:
                peak_val = val
                peak_idx = i

        # Constraints:
        # Pole needs at least 3 bars (idx > 2)
        # Flag needs at least 3 bars (idx < len - 3)
        if peak_idx < 3 or peak_idx > (lookback - 3):
            return None

        # 2. Analyze Pole (Start to Peak)
        pole_start = min(rec_l[:peak_idx])  # Lowest low before peak
        pole_height = peak_val - pole_start

        # Filter: Pole must be significant (Impulse move)
        if pole_height < (3 * atr):
            return None

        # 3. Analyze Flag (Peak to Now)
        flag_lows = rec_l[peak_idx:]
        flag_highs = rec_h[peak_idx:]
        flag_min = min(flag_lows)

        # Retracement Check (Fibonacci-ish logic)
        retracement = peak_val - flag_min
        retracement_pct = retracement / pole_height

        # Flag should retrace between 10% and 50% (strong trend)
        if not (0.1 < retracement_pct < 0.5):
            return None

        # 4. Breakout
        # Define resistance as the trendline or max of the consolidation
        # Simple approach: Max of the flag period (excluding the peak itself)
        flag_resistance = (
            max(flag_highs[1:]) if len(flag_highs) > 1 else max(flag_highs)
        )

        if data.current_close > flag_resistance:
            return PatternResult(
                name="Bull Flag",
                bias="long",
                stop=flag_min,
                target=data.current_close + pole_height,
            )
        return None


class BearFlagDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        """
        Bear Flag: Inverted Bull Flag logic.
        Pole Down -> Consolidation Up -> Breakout Down.
        """
        highs = data.highs_history
        lows = data.lows_history
        atr = data.atr
        lookback = 20

        if not highs or len(highs) < lookback or atr <= 0:
            return None

        rec_h = highs[-lookback:]
        rec_l = lows[-lookback:]

        # 1. Find the Bottom (Tip of upside down pole)
        bottom_val = float("inf")
        bottom_idx = -1

        for i, val in enumerate(rec_l):
            if val < bottom_val:
                bottom_val = val
                bottom_idx = i

        if bottom_idx < 3 or bottom_idx > (lookback - 3):
            return None

        # 2. Pole (High to Low)
        pole_start = max(rec_h[:bottom_idx])
        pole_height = pole_start - bottom_val

        if pole_height < (3 * atr):
            return None

        # 3. Flag (Consolidation Up)
        flag_max = max(rec_h[bottom_idx:])
        retracement = flag_max - bottom_val
        retracement_pct = retracement / pole_height

        if not (0.1 < retracement_pct < 0.5):
            return None

        # 4. Breakout Check
        # Breakdown acts below the consolidation lows
        flag_support = (
            min(rec_l[bottom_idx:][1:])
            if len(rec_l[bottom_idx:]) > 1
            else min(rec_l[bottom_idx:])
        )

        if data.current_close < flag_support:
            return PatternResult(
                name="Bear Flag",
                bias="short",
                stop=flag_max,
                target=data.current_close - pole_height,
            )
        return None
