from typing import List, Optional, Dict, Any, Tuple
import math

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

class HiddenDivergenceStrategy(TradingStrategy):
    """
    隐藏背离策略

    特点:
    1. 检测RSI和MACD的隐藏背离
    2. 使用OBV确认趋势持续性
    3. 布林带位置作为趋势过滤
    4. 权重打分系统

    Parameters
    ----------
    bb_period: int = 20
        布林带周期
    bb_std: float = 2.0
        布林带标准差
    rsi_period: int = 14
        RSI周期
    macd_params: dict 
        MACD参数
    lookback_bars: int = 20
        寻找背离的历史K线数
    weights: dict
        各指标权重:
        - rsi_div: RSI隐藏背离
        - macd_div: MACD隐藏背离
        - obv: OBV趋势确认
        - bb: 布林带趋势过滤
        - volume: 成交量确认
    score_threshold: float = 0.65
        信号触发阈值
    """
    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        macd_params: Optional[Dict[str, int]] = None,
        lookback_bars: int = 20,
        weights: Optional[Dict[str, float]] = None,
        score_threshold: float = 0.65,
        data_provider = None
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.lookback_bars = lookback_bars
        
        # 默认权重配置
        default_weights = {
            "rsi_div": 0.35,   # RSI隐藏背离权重
            "macd_div": 0.25,  # MACD隐藏背离权重
            "obv": 0.20,       # OBV趋势确认
            "bb": 0.12,        # 布林带趋势过滤
            "volume": 0.08     # 成交量确认
        }
        
        # 合并权重
        merged = default_weights.copy()
        if weights:
            merged.update(weights)
            
        # 归一化权重
        total = sum(merged.values())
        self.weights = {k: v/total for k,v in merged.items()}
        
        self.score_threshold = score_threshold
        self.provider = data_provider
        
    def get_name(self) -> str:
        return "HiddenDivergence"

    def get_lookback_window(self) -> int:
        return max(self.lookback_bars, self.bb_period + self.rsi_period)

    def _safe(self, obj: Any, attr: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

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

    def _check_hidden_divergence(
        self,
        price_points: List[Tuple[int, float, str]],
        indicator_points: List[Tuple[int, float, str]],
        point_type: str
    ) -> Tuple[bool, float, str]:
        """检查隐藏背离: (是否背离, 强度, 详细说明)"""
        if len(price_points) < 2 or len(indicator_points) < 2:
            return False, 0.0, ""
            
        p1, p2 = price_points[-2:]  # 最近两个价格极值
        i1, i2 = indicator_points[-2:]  # 最近两个指标极值
        
        details = []
        if point_type == "low":  # 看涨隐藏背离
            price_div = p2[1] > p1[1]  # 价格更高
            ind_div = i2[1] < i1[1]    # 指标更低
            
            if price_div and ind_div:
                price_chg = (p2[1] - p1[1])/p1[1] * 100
                ind_chg = (i2[1] - i1[1])/i1[1] * 100
                details.extend([
                    f"价格较高: +{price_chg:.1f}%",
                    f"指标较低: {ind_chg:.1f}%"
                ])
                strength = min(abs(price_chg), abs(ind_chg))/100
                return True, strength, " | ".join(details)
                
        elif point_type == "high":  # 看跌隐藏背离
            price_div = p2[1] < p1[1]  # 价格更低
            ind_div = i2[1] > i1[1]    # 指标更高
            
            if price_div and ind_div:
                price_chg = (p2[1] - p1[1])/p1[1] * 100
                ind_chg = (i2[1] - i1[1])/i1[1] * 100
                details.extend([
                    f"价格较低: {price_chg:.1f}%",
                    f"指标较高: +{ind_chg:.1f}%"
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
        bb = self.provider.get_indicator("bbands", candles, 
                                       {"length": self.bb_period, "std": self.bb_std})
        rsi = self.provider.get_indicator("rsi", candles, 
                                        {"length": self.rsi_period})
        macd = self.provider.get_indicator("macd", candles, 
                                         self.macd_params)
        obv = self.provider.get_indicator("obv", candles, {})
        
        # 提取历史数据
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
                name_val = f'close_MACD_{self.macd_params["fast"]}_{self.macd_params["slow"]}_{self.macd_params["signal"]}'
                name_sig = f'close_MACDs_{self.macd_params["fast"]}_{self.macd_params["slow"]}_{self.macd_params["signal"]}'
                m = self._safe(macd[-i-1], name_val)
                s = self._safe(macd[-i-1], name_sig)
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
        
        # 检查隐藏背离
        rsi_bull_hidden, rsi_bull_str, rsi_bull_detail = self._check_hidden_divergence(
            price_points, rsi_points, "low")
        rsi_bear_hidden, rsi_bear_str, rsi_bear_detail = self._check_hidden_divergence(
            price_points, rsi_points, "high")
            
        macd_bull_hidden, macd_bull_str, macd_bull_detail = self._check_hidden_divergence(
            price_points, macd_points, "low")
        macd_bear_hidden, macd_bear_str, macd_bear_detail = self._check_hidden_divergence(
            price_points, macd_points, "high")
            
        # 布林带趋势过滤
        close = closes[-1]
        bbu = self._safe(bb[-1], f"close_BBU_{self.bb_period}_{self.bb_std}")
        bbl = self._safe(bb[-1], f"close_BBL_{self.bb_period}_{self.bb_std}")
        bbm = self._safe(bb[-1], f"close_BBM_{self.bb_period}_{self.bb_std}")
        
        bb_score = 0.0
        bb_detail = ""
        if None not in (bbu, bbl, bbm):
            bb_pos = (close - bbm) / (bbu - bbl) if bbu > bbl else 0
            if bb_pos > 0:  # 上方看涨
                bb_score = min(bb_pos, 1.0)
                bb_detail = f"价格位于布林带上方 ({bb_pos:.2f})"
            else:  # 下方看跌
                bb_score = max(bb_pos, -1.0)
                bb_detail = f"价格位于布林带下方 ({bb_pos:.2f})"
                
        # OBV趋势确认
        obv_score = 0.0
        obv_detail = ""
        if len(obv_values) >= 2:
            obv_sma = sum(obv_values[-20:])/20 if len(obv_values) >= 20 else sum(obv_values)/len(obv_values)
            obv_curr = obv_values[-1]
            obv_chg = (obv_curr - obv_sma)/abs(obv_sma) if abs(obv_sma) > EPS else 0
            obv_score = max(min(obv_chg, 1.0), -1.0)
            obv_detail = f"OBV趋势: {obv_chg:+.1%}"
            
        # 成交量确认
        vol_score = 0.0
        vol_detail = ""
        if len(volumes) >= 2:
            vol_sma = sum(volumes[-20:])/20 if len(volumes) >= 20 else sum(volumes)/len(volumes)
            vol_curr = volumes[-1]
            vol_chg = (vol_curr - vol_sma)/vol_sma if vol_sma > 0 else 0
            vol_score = max(min(vol_chg, 1.0), -1.0)
            vol_detail = f"成交量: {vol_chg:+.1%}"
            
        # 计算总分
        bull_score = (
            self.weights["rsi_div"] * rsi_bull_str +
            self.weights["macd_div"] * macd_bull_str +
            self.weights["obv"] * (obv_score if obv_score > 0 else 0) +
            self.weights["bb"] * (bb_score if bb_score > 0 else 0) +
            self.weights["volume"] * (vol_score if vol_score > 0 else 0)
        )
        
        bear_score = (
            self.weights["rsi_div"] * rsi_bear_str +
            self.weights["macd_div"] * macd_bear_str +
            self.weights["obv"] * (-obv_score if obv_score < 0 else 0) +
            self.weights["bb"] * (-bb_score if bb_score < 0 else 0) +
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
            
            if rsi_bull_hidden:
                details.append(f"RSI看涨隐藏背离 ({rsi_bull_detail})")
            if macd_bull_hidden:
                details.append(f"MACD看涨隐藏背离 ({macd_bull_detail})")
            if bb_score > 0:
                details.append(bb_detail)
            if obv_score > 0:
                details.append(obv_detail)
            if vol_score > 0:
                details.append(vol_detail)
                
            # 信号强度描述
            if confidence >= 0.8:
                strength = "强"
            elif confidence >= 0.65:
                strength = "中等"
            else:
                strength = "弱"
            details.append(f"信号强度: {strength} ({confidence:.2f})")
            
        elif bear_score > bull_score and bear_score >= self.score_threshold:
            signal = "sell"
            confidence = bear_score
            
            if rsi_bear_hidden:
                details.append(f"RSI看跌隐藏背离 ({rsi_bear_detail})")
            if macd_bear_hidden:
                details.append(f"MACD看跌隐藏背离 ({macd_bear_detail})")
            if bb_score < 0:
                details.append(bb_detail)
            if obv_score < 0:
                details.append(obv_detail)
            if vol_score > 0:
                details.append(vol_detail)
                
            if confidence >= 0.8:
                strength = "强"
            elif confidence >= 0.65:
                strength = "中等"
            else:
                strength = "弱"
            details.append(f"信号强度: {strength} ({confidence:.2f})")
            
        else:
            reason = "无有效隐藏背离信号"
            
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
                "close": close,
                "rsi_bull_hidden": rsi_bull_hidden,
                "rsi_bear_hidden": rsi_bear_hidden,
                "macd_bull_hidden": macd_bull_hidden,
                "macd_bear_hidden": macd_bear_hidden,
                "bb_score": round(bb_score, 4),
                "obv_score": round(obv_score, 4),
                "volume_score": round(vol_score, 4),
                "bull_score": round(bull_score, 4),
                "bear_score": round(bear_score, 4)
            }
        )

def make_hidden_divergence_presets() -> Dict[str, Dict[str, Any]]:
    """预设参数配置"""
    
    sensitive = {
        "bb_period": 16,
        "bb_std": 1.8,
        "rsi_period": 10,
        "macd_params": {"fast": 8, "slow": 17, "signal": 9},
        "lookback_bars": 15,
        "weights": {
            "rsi_div": 0.40,
            "macd_div": 0.25,
            "obv": 0.20,
            "bb": 0.10,
            "volume": 0.05
        },
        "score_threshold": 0.60
    }
    
    balanced = {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "lookback_bars": 20,
        "weights": {
            "rsi_div": 0.35,
            "macd_div": 0.25,
            "obv": 0.20,
            "bb": 0.12,
            "volume": 0.08
        },
        "score_threshold": 0.65
    }
    
    conservative = {
        "bb_period": 24,
        "bb_std": 2.2,
        "rsi_period": 16,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "lookback_bars": 25,
        "weights": {
            "rsi_div": 0.30,
            "macd_div": 0.30,
            "obv": 0.20,
            "bb": 0.15,
            "volume": 0.05
        },
        "score_threshold": 0.70
    }
    
    return {
        "sensitive": sensitive,
        "balanced": balanced,
        "conservative": conservative
    }