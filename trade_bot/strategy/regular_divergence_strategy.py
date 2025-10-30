from typing import List, Optional, Dict, Any, Tuple
import math

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

class RegularDivergenceStrategy(TradingStrategy):
    """
    多周期正常背离策略
    
    策略特点:
    ----------
    1. 基于日线识别短期背离机会
    2. 结合多周期指标确认
    3. 使用成交量趋势验证
    4. 适合波段和趋势交易
    
    主要应用场景:
    ----------
    1. 日线级别背离交易
    2. 周线级别趋势确认
    3. 波段交易和趋势跟踪
    4. 适合波动率中等的市场
    
    背离识别规则:
    ----------
    1. 短期背离(1-3天):
       - RSI背离信号
       - MACD柱状图背离
       - 成交量支持
       
    2. 中期背离(3-5天):
       - 价格创新高/低
       - 指标确认背离
       - OBV趋势验证
       
    3. 长期背离(5天以上):
       - 主要趋势确认
       - 关键位置背离
       - 多重指标共振
    
    参数说明:
    ----------
    rsi_periods: List[int]
        RSI多周期设置 [短期, 中期, 长期]
    macd_params: Dict
        MACD参数配置
    lookback_periods: List[int]
        背离查找周期 [短期, 中期, 长期]
    volume_ma: int
        成交量均线周期
    """
    
    def __init__(
        self,
        rsi_periods: Optional[List[int]] = None,
        macd_params: Optional[Dict[str, int]] = None,
        lookback_periods: Optional[List[int]] = None,
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
        self.lookback_periods = lookback_periods or [10, 20, 40]  # 短中长期回看
        self.volume_ma = volume_ma
        
        # 默认权重配置
        default_weights = {
            "divergence": 0.40,  # 背离信号权重
            "trend": 0.25,      # 趋势方向权重
            "momentum": 0.20,   # 动量指标权重
            "volume": 0.15      # 成交量权重
        }
        
        merged = default_weights.copy()
        if weights:
            merged.update(weights)
        total = sum(merged.values())
        self.weights = {k: v/total for k,v in merged.items()}
        
        self.score_threshold = score_threshold
        self.provider = data_provider

    def get_name(self) -> str:
        return "RegularDivergence(RSI+MACD+OBV)"

    def get_lookback_window(self) -> int:
        return max(max(self.rsi_periods), max(self.lookback_periods)) + self.volume_ma

    def _find_extremes(
        self, 
        values: List[float], 
        window: int = 3
    ) -> List[Tuple[int, float, str]]:
        """查找极值点: [(index, value, type)]"""
        result = []
        if len(values) < window * 2 + 1:
            return result
            
        for i in range(window, len(values)-window):
            left = values[i-window:i]
            right = values[i+1:i+window+1]
            curr = values[i]
            
            if curr > max(left) and curr > max(right):
                result.append((i, curr, "high"))
            elif curr < min(left) and curr < min(right):
                result.append((i, curr, "low"))
                
        return result

    def _check_divergence(
        self,
        price_points: List[Tuple[int, float, str]],
        indicator_points: List[Tuple[int, float, str]],
        point_type: str
    ) -> Tuple[bool, float, str]:
        """检查背离: (是否背离, 强度, 详细说明)"""
        if len(price_points) < 2 or len(indicator_points) < 2:
            return False, 0.0, ""
            
        p1, p2 = price_points[-2:]  # 最近两个价格极值
        i1, i2 = indicator_points[-2:]  # 最近两个指标极值
        
        details = []
        if point_type == "low":  # 底背离
            price_div = p2[1] < p1[1]  # 价格更低
            ind_div = i2[1] > i1[1]    # 指标更高
            
            if price_div and ind_div:
                price_chg = (p2[1] - p1[1])/p1[1] * 100
                ind_chg = (i2[1] - i1[1])/i1[1] * 100
                details.extend([
                    f"价格新低: {price_chg:.1f}%",
                    f"指标走高: +{ind_chg:.1f}%"
                ])
                strength = min(abs(price_chg), abs(ind_chg))/100
                return True, strength, " | ".join(details)
                
        elif point_type == "high":  # 顶背离
            price_div = p2[1] > p1[1]  # 价格更高
            ind_div = i2[1] < i1[1]    # 指标更低
            
            if price_div and ind_div:
                price_chg = (p2[1] - p1[1])/p1[1] * 100
                ind_chg = (i2[1] - i1[1])/i1[1] * 100
                details.extend([
                    f"价格新高: +{price_chg:.1f}%",
                    f"指标走低: {ind_chg:.1f}%"
                ])
                strength = min(abs(price_chg), abs(ind_chg))/100
                return True, strength, " | ".join(details)
                
        return False, 0.0, ""

    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """生成信号"""
        if not candles or len(candles) < self.lookback_bars + 2:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date if candles else None,
                reason="数据不足",
                confidence=0.0
            )

        # 获取指标数据
        rsi = self.provider.get_indicator("rsi", candles, 
                                        {"length": self.rsi_period})
        macd = self.provider.get_indicator("macd", candles, 
                                         self.macd_params)
        obv = self.provider.get_indicator("obv", candles, {})
        
        # 提取最近的历史数据
        closes = []
        volumes = []
        rsi_values = []
        macd_hist = []
        obv_values = []
        
        for i in range(min(self.lookback_bars, len(candles))):
            candle = candles[-i-1]
            closes.append(float(candle.close))
            volumes.append(float(candle.volume))
            
            if i < len(rsi):
                r = getattr(rsi[-i-1], f"close_RSI_{self.rsi_period}", None)
                if r is not None:
                    rsi_values.append(float(r))
                    
            if i < len(macd):
                m = getattr(macd[-i-1], "macd", None)
                s = getattr(macd[-i-1], "signal", None)
                if m is not None and s is not None:
                    macd_hist.append(float(m - s))
                    
            if i < len(obv):
                o = getattr(obv[-i-1], "OBV", None)
                if o is not None:
                    obv_values.append(float(o))
                    
        # 查找极值点
        price_points = self._find_extremes(closes)
        rsi_points = self._find_extremes(rsi_values)
        macd_points = self._find_extremes(macd_hist)
        
        # 检查RSI背离
        rsi_bull, rsi_bull_str, rsi_bull_detail = self._check_divergence(
            price_points, rsi_points, "low")
        rsi_bear, rsi_bear_str, rsi_bear_detail = self._check_divergence(
            price_points, rsi_points, "high")
            
        # 检查MACD柱状图背离
        macd_bull, macd_bull_str, macd_bull_detail = self._check_divergence(
            price_points, macd_points, "low")
        macd_bear, macd_bear_str, macd_bear_detail = self._check_divergence(
            price_points, macd_points, "high")
            
        # OBV趋势确认
        obv_score = 0.0
        obv_detail = ""
        if len(obv_values) >= 2:
            obv_ma = sum(obv_values[-self.volume_ma:])/self.volume_ma
            obv_curr = obv_values[-1]
            obv_prev = obv_values[-2]
            
            if obv_curr > obv_ma:  # 高于均线看涨
                obv_score = min((obv_curr - obv_ma)/obv_ma, 1.0)
                obv_detail = f"OBV高于均线: +{obv_score*100:.1f}%"
            else:  # 低于均线看跌
                obv_score = max((obv_curr - obv_ma)/obv_ma, -1.0)
                obv_detail = f"OBV低于均线: {obv_score*100:.1f}%"
                
        # 成交量确认
        vol_score = 0.0
        vol_detail = ""
        if len(volumes) >= 2:
            vol_ma = sum(volumes[:-1])/len(volumes[:-1])
            vol_curr = volumes[-1]
            if vol_ma > 0:
                vol_score = (vol_curr - vol_ma)/vol_ma
                vol_detail = f"量能较均值: {vol_score*100:+.1f}%"
                
        # 计算总分
        bull_score = (
            self.weights["rsi"] * rsi_bull_str +
            self.weights["macd"] * macd_bull_str +
            self.weights["obv"] * (obv_score if obv_score > 0 else 0) +
            self.weights["volume"] * (vol_score if vol_score > 0 else 0)
        )
        
        bear_score = (
            self.weights["rsi"] * rsi_bear_str +
            self.weights["macd"] * macd_bear_str +
            self.weights["obv"] * (-obv_score if obv_score < 0 else 0) +
            self.weights["volume"] * (vol_score if vol_score > 0 else 0)
        )
        
        # 生成信号
        signal = "hold"
        reason = ""
        confidence = 0.0
        details = []
        
        if bull_score > bear_score and bull_score >= self.score_threshold:
            signal = "buy"
            confidence = bull_score
            
            if rsi_bull:
                details.append(f"RSI底背离 ({rsi_bull_detail})")
            if macd_bull:
                details.append(f"MACD柱底背离 ({macd_bull_detail})")
            if obv_score > 0:
                details.append(obv_detail)
            if vol_score > 0:
                details.append(vol_detail)
                
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
            
            if rsi_bear:
                details.append(f"RSI顶背离 ({rsi_bear_detail})")
            if macd_bear:
                details.append(f"MACD柱顶背离 ({macd_bear_detail})")
            if obv_score < 0:
                details.append(obv_detail)
            if vol_score > 0:
                details.append(vol_detail)
                
            if confidence >= 0.8:
                strength = "强"
            elif confidence >= 0.6:
                strength = "中等"
            else:
                strength = "弱"
            details.append(f"信号强度: {strength} ({confidence:.2f})")
            
        else:
            reason = "无有效背离信号"
            
        if details:
            reason = " | ".join(details)
            
        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=candles[-1].date,
            confidence=round(min(1.0, confidence), 3),
            reason=reason,
            details={
                "close": closes[-1],
                "rsi_bull": rsi_bull,
                "rsi_bear": rsi_bear,
                "macd_bull": macd_bull,
                "macd_bear": macd_bear,
                "obv_score": round(obv_score, 4),
                "volume_score": round(vol_score, 4),
                "bull_score": round(bull_score, 4),
                "bear_score": round(bear_score, 4)
            }
        )

