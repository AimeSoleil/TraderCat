from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import isinf, isnan
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

@dataclass
class TrendStrength:
    signal: bool                # 最终信号（True/False）
    mode: str                   # 模式："trend" 或 "reversal"
    trend: Dict[str, Any]       # 趋势检测结果（来自 _check_trend_strength）
    volatility: Dict[str, Any]  # 波动检测结果（来自 _check_volatility）
    reason: str                 # 解释原因

class TradingStrategy(ABC):

    @abstractmethod
    def generate_signal(self, symbol: str = None, candles: dict = None) -> SignalModel:
        """
        Returns a dict: { "strategy": name, "signal": 'buy'|'sell'|'hold', "details": {...} }
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """
        Returns strategy name
        """
        pass

    @abstractmethod
    def get_lookback_window(self) -> int:
        """
        Returns minimum length of candle window
        """
        pass
    
    # --- 指标函数 ---
    def _momentum_confirmation(self,
        rsi_val_history: Optional[List[Any]],
        macd_hist_val_history: Optional[List[Any]],
        prefer: str = "bull",
    ) -> bool:
        # 简单动量确认：RSI or MACD hist 指向反转方向
        r_latest = rsi_val_history[-1]
        macd_hist_latest = macd_hist_val_history[-1]

        if prefer == "bull":
            if r_latest is not None and r_latest > 30:
                return True
            if macd_hist_latest is not None and macd_hist_latest > 0:
                return True
            return False
        else:
            if r_latest is not None and r_latest < 70:
                return True
            if macd_hist_latest is not None and macd_hist_latest < 0:
                return True
            return False
        
    def _check_volume_zscore(self, vols, window=20, threshold=2.0):
        """
        Check if the latest volume is significantly higher than recent volumes using z-score.
        - z ≈ 0 → Value is near the average (normal activity).
        - z > 1 → Value is 1 standard deviation above average (slightly unusual).
        - z > 2 → Value is 2 standard deviations above average (significant spike).
        - z > 3 → Very rare event (strong breakout confirmation).
        - For volume confirmation: z ≥ 2 (volume is significantly higher than normal).
        Args:
            vols (list): List of volume values (latest at the end).
            window (int): Number of recent samples to consider.
            threshold (float): Minimum z-score to confirm breakout.

        Returns:
            tuple: (vol_ok, volume_z)
                vol_ok (bool): True if z-score >= threshold.
                volume_z (float or None): Computed z-score, None if not available.
        """
        vol_ok = False
        volume_z = None

        try:
            recent_window = max(1, min(window, len(vols)))
            recent_vols = [v for v in vols[-recent_window:] if v is not None]

            if recent_vols and len(recent_vols) >= 2 and vols[-1] is not None:
                mean_v = sum(recent_vols) / len(recent_vols)
                std_v = statistics.pstdev(recent_vols) if len(recent_vols) > 1 else 0.0

                if std_v > 0:
                    volume_z = (vols[-1] - mean_v) / std_v
                    vol_ok = volume_z >= threshold

        except Exception:
            vol_ok = False

        return vol_ok, volume_z

    def _check_volatility(self, atr_history, close, window=100, base_threshold=0.02, quantile=0.8):
        """
        判断市场是否处于高波动状态，采用两步过滤：
        1. ATR/Price 相对值过滤
        2. 动态分位数确认
        返回详细信息而非仅布尔值
        """
        if len(atr_history) == 0:
            return {"signal": False, "reason": "No ATR history", "current": None, "threshold": None}

        atr = atr_history[-1]
        safe_close = close if abs(close) > EPS else 1.0
        atr_ratio = atr / safe_close

        if atr_ratio < base_threshold:
            return {"signal": False, "reason": f"ATR ratio {atr_ratio:.4f} < base threshold {base_threshold}", 
                    "current": atr_ratio, "threshold": base_threshold}

        recent_atr = atr_history[-window:] if len(atr_history) >= window else atr_history
        recent_safe_atr_list = [x for x in recent_atr if x is not None]
        threshold_dynamic = np.quantile(recent_safe_atr_list, quantile)

        signal = atr >= threshold_dynamic
        reason = "ATR above dynamic threshold" if signal else "ATR below dynamic threshold"
        return {"signal": signal, "reason": reason, "current": atr, "threshold": threshold_dynamic}

    def _check_trend_strength(self, adx_history, window=100, quantile=0.8):
        """
        判断趋势强度是否达到动态标准（基于历史分位数）
        返回详细信息
        """
        if len(adx_history) == 0:
            return {"signal": False, "reason": "No ADX history", "current": None, "threshold": None}

        adx_val = adx_history[-1]
        recent_adx = adx_history[-window:] if len(adx_history) >= window else adx_history
        recent_safe_adx_list = [x for x in recent_adx if x is not None]
        threshold_dynamic = np.quantile(recent_safe_adx_list, quantile)

        signal = adx_val >= threshold_dynamic
        reason = "ADX above dynamic threshold" if signal else "ADX below dynamic threshold"
        return {"signal": signal, "reason": reason, "current": adx_val, "threshold": threshold_dynamic}

    def _check_trend_and_volatility(self, atr_val_history, adx_val_history, close,
                                window=100, atr_base_threshold=0.02,
                                atr_quantile=0.8, adx_quantile=0.8, mode="trend") -> TrendStrength:
        """
        综合判断市场状态：趋势跟随或反转
        返回 MarketSignalResult 数据类实例
        """
        vol_info = self._check_volatility(atr_val_history, close, window, atr_base_threshold, atr_quantile)
        trend_info = self._check_trend_strength(adx_val_history, window, adx_quantile)

        if mode == "trend":
            signal = vol_info["signal"] and trend_info["signal"]
            reason = "Strong trend + high volatility" if signal else "Conditions not met for trend"
        elif mode == "reversal":
            signal = (not trend_info["signal"]) and vol_info["signal"]
            reason = "Weak trend + high volatility" if signal else "Conditions not met for reversal"
        else:
            signal = False
            reason = "Invalid mode"

        return TrendStrength(signal=signal, mode=mode, trend=trend_info, volatility=vol_info, reason=reason)
        
    # --- 工具函数 ---
    def _compute_return_L(self, closes: List[float], L: int) -> Optional[float]:
        if len(closes) <= L:
            return None
        past = closes[-L - 1]
        curr = closes[-1]
        if abs(past) < EPS:
            return None
        return curr / past - 1.0
    
    def _make_exit_plan(
        self,
        side: str,
        entry_price: float,
        atr: Optional[float],
        stop_atr_mult: float,
        tp_atr_mult: float,
        stop_fib_level: Optional[float] = None,
    ) -> Dict[str, Any]:
        plan = {"stop": None, "tp": None, "trailing": None, "atr": atr}
        if atr is None or not self._is_finite(entry_price):
            return plan
        if side == "long":
            # stop by ATR or by fib stop level if given (use tighter)
            stop_atr = entry_price - stop_atr_mult * atr
            if stop_fib_level is not None:
                plan["stop"] = min(stop_atr, stop_fib_level)
            else:
                plan["stop"] = stop_atr
            plan["tp"] = entry_price + tp_atr_mult * atr
            plan["trailing"] = entry_price - 0.8 * atr
        else:
            stop_atr = entry_price + stop_atr_mult * atr
            if stop_fib_level is not None:
                plan["stop"] = max(stop_atr, stop_fib_level)
            else:
                plan["stop"] = stop_atr
            plan["tp"] = entry_price - tp_atr_mult * atr
            plan["trailing"] = entry_price + 0.8 * atr
        return plan
    
    def _extract_latest_indicator_value(self, series: Optional[List[Any]], keys: List[str]) -> Optional[float]:
        """
        从 provider 返回的指标序列中提取最后一条数值，兼容不同字段命名或直接数值列表。
        keys: 候选属性名列表（优先级顺序）
        """
        if not series:
            return None
        last = series[-1]
        if last is None:
            return None
        if isinstance(last, (int, float)):
            try:
                return float(last)
            except Exception:
                return None
        for k in keys:
            try:
                if hasattr(last, k):
                    v = getattr(last, k)
                elif isinstance(last, dict):
                    v = last.get(k)
                else:
                    v = None
            except Exception:
                v = None
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    continue
        return None
    
    def _percentile_rank(self, arr: List[float], value: float) -> float:
        """返回 value 在 arr 中的百分位(0-100)；arr 长度应>0"""
        if not arr:
            return 100.0
        less = sum(1 for x in arr if x < value)
        equal = sum(1 for x in arr if x == value)
        rank = (less + 0.5 * equal) / len(arr) * 100.0
        return rank
    
    def _find_fractal_swings(
        self, highs: List[float], lows: List[float], window: int
    ) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
        """
        N-bar fractal 高/低点 (index, value)，index 相对整个序列起点
        window: 左右各比较 window 根 bar
        """
        H, L = len(highs), len(lows)
        high_pts, low_pts = [], []
        for i in range(window, H - window):
            left_h = highs[i - window : i]
            right_h = highs[i + 1 : i + window + 1]
            if highs[i] > max(left_h + right_h):
                high_pts.append((i, highs[i]))
            left_l = lows[i - window : i]
            right_l = lows[i + 1 : i + window + 1]
            if lows[i] < min(left_l + right_l):
                low_pts.append((i, lows[i]))
        return high_pts, low_pts

    def _get_indicator_values_at_indices(
        self, series: List[Optional[float]], indices: List[int], total_candles_len: int
    ) -> List[Optional[float]]:
        """
        从 provider 的指标 history 列表（series，长度可能小于 total_candles_len）中，按全局索引列表 indices 返回对应值列表。
        返回顺序与 indices 对应，若对应位置不可用返回 None。
        """
        out = []
        if not series:
            return [None] * len(indices)
        rel_base = total_candles_len - len(series)
        for idx in indices:
            rel = idx - rel_base
            if 0 <= rel < len(series):
                out.append(series[rel])
            else:
                out.append(None)
        return out

class ExitPlanner:
    def __init__(
            self,
            highs: List[float],
            lows: List[float],
            atr: float,
            atr_period: Optional[int] = 14,
            close_price: Optional[float ]= None,
            atr_mult: float = 3.0,
            atr_tp_mult: float = 2.0,        # Default ATR-based TP multiplier
            fib_stop_ratio: float = 0.236,   # Default for stop-loss
            fib_tp_ratio: float = 0.618,     # Default for take-profit
    ):
        """
        Initialize ExitPlanner with ATR multiplier, Fibonacci ratios, and ATR-based TP multiplier.
        """
        self.highs = highs
        self.lows = lows
        self.atr = atr
        self.atr_period = atr_period
        self.close_price = close_price
        self.atr_mult = atr_mult
        self.fib_stop_ratio = fib_stop_ratio
        self.fib_tp_ratio = fib_tp_ratio
        self.atr_tp_mult = atr_tp_mult

    def make_exit_plan(self, side: str) -> Dict[str, Any]:
        """
        Create exit plan combining Chandelier Exit, Fibonacci stop, and take-profit levels.
        """
        plan = {
            "atr": self.atr,
            "atr_period": self.atr_period,
            "atr_mult": self.atr_mult,
            "fib_stop_ratio": self.fib_stop_ratio,
            "fib_tp_ratio": self.fib_tp_ratio,
            "atr_tp_mult": self.atr_tp_mult,
        }

        if self.atr is None or not self.highs or not self.lows:
            return plan

        # Slice highs and lows based on lookback
        lookback = self.atr_period
        highs_slice = self.highs[-lookback:] if len(self.highs) >= lookback else self.highs
        lows_slice = self.lows[-lookback:] if len(self.lows) >= lookback else self.lows

        highest_high = max(highs_slice)
        lowest_low = min(lows_slice)

        # --- Stop Loss Calculation ---
        if self.fib_stop_ratio is not None and self.close_price is not None:
            if side == "long":
                stop_fib_level = lowest_low + (highest_high - lowest_low) * self.fib_stop_ratio
            else:
                stop_fib_level = highest_high - (highest_high - lowest_low) * self.fib_stop_ratio
            plan["fib_stop_loss_at"] = stop_fib_level

        # Chandelier stop
        if side == "long":
            chandelier_stop = highest_high - self.atr_mult * self.atr
        else:
            chandelier_stop = lowest_low + self.atr_mult * self.atr
        plan["chandelier_stop_loss_at"] = chandelier_stop

        # --- Take Profit Calculation ---
        tp_levels = {}

        # ATR-based TP
        if self.atr_tp_mult is not None and self.close_price is not None:
            if side == "long":
                tp_levels["atr_tp"] = self.close_price + self.atr_tp_mult * self.atr
            else:
                tp_levels["atr_tp"] = self.close_price - self.atr_tp_mult * self.atr

        # Fibonacci-based TP
        if self.fib_tp_ratio is not None and self.close_price is not None:
            if side == "long":
                tp_levels["fib_tp"] = lowest_low + (highest_high - lowest_low) * self.fib_tp_ratio
            else:
                tp_levels["fib_tp"] = highest_high - (highest_high - lowest_low) * self.fib_tp_ratio

        if tp_levels:
            plan["take_profit_levels"] = tp_levels

        return plan


class StrategyUtilities:

    @staticmethod
    def _normalize(self, val: float, min_val: float, max_val: float) -> float:
        if val is None or max_val <= min_val:
            return 0.0
        return (val - min_val) / (max_val - min_val)

    @staticmethod
    def is_finite(v: Any) -> bool:
        try:
            return v is not None and not (
                isinstance(v, float) and (isnan(v) or isinf(v))
            )
        except Exception:
            return False
    @staticmethod
    def highest(vals: List[float], n: int) -> float:
        return max(vals[-n:]) if len(vals) >= n and n > 0 else max(vals)
    @staticmethod
    def lowest(vals: List[float], n: int) -> float:
        return min(vals[-n:]) if len(vals) >= n and n > 0 else min(vals)