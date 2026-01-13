from typing import Optional
from .base_detector import ChartPatternDetector, ChartData, PatternResult

class AscendingTriangleDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        """
        Ascending Triangle (Bullish): Flat Top + Rising Lows.
        """
        if len(data.pivots_high) < 2 or len(data.pivots_low) < 2: return None
        
        h1, h2 = data.pivots_high[-2], data.pivots_high[-1]
        if not self._is_price_similar(h1.price, h2.price): return None
        resistance = (h1.price + h2.price) / 2
        
        l1, l2 = data.pivots_low[-2], data.pivots_low[-1]
        # l2 should be higher than l1
        if not (l2.price > l1.price * (1 + self.tol)): return None
        if l2.price >= resistance: return None # Invalid geometry
        
        if data.current_close > resistance:
            height = resistance - l1.price
            return PatternResult(
                name="Ascending Triangle", bias="long", 
                stop=l2.price, target=resistance + height
            )
        return None

class DescendingTriangleDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        """
        Descending Triangle (Bearish): Flat Bottom + Falling Highs.
        """
        if len(data.pivots_low) < 2 or len(data.pivots_high) < 2: return None
        
        l1, l2 = data.pivots_low[-2], data.pivots_low[-1]
        if not self._is_price_similar(l1.price, l2.price): return None
        support = (l1.price + l2.price) / 2
        
        h1, h2 = data.pivots_high[-2], data.pivots_high[-1]
        if not (h2.price < h1.price * (1 - self.tol)): return None
        if h2.price <= support: return None
        
        if data.current_close < support:
            height = h1.price - support
            return PatternResult(
                name="Descending Triangle", bias="short", 
                stop=h2.price, target=support - height
            )
        return None

class BullFlagDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        """
        Bull Flag (Simplified logic using raw history, not pivots).
        Pole -> Consolidation -> Breakout
        
        Note: The pivot lists are prefixed with '_' to indicate they are unused in this specific
        implementation, as Flags require denser, raw price data rather than sparse pivots.
        """
        # Cleanly access raw data needed for flags
        highs = data.highs_history
        lows = data.lows_history
        atr = data.atr
        
        if not highs or not lows or atr <= 0: return None
        
        lookback = 20
        if len(highs) < lookback: return None
        
        recent_highs = highs[-lookback:]
        recent_lows = lows[-lookback:]
        
        # 1. Pole
        start_price = recent_lows[0]
        peak_price = max(recent_highs[:10])
        pole_height = peak_price - start_price
        
        if pole_height < (3 * atr): return None
        
        # 2. Flag
        flag_low = min(recent_lows[10:])
        retracement = (peak_price - flag_low) / pole_height
        
        if not (0.1 < retracement < 0.5): return None
            
        # 3. Breakout
        consolidation_high = max(recent_highs[-5:-1])
        if data.current_close > consolidation_high:
            return PatternResult(
                name="Bull Flag", bias="long",
                stop=flag_low, target=data.current_close + pole_height
            )
        return None