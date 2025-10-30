from typing import List, Optional, Dict, Any, Tuple
import numpy as np
from datetime import datetime

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

class FibonacciStrategy(TradingStrategy):
    """
    斐波那契波段交易策略
    
    核心特点:
    1. 基于日线数据识别周度波段机会
    2. 使用高低点构建斐波那契水平
    3. 重点关注0.382/0.618回调位
    4. 结合趋势和动量确认
    
    参数说明:
    ----------
    swing_period: int = 20
        波段周期(约等于一个月交易日)
    fib_ratios: List[float]
        斐波那契比率序列
    trend_period: int = 50
        趋势判断周期(约等于10周)
    macd_params: dict
        MACD参数配置
    volume_ma: int = 20
        成交量均线周期
    """
    
    def __init__(
        self,
        swing_period: int = 20,
        fib_ratios: Optional[List[float]] = None,
        trend_period: int = 50,
        macd_params: Optional[Dict[str, int]] = None,
        volume_ma: int = 20,
        weights: Optional[Dict[str, float]] = None,
        score_threshold: float = 0.65,
        data_provider = None
    ):
        self.swing_period = swing_period
        self.fib_ratios = fib_ratios or [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
        self.trend_period = trend_period
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.volume_ma = volume_ma
        
        # 默认权重配置 - 更重视斐波那契位置
        default_weights = {
            "fib": 0.45,      # 斐波那契回调权重
            "trend": 0.25,    # 趋势方向权重
            "momentum": 0.20, # MACD动量权重
            "volume": 0.10    # 成交量确认权重
        }
        
        merged = default_weights.copy()
        if weights:
            merged.update(weights)
        total = sum(merged.values())
        self.weights = {k: v/total for k,v in merged.items()}
        
        self.score_threshold = score_threshold
        self.provider = data_provider
        
    def get_name(self) -> str:
        return "Fibonacci"

    def get_lookback_window(self) -> int:
        return max(self.trend_period, self.swing_period + self.volume_ma)
    
    def _safe(self, obj: Any, attr: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)
    
    def _find_swing_points(self, highs: List[float], lows: List[float], window: int = 5) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
        high_points, low_points = [], []
        for i in range(window, len(highs) - window):
            if highs[i] > max(highs[i - window:i] + highs[i + 1:i + window + 1]):
                high_points.append((i, highs[i]))
            if lows[i] < min(lows[i - window:i] + lows[i + 1:i + window + 1]):
                low_points.append((i, lows[i]))
        return high_points, low_points

    def _get_trend_direction(self, closes: List[float], period: int = None) -> Tuple[str, float]:
        period = period or self.trend_period
        if len(closes) < period:
            return "neutral", 0.0
        ma = sum(closes[-period:]) / period
        curr = closes[-1]
        strength = min(abs(curr - ma) / ma, 1.0)
        return ("up" if curr > ma else "down"), strength

    def _calculate_fib_levels(self, high: float, low: float, trend: str = "up") -> Dict[float, float]:
        diff = high - low
        return {r: (high - diff * r if trend == "up" else low + diff * r) for r in self.fib_ratios}

    def _get_closest_fib_level(self, price: float, levels: Dict[float, float]) -> Tuple[float, float, float]:
        closest = min(levels.items(), key=lambda x: abs(price - x[1]))
        return closest[0], closest[1], abs(price - closest[1])

    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """生成信号"""
        if not candles or len(candles) < max(self.swing_period, self.trend_period) + 2:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date if candles else None,
                reason="数据不足",
                confidence=0.0
            )

        # 获取技术指标
        macd = self.provider.get_indicator("macd", candles, self.macd_params)
        
        # 提取价格数据
        highs = [float(c.high) for c in candles[-self.trend_period:]]
        lows = [float(c.low) for c in candles[-self.trend_period:]]
        closes = [float(c.close) for c in candles[-self.trend_period:]]
        volumes = [float(c.volume) for c in candles[-self.trend_period:]]
        
        curr_close = closes[-1]
        prev_close = closes[-2]
        
        # 1. 获取趋势方向和强度
        trend_dir, trend_strength = self._get_trend_direction(closes)
        
        # 2. 查找波段高低点
        high_points, low_points = self._find_swing_points(highs, lows)
        
        # 取最近的高低点
        if len(high_points) > 0 and len(low_points) > 0:
            recent_high = max(high_points[-3:], key=lambda x: x[1])[1]
            recent_low = min(low_points[-3:], key=lambda x: x[1])[1]
            
            # 计算斐波那契水平
            fib_levels = self._calculate_fib_levels(
                recent_high, recent_low, 
                trend_dir)
                
            # 获取最接近的水平
            closest_ratio, closest_level, level_diff = self._get_closest_fib_level(
                curr_close, fib_levels)
        else:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date,
                reason="未找到有效波段点",
                confidence=0.0
            )
            
        # 3. 斐波那契位置评分
        fib_score = 0.0
        fib_detail = ""
        
        price_diff_pct = level_diff / curr_close * 100
        if price_diff_pct < 1.0:  # 接近斐波那契水平
            # 重点关注0.382和0.618水平
            if abs(closest_ratio - 0.382) < 0.1 or abs(closest_ratio - 0.618) < 0.1:
                if trend_dir == "up":
                    fib_score = 1.0 - closest_ratio  # 回调位越浅分数越高
                    fib_detail = f"接近上升趋势{closest_ratio:.3f}回调位 ({price_diff_pct:.1f}%)"
                else:
                    fib_score = closest_ratio  # 回调位越深分数越高
                    fib_detail = f"接近下降趋势{closest_ratio:.3f}回调位 ({price_diff_pct:.1f}%)"
                    
        # 4. 趋势评分
        trend_score = trend_strength * (1 if trend_dir == "up" else -1)
        trend_detail = f"{'上升' if trend_dir == 'up' else '下降'}趋势 强度:{trend_strength:.2f}"
        
        # 5. MACD动量评分
        name_val = f'close_MACD_{self.macd_params["fast"]}_{self.macd_params["slow"]}_{self.macd_params["signal"]}'
        name_sig = f'close_MACDs_{self.macd_params["fast"]}_{self.macd_params["slow"]}_{self.macd_params["signal"]}'
        curr_macd = self._safe(macd[-1], name_val)
        curr_signal = self._safe(macd[-1], name_sig)
        curr_hist = curr_macd - curr_signal
        prev_macd = self._safe(macd[-2], name_val)
        prev_signal = self._safe(macd[-2], name_sig)
        prev_hist = prev_macd - prev_signal
        
        momentum_score = 0.0
        momentum_detail = ""
        
        if curr_hist > 0 and curr_hist > prev_hist:
            momentum_score = min(curr_hist / abs(prev_hist) if prev_hist != 0 else 1, 1.0)
            momentum_detail = f"MACD柱状图向上 {curr_hist:.3f}"
        elif curr_hist < 0 and curr_hist < prev_hist:
            momentum_score = -min(curr_hist / abs(prev_hist) if prev_hist != 0 else 1, 1.0)
            momentum_detail = f"MACD柱状图向下 {curr_hist:.3f}"
            
        # 6. 成交量评分
        vol_ma = sum(volumes[-self.volume_ma:]) / self.volume_ma
        curr_vol = volumes[-1]
        
        volume_score = 0.0
        volume_detail = ""
        
        if curr_vol > vol_ma:
            vol_chg = (curr_vol - vol_ma) / vol_ma
            if curr_close > prev_close:  # 上涨放量
                volume_score = min(vol_chg, 1.0)
                volume_detail = f"量能放大 (+{vol_chg*100:.1f}%)"
            else:  # 下跌放量
                volume_score = -min(vol_chg, 1.0)
                volume_detail = f"量能放大 (-{vol_chg*100:.1f}%)"
                
        # 计算总分
        bull_score = (
            self.weights["fib"] * (fib_score if fib_score > 0 else 0) +
            self.weights["trend"] * (trend_score if trend_score > 0 else 0) +
            self.weights["momentum"] * (momentum_score if momentum_score > 0 else 0) +
            self.weights["volume"] * (volume_score if volume_score > 0 else 0)
        )
        
        bear_score = (
            self.weights["fib"] * (-fib_score if fib_score < 0 else 0) +
            self.weights["trend"] * (-trend_score if trend_score < 0 else 0) +
            self.weights["momentum"] * (-momentum_score if momentum_score < 0 else 0) +
            self.weights["volume"] * (-volume_score if volume_score < 0 else 0)
        )
        
        # 生成信号
        signal = "hold"
        reason = ""
        confidence = 0.0
        details = []
        
        if bull_score > bear_score and bull_score >= self.score_threshold:
            signal = "buy"
            confidence = bull_score
            
            if fib_score > 0:
                details.append(fib_detail)
            if trend_score > 0:
                details.append(trend_detail)
            if momentum_score > 0:
                details.append(momentum_detail)
            if volume_score > 0:
                details.append(volume_detail)
                
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
            
            if fib_score < 0:
                details.append(fib_detail)
            if trend_score < 0:
                details.append(trend_detail)
            if momentum_score < 0:
                details.append(momentum_detail)
            if volume_score < 0:
                details.append(volume_detail)
                
            if confidence >= 0.8:
                strength = "强"
            elif confidence >= 0.65:
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
                "trend": trend_dir,
                "trend_strength": round(trend_strength, 3),
                "fib_ratio": round(closest_ratio, 3),
                "fib_level": round(closest_level, 2),
                "macd_hist": round(curr_hist, 4),
                "fib_score": round(fib_score, 4),
                "trend_score": round(trend_score, 4),
                "momentum_score": round(momentum_score, 4),
                "volume_score": round(volume_score, 4),
                "bull_score": round(bull_score, 4),
                "bear_score": round(bear_score, 4)
            }
        )

def make_fibonacci_presets() -> Dict[str, Dict[str, Any]]:
    """预设参数配置"""
    
    aggressive = {  # 进取型配置
        "swing_period": 15,
        "trend_period": 40,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "volume_ma": 15,
        "weights": {
            "fib": 0.40,
            "trend": 0.25,
            "momentum": 0.25,
            "volume": 0.10
        },
        "score_threshold": 0.60
    }
    
    balanced = {  # 平衡型配置
        "swing_period": 20,
        "trend_period": 50,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "volume_ma": 20,
        "weights": {
            "fib": 0.45,
            "trend": 0.25,
            "momentum": 0.20,
            "volume": 0.10
        },
        "score_threshold": 0.65
    }
    
    conservative = {  # 保守型配置
        "swing_period": 25,
        "trend_period": 60,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "volume_ma": 25,
        "weights": {
            "fib": 0.50,
            "trend": 0.25,
            "momentum": 0.15,
            "volume": 0.10
        },
        "score_threshold": 0.70
    }
    
    return {
        "aggressive": aggressive,
        "balanced": balanced,
        "conservative": conservative
    }