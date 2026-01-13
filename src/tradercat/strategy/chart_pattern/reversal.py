from typing import List, Optional, Dict, Any
from .base_detector import ChartPatternDetector, ChartData, PatternResult

class DoubleBottomDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        # Access pivots from the data object
        l_pivots, h_pivots = data.pivots_low, data.pivots_high
        
        if len(l_pivots) < 2 or len(h_pivots) < 1: return None
        l1, l2 = l_pivots[-2], l_pivots[-1]
        
        neck_candidates = [h for h in h_pivots if l1.index < h.index < l2.index]
        if not neck_candidates: return None
        neck_pivot = max(neck_candidates, key=lambda p: p.price)
        
        if not self._is_price_similar(l1.price, l2.price): return None
        
        pattern_height = neck_pivot.price - (l1.price + l2.price)/2
        if pattern_height <= 0: return None

        if data.current_close > neck_pivot.price:
            return PatternResult(
                name="Double Bottom",
                bias="long",
                stop=min(l1.price, l2.price),
                target=neck_pivot.price + pattern_height
            )
        return None

class DoubleTopDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        l_pivots, h_pivots = data.pivots_low, data.pivots_high

        if len(h_pivots) < 2 or len(l_pivots) < 1: return None
        h1, h2 = h_pivots[-2], h_pivots[-1]
        
        neck_candidates = [l for l in l_pivots if h1.index < l.index < h2.index]
        if not neck_candidates: return None
        neck_pivot = min(neck_candidates, key=lambda p: p.price)
        
        if not self._is_price_similar(h1.price, h2.price): return None
        
        pattern_height = (h1.price + h2.price)/2 - neck_pivot.price
        if pattern_height <= 0: return None

        if data.current_close < neck_pivot.price:
            return PatternResult(
                name="Double Top",
                bias="short",
                stop=max(h1.price, h2.price),
                target=neck_pivot.price - pattern_height
            )
        return None

class TripleBottomDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        l_pivots = data.pivots_low
        
        if len(l_pivots) < 3: return None
        l1, l2, l3 = l_pivots[-3], l_pivots[-2], l_pivots[-1]
        
        avg_low = (l1.price + l2.price + l3.price) / 3
        if not (self._is_price_similar(l1.price, avg_low) and 
                self._is_price_similar(l2.price, avg_low) and 
                self._is_price_similar(l3.price, avg_low)):
            return None
            
        highs_in_between = [h for h in data.pivots_high if l1.index < h.index < l3.index]
        if not highs_in_between: return None
        resistance_level = max(h.price for h in highs_in_between)
        
        if data.current_close > resistance_level:
            height = resistance_level - avg_low
            return PatternResult(
                name="Triple Bottom",
                bias="long",
                stop=avg_low,
                target=resistance_level + height
            )
        return None

class HeadAndShouldersTopDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        if len(data.pivots_high) < 3: return None
        ls, h, rs = data.pivots_high[-3], data.pivots_high[-2], data.pivots_high[-1]
        
        if not (h.price > ls.price and h.price > rs.price): return None
        
        lows_between = [p for p in data.pivots_low if ls.index < p.index < rs.index]
        if not lows_between: return None
        neckline = min(p.price for p in lows_between)
        
        if data.current_close < neckline:
            height = h.price - neckline
            return PatternResult(
                name="Head & Shoulders Top", bias="short", 
                stop=rs.price, target=neckline - height
            )
        return None

class HeadAndShouldersBottomDetector(ChartPatternDetector):
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        if len(data.pivots_low) < 3: return None
        ls, h, rs = data.pivots_low[-3], data.pivots_low[-2], data.pivots_low[-1]
        
        if not (h.price < ls.price and h.price < rs.price): return None
        highs_between = [p for p in data.pivots_high if ls.index < p.index < rs.index]
        if not highs_between: return None
        neckline = max(p.price for p in highs_between)
        
        if data.current_close > neckline:
            height = neckline - h.price
            return PatternResult(
                name="Inv. Head & Shoulders", bias="long", 
                stop=rs.price, target=neckline + height
            )
        return None