import unittest
from tradercat.core.strategy.candle_pattern.detectors.bearish_engulfing import BearishEngulfingDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestBearishEngulfing(unittest.TestCase):
    def setUp(self):
        self.detector = BearishEngulfingDetector()

    def test_detect_valid_pattern(self):
        """
        Test Bearish Engulfing:
        Day 1: Bullish
        Day 2: Bearish, Engulfs Day 1
        """
        candles = [
            MockCandle(90, 100, 85, 95),   # Day 1: Bullish
            MockCandle(100, 105, 82, 85)   # Day 2: Bearish & Engulfing, Low 82 (Wick 3, Body 15, Ratio 0.2)
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low)
        self.assertTrue(result.is_pattern, "Should detect valid Bearish Engulfing")

    def test_detect_invalid_trend(self):
        """
        Test Invalid Trend:
        Day 1 is Bearish (should be Bullish for Bearish Engulfing).
        """
        candles = [
            MockCandle(100, 105, 90, 95),  # Day 1: Bearish
            MockCandle(100, 105, 82, 85)   # Day 2: Bearish
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low)
        self.assertFalse(result.is_pattern, "Should NOT detect if previous candle is bearish")
