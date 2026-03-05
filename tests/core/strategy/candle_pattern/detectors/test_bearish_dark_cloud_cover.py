import unittest
from tradercat.core.strategy.candle_pattern.detectors.bearish_dark_cloud_cover import DarkCloudCoverDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestDarkCloudCover(unittest.TestCase):
    def setUp(self):
        self.detector = DarkCloudCoverDetector()

    def test_detect_valid_pattern(self):
        """
        Test Dark Cloud Cover:
        Day 1: Bullish
        Day 2: Bearish, Opens above Day 1 High, Closes below 50% of Day 1 Body
        """
        candles = [
            MockCandle(90, 100, 85, 98),    # Day 1: Bullish (Body 90-98, Mid 94)
            MockCandle(102, 105, 92, 93)    # Day 2: Bearish, Open 102 > 100, Close 93 < 94
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low)
        self.assertTrue(result.is_pattern, "Should detect valid Dark Cloud Cover")

    def test_detect_invalid_close(self):
        """
        Test Invalid Close:
        Day 2 closes above 50% of Day 1 Body.
        """
        candles = [
            MockCandle(90, 100, 85, 98),    # Day 1: Mid 94
            MockCandle(102, 105, 95, 96)    # Day 2: Close 96 > 94
        ]
        c1, c2 = candles[0], candles[1]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low)
        self.assertFalse(result.is_pattern, "Should NOT detect if close is not deep enough")
