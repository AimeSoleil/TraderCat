from typing import List, Optional, Dict, Any
import math

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.strategy.signal_scorer import SignalScorer

EPS = 1e-9

class BBBreakoutStrategy(TradingStrategy):
    """
    Volatility-sensitive Bollinger Band Breakout Strategy

    Description
    -----------
    在布林带突破处捕捉短期高波动行情。设计重点:
    1. 使用较短的布林带周期(10-14天)提高敏感度
    2. 波动率和成交量指标权重占比高
    3. RSI作为过滤极端情况的确认指标
    4. 详细的信号原因描述系统

    Parameters
    ----------
    bb_period : int = 12
        布林带周期(短于传统20天以提高敏感度)
    bb_std : float = 1.8
        布林带标准差(略窄以提高信号灵敏度)
    rsi_period : int = 6
        RSI周期
    volume_window : int = 10
        成交量zscore窗口
    volume_zscore_threshold : float = 1.2
        成交量zscore阈值
    atr_period : int = 10
        ATR周期
    weights : Dict[str, float], optional
        各指标权重,默认:
        - bb: 0.35 (布林突破)
        - atr: 0.25 (波动率)
        - volume: 0.20 (成交量)
        - momentum: 0.15 (动量)
        - rsi: 0.05 (过滤)
    score_threshold : float = 0.7
        信号触发所需的最小得分
    """

    def __init__(
        self,
        bb_period: int = 12,
        bb_std: float = 1.8,
        rsi_period: int = 6,
        volume_window: int = 10,
        volume_zscore_threshold: float = 1.2,
        atr_period: int = 10,
        weights: Optional[Dict[str, float]] = None,
        score_threshold: float = 0.7,
        data_provider = None,
    ):
        self.bb_period = int(bb_period)
        self.bb_std = float(bb_std)
        self.rsi_period = int(rsi_period)
        self.volume_window = int(volume_window)
        self.volume_zscore_threshold = float(volume_zscore_threshold)
        self.atr_period = int(atr_period)
        
        # 默认权重设置
        default_weights = {
            "bb": 0.35,      # 布林突破基础权重 
            "atr": 0.25,     # 波动率权重
            "volume": 0.20,  # 成交量权重
            "momentum": 0.15,# 价格动量权重
            "rsi": 0.05,     # RSI过滤权重
        }
        
        merged = default_weights.copy()
        if weights:
            merged.update(weights)
        total = sum(merged.values())
        self.weights = {k: v/total for k,v in merged.items()}
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

    def get_name(self) -> str:
        return "VolatilityBreakout"

    def get_lookback_window(self) -> int:
        return self.bb_period + self.rsi_period + self.volume_window + self.atr_period

    def _safe(self, obj: Any, attr: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    def _volume_zscore(self, volumes: List[float], current: float) -> float:
        if not volumes:
            return 0.0
        mean = sum(volumes) / len(volumes)
        std = math.sqrt(sum((v - mean) ** 2 for v in volumes) / len(volumes))
        if std < EPS:
            return 0.0
        return (current - mean) / std

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        """生成信号,使用最后一根完整K线"""
        if not candles or len(candles) < self.bb_period + 2:
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
        atr = self.provider.get_indicator("atr", candles,
                                        {"length": self.atr_period})

        completed = candles[-1]  # 最后一根完整K线
        current_date = self._safe(completed, "date")
        
        # 基础数据
        close = float(self._safe(completed, "close", 0))
        volume = float(self._safe(completed, "volume", 0))
        
        # BB值
        bbu = self._safe(bb[-1], f"close_BBU_{self.bb_period}_{self.bb_std}")
        bbl = self._safe(bb[-1], f"close_BBL_{self.bb_period}_{self.bb_std}")
        bbm = self._safe(bb[-1], f"close_BBM_{self.bb_period}_{self.bb_std}")
        
        if None in (bbu, bbl, bbm):
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=current_date,
                reason="布林带数据缺失",
                confidence=0.0
            )

        # 计算得分
        scorer = SignalScorer()
        
        # 1. BB突破得分
        bb_break_up = close > bbu
        bb_break_down = close < bbl
        bb_score = 0.0
        if bb_break_up:
            bb_score = (close - bbu) / bbu
            bb_detail = f"向上突破{((close-bbu)/bbu*100):.1f}%"
        elif bb_break_down:
            bb_score = (bbl - close) / bbl
            bb_detail = f"向下突破{((bbl-close)/bbl*100):.1f}%"
        else:
            bb_detail = "无突破"
            
        # 2. ATR波动率得分
        curr_atr = self._safe(atr[-1], f"ATRr_{self.atr_period}")
        if curr_atr:
            atr_hist = [self._safe(atr[-i], f"ATRr_{self.atr_period}", 0) 
                       for i in range(2, self.atr_period+2)]
            atr_score = self._volume_zscore(atr_hist, curr_atr)
            atr_detail = f"ATR Z-score: {atr_score:.2f}"
        else:
            atr_score = 0.0
            atr_detail = "ATR数据不足"
            
        # 3. 成交量得分
        vol_hist = [float(self._safe(candles[-i], "volume", 0)) 
                   for i in range(2, self.volume_window+2)]
        vol_score = self._volume_zscore(vol_hist, volume)
        vol_detail = f"成交量 Z-score: {vol_score:.2f}"
        
        # 4. 动量得分
        close_hist = [float(self._safe(candles[-i], "close", 0)) 
                     for i in range(2, 5)]
        mom_score = 0.0
        if close_hist:
            mom_score = (close - sum(close_hist)/len(close_hist)) / close
            mom_detail = f"价格动量: {(mom_score*100):.1f}%"
        else:
            mom_detail = "动量数据不足"
            
        # 5. RSI过滤
        curr_rsi = self._safe(rsi[-1], f"close_RSI_{self.rsi_period}")
        rsi_score = 0.0
        if curr_rsi:
            if bb_break_up and curr_rsi < 70:  # 上突破但未超买
                rsi_score = 1.0
                rsi_detail = f"RSI支持上涨({curr_rsi:.1f})"
            elif bb_break_down and curr_rsi > 30:  # 下突破但未超卖
                rsi_score = 1.0
                rsi_detail = f"RSI支持下跌({curr_rsi:.1f})"
            else:
                rsi_detail = f"RSI={curr_rsi:.1f}"
        else:
            rsi_detail = "RSI数据不足"
                
        # 计算总分
        total_score = (
            self.weights["bb"] * abs(bb_score) +
            self.weights["atr"] * abs(atr_score) +
            self.weights["volume"] * abs(vol_score) +
            self.weights["momentum"] * abs(mom_score) +
            self.weights["rsi"] * abs(rsi_score)
        )
        
        # 生成信号
        signal = "hold"
        reasons = []
        
        if total_score >= self.score_threshold:
            if bb_break_up and mom_score > 0:
                signal = "buy"
                reasons = [
                    f"布林带突破: {bb_detail}",
                    f"波动率确认: {atr_detail}",
                    f"成交量确认: {vol_detail}",
                    f"动量确认: {mom_detail}",
                    f"RSI状态: {rsi_detail}"
                ]
            elif bb_break_down and mom_score < 0:
                signal = "sell"
                reasons = [
                    f"布林带突破: {bb_detail}",
                    f"波动率确认: {atr_detail}",
                    f"成交量确认: {vol_detail}",
                    f"动量确认: {mom_detail}",
                    f"RSI状态: {rsi_detail}"
                ]
        else:
            reasons = ["总得分未达标"] if total_score > 0 else ["无显著信号"]
                
        # 信号强度描述
        if total_score >= 0.9:
            strength = "强信号"
        elif total_score >= 0.7:
            strength = "中等信号"
        elif total_score >= self.score_threshold:
            strength = "弱信号"
        else:
            strength = "观望"
            
        reasons.append(f"信号强度: {strength} (得分:{total_score:.3f})")
                
        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=current_date,
            confidence=min(1.0, total_score),
            reason=" | ".join(reasons),
            details={
                "bb_score": round(bb_score, 4),
                "atr_score": round(atr_score, 4),
                "vol_score": round(vol_score, 4),
                "mom_score": round(mom_score, 4),
                "rsi_score": round(rsi_score, 4),
                "total_score": round(total_score, 4),
                "close": close,
                "bbu": bbu,
                "bbl": bbl,
                "curr_rsi": curr_rsi,
                "curr_atr": curr_atr,
                "strength": strength
            }
        )

