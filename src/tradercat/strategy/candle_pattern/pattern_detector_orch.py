from typing import List, Optional, Dict, Any
from tradercat.strategy.candle_pattern.pattern_detector import (
    PatternResult,
    SingleCandlePatternDetector,
    DoubleCandlePatternDetector,
    TripleCandlePatternDetector,
)

# Single-candle
from tradercat.strategy.candle_pattern.detectors.neutral_standard_doji import StandardDojiDetector
from tradercat.strategy.candle_pattern.detectors.bullish_hammer import HammerDetector
from tradercat.strategy.candle_pattern.detectors.bearish_shooting_star import ShootingStarDetector
from tradercat.strategy.candle_pattern.detectors.neutral_spinning_top import SpinningTopDetector
from tradercat.strategy.candle_pattern.detectors.bullish_dragonfly_doji import DragonflyDojiDetector
from tradercat.strategy.candle_pattern.detectors.bearish_gravestone_doji import GravestoneDojiDetector

# Double-candle
from tradercat.strategy.candle_pattern.detectors.bullish_engulfing import BullishEngulfingDetector
from tradercat.strategy.candle_pattern.detectors.bearish_engulfing import BearishEngulfingDetector
from tradercat.strategy.candle_pattern.detectors.bullish_harami import BullishHaramiDetector
from tradercat.strategy.candle_pattern.detectors.bearish_harami import BearishHaramiDetector
from tradercat.strategy.candle_pattern.detectors.bullish_piercing import PiercingPatternDetector
from tradercat.strategy.candle_pattern.detectors.bearish_dark_cloud_cover import DarkCloudCoverDetector
from tradercat.strategy.candle_pattern.detectors.bullish_tweezer_bottom import TweezerBottomDetector
from tradercat.strategy.candle_pattern.detectors.bearish_tweezer_top import TweezerTopDetector

# Triple-candle
from tradercat.strategy.candle_pattern.detectors.bullish_morning_star import MorningStarDetector
from tradercat.strategy.candle_pattern.detectors.bearish_evening_star import EveningStarDetector
from tradercat.strategy.candle_pattern.detectors.bullish_three_white_soldiers import ThreeWhiteSoldiersDetector
from tradercat.strategy.candle_pattern.detectors.bearish_three_black_crows import ThreeBlackCrowsDetector

def _first_match(results: List[PatternResult]) -> PatternResult:
    """Return the first PatternResult that is a pattern."""
    for r in results:
        if r and r.is_pattern:
            return r
    return PatternResult(False, None, None, None)

