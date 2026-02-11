from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any
from abc import ABC, abstractmethod

@dataclass
class PatternResult:
    is_pattern: bool = False
    name: Optional[str] = None
    bias: Optional[Literal["long", "short", "neutral"]] = None
    metrics: Optional[Dict[str, Any]] = None

class BasePatternUtils:
    """Helper mixin for common candle math."""
    
    @staticmethod
    def get_body(o: float, c: float) -> float:
        return abs(c - o)
    
    @staticmethod
    def get_range(h: float, l: float) -> float:
        return h - l

    @staticmethod
    def is_bullish(o: float, c: float) -> float:
        return c > o

    @staticmethod
    def get_upper_shadow(o: float, h: float, c: float) -> float:
        return h - max(o, c)

    @staticmethod
    def get_lower_shadow(o: float, l: float, c: float) -> float:
        return min(o, c) - l

class SingleCandlePatternDetector(ABC, BasePatternUtils):
    """
    Base class for single-candle patterns.
    Added previous candle context vars to signature as optional but recommended.
    """

    @abstractmethod
    def detect(
        self,
        open_: float, high: float, low: float, close: float,
        volume: Optional[float] = None,
        prev_close: Optional[float] = None, # Context is key for single patterns (e.g. Gaps)
        **kwargs
    ) -> PatternResult:
        pass


class DoubleCandlePatternDetector(ABC, BasePatternUtils):
    """
    Base class for two-candle patterns.
    explicitly requires Highs and Lows in signature.
    """

    @abstractmethod
    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        h1: float, l1: float,
        h2: float, l2: float,
        v1: Optional[float] = None, 
        v2: Optional[float] = None,
        **kwargs
    ) -> PatternResult:
        pass

class TripleCandlePatternDetector(ABC, BasePatternUtils):
    """
    Base class for three-candle patterns.
    explicitly requires Highs and Lows in signature.
    """

    @abstractmethod
    def detect(
        self,
        o1: float, c1: float,
        o2: float, c2: float,
        o3: float, c3: float,
        h1: float, l1: float,
        h2: float, l2: float,
        h3: float, l3: float,
        v1: Optional[float] = None, 
        v2: Optional[float] = None, 
        v3: Optional[float] = None,
        **kwargs
    ) -> PatternResult:
        pass
