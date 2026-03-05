import unittest
from tradercat.core.strategy.candle_pattern.detectors.bullish_morning_star import MorningStarDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestMorningStar(unittest.TestCase):
    def setUp(self):
        self.detector = MorningStarDetector()

    def test_detect_valid_pattern(self):
        """
        Test Morning Star:
        Day 1: Long Bearish
        Day 2: Small Body (Gap Down)
        Day 3: Bullish (Close deep into Day 1)
        """
        candles = [
            MockCandle(100, 105, 90, 92),   # Day 1: Long Bearish
            MockCandle(90, 91, 87, 89),     # Day 2: Small Body, Gap Down, Low 87 (Range 4, Body 1)
            MockCandle(90, 98, 89, 97)      # Day 3: Bullish, Close 97 > 96 (Mid of Day 1)
        ]
        c1, c2, c3 = candles[0], candles[1], candles[2]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, c3.open, c3.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, h3=c3.high, l3=c3.low)
        self.assertTrue(result.is_pattern, "Should detect valid Morning Star")

    def test_detect_invalid_day3_bearish(self):
        """
        Test Invalid:
        Day 3 is bearish.
        """
        candles = [
            MockCandle(100, 105, 90, 92),   # Day 1: Long Bearish
            MockCandle(90, 91, 87, 89),     # Day 2: Small Body
            MockCandle(90, 92, 85, 88)      # Day 3: Bearish
        ]
        c1, c2, c3 = candles[0], candles[1], candles[2]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, c3.open, c3.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, h3=c3.high, l3=c3.low)
        self.assertFalse(result.is_pattern, "Should NOT detect if Day 3 is bearish")
