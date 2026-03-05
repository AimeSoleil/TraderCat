import unittest
from tradercat.core.strategy.candle_pattern.detectors.bearish_gravestone_doji import GravestoneDojiDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestGravestoneDoji(unittest.TestCase):
    def setUp(self):
        self.detector = GravestoneDojiDetector()

    def test_detect_valid_gravestone(self):
        """
        Test Gravestone Doji:
        Open/Close near Low, Long Upper Shadow.
        """
        candles = [
            MockCandle(90, 100, 89.5, 90.2)  # Low close to Open/Close, Long upper shadow
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertTrue(result.is_pattern, "Should detect valid Gravestone Doji")

    def test_detect_invalid_large_lower_shadow(self):
        """
        Test Invalid Gravestone:
        Large lower shadow.
        """
        candles = [
            MockCandle(90, 100, 80, 90.2)  # Large lower shadow
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertFalse(result.is_pattern, "Should NOT detect Gravestone if lower shadow is large")
