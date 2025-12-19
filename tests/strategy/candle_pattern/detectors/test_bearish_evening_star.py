import unittest
from tradercat.strategy.candle_pattern.detectors.bearish_evening_star import EveningStarDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestEveningStar(unittest.TestCase):
    def setUp(self):
        self.detector = EveningStarDetector()

    def test_detect_valid_pattern(self):
        """
        Test Evening Star:
        Day 1: Long Bullish
        Day 2: Small Body (Gap Up)
        Day 3: Bearish (Close deep into Day 1)
        """
        candles = [
            MockCandle(90, 100, 85, 98),    # Day 1: Long Bullish
            MockCandle(100, 103, 99, 101),  # Day 2: Small Body, Gap Up, High 103 (Range 4, Body 1)
            MockCandle(100, 101, 90, 92)    # Day 3: Bearish, Close 92 < 94 (Mid of Day 1)
        ]
        c1, c2, c3 = candles[0], candles[1], candles[2]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, c3.open, c3.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, h3=c3.high, l3=c3.low)
        self.assertTrue(result.is_pattern, "Should detect valid Evening Star")

    def test_detect_invalid_day3_bullish(self):
        """
        Test Invalid:
        Day 3 is bullish.
        """
        candles = [
            MockCandle(90, 100, 85, 98),    # Day 1: Long Bullish
            MockCandle(100, 103, 99, 101),  # Day 2: Small Body
            MockCandle(100, 105, 99, 103)   # Day 3: Bullish
        ]
        c1, c2, c3 = candles[0], candles[1], candles[2]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, c3.open, c3.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, h3=c3.high, l3=c3.low)
        self.assertFalse(result.is_pattern, "Should NOT detect if Day 3 is bullish")
