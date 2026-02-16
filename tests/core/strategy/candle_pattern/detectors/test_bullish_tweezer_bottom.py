import unittest
from tradercat.core.strategy.candle_pattern.detectors.bullish_tweezer_bottom import TweezerBottomDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestTweezerBottom(unittest.TestCase):
    def setUp(self):
        self.detector = TweezerBottomDetector()

    def test_detect_valid_pattern(self):
        """
        Test Tweezer Bottom:
        Day 1: Bearish
        Day 2: Bullish
        Lows are very close.
        """
        candles = [
            MockCandle(100, 105, 90, 95),   # Day 1: Bearish, Low 90
            MockCandle(92, 100, 90.05, 98)  # Day 2: Bullish, Low 90.05 (Close to 90)
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low)
        self.assertTrue(result.is_pattern, "Should detect valid Tweezer Bottom")

    def test_detect_invalid_lows(self):
        """
        Test Invalid Lows:
        Lows are not close enough.
        """
        candles = [
            MockCandle(100, 105, 90, 95),   # Day 1: Low 90
            MockCandle(92, 100, 85, 98)     # Day 2: Low 85 (Too far)
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low)
        self.assertFalse(result.is_pattern, "Should NOT detect if lows are different")
