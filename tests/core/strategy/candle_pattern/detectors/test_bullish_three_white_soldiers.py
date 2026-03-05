import unittest
from tradercat.core.strategy.candle_pattern.detectors.bullish_three_white_soldiers import ThreeWhiteSoldiersDetector

class MockCandle:
    def __init__(self, open, high, low, close):
        self.open = open
        self.high = high
        self.low = low
        self.close = close

class TestThreeWhiteSoldiers(unittest.TestCase):
    def setUp(self):
        self.detector = ThreeWhiteSoldiersDetector()

    def test_detect_valid_pattern(self):
        """
        Test a valid Three White Soldiers pattern.
        Constraints:
        - min_body_ratio_vs_range = 0.40
        - max_upper_shadow_to_body = 0.30
        - Higher Highs, Higher Lows, Higher Closes
        """
        candles = [
            # Candle 1: Open 100, Close 106 (Body 6). Range 7 (99.5-106.5). Ratio 0.86.
            MockCandle(100.0, 106.5, 99.5, 106.0),
            # Candle 2: Open 105.5, Close 111 (Body 5.5). Range 6.5 (105.0-111.5). Ratio 0.84.
            MockCandle(105.5, 111.5, 105.0, 111.0),
            # Candle 3: Open 111.5, Close 117 (Body 5.5). Range 6.5 (111.0-117.5). Ratio 0.84.
            MockCandle(111.5, 117.5, 111.0, 117.0)
        ]
        c1, c2, c3 = candles[0], candles[1], candles[2]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, c3.open, c3.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, h3=c3.high, l3=c3.low)
        self.assertTrue(result.is_pattern, "Should detect valid Three White Soldiers")
        self.assertEqual(result.name, "Three White Soldiers")

    def test_detect_invalid_bearish(self):
        """
        Test Invalid:
        One candle is bearish.
        """
        candles = [
            MockCandle(90, 92.5, 85, 92),   # Day 1: Bullish
            MockCandle(96, 98, 90, 91),     # Day 2: Bearish
            MockCandle(95, 102, 94, 100)    # Day 3: Bullish
        ]
        c1, c2, c3 = candles[0], candles[1], candles[2]
        result = self.detector.detect(c1.open, c1.close, c2.open, c2.close, c3.open, c3.close, h1=c1.high, l1=c1.low, h2=c2.high, l2=c2.low, h3=c3.high, l3=c3.low)
        self.assertFalse(result.is_pattern, "Should NOT detect if any candle is bearish")
