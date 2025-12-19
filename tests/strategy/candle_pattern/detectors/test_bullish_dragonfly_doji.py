import unittest
from tradercat.strategy.candle_pattern.detectors.bullish_dragonfly_doji import DragonflyDojiDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestDragonflyDoji(unittest.TestCase):
    def setUp(self):
        self.detector = DragonflyDojiDetector()

    def test_detect_valid_dragonfly(self):
        """
        Test Dragonfly Doji:
        Open/Close near High, Long Lower Shadow.
        """
        candles = [
            MockCandle(100, 100.5, 90, 100.2)  # High close to Open/Close, Long lower shadow
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertTrue(result.is_pattern, "Should detect valid Dragonfly Doji")

    def test_detect_invalid_large_upper_shadow(self):
        """
        Test Invalid Dragonfly:
        Large upper shadow (looks like Spinning Top or Long Legged Doji).
        """
        candles = [
            MockCandle(100, 110, 90, 100.2)  # Large upper shadow
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertFalse(result.is_pattern, "Should NOT detect Dragonfly if upper shadow is large")
