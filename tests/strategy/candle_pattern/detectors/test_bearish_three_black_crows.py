import unittest
from tradercat.strategy.candle_pattern.detectors.bearish_three_black_crows import ThreeBlackCrowsDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestThreeBlackCrows(unittest.TestCase):
    def setUp(self):
        self.detector = ThreeBlackCrowsDetector()

    def test_detect_valid_pattern(self):
        """
        Test Three Black Crows:
        3 consecutive bearish candles.
        Each opens within previous body.
        Each closes lower than previous close.
        """
        candles = [
            MockCandle(100, 102, 91, 92),   # Day 1: Bearish, Low 91 (Wick 1)
            MockCandle(94, 95, 87, 88),     # Day 2: Bearish, Open 94 < 100, Close 88 < 92, Low 87 (Wick 1)
            MockCandle(89, 90, 81, 82)      # Day 3: Bearish, Open 89 < 94, Close 82 < 88, Low 81 (Wick 1)
        ]
        c1, c2, c3 = candles[0], candles[1], candles[2]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, c3.open, c3.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, h3=c3.high, l3=c3.low)
        self.assertTrue(result.is_pattern, "Should detect valid Three Black Crows")

    def test_detect_invalid_bullish(self):
        """
        Test Invalid:
        One candle is bullish.
        """
        candles = [
            MockCandle(100, 102, 90, 92),   # Day 1: Bearish
            MockCandle(92, 98, 90, 96),     # Day 2: Bullish
            MockCandle(89, 90, 80, 82)      # Day 3: Bearish
        ]
        c1, c2, c3 = candles[0], candles[1], candles[2]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, c3.open, c3.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, h3=c3.high, l3=c3.low)
        self.assertFalse(result.is_pattern, "Should NOT detect if any candle is bullish")
