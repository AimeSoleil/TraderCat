class CandlePatterns:
    """
    蜡烛图形态检测类
    提供常见的看涨、看跌以及中性形态检测方法，并统一返回格式：
    (found: bool, pattern_name: str, pattern_type: str)
    pattern_type 可取值：'bull'（看涨）、'bear'（看跌）、'neutral'（中性）
    """

    # -------------------------
    # 中性形态（犹豫信号）
    # -------------------------
    @staticmethod
    def _is_doji(open_, high, low, close, tolerance=0.001):
        """
        检测标准十字星（Doji）
        条件：
            - 开盘价与收盘价非常接近（实体极小）
            - tolerance 控制接近程度（默认 0.1%）
        """
        body = abs(close - open_)
        price_range = high - low
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low
        if price_range == 0:
            return False, None, None
        if body / price_range <= tolerance and upper_shadow > 0 and lower_shadow > 0:
            return True, "Doji", "neutral"
        return False, None, None

    @staticmethod
    def _is_dragonfly_doji(open_, high, low, close, tolerance=0.001):
        """
        检测蜻蜓十字星（Dragonfly Doji）
        特征：
            - 实体极小
            - 下影线很长，上影线极短
            - 通常出现在下跌趋势末端，可能看涨反转
        """
        body = abs(close - open_)
        price_range = high - low
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low
        if (
            body / price_range <= tolerance
            and lower_shadow >= price_range * 0.6
            and upper_shadow <= body
        ):
            return True, "Dragonfly Doji", "neutral"
        return False, None, None

    @staticmethod
    def _is_gravestone_doji(open_, high, low, close, tolerance=0.001):
        """
        检测墓碑十字星（Gravestone Doji）
        特征：
            - 实体极小
            - 上影线很长，下影线极短
            - 通常出现在上涨趋势末端，可能看跌反转
        """
        body = abs(close - open_)
        price_range = high - low
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low
        if (
            body / price_range <= tolerance
            and upper_shadow >= price_range * 0.6
            and lower_shadow <= body
        ):
            return True, "Gravestone Doji", "neutral"
        return False, None, None
    
    @staticmethod
    def _is_spinning_top(open_, high, low, close, tolerance=0.001):
        """
        Detect Spinning Top pattern.
        Conditions:
            - Body < 30% of total range
            - Upper and lower shadows >= 1.5 × body
            - Body > minimal threshold (avoid doji misclassification)
            - Indicates market indecision, potential reversal depending on trend
        """
        price_range = high - low
        if price_range == 0:
            return False, None, None

        body = abs(close - open_)
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low

        if (
            body / price_range < 0.3 * (1 + tolerance) and
            body >= price_range * 0.05 and
            upper_shadow >= body * 1.5 * (1 - tolerance) and
            lower_shadow >= body * 1.5 * (1 - tolerance)
        ):
            return True, "Spinning Top", "neutral"
        return False, None, None

    # -------------------------
    # 看涨形态（Bullish Patterns）
    # -------------------------
    @staticmethod
    def _is_hammer(open_, high, low, close, tolerance=0.001):
        """
        Detect Hammer candlestick pattern.
        Conditions:
            - Lower shadow >= 2 * body
            - Upper shadow <= 0.2 * body
            - Body >= 10% of total range
            - Typically after a downtrend (trend check recommended externally)
        """
        body = abs(close - open_)
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low
        total_range = high - low

        if body >= total_range * 0.1 and \
        lower_shadow >= body * 2 * (1 - tolerance) and \
        upper_shadow <= body * 0.2 * (1 + tolerance):
            return True, "Hammer", "bull"
        return False, None, None

    @staticmethod
    def _is_bullish_engulfing(o1, c1, o2, c2, tolerance=0.001):
        """
        Detect Bullish Engulfing pattern.
        Conditions:
            - First candle bearish, second bullish
            - Second body fully (or nearly) engulfs first body
            - Ideally after a downtrend (trend check recommended externally)
        """
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)

        if c1 < o1 and c2 > o2 and \
        c2 >= o1 * (1 - tolerance) and \
        o2 <= c1 * (1 + tolerance) and \
            body2 >= body1 * 1.2:  # second body stronger
                return True, "Bullish Engulfing", "bull"
        return False, None, None

    @staticmethod
    def _is_morning_star(o1, c1, o2, c2, o3, c3, tolerance=0.001):
        """
        Detect Morning Star pattern.
        Conditions:
            - First candle bearish
            - Second candle small body (indecision)
            - Third candle bullish, closes above midpoint of first candle
            - Ideally after a downtrend (trend check recommended externally)
        """
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        body3 = abs(c3 - o3)
        midpoint1 = (o1 + c1) / 2

        if (
            c1 < o1 and
            body2 <= body1 * 0.5 and
            c3 > o3 and
            c3 >= midpoint1 * (1 - tolerance) and
            body3 >= body1 * 0.8
        ):
            return True, "Morning Star", "bull"
        return False, None, None

    @staticmethod
    def _is_piercing_pattern(o1, c1, o2, c2, tolerance=0.001):
        """
        Detect Piercing Pattern.
        Conditions:
            - First candle bearish
            - Second candle bullish
            - Second opens below first close
            - Second closes above midpoint of first but below first open
            - Ideally after a downtrend (trend check recommended externally)
        """
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        midpoint1 = (o1 + c1) / 2

        if (
            c1 < o1 and
            c2 > o2 and
            o2 < c1 and
            c2 >= midpoint1 * (1 - tolerance) and
            c2 < o1 and
            body2 >= body1 * 0.8
        ):
            return True, "Piercing Pattern", "bull"
        return False, None, None

    @staticmethod
    def _is_bullish_harami(o1, c1, o2, c2, tolerance=0.001):
        """
        Detect Bullish Harami pattern.
        Conditions:
            - First candle bearish
            - Second candle bullish
            - Second body inside first body
            - Ideally after a downtrend (trend check recommended externally)
        """
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)

        if (
            c1 < o1 and
            c2 > o2 and
            o2 >= c1 * (1 - tolerance) and
            c2 <= o1 * (1 + tolerance) and
            body2 <= body1 * 0.5
        ):
            return True, "Bullish Harami", "bull"
        return False, None, None

    @staticmethod
    def _is_three_white_soldiers(opens, closes, tolerance=0.001):
        """
        Detect Three White Soldiers pattern.
        Conditions:
            - Three consecutive bullish candles
            - Each close higher than previous close
            - Each candle has a strong body
            - Ideally after a downtrend (trend check recommended externally)
        """
        bodies = [abs(closes[i] - opens[i]) for i in range(3)]
        avg_body = sum(bodies) / 3

        if (
            all(closes[i] > opens[i] for i in range(3)) and
            closes[1] > closes[0] * (1 + tolerance) and
            closes[2] > closes[1] * (1 + tolerance) and
            all(b >= avg_body * 0.8 for b in bodies)
        ):
            return True, "Three White Soldiers", "bull"
        return False, None, None

    @staticmethod
    def _is_tweezer_bottom(o1, c1, l1, o2, c2, l2, tolerance=0.001):
        """
        Detect Tweezer Bottom pattern.
        Conditions:
            - Two candles with similar lows (within tolerance)
            - First candle bearish, second bullish
            - Ideally after a downtrend (trend check recommended externally)
        """
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        avg_low = (l1 + l2) / 2

        if (
            abs(l1 - l2) <= avg_low * tolerance and
            c1 < o1 and
            c2 > o2 and
            body1 >= body2 * 0.5  # ensure meaningful bodies
        ):
            return True, "Tweezer Bottom", "bull"
        return False, None, None

    # -------------------------
    # 看跌形态（Bearish Patterns）
    # -------------------------
    @staticmethod
    def _is_shooting_star(open_, high, low, close, tolerance=0.001):
        """
        Detect Shooting Star pattern.
        Conditions:
            - Upper shadow >= 2 * body
            - Lower shadow very small (<= 20% of body)
            - Body >= 10% of total range
            - Ideally after an uptrend (trend check recommended externally)
        """
        body = abs(close - open_)
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low
        total_range = high - low

        if (
            body >= total_range * 0.1 and
            upper_shadow >= body * 2 * (1 - tolerance) and
            lower_shadow <= body * 0.2 * (1 + tolerance)
        ):
            return True, "Shooting Star", "bear"
        return False, None, None

    @staticmethod
    def _is_bearish_engulfing(o1, c1, o2, c2, tolerance=0.001):
        """
        Detect Bearish Engulfing pattern.
        Conditions:
            - First candle bullish
            - Second candle bearish
            - Second body fully engulfs first body
            - Ideally after an uptrend (trend check recommended externally)
        """
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)

        if (
            c1 > o1 and
            c2 < o2 and
            c2 <= o1 * (1 + tolerance) and
            o2 >= c1 * (1 - tolerance) and
            body2 >= body1 * 1.2
        ):
            return True, "Bearish Engulfing", "bear"
        return False, None, None

    @staticmethod
    def _is_evening_star(o1, c1, o2, c2, o3, c3, tolerance=0.001):
        """
        Detect Evening Star pattern.
        Conditions:
            - First candle bullish
            - Second candle small body (indecision)
            - Third candle bearish, closes below midpoint of first candle
            - Ideally after an uptrend (trend check recommended externally)
        """
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        body3 = abs(c3 - o3)
        midpoint1 = (o1 + c1) / 2

        if (
            c1 > o1 and
            body2 <= body1 * 0.5 and
            c3 < o3 and
            c3 <= midpoint1 * (1 + tolerance) and
            body3 >= body1 * 0.8
        ):
            return True, "Evening Star", "bear"
        return False, None, None

    @staticmethod
    def _is_dark_cloud_cover(o1, c1, o2, c2, tolerance=0.001):
        """
        Detect Dark Cloud Cover pattern.
        Conditions:
            - First candle bullish
            - Second candle bearish
            - Second opens above previous close
            - Second closes below midpoint of first but above first open
            - Ideally after an uptrend (trend check recommended externally)
        """
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        midpoint1 = (o1 + c1) / 2

        if (
            c1 > o1 and
            c2 < o2 and
            o2 > c1 and
            c2 <= midpoint1 * (1 + tolerance) and
            c2 > o1 and
            body2 >= body1 * 0.8
        ):
            return True, "Dark Cloud Cover", "bear"
        return False, None, None

    @staticmethod
    def _is_bearish_harami(o1, c1, o2, c2, tolerance=0.001):
        """
        Detect Bearish Harami pattern.
        Conditions:
            - First candle bullish
            - Second candle bearish
            - Second body inside first body
            - Ideally after an uptrend (trend check recommended externally)
        """
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)

        if (
            c1 > o1 and
            o2 < c2 and
            o2 <= c1 * (1 + tolerance) and
            c2 >= o1 * (1 - tolerance) and
            body2 <= body1 * 0.5
        ):
            return True, "Bearish Harami", "bear"
        return False, None, None

    @staticmethod
    def _is_three_black_crows(opens, closes, tolerance=0.001):
        """
        Detect Three Black Crows pattern.
        Conditions:
            - Three consecutive bearish candles
            - Each close lower than previous close
            - Each candle has a strong body
            - Ideally after an uptrend (trend check recommended externally)
        """
        bodies = [abs(closes[i] - opens[i]) for i in range(3)]
        avg_body = sum(bodies) / 3

        if (
            all(closes[i] < opens[i] for i in range(3)) and
            closes[1] < closes[0] * (1 - tolerance) and
            closes[2] < closes[1] * (1 - tolerance) and
            all(b >= avg_body * 0.8 for b in bodies)
        ):
            return True, "Three Black Crows", "bear"
        return False, None, None

    @staticmethod
    def _is_tweezer_top(o1, c1, h1, o2, c2, h2, tolerance=0.001):
        """
        Detect Tweezer Top pattern.
        Conditions:
            - Two candles with similar highs (within tolerance)
            - First candle bullish, second bearish
            - Ideally after an uptrend (trend check recommended externally)
        """
        body1 = abs(c1 - o1)
        body2 = abs(c2 - o2)
        avg_high = (h1 + h2) / 2

        if (
            abs(h1 - h2) <= avg_high * tolerance and
            c1 > o1 and
            c2 < o2 and
            body1 >= body2 * 0.5  # ensure meaningful bodies
        ):
            return True, "Tweezer Top", "bear"
        return False, None, None

    # -------------------------
    # 统一检测方法
    # -------------------------
    @staticmethod
    def detect_bullish_pattern(opens, highs, lows, closes, idx, atr=None):
        """
        检测看涨形态
        按优先级依次检测单根、双根、三根组合形态
        """
        # Adaptive Based on ATR (Best Practice)
        tolerance = (atr / closes[-1]) if atr else 0.001
        if idx >= 0:
            for func in [
                CandlePatterns._is_hammer,
                CandlePatterns._is_doji,
                CandlePatterns._is_dragonfly_doji,
                CandlePatterns._is_spinning_top,
            ]:
                found, name, ptype = func(
                    opens[idx], highs[idx], lows[idx], closes[idx], tolerance
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
                    opens[idx - 1], closes[idx - 1], opens[idx], closes[idx], tolerance
                )
                if found:
                    return found, name, ptype
            
            # Tweezer Bottom uses lows
            found, name, ptype = CandlePatterns._is_tweezer_bottom(
                opens[idx - 1], 
                closes[idx - 1],
                lows[idx - 1], 
                opens[idx], 
                closes[idx],
                lows[idx],
                tolerance
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
                tolerance
            )
            if found:
                return found, name, ptype
            found, name, ptype = CandlePatterns._is_three_white_soldiers(
                [opens[idx - 2], opens[idx - 1], opens[idx]],
                [closes[idx - 2], closes[idx - 1], closes[idx]], tolerance
            )
            if found:
                return found, name, ptype
        return False, None, None

    @staticmethod
    def detect_bearish_pattern(opens, highs, lows, closes, idx, atr=None):
        """
        检测看跌形态
        按优先级依次检测单根、双根、三根组合形态
        """
        # Adaptive Based on ATR (Best Practice)
        tolerance = (atr / closes[-1]) if atr else 0.001
        if idx >= 0:
            for func in [
                CandlePatterns._is_shooting_star,
                CandlePatterns._is_doji,
                CandlePatterns._is_gravestone_doji,
                CandlePatterns._is_spinning_top,
            ]:
                found, name, ptype = func(
                    opens[idx], highs[idx], lows[idx], closes[idx], tolerance
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
                    opens[idx - 1], closes[idx - 1], opens[idx], closes[idx], tolerance
                )
                if found:
                    return found, name, ptype
            
            # Tweezer Top uses highs
            found, name, ptype = CandlePatterns._is_tweezer_top(
                opens[idx - 1], 
                closes[idx - 1],
                highs[idx - 1], 
                opens[idx], 
                closes[idx],
                highs[idx],
                tolerance
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
                tolerance
            )
            if found:
                return found, name, ptype
            found, name, ptype = CandlePatterns._is_three_black_crows(
                [opens[idx - 2], opens[idx - 1], opens[idx]],
                [closes[idx - 2], closes[idx - 1], closes[idx]], tolerance
            )
            if found:
                return found, name, ptype
        return False, None, None
