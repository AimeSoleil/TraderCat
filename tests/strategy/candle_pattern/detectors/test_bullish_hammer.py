import unittest
from tradercat.strategy.candle_pattern.detectors.bullish_hammer import HammerDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestHammer(unittest.TestCase):
    def setUp(self):
        self.detector = HammerDetector()

    def test_detect_valid_hammer(self):
        """
        Test a valid Hammer pattern.
        Constraints:
        - min_lower_shadow_to_body = 2.0 (Lower shadow >= 2x Body)
        - max_upper_shadow_to_body = 0.20 (Upper shadow <= 0.2x Body)
        - require_close_upper_fraction = 0.75 (Close in top 25% of range)
        """
        # Valid Hammer
        # Body: 2.0 (102.0 - 104.0)
        # Lower Shadow: 6.0 (102.0 - 96.0) -> Ratio 3.0 (> 2.0)
        # Upper Shadow: 0.2 (104.2 - 104.0) -> Ratio 0.1 (< 0.20)
        # Close Location: Top 97%
        c = MockCandle(102.0, 104.2, 96.0, 104.0) # Hammer

        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertTrue(result.is_pattern)
        self.assertEqual(result.name, "Hammer")

    def test_detect_invalid_large_upper_shadow(self):
        """
        Test Invalid Hammer:
        Large upper shadow.
        """
        candles = [
            MockCandle(100, 110, 90, 100.5)  # Large upper shadow
        ]
        c = candles[0]
        result = self.detector.detect(c.open, c.high, c.low, c.close)
        self.assertFalse(result.is_pattern, "Should NOT detect Hammer if upper shadow is large")
