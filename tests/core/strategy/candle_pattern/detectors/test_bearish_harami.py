import unittest
from tradercat.core.strategy.candle_pattern.detectors.bearish_harami import BearishHaramiDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestBearishHarami(unittest.TestCase):
    def setUp(self):
        self.detector = BearishHaramiDetector()

    def test_detect_valid_pattern(self):
        """
        Test Bearish Harami:
        Day 1: Long Bullish
        Day 2: Small Bearish inside Day 1 body
        """
        candles = [
            MockCandle(90, 100, 85, 98),   # Day 1: Long Bullish
            MockCandle(96, 97, 94, 95)     # Day 2: Small Bearish, inside 90-98
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, v1=1000, v2=500)
        self.assertTrue(result.is_pattern, "Should detect valid Bearish Harami")

    def test_detect_invalid_outside(self):
        """
        Test Invalid:
        Day 2 is outside Day 1 body.
        """
        candles = [
            MockCandle(90, 100, 85, 98),   # Day 1: Long Bullish
            MockCandle(100, 102, 98, 99)   # Day 2: Outside
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, v1=1000, v2=500)
        self.assertFalse(result.is_pattern, "Should NOT detect if Day 2 is outside Day 1")
