from typing import List, Optional, Dict, Any, Tuple
import math

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.strategy.signal_scorer import SignalScorer

EPS = 1e-9

class BBDivergenceStrategy(TradingStrategy):
    """
    快速背离策略 (基于布林带)

    Description
    -----------
    专注于检测快速背离信号,使用短周期指标提高敏感度,
    同时使用布林带位置作为确认。支持:
    1. RSI背离 (短周期)
    2. MACD柱状图背离
    3. 布林带位置确认
    4. 成交量确认
    5. 价格动量确认

    Parameters
    ----------
    bb_period : int = 14
        布林带周期
    bb_std : float = 2.0
        布林带标准差
    rsi_period : int = 6  # 短周期提高敏感度
        RSI周期
    macd_params : dict = {"fast":8,"slow":17,"signal":9}
        MACD参数(使用较短周期)
    lookback_bars : int = 20
        寻找背离的回看K线数
    weights : Dict[str, float], optional
        各指标权重,默认:
        - rsi_div: 0.30 (RSI背离)
        - macd_div: 0.25 (MACD柱状图背离)
        - bb_position: 0.20 (布林带位置)
        - momentum: 0.15 (价格动量)
        - volume: 0.10 (成交量确认)
    score_threshold : float = 0.65
        信号触发所需的最小得分
    """
    def __init__(
        self,
        bb_period: int = 14,
        bb_std: float = 2.0,
        rsi_period: int = 6,
        macd_params: Optional[Dict[str, int]] = None,
        lookback_bars: int = 20,
        weights: Optional[Dict[str, float]] = None,
        score_threshold: float = 0.65,
        data_provider = None
    ):
        self.bb_period = int(bb_period)
        self.bb_std = float(bb_std)
        self.rsi_period = int(rsi_period)
        self.macd_params = macd_params or {"fast": 8, "slow": 17, "signal": 9}
        self.lookback_bars = int(lookback_bars)
        
        # 默认权重设置
        default_weights = {
            "rsi_div": 0.30,     # RSI背离权重
            "macd_div": 0.25,    # MACD背离权重
            "bb_position": 0.20,  # 布林带位置确认
            "momentum": 0.15,     # 价格动量
            "volume": 0.10,       # 成交量确认
        }
        
        # 合并自定义权重
        merged = default_weights.copy()
        if weights:
            merged.update(weights)
        
        # 归一化权重
        total = sum(merged.values())
        self.weights = {k: v/total for k,v in merged.items()}
        
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

    def get_name(self) -> str:
        return "FastDivergence(BB)"

    def get_lookback_window(self) -> int:
        return self.bb_period + self.rsi_period + self.lookback_bars

    def _safe(self, obj: Any, attr: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    def _find_swing_points(self, values: List[float], window: int = 3) -> List[Tuple[int, float, str]]:
        """查找波动极值点 (索引,值,类型)"""
        points = []
        if len(values) < window * 2 + 1:
            return points
            
        for i in range(window, len(values)-window):
            left = values[i-window:i]
            right = values[i+1:i+window+1]
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
        point_type: str
    ) -> Tuple[bool, float, str]:
        """检查背离并返回(是否背离,强度得分,详细原因)"""
        if len(price_points) < 2 or len(indicator_points) < 2:
            return False, 0.0, ""
            
        # 仅比较最近两个极值点
        p1, p2 = price_points[-2:]
        i1, i2 = indicator_points[-2:]
        
        details = []
        if point_type == "low":
            price_div = p2[1] < p1[1]  # 价格更低
            ind_div = i2[1] > i1[1]    # 指标更高
            if price_div and ind_div:
                price_change = (p2[1] - p1[1])/abs(p1[1]) * 100
                ind_change = (i2[1] - i1[1])/abs(i1[1]) * 100
                details.extend([
                    f"价格创新低: {price_change:.1f}%",
                    f"指标走高: +{ind_change:.1f}%"
                ])
                strength = min(abs(price_change), abs(ind_change)) / 100
                return True, strength, " | ".join(details)
                
        elif point_type == "high":
            price_div = p2[1] > p1[1]  # 价格更高
            ind_div = i2[1] < i1[1]    # 指标更低
            if price_div and ind_div:
                price_change = (p2[1] - p1[1])/abs(p1[1]) * 100
                ind_change = (i2[1] - i1[1])/abs(i1[1]) * 100
                details.extend([
                    f"价格创新高: +{price_change:.1f}%",
                    f"指标走低: {ind_change:.1f}%"
                ])
                strength = min(abs(price_change), abs(ind_change)) / 100
                return True, strength, " | ".join(details)
                
        return False, 0.0, ""

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        """生成信号,使用最后一根完整K线"""
        if not candles or len(candles) < max(self.bb_period, self.lookback_bars) + 2:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=self._safe(candles[-1] if candles else None, "date"),
                reason="数据不足",
                confidence=0.0
            )
            
        # 获取指标
        bb = self.provider.get_indicator("bbands", candles, 
                                       {"length": self.bb_period, "std": self.bb_std})
        rsi = self.provider.get_indicator("rsi", candles,
                                        {"length": self.rsi_period})
        macd = self.provider.get_indicator("macd", candles, self.macd_params)
        
        completed = candles[-1]
        current_date = self._safe(completed, "date")
        close = float(self._safe(completed, "close", 0))
        
        # 获取历史数据用于寻找极值点
        closes = [float(self._safe(c, "close", 0)) for c in candles[-self.lookback_bars:]]
        volumes = [float(self._safe(c, "volume", 0)) for c in candles[-self.lookback_bars:]]
        
        rsi_values = []
        macd_hist = []
        for i in range(min(self.lookback_bars, len(candles))):
            if i >= len(rsi):
                break
            r = self._safe(rsi[-i-1], f"close_RSI_{self.rsi_period}")
            if r is not None:
                rsi_values.append(r)
                
            if i >= len(macd):
                continue
            m = self._safe(macd[-i-1], "macd")
            s = self._safe(macd[-i-1], "signal")
            if m is not None and s is not None:
                macd_hist.append(m - s)
                
        # 查找极值点
        price_points = self._find_swing_points(closes)
        rsi_points = self._find_swing_points(rsi_values)
        macd_points = self._find_swing_points(macd_hist)
        
        # 计算得分
        scorer = SignalScorer()
        signal_details = []
        
        # 1. RSI背离得分
        rsi_bull_div, rsi_bull_strength, rsi_bull_detail = self._check_divergence(
            price_points, rsi_points, "low")
        rsi_bear_div, rsi_bear_strength, rsi_bear_detail = self._check_divergence(
            price_points, rsi_points, "high")
            
        # 2. MACD柱状图背离得分
        macd_bull_div, macd_bull_strength, macd_bull_detail = self._check_divergence(
            price_points, macd_points, "low")
        macd_bear_div, macd_bear_strength, macd_bear_detail = self._check_divergence(
            price_points, macd_points, "high")
            
        # 3. 布林带位置得分
        bbu = self._safe(bb[-1], f"close_BBU_{self.bb_period}_{self.bb_std}")
        bbl = self._safe(bb[-1], f"close_BBL_{self.bb_period}_{self.bb_std}")
        bbm = self._safe(bb[-1], f"close_BBM_{self.bb_period}_{self.bb_std}")
        
        bb_score = 0.0
        bb_detail = ""
        if None not in (bbu, bbl, bbm):
            if close < bbl:  # 靠近下轨利于做多
                bb_score = (bbl - close) / bbl
                bb_detail = f"价格位于布林下轨下方 ({(bb_score*100):.1f}%)"
            elif close > bbu:  # 靠近上轨利于做空
                bb_score = (close - bbu) / bbu
                bb_detail = f"价格位于布林上轨上方 ({(bb_score*100):.1f}%)"
                
        # 4. 动量得分
        mom_score = 0.0
        mom_detail = ""
        if len(closes) >= 3:
            mom_score = (closes[-1] - sum(closes[-3:])/3) / closes[-1]
            mom_detail = f"短期动量: {(mom_score*100):.1f}%"
            
        # 5. 成交量确认
        vol_score = 0.0
        vol_detail = ""
        if len(volumes) >= 2:
            curr_vol = volumes[-1]
            avg_vol = sum(volumes[:-1])/len(volumes[:-1])
            if avg_vol > 0:
                vol_score = (curr_vol - avg_vol) / avg_vol
                vol_detail = f"成交量较均值: {(vol_score*100):+.1f}%"
                
        # 计算总分并确定方向
        bull_score = (
            self.weights["rsi_div"] * rsi_bull_strength +
            self.weights["macd_div"] * macd_bull_strength +
            self.weights["bb_position"] * (bb_score if bb_score < 0 else 0) +
            self.weights["momentum"] * (-mom_score if mom_score < 0 else 0) +
            self.weights["volume"] * (vol_score if vol_score > 0 else 0)
        )
        
        bear_score = (
            self.weights["rsi_div"] * rsi_bear_strength +
            self.weights["macd_div"] * macd_bear_strength +
            self.weights["bb_position"] * (bb_score if bb_score > 0 else 0) +
            self.weights["momentum"] * (mom_score if mom_score > 0 else 0) +
            self.weights["volume"] * (vol_score if vol_score > 0 else 0)
        )
        
        # 生成信号
        signal = "hold"
        reason = ""
        confidence = 0.0
        
        if bull_score > bear_score and bull_score >= self.score_threshold:
            signal = "buy"
            confidence = bull_score
            
            # 收集详细原因
            if rsi_bull_div:
                signal_details.append(f"RSI底部背离 ({rsi_bull_detail})")
            if macd_bull_div:
                signal_details.append(f"MACD柱状图底部背离 ({macd_bull_detail})")
            if bb_score < 0:
                signal_details.append(bb_detail)
            if mom_score < 0:
                signal_details.append(mom_detail)
            if vol_score > 0:
                signal_details.append(vol_detail)
                
            # 添加信号强度描述
            if confidence >= 0.8:
                strength = "强"
            elif confidence >= 0.65:
                strength = "中等"
            else:
                strength = "弱"
            signal_details.append(f"信号强度: {strength} ({confidence:.2f})")
            
            reason = " | ".join(signal_details)
            
        elif bear_score > bull_score and bear_score >= self.score_threshold:
            signal = "sell"
            confidence = bear_score
            
            if rsi_bear_div:
                signal_details.append(f"RSI顶部背离 ({rsi_bear_detail})")
            if macd_bear_div:
                signal_details.append(f"MACD柱状图顶部背离 ({macd_bear_detail})")
            if bb_score > 0:
                signal_details.append(bb_detail)
            if mom_score > 0:
                signal_details.append(mom_detail)
            if vol_score > 0:
                signal_details.append(vol_detail)
                
            if confidence >= 0.8:
                strength = "强"
            elif confidence >= 0.65:
                strength = "中等"
            else:
                strength = "弱"
            signal_details.append(f"信号强度: {strength} ({confidence:.2f})")
            
            reason = " | ".join(signal_details)
        else:
            reason = "无有效背离信号"
            
        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=current_date,
            confidence=round(min(1.0, confidence), 3),
            reason=reason,
            details={
                "close": close,
                "bbu": bbu,
                "bbl": bbl,
                "bbm": bbm,
                "bb_score": round(bb_score, 4),
                "rsi_bull_div": rsi_bull_div,
                "rsi_bear_div": rsi_bear_div,
                "macd_bull_div": macd_bull_div,
                "macd_bear_div": macd_bear_div,
                "momentum_score": round(mom_score, 4),
                "volume_score": round(vol_score, 4),
                "bull_score": round(bull_score, 4),
                "bear_score": round(bear_score, 4)
            }
        )

