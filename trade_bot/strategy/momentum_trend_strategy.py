from typing import List, Optional, Dict, Any, Tuple
import math

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel


class MomentumTrendStrategy(TradingStrategy):
    """
    多周期动量波段策略
    
    策略特点:
    ----------
    1. 基于日线数据识别短期动量变化
    2. 结合多个时间周期的动量指标
    3. 使用成交量和趋势确认
    4. 适合做波段交易和趋势跟踪
    
    主要应用场景:
    ----------
    1. 日线级别动量突破
    2. 周线级别趋势确认
    3. 波段交易和趋势跟踪
    4. 适合波动率中等的市场
    
    交易逻辑:
    ----------
    1. 短期:
       - RSI背离信号
       - MACD柱状图转向
       - 成交量突破确认
       
    2. 中期:
       - ADX趋势强度
       - 均线系统排列
       - OBV趋势确认
       
    3. 长期:
       - 趋势方向判断
       - 波段高低点分析
       - 大周期支撑阻力
    
    参数说明:
    ----------
    rsi_periods: List[int]
        RSI多周期设置 [短期, 中期, 长期]
    macd_params: Dict
        MACD参数配置
    adx_period: int
        ADX趋势强度周期
    ma_periods: List[int]
        均线周期 [短期, 中期, 长期]
    volume_ma: int
        成交量均线周期
    """

    def __init__(
        self,
        rsi_periods: Optional[List[int]] = None,
        macd_params: Optional[Dict[str, int]] = None,
        adx_period: int = 14,
        ma_periods: Optional[List[int]] = None,
        volume_ma: int = 20,
        weights: Optional[Dict[str, float]] = None,
        score_threshold: float = 0.6,
        data_provider = None
    ):
        # 默认参数配置
        self.rsi_periods = rsi_periods or [10, 14, 21]  # 短中长期RSI
        self.macd_params = macd_params or {
            "fast": 12,
            "slow": 26,
            "signal": 9
        }
        self.adx_period = adx_period
        self.ma_periods = ma_periods or [10, 20, 50]  # 短中长期MA
        self.volume_ma = volume_ma
        
        # 默认权重配置
        default_weights = {
            "momentum": 0.35,   # 动量指标权重
            "trend": 0.25,     # 趋势指标权重
            "volume": 0.20,    # 成交量权重
            "pattern": 0.20    # 形态特征权重
        }
        
        merged = default_weights.copy()
        if weights:
            merged.update(weights)
        total = sum(merged.values())
        self.weights = {k: v/total for k,v in merged.items()}
        
        self.score_threshold = score_threshold
        self.provider = data_provider

    def get_name(self) -> str:
        return "MomentumTrend"

    def get_lookback_window(self) -> int:
        return max(max(self.rsi_periods), max(self.ma_periods)) + self.adx_period

    def _find_swing_points(
        self, values: List[float], window: int = 3
    ) -> List[Tuple[int, float, str]]:
        """查找序列中的波动极值点"""
        points = []
        if len(values) < window * 2 + 1:
            return points

        for i in range(window, len(values) - window):
            left = values[i - window : i]
            right = values[i + 1 : i + window + 1]
            curr = values[i]

            if curr > max(left) and curr > max(right):
                points.append((i, curr, "high"))
            elif curr < min(left) and curr < min(right):
                points.append((i, curr, "low"))

        return points

    def _check_divergence(
        self,
        price_points: List[Tuple[int, float, str]],
        indicator_points: List[Tuple[int, float, str]],
        point_type: str,
    ) -> Tuple[bool, float, str]:
        """检查背离"""
        if len(price_points) < 2 or len(indicator_points) < 2:
            return False, 0.0, ""

        p1, p2 = price_points[-2:]
        i1, i2 = indicator_points[-2:]

        details = []
        if point_type == "low":  # 底背离
            price_div = p2[1] < p1[1]  # 价格更低
            ind_div = i2[1] > i1[1]  # 指标更高

            if price_div and ind_div:
                price_chg = (p2[1] - p1[1]) / p1[1] * 100
                ind_chg = (i2[1] - i1[1]) / i1[1] * 100
                details.extend(
                    [f"价格新低: {price_chg:.1f}%", f"指标走高: +{ind_chg:.1f}%"]
                )
                strength = min(abs(price_chg), abs(ind_chg)) / 100
                return True, strength, " | ".join(details)

        elif point_type == "high":  # 顶背离
            price_div = p2[1] > p1[1]  # 价格更高
            ind_div = i2[1] < i1[1]  # 指标更低

            if price_div and ind_div:
                price_chg = (p2[1] - p1[1]) / p1[1] * 100
                ind_chg = (i2[1] - i1[1]) / i1[1] * 100
                details.extend(
                    [f"价格新高: +{price_chg:.1f}%", f"指标走低: {ind_chg:.1f}%"]
                )
                strength = min(abs(price_chg), abs(ind_chg)) / 100
                return True, strength, " | ".join(details)

        return False, 0.0, ""

    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """生成信号"""
        if not candles or len(candles) < max(self.adx_period, self.rsi_period) + 2:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date if candles else None,
                reason="数据不足",
                confidence=0.0,
            )

        # 获取技术指标
        adx = self.provider.get_indicator("adx", candles, {"length": self.adx_period})
        print(f"adx: {adx[-1]}")
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        stoch = self.provider.get_indicator(
            "stoch", candles, {"length": self.stoch_period}
        )
        obv = self.provider.get_indicator("obv", candles, {})

        # 提取当前值
        curr_close = float(candles[-1].close)
        curr_adx = float(adx[-1].ADX_14)
        curr_pdi = float(adx[-1].DMP_14)
        curr_ndi = float(adx[-1].DMN_14)
        curr_rsi = float(rsi[-1].RSI_14)
        curr_stoch_k = float(stoch[-1].STOCHk_14_3_3)
        curr_stoch_d = float(stoch[-1].STOCHd_14_3_3)

        # 1. 趋势评分 (ADX/DI)
        trend_score = 0.0
        trend_detail = ""

        if curr_adx > 25:  # 趋势显著
            if curr_pdi > curr_ndi:  # 上涨趋势
                trend_score = min((curr_adx - 25) / 25, 1.0)
                trend_detail = f"强上涨趋势 ADX:{curr_adx:.1f} +DI:{curr_pdi:.1f} > -DI:{curr_ndi:.1f}"
            else:  # 下跌趋势
                trend_score = -min((curr_adx - 25) / 25, 1.0)
                trend_detail = f"强下跌趋势 ADX:{curr_adx:.1f} -DI:{curr_ndi:.1f} > +DI:{curr_pdi:.1f}"

        # 2. 动量评分 (RSI)
        momentum_score = 0.0
        momentum_detail = ""

        # RSI背离检测
        closes = [float(c.close) for c in candles[-20:]]
        rsi_values = [float(r.RSI_14) for r in rsi[-20:]]

        price_points = self._find_swing_points(closes)
        rsi_points = self._find_swing_points(rsi_values)

        rsi_bull_div, rsi_bull_str, rsi_bull_detail = self._check_divergence(
            price_points, rsi_points, "low"
        )
        rsi_bear_div, rsi_bear_str, rsi_bear_detail = self._check_divergence(
            price_points, rsi_points, "high"
        )

        if rsi_bull_div:
            momentum_score = rsi_bull_str
            momentum_detail = f"RSI底背离 ({rsi_bull_detail})"
        elif rsi_bear_div:
            momentum_score = -rsi_bear_str
            momentum_detail = f"RSI顶背离 ({rsi_bear_detail})"
        else:
            # 无背离时用RSI数值
            if curr_rsi > 70:
                momentum_score = -((curr_rsi - 70) / 30)
                momentum_detail = f"RSI超买 ({curr_rsi:.1f})"
            elif curr_rsi < 30:
                momentum_score = (30 - curr_rsi) / 30
                momentum_detail = f"RSI超卖 ({curr_rsi:.1f})"

        # 3. StochRSI评分
        stoch_score = 0.0
        stoch_detail = ""

        if curr_stoch_k > curr_stoch_d:  # 金叉
            stoch_score = min((curr_stoch_k - curr_stoch_d) / 20, 1.0)
            stoch_detail = f"StochRSI金叉 K:{curr_stoch_k:.1f} > D:{curr_stoch_d:.1f}"
        else:  # 死叉
            stoch_score = -min((curr_stoch_d - curr_stoch_k) / 20, 1.0)
            stoch_detail = f"StochRSI死叉 K:{curr_stoch_k:.1f} < D:{curr_stoch_d:.1f}"

        # 4. 成交量趋势评分 (OBV)
        volume_score = 0.0
        volume_detail = ""

        if len(obv) >= self.volume_ma:
            obv_ma = (
                sum([float(o.OBV) for o in obv[-self.volume_ma :]]) / self.volume_ma
            )
            obv_curr = float(obv[-1].OBV)
            obv_prev = float(obv[-2].OBV)

            if obv_curr > obv_ma:  # OBV高于均线
                volume_score = min((obv_curr - obv_ma) / obv_ma, 1.0)
                volume_detail = f"OBV上升趋势 ({volume_score*100:.1f}%)"
            else:  # OBV低于均线
                volume_score = -min((obv_ma - obv_curr) / obv_ma, 1.0)
                volume_detail = f"OBV下降趋势 ({volume_score*100:.1f}%)"

        # 计算总分
        bull_score = (
            self.weights["trend"] * (trend_score if trend_score > 0 else 0)
            + self.weights["momentum"] * (momentum_score if momentum_score > 0 else 0)
            + self.weights["stoch"] * (stoch_score if stoch_score > 0 else 0)
            + self.weights["volume"] * (volume_score if volume_score > 0 else 0)
        )

        bear_score = (
            self.weights["trend"] * (-trend_score if trend_score < 0 else 0)
            + self.weights["momentum"] * (-momentum_score if momentum_score < 0 else 0)
            + self.weights["stoch"] * (-stoch_score if stoch_score < 0 else 0)
            + self.weights["volume"] * (-volume_score if volume_score < 0 else 0)
        )

        # 生成信号
        signal = "hold"
        reason = ""
        confidence = 0.0
        details = []

        if bull_score > bear_score and bull_score >= self.score_threshold:
            signal = "buy"
            confidence = bull_score

            if trend_score > 0:
                details.append(trend_detail)
            if momentum_score > 0:
                details.append(momentum_detail)
            if stoch_score > 0:
                details.append(stoch_detail)
            if volume_score > 0:
                details.append(volume_detail)

            # 信号强度描述
            if confidence >= 0.8:
                strength = "强"
            elif confidence >= 0.6:
                strength = "中等"
            else:
                strength = "弱"
            details.append(f"信号强度: {strength} ({confidence:.2f})")

        elif bear_score > bull_score and bear_score >= self.score_threshold:
            signal = "sell"
            confidence = bear_score

            if trend_score < 0:
                details.append(trend_detail)
            if momentum_score < 0:
                details.append(momentum_detail)
            if stoch_score < 0:
                details.append(stoch_detail)
            if volume_score < 0:
                details.append(volume_detail)

            if confidence >= 0.8:
                strength = "强"
            elif confidence >= 0.6:
                strength = "中等"
            else:
                strength = "弱"
            details.append(f"信号强度: {strength} ({confidence:.2f})")

        if details:
            reason = " | ".join(details)
        else:
            reason = "无明确信号"

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=candles[-1].date,
            confidence=round(min(1.0, confidence), 3),
            reason=reason,
            details={
                "close": curr_close,
                "adx": round(curr_adx, 2),
                "pdi": round(curr_pdi, 2),
                "ndi": round(curr_ndi, 2),
                "rsi": round(curr_rsi, 2),
                "stoch_k": round(curr_stoch_k, 2),
                "stoch_d": round(curr_stoch_d, 2),
                "trend_score": round(trend_score, 4),
                "momentum_score": round(momentum_score, 4),
                "stoch_score": round(stoch_score, 4),
                "volume_score": round(volume_score, 4),
                "bull_score": round(bull_score, 4),
                "bear_score": round(bear_score, 4),
            },
        )

