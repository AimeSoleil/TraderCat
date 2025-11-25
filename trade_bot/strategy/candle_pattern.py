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
        if price_range == 0:
            return False, None, None
        if body / price_range <= tolerance:
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
        if (
            body / price_range <= tolerance
            and (high - close) <= body
            and (open_ - low) >= price_range * 0.6
        ):
            return True, "Dragonfly Doji", "bull"
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
        if (
            body / price_range <= tolerance
            and (close - low) <= body
            and (high - open_) >= price_range * 0.6
        ):
            return True, "Gravestone Doji", "bear"
        return False, None, None

    @staticmethod
    def _is_spinning_top(open_, high, low, close):
        """
        检测纺锤线（Spinning Top）
        特征：
            - 实体较小
            - 上下影线较长
            - 表示市场犹豫，可能是趋势反转信号
        """
        body = abs(close - open_)
        price_range = high - low
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low
        if body / price_range < 0.3 and upper_shadow > body and lower_shadow > body:
            return True, "Spinning Top", "neutral"
        return False, None, None

    # -------------------------
    # 看涨形态（Bullish Patterns）
    # -------------------------
    @staticmethod
    def _is_hammer(open_, high, low, close):
        """
        检测锤子线（Hammer）
        特征：
            - 下影线至少是实体的两倍
            - 上影线很短
            - 通常出现在下跌趋势末端，可能看涨反转
        """
        body = abs(close - open_)
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low
        if lower_shadow >= body * 2 and upper_shadow <= body:
            return True, "Hammer", "bull"
        return False, None, None

    @staticmethod
    def _is_bullish_engulfing(o1, c1, o2, c2):
        """
        检测看涨吞没（Bullish Engulfing）
        条件：
            - 前一根是阴线，后一根是阳线
            - 后一根实体完全吞没前一根实体
        """
        if c1 < o1 and c2 > o2 and c2 > o1 and o2 < c1:
            return True, "Bullish Engulfing", "bull"
        return False, None, None

    @staticmethod
    def _is_morning_star(o1, c1, o2, c2, o3, c3):
        """
        检测晨星（Morning Star）
        三根蜡烛组合：
            - 第一根阴线
            - 第二根小实体（犹豫）
            - 第三根阳线，收盘价高于第一根实体中点
        """
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
        """
        检测刺透形态（Piercing Pattern）
        条件：
            - 第一根阴线
            - 第二根阳线，收盘价超过第一根实体中点
        """
        if c1 < o1 and o2 < c1 and c2 > (o1 + c1) / 2 and c2 < o1:
            return True, "Piercing Pattern", "bull"
        return False, None, None

    @staticmethod
    def _is_bullish_harami(o1, c1, o2, c2):
        """
        检测看涨孕线（Bullish Harami）
        条件：
            - 第一根阴线
            - 第二根阳线，实体在第一根实体内部
        """
        if c1 < o1 and o2 > c2 and o2 >= c1 and c2 <= o1:
            return True, "Bullish Harami", "bull"
        return False, None, None

    @staticmethod
    def _is_three_white_soldiers(opens, closes):
        """
        检测三白兵（Three White Soldiers）
        条件：
            - 连续三根阳线
            - 每根收盘价高于前一根
        """
        if (
            all(closes[i] > opens[i] for i in range(3))
            and closes[1] > closes[0]
            and closes[2] > closes[1]
        ):
            return True, "Three White Soldiers", "bull"
        return False, None, None

    @staticmethod
    def _is_tweezer_bottom(o1, c1, o2, c2):
        """
        检测双针底（Tweezer Bottom）
        条件：
            - 两根蜡烛低点接近
            - 通常出现在下跌趋势末端
        """
        if abs(o1 - o2) < (o1 * 0.001) and abs(c1 - c2) < (o1 * 0.001):
            return True, "Tweezer Bottom", "bull"
        return False, None, None

    # -------------------------
    # 看跌形态（Bearish Patterns）
    # -------------------------
    @staticmethod
    def _is_shooting_star(open_, high, low, close):
        """
        检测流星线（Shooting Star）
        特征：
            - 上影线至少是实体的两倍
            - 下影线很短
            - 通常出现在上涨趋势末端，可能看跌反转
        """
        body = abs(close - open_)
        upper_shadow = high - max(open_, close)
        lower_shadow = min(open_, close) - low
        if upper_shadow >= body * 2 and lower_shadow <= body:
            return True, "Shooting Star", "bear"
        return False, None, None

    @staticmethod
    def _is_bearish_engulfing(o1, c1, o2, c2):
        """
        检测看跌吞没（Bearish Engulfing）
        条件：
            - 前一根阳线，后一根阴线
            - 后一根实体完全吞没前一根实体
        """
        if c1 > o1 and c2 < o2 and c2 < o1 and o2 > c1:
            return True, "Bearish Engulfing", "bear"
        return False, None, None

    @staticmethod
    def _is_evening_star(o1, c1, o2, c2, o3, c3):
        """
        检测暮星（Evening Star）
        三根蜡烛组合：
            - 第一根阳线
            - 第二根小实体（犹豫）
            - 第三根阴线，收盘价低于第一根实体中点
        """
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
        """
        检测乌云盖顶（Dark Cloud Cover）
        条件：
            - 第一根阳线
            - 第二根阴线，收盘价低于第一根实体中点
        """
        if c1 > o1 and o2 > c1 and c2 < (o1 + c1) / 2 and c2 > o1:
            return True, "Dark Cloud Cover", "bear"
        return False, None, None

    @staticmethod
    def _is_bearish_harami(o1, c1, o2, c2):
        """
        检测看跌孕线（Bearish Harami）
        条件：
            - 第一根阳线
            - 第二根阴线，实体在第一根实体内部
        """
        if c1 > o1 and o2 < c2 and o2 <= c1 and c2 >= o1:
            return True, "Bearish Harami", "bear"
        return False, None, None

    @staticmethod
    def _is_three_black_crows(opens, closes):
        """
        检测三只乌鸦（Three Black Crows）
        条件：
            - 连续三根阴线
            - 每根收盘价低于前一根
        """
        if (
            all(closes[i] < opens[i] for i in range(3))
            and closes[1] < closes[0]
            and closes[2] < closes[1]
        ):
            return True, "Three Black Crows", "bear"
        return False, None, None

    @staticmethod
    def _is_tweezer_top(o1, c1, o2, c2):
        """
        检测双针顶（Tweezer Top）
        条件：
            - 两根蜡烛高点接近
            - 通常出现在上涨趋势末端
        """
        if abs(o1 - o2) < (o1 * 0.001) and abs(c1 - c2) < (o1 * 0.001):
            return True, "Tweezer Top", "bear"
        return False, None, None

    # -------------------------
    # 统一检测方法
    # -------------------------
    @staticmethod
    def detect_bullish_pattern(opens, highs, lows, closes, idx):
        """
        检测看涨形态
        按优先级依次检测单根、双根、三根组合形态
        """
        if idx >= 0:
            for func in [
                CandlePatterns._is_hammer,
                CandlePatterns._is_doji,
                CandlePatterns._is_dragonfly_doji,
                CandlePatterns._is_spinning_top,
            ]:
                found, name, ptype = func(
                    opens[idx], highs[idx], lows[idx], closes[idx]
                )
                if found:
                    return found, name, ptype
        if idx >= 1:
            for func in [
                CandlePatterns._is_bullish_engulfing,
                CandlePatterns._is_piercing_pattern,
                CandlePatterns._is_bullish_harami,
                CandlePatterns._is_tweezer_bottom,
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
        检测看跌形态
        按优先级依次检测单根、双根、三根组合形态
        """
        if idx >= 0:
            for func in [
                CandlePatterns._is_shooting_star,
                CandlePatterns._is_doji,
                CandlePatterns._is_gravestone_doji,
                CandlePatterns._is_spinning_top,
            ]:
                found, name, ptype = func(
                    opens[idx], highs[idx], lows[idx], closes[idx]
                )
                if found:
                    return found, name, ptype
        if idx >= 1:
            for func in [
                CandlePatterns._is_bearish_engulfing,
                CandlePatterns._is_dark_cloud_cover,
                CandlePatterns._is_bearish_harami,
                CandlePatterns._is_tweezer_top,
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
