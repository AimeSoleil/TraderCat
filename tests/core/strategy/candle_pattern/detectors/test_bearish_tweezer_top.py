import unittest
from tradercat.core.strategy.candle_pattern.detectors.bearish_tweezer_top import TweezerTopDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestTweezerTop(unittest.TestCase):
    def setUp(self):
        self.detector = TweezerTopDetector()

    def test_detect_valid_pattern(self):
        """
        Test Tweezer Top:
        Day 1: Bullish
        Day 2: Bearish
        Highs are very close.
        """
        candles = [
            MockCandle(90, 100, 85, 95),   # Day 1: Bullish, High 100
            MockCandle(98, 100.05, 90, 92) # Day 2: Bearish, High 100.05 (Close to 100)
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low)
        self.assertTrue(result.is_pattern, "Should detect valid Tweezer Top")

    def test_detect_invalid_highs(self):
        """
        Test Invalid Highs:
        Highs are not close enough.
        """
        candles = [
            MockCandle(90, 100, 85, 95),   # Day 1: High 100
            MockCandle(98, 105, 90, 92)    # Day 2: High 105 (Too far)
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low)
        self.assertFalse(result.is_pattern, "Should NOT detect if highs are different")
