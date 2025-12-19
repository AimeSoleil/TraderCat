import unittest
from tradercat.strategy.candle_pattern.detectors.neutral_spinning_top import SpinningTopDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestSpinningTop(unittest.TestCase):
    def setUp(self):
        self.detector = SpinningTopDetector()

    def test_detect_valid_spinning_top(self):
        """
        Test Spinning Top:
        Small Body, Upper and Lower Shadows present.
        """
        candles = [
            MockCandle(100, 110, 90, 102)  # Small body, shadows on both sides
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertTrue(result.is_pattern, "Should detect valid Spinning Top")

    def test_detect_invalid_large_body(self):
        """
        Test Invalid Spinning Top:
        Body is too large.
        """
        candles = [
            MockCandle(100, 110, 90, 108)  # Large body
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertFalse(result.is_pattern, "Should NOT detect Spinning Top if body is large")
