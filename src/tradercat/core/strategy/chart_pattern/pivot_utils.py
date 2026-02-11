from typing import List, Tuple
from dataclasses import dataclass

@dataclass
class Pivot:
    index: int
    price: float
    type: str  # 'high' or 'low'

class PivotFinder:
    def __init__(self, left_bars: int = 5, right_bars: int = 5):
        self.left = left_bars
        self.right = right_bars

    def find_pivots(self, highs: List[float], lows: List[float]) -> Tuple[List[Pivot], List[Pivot]]:
        """
        Identify Swing Highs and Swing Lows based on local maxima/minima.
        """
        pivot_highs = []
        pivot_lows = []

        # We need a window of left + 1 + right bars
        # The pivot candidate is at index i
        for i in range(self.left, len(highs) - self.right):
            window_h = highs[i - self.left : i + self.right + 1]
            window_l = lows[i - self.left : i + self.right + 1]

            if highs[i] == max(window_h):
                pivot_highs.append(Pivot(i, highs[i], 'high'))

            if lows[i] == min(window_l):
                pivot_lows.append(Pivot(i, lows[i], 'low'))

        return pivot_highs, pivot_lows