import unittest
from tradercat.core.strategy.candle_pattern.detectors.neutral_standard_doji import StandardDojiDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestStandardDoji(unittest.TestCase):
    def setUp(self):
        self.detector = StandardDojiDetector()

    def test_detect_valid_doji(self):
        """
        Test Standard Doji:
        Open and Close are very close (small body).
        """
        candles = [
            MockCandle(100, 105, 95, 100.05)  # Very small body
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertTrue(result.is_pattern, "Should detect valid Standard Doji")

    def test_detect_invalid_large_body(self):
        """
        Test Invalid Doji:
        Body is too large.
        """
        candles = [
            MockCandle(100, 105, 95, 103)  # Large body
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertFalse(result.is_pattern, "Should NOT detect Doji if body is large")
