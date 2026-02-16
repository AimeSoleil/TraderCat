import unittest
from tradercat.core.strategy.candle_pattern.detectors.bullish_harami import BullishHaramiDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestBullishHarami(unittest.TestCase):
    def setUp(self):
        self.detector = BullishHaramiDetector()

    def test_detect_valid_pattern(self):
        """
        Test Bullish Harami:
        Day 1: Long Bearish
        Day 2: Small Bullish inside Day 1 body
        """
        candles = [
            MockCandle(100, 105, 90, 92),   # Day 1: Long Bearish
            MockCandle(94, 96, 93, 95)      # Day 2: Small Bullish, inside 92-100
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, v1=1000, v2=500)
        self.assertTrue(result.is_pattern, "Should detect valid Bullish Harami")

    def test_detect_invalid_outside(self):
        """
        Test Invalid:
        Day 2 is outside Day 1 body.
        """
        candles = [
            MockCandle(100, 105, 90, 92),   # Day 1: Long Bearish
            MockCandle(90, 91, 88, 89)      # Day 2: Outside
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, v1=1000, v2=500)
        self.assertFalse(result.is_pattern, "Should NOT detect if Day 2 is outside Day 1")
