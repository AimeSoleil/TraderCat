import unittest
from tradercat.core.strategy.candle_pattern.detectors.bullish_piercing import PiercingPatternDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestPiercingPattern(unittest.TestCase):
    def setUp(self):
        self.detector = PiercingPatternDetector()

    def test_detect_valid_pattern(self):
        """
        Test Piercing Pattern:
        Day 1: Bearish
        Day 2: Bullish, Opens below Day 1 Low, Closes above 50% of Day 1 Body
        """
        candles = [
            MockCandle(100, 105, 90, 92),   # Day 1: Bearish (Body 92-100, Mid 96)
            MockCandle(88, 98, 85, 97)      # Day 2: Bullish, Open 88 < 90, Close 97 > 96
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low)
        self.assertTrue(result.is_pattern, "Should detect valid Piercing Pattern")

    def test_detect_invalid_close(self):
        """
        Test Invalid Close:
        Day 2 closes below 50% of Day 1 Body.
        """
        candles = [
            MockCandle(100, 105, 90, 92),   # Day 1: Mid 96
            MockCandle(88, 98, 85, 95)      # Day 2: Close 95 < 96
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low)
        self.assertFalse(result.is_pattern, "Should NOT detect if close is not high enough")
