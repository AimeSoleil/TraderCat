from typing import List, Literal, Optional, Dict, Any
from abc import ABC, abstractmethod
from dataclasses import dataclass
from .pivot_utils import Pivot

@dataclass
class ChartData:
    """
    Encapsulates all necessary market data for pattern detection.
    This acts as a 'Context Object' to prevent messy argument signatures.
    """
    current_close: float
    pivots_high: List[Pivot]
    pivots_low: List[Pivot]
    highs_history: List[float] # Raw history for flags/pennants
    lows_history: List[float]  # Raw history
    atr: float = 0.0

@dataclass
class PatternResult:
    """
    Standardized output for a detected pattern.
    """
    name: str
    bias: Literal["long", "short", "neutral"]
    stop: float
    target: float
    # Optional metadata
    confidence: float = 0.8
    meta: Optional[Dict[str, Any]] = None

class ChartPatternDetector(ABC):
    def __init__(self, price_tolerance: float = 0.03, slope_tolerance: float = 0.1):
        self.tol = price_tolerance
        self.slope_tol = slope_tolerance

    def _is_price_similar(self, p1: float, p2: float) -> bool:
        """Returns True if p2 is within tolerance % of p1."""
        if p1 == 0: return False
        return abs(p1 - p2) / p1 <= self.tol

    @abstractmethod
    def detect(self, data: ChartData) -> Optional[PatternResult]:
        """
        Attempts to detect a pattern using the provided ChartData context.
        """
        pass