def make_divergence_presets() -> Dict[str, Dict[str, Any]]:
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
       - 日线级别背离交易
       - 短期趋势反转
       - 高波动率市场
       - 快速交易策略
       
       背离确认要点:
       - RSI(10)背离确认
       - MACD(8,17,9)背离
       - 短期成交量支持
       
       风险控制:
       - 背离失效快速止损
       - 设置较紧止损位
       - 注意盘中走势
    
    2. Intermediate Preset (中线波段)
       适用场景:
       - 周线级别背离
       - 中期趋势转折
       - 中等波动率市场
       - 摇摆交易策略
       
       背离确认要点:
       - RSI(14)背离确认
       - MACD标准参数背离
       - OBV趋势验证
       
       风险控制:
       - 使用趋势线止损
       - 结合支撑阻力位
       - 分批建仓/减仓
    
    3. Position Trading Preset (趋势持仓)
       适用场景:
       - 大周期背离信号
       - 主要趋势转折
       - 低波动率市场
       - 趋势跟踪策略
       
       背离确认要点:
       - RSI(21)背离确认
       - MACD长周期背离
       - 多重指标共振
       
       风险控制:
       - 使用移动止损
       - 关注趋势线支撑
       - 控制好仓位比例
    """
    
    swing = {  # 短线波段配置
        "rsi_periods": [6, 10, 14],
        "macd_params": {
            "fast": 8,
            "slow": 17,
            "signal": 9
        },
        "lookback_periods": [5, 10, 20],
        "volume_ma": 10,
        "weights": {
            "divergence": 0.45,
            "trend": 0.20,
            "momentum": 0.20,
            "volume": 0.15
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
        "lookback_periods": [10, 20, 40],
        "volume_ma": 20,
        "weights": {
            "divergence": 0.40,
            "trend": 0.25,
            "momentum": 0.20,
            "volume": 0.15
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
        "lookback_periods": [20, 40, 60],
        "volume_ma": 30,
        "weights": {
            "divergence": 0.35,
            "trend": 0.30,
            "momentum": 0.20,
            "volume": 0.15
        },
        "score_threshold": 0.70
    }
    
    return {
        "swing": swing,
        "intermediate": intermediate,
        "position": position
    }