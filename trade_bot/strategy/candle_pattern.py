class CandlePatterns:
    # -------------------------
    # Bullish Patterns (看涨形态)
    # -------------------------

    @staticmethod
    def _is_hammer(open_, high, low, close):
        # Hammer (锤子线)
        body = abs(close - open_)
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low
        if lower_shadow >= body * 2 and upper_shadow <= body:
            return True, "Hammer", "bull"
        return False, None, None

    @staticmethod
    def _is_bullish_engulfing(o1, c1, o2, c2):
        # Bullish Engulfing (看涨吞没)
        if c1 < o1 and c2 > o2 and c2 > o1 and o2 < c1:
            return True, "Bullish Engulfing", "bull"
        return False, None, None

    @staticmethod
    def _is_morning_star(o1, c1, o2, c2, o3, c3):
        # Morning Star (晨星)
        if (
            c1 < o1
            and abs(c2 - o2) < abs(c1 - o1) * 0.5
            and c3 > o3
            and c3 > (o1 + c1) / 2
        ):
            return True, "Morning Star", "bull"
        return False, None, None

    @staticmethod
    def _is_piercing_pattern(o1, c1, o2, c2):
        # Piercing Pattern (刺透形态)
        if c1 < o1 and o2 < c1 and c2 > (o1 + c1) / 2 and c2 < o1:
            return True, "Piercing Pattern", "bull"
        return False, None, None

    @staticmethod
    def _is_bullish_harami(o1, c1, o2, c2):
        # Bullish Harami (看涨孕线)
        if c1 < o1 and o2 > c2 and o2 >= c1 and c2 <= o1:
            return True, "Bullish Harami", "bull"
        return False, None, None

    @staticmethod
    def _is_three_white_soldiers(opens, closes):
        # Three White Soldiers (三白兵)
        if (
            closes[0] > opens[0]
            and closes[1] > opens[1]
            and closes[2] > opens[2]
            and closes[1] > closes[0]
            and closes[2] > closes[1]
        ):
            return True, "Three White Soldiers", "bull"
        return False, None, None

    # -------------------------
    # Bearish Patterns (看跌形态)
    # -------------------------

    @staticmethod
    def _is_shooting_star(open_, high, low, close):
        # Shooting Star (流星线)
        body = abs(close - open_)
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low
        if upper_shadow >= body * 2 and lower_shadow <= body:
            return True, "Shooting Star", "bear"
        return False, None, None

    @staticmethod
    def _is_bearish_engulfing(o1, c1, o2, c2):
        # Bearish Engulfing (看跌吞没)
        if c1 > o1 and c2 < o2 and c2 < o1 and o2 > c1:
            return True, "Bearish Engulfing", "bear"
        return False, None, None

    @staticmethod
    def _is_evening_star(o1, c1, o2, c2, o3, c3):
        # Evening Star (暮星)
        if (
            c1 > o1
            and abs(c2 - o2) < abs(c1 - o1) * 0.5
            and c3 < o3
            and c3 < (o1 + c1) / 2
        ):
            return True, "Evening Star", "bear"
        return False, None, None

    @staticmethod
    def _is_dark_cloud_cover(o1, c1, o2, c2):
        # Dark Cloud Cover (乌云盖顶)
        if c1 > o1 and o2 > c1 and c2 < (o1 + c1) / 2 and c2 > o1:
            return True, "Dark Cloud Cover", "bear"
        return False, None, None

    @staticmethod
    def _is_bearish_harami(o1, c1, o2, c2):
        # Bearish Harami (看跌孕线)
        if c1 > o1 and o2 < c2 and o2 <= c1 and c2 >= o1:
            return True, "Bearish Harami", "bear"
        return False, None, None

    @staticmethod
    def _is_three_black_crows(opens, closes):
        # Three Black Crows (三只乌鸦)
        if (
            closes[0] < opens[0]
            and closes[1] < opens[1]
            and closes[2] < opens[2]
            and closes[1] < closes[0]
            and closes[2] < closes[1]
        ):
            return True, "Three Black Crows", "bear"
        return False, None, None

    # -------------------------
    # Unified Detection Methods
    # -------------------------

    @staticmethod
    def detect_bullish_pattern(opens, highs, lows, closes, idx):
        """
        检测看涨形态 (Bullish Patterns)
        Returns: (found: bool, pattern_name: str, pattern_type: str)
        """
        if idx >= 0:
            found, name, ptype = CandlePatterns._is_hammer(
                opens[idx], highs[idx], lows[idx], closes[idx]
            )
            if found:
                return found, name, ptype

        if idx >= 1:
            for func in [
                CandlePatterns._is_bullish_engulfing,
                CandlePatterns._is_piercing_pattern,
                CandlePatterns._is_bullish_harami,
            ]:
                found, name, ptype = func(
                    opens[idx - 1], closes[idx - 1], opens[idx], closes[idx]
                )
                if found:
                    return found, name, ptype

        if idx >= 2:
            found, name, ptype = CandlePatterns._is_morning_star(
                opens[idx - 2],
                closes[idx - 2],
                opens[idx - 1],
                closes[idx - 1],
                opens[idx],
                closes[idx],
            )
            if found:
                return found, name, ptype
            found, name, ptype = CandlePatterns._is_three_white_soldiers(
                [opens[idx - 2], opens[idx - 1], opens[idx]],
                [closes[idx - 2], closes[idx - 1], closes[idx]],
            )
            if found:
                return found, name, ptype

        return False, None, None

    @staticmethod
    def detect_bearish_pattern(opens, highs, lows, closes, idx):
        """
        检测看跌形态 (Bearish Patterns)
        Returns: (found: bool, pattern_name: str, pattern_type: str)
        """
        if idx >= 0:
            found, name, ptype = CandlePatterns._is_shooting_star(
                opens[idx], highs[idx], lows[idx], closes[idx]
            )
            if found:
                return found, name, ptype

        if idx >= 1:
            for func in [
                CandlePatterns._is_bearish_engulfing,
                CandlePatterns._is_dark_cloud_cover,
                CandlePatterns._is_bearish_harami,
            ]:
                found, name, ptype = func(
                    opens[idx - 1], closes[idx - 1], opens[idx], closes[idx]
                )
                if found:
                    return found, name, ptype

        if idx >= 2:
            found, name, ptype = CandlePatterns._is_evening_star(
                opens[idx - 2],
                closes[idx - 2],
                opens[idx - 1],
                closes[idx - 1],
                opens[idx],
                closes[idx],
            )
            if found:
                return found, name, ptype
            found, name, ptype = CandlePatterns._is_three_black_crows(
                [opens[idx - 2], opens[idx - 1], opens[idx]],
                [closes[idx - 2], closes[idx - 1], closes[idx]],
            )
            if found:
                return found, name, ptype

        return False, None, None
