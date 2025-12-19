
from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any
from abc import ABC, abstractmethod

@dataclass
class PatternResult:
    is_pattern: bool = False
    name: Optional[str] = None
    bias: Optional[Literal["long", "short", "neutral"]] = None
    metrics: Optional[Dict[str, Any]] = None


class SingleCandlePatternDetector(ABC):
    """Base class for single-candle patterns (Doji, Hammer, Spinning Top, etc.)."""

    @abstractmethod
    def detect(
        self,
        open_: float,
        high: float,
        low: float,
        close: float,
        **kwargs
    ) -> PatternResult:
        """Return PatternResult; kwargs are keyword-only overrides for detector parameters."""
        pass


class DoubleCandlePatternDetector(ABC):
    """Base class for two-candle patterns (Engulfing, Harami, etc.)."""

    @abstractmethod
    def detect(
        self,
        o1: float, c1: float, o2: float, c2: float,
        **kwargs
    ) -> PatternResult:
        """Return PatternResult; kwargs are keyword-only overrides for detector parameters."""
        pass

class TripleCandlePatternDetector(ABC):
    """Base class for three-candle patterns (morning star)."""

    @abstractmethod
    def detect(
        self,
        o1: float, c1: float, o2: float, c2: float, o3: float, c3: float,
        **kwargs
    ) -> PatternResult:
        """Return PatternResult; kwargs are keyword-only overrides for detector parameters."""
        pass
