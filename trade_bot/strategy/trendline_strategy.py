import math
from typing import List, Optional, Dict, Any, Tuple
import numpy as np
from datetime import datetime

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

class TrendlineStrategy(TradingStrategy):
    """
    多周期趋势线波段策略
    
    核心功能:
    1. 多周期趋势分析
    2. 智能趋势线识别
    3. 波段特征识别
    4. 动量突破确认
    
    参数说明:
    ----------
    lookback_days: int 
        趋势线回看天数
    min_touch_points: int
        趋势线最少接触点
    trend_ma_periods: List[int]
        多周期均线周期[短期,中期,长期]
    momentum_params: Dict
        动量指标参数
    volume_ma: int
        成交量均线周期
    """
    
    def __init__(
        self,
        lookback_days: int = 30,
        min_touch_points: int = 3,
        trend_ma_periods: Optional[List[int]] = None,
        momentum_params: Optional[Dict[str, int]] = None,
        volume_ma: int = 20,
        weights: Optional[Dict[str, float]] = None,
        score_threshold: float = 0.6,
        data_provider = None
    ):
        self.lookback_days = lookback_days
        self.min_touch_points = min_touch_points
        self.trend_ma_periods = trend_ma_periods or [10, 20, 50]  # 短中长期
        self.momentum_params = momentum_params or {
            "rsi_period": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9
        }
        self.volume_ma = volume_ma
        
        # 默认权重配置
        default_weights = {
            "trendline": 0.30,  # 趋势线权重
            "ma_trend": 0.25,   # 均线趋势权重
            "momentum": 0.25,   # 动量指标权重
            "pattern": 0.20     # 形态特征权重
        }
        
        merged = default_weights.copy()
        if weights:
            merged.update(weights)
        total = sum(merged.values())
        self.weights = {k: v/total for k,v in merged.items()}
        
        self.score_threshold = score_threshold
        self.provider = data_provider
        
    def get_name(self) -> str:
        return "SwingTrendline"

    def get_lookback_window(self) -> int:
        return max(
            (max(self.trend_ma_periods) + self.volume_ma), 
            self.lookback_days
        )
        
    def _find_swing_points(
        self,
        highs: List[float],
        lows: List[float],
        window: int = 5  # 约一周
    ) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
        """查找波动极值点"""
        high_points = []
        low_points = []
        
        for i in range(window, len(highs)-window):
            # 高点
            left_highs = highs[i-window:i]
            right_highs = highs[i+1:i+window+1]
            
            if highs[i] > max(left_highs) and highs[i] > max(right_highs):
                high_points.append((i, highs[i]))
                
            # 低点
            left_lows = lows[i-window:i]
            right_lows = lows[i+1:i+window+1]
            
            if lows[i] < min(left_lows) and lows[i] < min(right_lows):
                low_points.append((i, lows[i]))
                
        return high_points, low_points
        
    def _fit_trendline(
        self,
        points: List[Tuple[int, float]],
        min_points: int = 3
    ) -> Tuple[float, float, float]:
        """拟合趋势线并返回R方值"""
        if len(points) < min_points:
            return 0, 0, 0
            
        x = np.array([p[0] for p in points])
        y = np.array([p[1] for p in points])
        
        # 线性回归
        A = np.vstack([x, np.ones(len(x))]).T
        slope, intercept = np.linalg.lstsq(A, y, rcond=None)[0]
        
        # 计算R方值
        y_pred = slope * x + intercept
        r_squared = 1 - np.sum((y - y_pred) ** 2) / np.sum((y - np.mean(y)) ** 2)
        
        return slope, intercept, r_squared
        
    def _analyze_ma_trend(
        self,
        closes: List[float],
        periods: List[int]
    ) -> Tuple[str, float]:
        """分析多周期均线趋势"""
        if len(closes) < max(periods):
            return "neutral", 0.0
            
        ma_values = []
        for period in periods:
            ma = sum(closes[-period:]) / period
            ma_values.append(ma)
            
        # 检查均线排列
        curr_price = closes[-1]
        ma_short, ma_mid, ma_long = ma_values
        
        if ma_short > ma_mid > ma_long and curr_price > ma_short:
            strength = min((curr_price - ma_long) / ma_long, 1.0)
            return "up", strength
        elif ma_short < ma_mid < ma_long and curr_price < ma_short:
            strength = min((ma_long - curr_price) / curr_price, 1.0)
            return "down", strength
        else:
            return "neutral", 0.0
            
    def _identify_pattern(
        self,
        highs: List[float],
        lows: List[float],
        closes: List[float],
        window: int = 20
    ) -> Tuple[str, float]:
        """识别价格形态"""
        if len(closes) < window:
            return "none", 0.0
            
        recent = closes[-window:]
        high = max(highs[-window:])
        low = min(lows[-window:])
        curr = closes[-1]
        
        # 计算波动范围
        range_size = high - low
        if range_size == 0:
            return "none", 0.0
            
        # 识别形态
        upper_quarter = high - range_size * 0.25
        lower_quarter = low + range_size * 0.25
        
        if curr > upper_quarter:
            rel_strength = min((curr - upper_quarter) / range_size * 4, 1.0)
            return "resistance_test", rel_strength
        elif curr < lower_quarter:
            rel_strength = min((lower_quarter - curr) / range_size * 4, 1.0)
            return "support_test", rel_strength
        else:
            return "range_bound", 0.5

    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """生成信号"""
        if not candles or len(candles) < self.lookback_days + 2:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date if candles else None,
                reason="数据不足",
                confidence=0.0
            )

        # 获取技术指标
        rsi = self.provider.get_indicator(
            "rsi", candles, 
            {"length": self.momentum_params["rsi_period"]}
        )
        macd = self.provider.get_indicator(
            "macd", candles, 
            {
                "fast": self.momentum_params["macd_fast"],
                "slow": self.momentum_params["macd_slow"],
                "signal": self.momentum_params["macd_signal"]
            }
        )
        
        # 提取价格数据
        highs = [float(c.high) for c in candles[-self.lookback_days:]]
        lows = [float(c.low) for c in candles[-self.lookback_days:]]
        closes = [float(c.close) for c in candles[-self.lookback_days:]]
        volumes = [float(c.volume) for c in candles[-self.lookback_days:]]
        
        curr_close = closes[-1]
        prev_close = closes[-2]
        
        # 1. 趋势线分析
        high_points, low_points = self._find_swing_points(highs, lows)
        
        up_slope, up_intercept, up_r2 = self._fit_trendline(low_points)
        down_slope, down_intercept, down_r2 = self._fit_trendline(high_points)
        
        # 计算当前价格与趋势线距离
        curr_idx = len(closes) - 1
        up_line = up_slope * curr_idx + up_intercept
        down_line = down_slope * curr_idx + down_intercept
        
        # 趋势线评分
        trendline_score = 0.0
        trendline_detail = ""
        
        if up_r2 > 0.7 or down_r2 > 0.7:  # R方值大于0.7认为趋势线有效
            if curr_close < up_line and up_r2 > 0.7:
                deviation = (up_line - curr_close) / curr_close
                trendline_score = -min(deviation, 1.0)
                trendline_detail = f"跌破上升趋势线 (-{deviation*100:.1f}%) R²:{up_r2:.2f}"
            elif curr_close > down_line and down_r2 > 0.7:
                deviation = (curr_close - down_line) / down_line
                trendline_score = min(deviation, 1.0)
                trendline_detail = f"突破下降趋势线 (+{deviation*100:.1f}%) R²:{down_r2:.2f}"
                
        # 2. 均线趋势分析
        ma_direction, ma_strength = self._analyze_ma_trend(closes, self.trend_ma_periods)
        ma_score = ma_strength * (1 if ma_direction == "up" else -1 if ma_direction == "down" else 0)
        ma_detail = f"均线趋势:{ma_direction} 强度:{ma_strength:.2f}"
        
        # 3. 动量分析
        curr_rsi = float(rsi[-1].RSI_14)
        curr_macd = float(macd[-1].macd)
        curr_signal = float(macd[-1].signal)
        curr_hist = curr_macd - curr_signal
        prev_hist = float(macd[-2].macd) - float(macd[-2].signal)
        
        momentum_score = 0.0
        momentum_detail = ""
        
        # RSI和MACD综合评分
        if curr_rsi > 50 and curr_hist > 0 and curr_hist > prev_hist:
            momentum_score = min(((curr_rsi - 50)/30 + curr_hist/abs(prev_hist))/2, 1.0)
            momentum_detail = f"上升动量 RSI:{curr_rsi:.1f} MACD柱增大"
        elif curr_rsi < 50 and curr_hist < 0 and curr_hist < prev_hist:
            momentum_score = -min(((50 - curr_rsi)/30 + abs(curr_hist/prev_hist))/2, 1.0)
            momentum_detail = f"下降动量 RSI:{curr_rsi:.1f} MACD柱减小"
            
        # 4. 形态分析
        pattern, pattern_strength = self._identify_pattern(highs, lows, closes)
        pattern_score = pattern_strength * (
            1 if pattern == "resistance_test" else 
            -1 if pattern == "support_test" else 0
        )
        pattern_detail = f"形态:{pattern} 强度:{pattern_strength:.2f}"
        
        # 计算总分
        bull_score = (
            self.weights["trendline"] * (trendline_score if trendline_score > 0 else 0) +
            self.weights["ma_trend"] * (ma_score if ma_score > 0 else 0) +
            self.weights["momentum"] * (momentum_score if momentum_score > 0 else 0) +
            self.weights["pattern"] * (pattern_score if pattern_score > 0 else 0)
        )
        
        bear_score = (
            self.weights["trendline"] * (-trendline_score if trendline_score < 0 else 0) +
            self.weights["ma_trend"] * (-ma_score if ma_score < 0 else 0) +
            self.weights["momentum"] * (-momentum_score if momentum_score < 0 else 0) +
            self.weights["pattern"] * (-pattern_score if pattern_score < 0 else 0)
        )
        
        # 生成信号
        signal = "hold"
        reason = ""
        confidence = 0.0
        details = []
        
        if bull_score > bear_score and bull_score >= self.score_threshold:
            signal = "buy"
            confidence = bull_score
            
            if trendline_score > 0:
                details.append(trendline_detail)
            if ma_score > 0:
                details.append(ma_detail)
            if momentum_score > 0:
                details.append(momentum_detail)
            if pattern_score > 0:
                details.append(pattern_detail)
                
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
            
            if trendline_score < 0:
                details.append(trendline_detail)
            if ma_score < 0:
                details.append(ma_detail)
            if momentum_score < 0:
                details.append(momentum_detail)
            if pattern_score < 0:
                details.append(pattern_detail)
                
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
                "up_slope": round(up_slope, 6),
                "down_slope": round(down_slope, 6),
                "up_r2": round(up_r2, 3),
                "down_r2": round(down_r2, 3),
                "ma_direction": ma_direction,
                "ma_strength": round(ma_strength, 3),
                "rsi": round(curr_rsi, 2),
                "macd_hist": round(curr_hist, 4),
                "pattern": pattern,
                "pattern_strength": round(pattern_strength, 3),
                "trendline_score": round(trendline_score, 4),
                "ma_score": round(ma_score, 4),
                "momentum_score": round(momentum_score, 4),
                "pattern_score": round(pattern_score, 4),
                "bull_score": round(bull_score, 4),
                "bear_score": round(bear_score, 4)
            }
        )