class PatternDetectorsOrchestrator:
    """
    Priority-driven pattern orchestrator.
    
    OPTIMIZATION:
    1. Priority Order: Triple -> Double -> Single. 
    (Complex patterns are stronger and contain simpler ones).
    2. Params: Initialized with 'Production Grade' strictness to reduce noise.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        # ==========================================
        # 1. TRIPLE CANDLE PATTERNS (Highest Priority)
        # ==========================================
        
        self.bullish_triple: List[TripleCandlePatternDetector] = [
            MorningStarDetector(),
            ThreeWhiteSoldiersDetector(),
        ]

        self.bearish_triple: List[TripleCandlePatternDetector] = [
            EveningStarDetector(),
            ThreeBlackCrowsDetector(),
        ]

        # ==========================================
        # 2. DOUBLE CANDLE PATTERNS (Medium Priority)
        # ==========================================

        self.bullish_double: List[DoubleCandlePatternDetector] = [
            BullishEngulfingDetector(),
            PiercingPatternDetector(),
            TweezerBottomDetector(),
            BullishHaramiDetector(),
        ]

        self.bearish_double: List[DoubleCandlePatternDetector] = [
            BearishEngulfingDetector(),
            DarkCloudCoverDetector(),
            TweezerTopDetector(),
            BearishHaramiDetector(),
        ]

        # ==========================================
        # 3. SINGLE CANDLE PATTERNS (Lowest Priority)
        # ==========================================
        
        self.bullish_single: List[SingleCandlePatternDetector] = [
            HammerDetector(),
            DragonflyDojiDetector(),
            StandardDojiDetector(),
            SpinningTopDetector(),
        ]

        self.bearish_single: List[SingleCandlePatternDetector] = [
            ShootingStarDetector(),
            GravestoneDojiDetector(),
            StandardDojiDetector(),
            SpinningTopDetector(),
        ]

    # -------------------------
    # Public API
    # -------------------------
    def detect_bullish(
        self,
        opens: List[float],
        highs: List[float],
        lows: List[float],
        closes: List[float],
        idx: int,
        *,
        atr: Optional[float] = None,
        trend_ok: Optional[bool] = None,
        extra_overrides: Optional[Dict[str, Any]] = None,
    ) -> PatternResult:
        """
        Detect bullish pattern at index `idx` with priority:
        TRIPLE -> DOUBLE -> SINGLE.
        """
        overrides = {"atr": atr}
        if trend_ok is not None:
            overrides["trend_ok"] = trend_ok
        if extra_overrides:
            overrides.update(extra_overrides)

        results: List[PatternResult] = []

        # 1. Triple-candle (Strongest)
        if idx >= 2:
            for det in self.bullish_triple:
                r = det.detect(
                    opens[idx - 2], closes[idx - 2],
                    opens[idx - 1], closes[idx - 1],
                    opens[idx],     closes[idx],
                    h1=highs[idx - 2], l1=lows[idx - 2],
                    h2=highs[idx - 1], l2=lows[idx - 1],
                    h3=highs[idx],     l3=lows[idx],
                    **overrides
                )
                if r.is_pattern:
                    results.append(r)
                    break # Priority match found

        # 2. Double-candle
        if not _first_match(results).is_pattern and idx >= 1:
            for det in self.bullish_double:
                r = det.detect(
                    opens[idx - 1], closes[idx - 1],
                    opens[idx], closes[idx],
                    h1=highs[idx - 1], l1=lows[idx - 1],
                    h2=highs[idx],     l2=lows[idx],
                    **overrides
                )
                if r.is_pattern:
                    results.append(r)
                    break

        # 3. Single-candle (Weakest)
        if not _first_match(results).is_pattern and idx >= 0:
            for det in self.bullish_single:
                r = det.detect(
                    opens[idx], highs[idx], lows[idx], closes[idx],
                    **overrides
                )
                if r.is_pattern:
                    results.append(r)
                    break

        return _first_match(results)

    def detect_bearish(
        self,
        opens: List[float],
        highs: List[float],
        lows: List[float],
        closes: List[float],
        idx: int,
        *,
        atr: Optional[float] = None,
        trend_ok: Optional[bool] = None,
        extra_overrides: Optional[Dict[str, Any]] = None,
    ) -> PatternResult:
        """
        Detect bearish pattern at index `idx` with priority:
        TRIPLE -> DOUBLE -> SINGLE.
        """
        overrides = {"atr": atr}
        if trend_ok is not None:
            overrides["trend_ok"] = trend_ok
        if extra_overrides:
            overrides.update(extra_overrides)

        results: List[PatternResult] = []

        # 1. Triple-candle
        if idx >= 2:
            for det in self.bearish_triple:
                r = det.detect(
                    opens[idx - 2], closes[idx - 2],
                    opens[idx - 1], closes[idx - 1],
                    opens[idx],     closes[idx],
                    h1=highs[idx - 2], l1=lows[idx - 2],
                    h2=highs[idx - 1], l2=lows[idx - 1],
                    h3=highs[idx],     l3=lows[idx],
                    **overrides
                )
                if r.is_pattern:
                    results.append(r)
                    break

        # 2. Double-candle
        if not _first_match(results).is_pattern and idx >= 1:
            for det in self.bearish_double:
                r = det.detect(
                    opens[idx - 1], closes[idx - 1],
                    opens[idx],     closes[idx],
                    h1=highs[idx - 1], l1=lows[idx - 1],
                    h2=highs[idx],     l2=lows[idx],
                    **overrides
                )
                if r.is_pattern:
                    results.append(r)
                    break

        # 3. Single-candle
        if not _first_match(results).is_pattern and idx >= 0:
            for det in self.bearish_single:
                r = det.detect(
                    opens[idx], highs[idx], lows[idx], closes[idx],
                    **overrides
                )
                if r.is_pattern:
                    results.append(r)
                    break

        return _first_match(results)

