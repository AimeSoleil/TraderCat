from typing import Optional
from .base_detector import ChartPatternDetector, ChartData, PatternResult


class DoubleBottomDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        l_pivots, h_pivots = data.pivots_low, data.pivots_high

        if len(l_pivots) < 2 or len(h_pivots) < 1:
            return None
        l1, l2 = l_pivots[-2], l_pivots[-1]

        # 1. Logic Check: Time Spacing (Veto "Zombie Patterns")
        width = l2.index - l1.index
        if width < 5:
            return None  # Too tight (V-shape, not W)
        if width > 100:
            return None  # Too wide (structure lost relevance)

        neck_candidates = [h for h in h_pivots if l1.index < h.index < l2.index]
        if not neck_candidates:
            return None
        neck_pivot = max(neck_candidates, key=lambda p: p.price)

        # 2. Logic Check: Level Bottoms
        if not self._is_price_similar(l1.price, l2.price):
            return None

        avg_bottom = (l1.price + l2.price) / 2
        pattern_height = neck_pivot.price - avg_bottom

        # 3. Logic Check: Minimal Depth (Filter noise)
        # Pattern must be at least 2*ATR deep (volatility based) or 1% if ATR missing
        if pattern_height < (2 * data.atr if data.atr else avg_bottom * 0.01):
            return None

        if data.current_close > neck_pivot.price:
            return PatternResult(
                name="Double Bottom",
                bias="long",
                stop=min(l1.price, l2.price),
                target=neck_pivot.price + pattern_height,
            )
        return None


class DoubleTopDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        l_pivots, h_pivots = data.pivots_low, data.pivots_high

        if len(h_pivots) < 2 or len(l_pivots) < 1:
            return None
        h1, h2 = h_pivots[-2], h_pivots[-1]

        # 1. Time Spacing
        width = h2.index - h1.index
        if width < 5 or width > 100:
            return None

        neck_candidates = [l for l in l_pivots if h1.index < l.index < h2.index]
        if not neck_candidates:
            return None
        neck_pivot = min(neck_candidates, key=lambda p: p.price)

        # 2. Logic Check: Level Tops
        if not self._is_price_similar(h1.price, h2.price):
            return None

        avg_top = (h1.price + h2.price) / 2
        pattern_height = avg_top - neck_pivot.price

        # 3. Minimal Depth
        # Use ATR priority for robustness
        if pattern_height < (2 * data.atr if data.atr else neck_pivot.price * 0.01):
            return None

        if data.current_close < neck_pivot.price:
            return PatternResult(
                name="Double Top",
                bias="short",
                stop=max(h1.price, h2.price),
                target=neck_pivot.price - pattern_height,
            )
        return None


class TripleBottomDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        l_pivots = data.pivots_low

        if len(l_pivots) < 3:
            return None
        l1, l2, l3 = l_pivots[-3], l_pivots[-2], l_pivots[-1]

        # 1. Time Check
        total_width = l3.index - l1.index
        if total_width > 120 or total_width < 10:
            return None

        avg_low = (l1.price + l2.price + l3.price) / 3
        if not (
            self._is_price_similar(l1.price, avg_low)
            and self._is_price_similar(l2.price, avg_low)
            and self._is_price_similar(l3.price, avg_low)
        ):
            return None

        highs_in_between = [
            h for h in data.pivots_high if l1.index < h.index < l3.index
        ]
        if not highs_in_between:
            return None
        resistance_level = max(h.price for h in highs_in_between)

        pattern_height = resistance_level - avg_low
        # 3. Minimal Depth Check
        if pattern_height < (2 * data.atr if data.atr else avg_low * 0.01):
            return None

        if data.current_close > resistance_level:
            return PatternResult(
                name="Triple Bottom",
                bias="long",
                stop=avg_low,
                target=resistance_level + pattern_height,
            )
        return None


class HeadAndShouldersTopDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        """
        Bearish Reversal: LS (High) -> Head (Higher) -> RS (High)
        """
        if len(data.pivots_high) < 3:
            return None
        ls, h, rs = data.pivots_high[-3], data.pivots_high[-2], data.pivots_high[-1]

        # 1. Basic Geometry: Head must be highest
        if not (h.price > ls.price and h.price > rs.price):
            return None

        # 2. Logic Check: Shoulder Symmetry (Crucial!)
        # Shoulders should be roughly same height. If RS is waaaay lower, it's just a downtrend.
        # We allow a slightly looser tolerance (e.g. 10%) for shoulder comparison than for double tops.
        shoulder_diff_pct = abs(ls.price - rs.price) / ls.price
        if shoulder_diff_pct > 0.10:
            return None

        # 3. Time Check
        if (rs.index - ls.index) > 120:
            return None

        lows_between = [p for p in data.pivots_low if ls.index < p.index < rs.index]
        if not lows_between:
            return None
        # Valid Neckline is usually the line connecting the two reaction lows
        # Use simple horizontal support level (min of the lows) for robustness
        neckline = min(p.price for p in lows_between)

        pattern_height = h.price - neckline
        # 4. Minimal Depth Check
        if pattern_height < (2 * data.atr if data.atr else h.price * 0.01):
            return None

        if data.current_close < neckline:
            return PatternResult(
                name="Head & Shoulders Top",
                bias="short",
                stop=h.price,  # Stop above Head is safest, or above RS for tighter risk
                target=neckline - pattern_height,
            )
        return None


class HeadAndShouldersBottomDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        """
        Bullish Reversal: LS (Low) -> Head (Lower) -> RS (Low)
        """
        if len(data.pivots_low) < 3:
            return None
        ls, h, rs = data.pivots_low[-3], data.pivots_low[-2], data.pivots_low[-1]

        # 1. Basic Geometry
        if not (h.price < ls.price and h.price < rs.price):
            return None

        # 2. Shoulder Symmetry
        shoulder_diff_pct = abs(ls.price - rs.price) / ls.price
        if shoulder_diff_pct > 0.10:
            return None

        # 3. Time Check
        if (rs.index - ls.index) > 120:
            return None

        highs_between = [p for p in data.pivots_high if ls.index < p.index < rs.index]
        if not highs_between:
            return None
        neckline = max(p.price for p in highs_between)

        pattern_height = neckline - h.price
        # 4. Minimal Depth Check
        if pattern_height < (2 * data.atr if data.atr else h.price * 0.01):
            return None

        if data.current_close > neckline:
            return PatternResult(
                name="Inv. Head & Shoulders",
                bias="long",
                stop=rs.price,
                target=neckline + pattern_height,
            )
        return None