def make_bb_breakout_presets() -> Dict[str, Dict[str, Any]]:
    """预设参数配置"""
    
    sensitive = {  # 敏感设置 - 短期高频
        "bb_period": 10,
        "bb_std": 1.6,
        "rsi_period": 5,
        "volume_window": 8,
        "volume_zscore_threshold": 1.0,
        "atr_period": 8,
        "weights": {
            "bb": 0.30,
            "atr": 0.30,
            "volume": 0.20,
            "momentum": 0.15,
            "rsi": 0.05
        },
        "score_threshold": 0.65
    }
    
    balanced = {  # 均衡设置 - 日内摆动
        "bb_period": 12,
        "bb_std": 1.8,
        "rsi_period": 6,
        "volume_window": 10,
        "volume_zscore_threshold": 1.2,
        "atr_period": 10,
        "weights": {
            "bb": 0.35,
            "atr": 0.25,
            "volume": 0.20,
            "momentum": 0.15,
            "rsi": 0.05
        },
        "score_threshold": 0.70
    }
    
    conservative = {  # 保守设置 - 多日持仓
        "bb_period": 14,
        "bb_std": 2.0,
        "rsi_period": 8,
        "volume_window": 12,
        "volume_zscore_threshold": 1.4,
        "atr_period": 12,
        "weights": {
            "bb": 0.40,
            "atr": 0.20,
            "volume": 0.20,
            "momentum": 0.15,
            "rsi": 0.05
        },
        "score_threshold": 0.75
    }
    
    return {
        "sensitive": sensitive,     # 适合短期高频
        "balanced": balanced,       # 适合日内摆动
        "conservative": conservative # 适合多日持仓
    }