from typing import List, Optional, Dict, Any
from trade_bot.strategy.candle_pattern.pattern_detector import (
    PatternResult,
    SingleCandlePatternDetector,
    DoubleCandlePatternDetector,
    TripeCandlePatternDetector,
)

# Single-candle
from trade_bot.strategy.candle_pattern.detectors.neutral_standard_doji import StandardDojiDetector
from trade_bot.strategy.candle_pattern.detectors.bullish_hammer import HammerDetector
from trade_bot.strategy.candle_pattern.detectors.bearish_shooting_star import ShootingStarDetector
from trade_bot.strategy.candle_pattern.detectors.neutral_spinning_top import SpinningTopDetector
from trade_bot.strategy.candle_pattern.detectors.neutral_dragonfly_doji import DragonflyDojiDetector
from trade_bot.strategy.candle_pattern.detectors.neutral_gravestone_doji import GravestoneDojiDetector

# Double-candle
from trade_bot.strategy.candle_pattern.detectors.bullish_engulfing import BullishEngulfingDetector
from trade_bot.strategy.candle_pattern.detectors.bearish_engulfing import BearishEngulfingDetector
from trade_bot.strategy.candle_pattern.detectors.bullish_harami import BullishHaramiDetector
from trade_bot.strategy.candle_pattern.detectors.bearish_harami import BearishHaramiDetector
from trade_bot.strategy.candle_pattern.detectors.bullish_piercing import PiercingPatternDetector
from trade_bot.strategy.candle_pattern.detectors.bearish_dark_cloud_cover import DarkCloudCoverDetector
from trade_bot.strategy.candle_pattern.detectors.bullish_tweezer_bottom import TweezerBottomDetector
from trade_bot.strategy.candle_pattern.detectors.bearish_tweezer_top import TweezerTopDetector

# Triple-candle
from trade_bot.strategy.candle_pattern.detectors.bullish_morning_star import MorningStarDetector
from trade_bot.strategy.candle_pattern.detectors.bearish_evening_star import EveningStarDetector
from trade_bot.strategy.candle_pattern.detectors.bullish_three_white_soldiers import ThreeWhiteSoldiersDetector
from trade_bot.strategy.candle_pattern.detectors.bearish_three_black_crows import ThreeBlackCrowsDetector

def _first_match(results: List[PatternResult]) -> PatternResult:
    """Return the first PatternResult that is a pattern."""
    for r in results:
        if r and r.is_pattern:
            return r
    return PatternResult(False, None, None, None)

class PatternDetectorsOrchestrator:
    """
    Priority-driven pattern orchestrator that tries single-, double-, triple-candle detectors
    for bullish and bearish flows. ATR and trend flags can be passed through as overrides.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        # Instantiate detectors once (state-less; params can be overridden per call)
        # --- Bullish single ---
        self.bullish_single: List[SingleCandlePatternDetector] = [
            HammerDetector(),            # typical bullish single
            StandardDojiDetector(),         # neutral; included to match your legacy priority
            DragonflyDojiDetector(),      # bullish-leaning
            SpinningTopDetector(),        # neutral
        ]

        # --- Bearish single ---
        self.bearish_single: List[SingleCandlePatternDetector] = [
            ShootingStarDetector(),       # typical bearish single
            StandardDojiDetector(),
            GravestoneDojiDetector(),     # bearish-leaning
            SpinningTopDetector(),
        ]

        # --- Bullish double ---
        self.bullish_double: List[DoubleCandlePatternDetector] = [
            BullishEngulfingDetector(),
            PiercingPatternDetector(),
            BullishHaramiDetector(),
            TweezerBottomDetector(),        # requires lows via kwargs
        ]

        # --- Bearish double ---
        self.bearish_double: List[DoubleCandlePatternDetector] = [
            BearishEngulfingDetector(),
            DarkCloudCoverDetector(),
            BearishHaramiDetector(),
            TweezerTopDetector(),           # requires highs via kwargs
        ]

        # --- Bullish triple ---
        self.bullish_triple: List[TripeCandlePatternDetector] = [
            MorningStarDetector(),
            ThreeWhiteSoldiersDetector(),
        ]

        # --- Bearish triple ---
        self.bearish_triple: List[TripeCandlePatternDetector] = [
            EveningStarDetector(),
            ThreeBlackCrowsDetector(),
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
        single -> double -> triple.
        `trend_ok` (if provided) can be used by detectors that want trend context.
        """
        overrides = {"atr": atr}
        if trend_ok is not None:
            overrides["trend_ok"] = trend_ok
        if extra_overrides:
            overrides.update(extra_overrides)

        results: List[PatternResult] = []

        # Single-candle
        if idx >= 0:
            for det in self.bullish_single:
                r = det.detect(
                    opens[idx], highs[idx], lows[idx], closes[idx],
                    **overrides
                )
                if r.is_pattern:
                    results.append(r)
                    break  # stop at first match by priority

        # Double-candle
        if not _first_match(results).is_pattern and idx >= 1:
            for det in self.bullish_double:
                # Detectors that need highs/lows can read them via kwargs
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

        # Triple-candle
        if not _first_match(results).is_pattern and idx >= 2:
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
        single -> double -> triple.
        """
        overrides = {"atr": atr}
        if trend_ok is not None:
            overrides["trend_ok"] = trend_ok
        if extra_overrides:
            overrides.update(extra_overrides)

        results: List[PatternResult] = []

        # Single-candle
        if idx >= 0:
            for det in self.bearish_single:
                r = det.detect(
                    opens[idx], highs[idx], lows[idx], closes[idx],
                    **overrides
                )
                if r.is_pattern:
                    results.append(r)
                    break

        # Double-candle
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

        # Triple-candle
        if not _first_match(results).is_pattern and idx >= 2:
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

        return _first_match(results)