def make_trendline_presets() -> Dict[str, Dict[str, Any]]:
    """预设参数配置"""
    
    swing = {  # 短线波段配置(1-2周)
        "lookback_days": 20,
        "min_touch_points": 3,
        "trend_ma_periods": [5, 10, 20],
        "momentum_params": {
            "rsi_period": 10,
            "macd_fast": 8,
            "macd_slow": 17,
            "macd_signal": 9
        },
        "volume_ma": 10,
        "weights": {
            "trendline": 0.30,
            "ma_trend": 0.25,
            "momentum": 0.25,
            "pattern": 0.20
        },
        "score_threshold": 0.60
    }
    
    intermediate = {  # 中线配置(2-4周)
        "lookback_days": 40,
        "min_touch_points": 4,
        "trend_ma_periods": [10, 20, 50],
        "momentum_params": {
            "rsi_period": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9
        },
        "volume_ma": 20,
        "weights": {
            "trendline": 0.35,
            "ma_trend": 0.25,
            "momentum": 0.20,
            "pattern": 0.20
        },
        "score_threshold": 0.65
    }
    
    position = {  # 长线持仓配置(1-3月)
        "lookback_days": 60,
        "min_touch_points": 5,
        "trend_ma_periods": [20, 50, 100],
        "momentum_params": {
            "rsi_period": 14,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9
        },
        "volume_ma": 30,
        "weights": {
            "trendline": 0.40,
            "ma_trend": 0.30,
            "momentum": 0.15,
            "pattern": 0.15
        },
        "score_threshold": 0.70
    }
    
    return {
        "swing": swing,
        "intermediate": intermediate,
        "position": position
    }