def make_bb_divergence_presets() -> Dict[str, Dict[str, Any]]:
    """预设参数配置"""
    
    sensitive = {
        "bb_period": 12,
        "bb_std": 1.8,
        "rsi_period": 5,
        "macd_params": {"fast": 6, "slow": 15, "signal": 9},
        "lookback_bars": 15,
        "weights": {
            "rsi_div": 0.35,
            "macd_div": 0.25,
            "bb_position": 0.20,
            "momentum": 0.12,
            "volume": 0.08
        },
        "score_threshold": 0.60
    }
    
    balanced = {
        "bb_period": 14,
        "bb_std": 2.0,
        "rsi_period": 6,
        "macd_params": {"fast": 8, "slow": 17, "signal": 9},
        "lookback_bars": 20,
        "weights": {
            "rsi_div": 0.30,
            "macd_div": 0.25,
            "bb_position": 0.20,
            "momentum": 0.15,
            "volume": 0.10
        },
        "score_threshold": 0.65
    }
    
    conservative = {
        "bb_period": 16,
        "bb_std": 2.2,
        "rsi_period": 8,
        "macd_params": {"fast": 10, "slow": 20, "signal": 9},
        "lookback_bars": 25,
        "weights": {
            "rsi_div": 0.25,
            "macd_div": 0.25,
            "bb_position": 0.25,
            "momentum": 0.15,
            "volume": 0.10
        },
        "score_threshold": 0.70
    }
    
    return {
        "sensitive": sensitive,
        "balanced": balanced, 
        "conservative": conservative
    }