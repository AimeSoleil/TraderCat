import unittest
from tradercat.core.strategy.candle_pattern.detectors.bearish_shooting_star import ShootingStarDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestShootingStar(unittest.TestCase):
    def setUp(self):
        self.detector = ShootingStarDetector()

    def test_detect_valid_shooting_star(self):
        """
        Test Shooting Star:
        Small Body near Low, Long Upper Shadow.
        """
        candles = [
            MockCandle(90, 100, 89.9, 91.1)  # Small body near low, long upper shadow, Low 89.9, Close 91.1 (Body 1.1, Ratio 0.11)
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertTrue(result.is_pattern, "Should detect valid Shooting Star")

    def test_detect_invalid_large_lower_shadow(self):
        """
        Test Invalid Shooting Star:
        Large lower shadow.
        """
        candles = [
            MockCandle(90, 100, 80, 91)  # Large lower shadow
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertFalse(result.is_pattern, "Should NOT detect Shooting Star if lower shadow is large")