def make_momentum_presets() -> Dict[str, Dict[str, Any]]:
    """
    预设参数配置
    
    包含三种交易风格:
    1. swing - 短线波段(1-2周)
    2. intermediate - 中线波段(2-4周)
    3. position - 趋势持仓(1-3月)
    
    使用场景说明:
    -------------
    
    1. Swing Trading Preset (短线波段)
       适用场景:
       - 日线级别动量突破
       - 短期趋势跟踪
       - 高波动率市场
       - 频繁交易策略
       
       风险控制:
       - 设置较紧的止损
       - 波动止损为主
       - 注意盘中走势
    
    2. Intermediate Preset (中线波段)
       适用场景:
       - 周线级别趋势跟踪
       - 中期动量策略
       - 中等波动率市场
       - 摇摆交易策略
       
       风险控制:
       - 使用趋势线止损
       - 结合动量指标
       - 关注支撑阻力
    
    3. Position Trading Preset (趋势持仓)
       适用场景:
       - 大趋势跟踪
       - 长期动量策略
       - 低波动率市场
       - 趋势跟踪策略
       
       风险控制:
       - 使用移动止损
       - 关注趋势转折
       - 注意仓位管理
    """
    
    swing = {  # 短线波段配置
        "rsi_periods": [6, 10, 14],
        "macd_params": {
            "fast": 8,
            "slow": 17,
            "signal": 9
        },
        "adx_period": 10,
        "ma_periods": [5, 10, 20],
        "volume_ma": 10,
        "weights": {
            "momentum": 0.40,
            "trend": 0.20,
            "volume": 0.25,
            "pattern": 0.15
        },
        "score_threshold": 0.60
    }
    
    intermediate = {  # 中线波段配置
        "rsi_periods": [10, 14, 21],
        "macd_params": {
            "fast": 12,
            "slow": 26,
            "signal": 9
        },
        "adx_period": 14,
        "ma_periods": [10, 20, 50],
        "volume_ma": 20,
        "weights": {
            "momentum": 0.35,
            "trend": 0.25,
            "volume": 0.20,
            "pattern": 0.20
        },
        "score_threshold": 0.65
    }
    
    position = {  # 趋势持仓配置
        "rsi_periods": [14, 21, 34],
        "macd_params": {
            "fast": 12,
            "slow": 26,
            "signal": 9
        },
        "adx_period": 21,
        "ma_periods": [20, 50, 100],
        "volume_ma": 30,
        "weights": {
            "momentum": 0.30,
            "trend": 0.35,
            "volume": 0.20,
            "pattern": 0.15
        },
        "score_threshold": 0.70
    }
    
    return {
        "swing": swing,
        "intermediate": intermediate,
        "position": position
    }