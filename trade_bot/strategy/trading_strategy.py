from abc import ABC, abstractmethod
from dataclasses import dataclass
import statistics
from typing import Any, Dict, List, Literal, Optional, Tuple

import numpy as np

from trade_bot.strategy.signal_model import SignalModel
from trade_bot.strategy.signal_scorer import FactorName

EPS = 1e-9

@dataclass
class TrendStrength:
    """
    ADX趋势强度和Volatility波动率
    """
    signal: bool                # 最终信号（True/False）
    mode: str                   # 模式："trend" 或 "reversal"
    reason: str                 # 解释原因
    trend: Dict[str, Any]       # 趋势检测结果（来自 _check_trend_strength）
    volatility: Dict[str, Any]  # 波动检测结果（来自 _check_volatility）
    adx_rollover: Optional[Dict[str, Any]]  # ADX回落检测结果（来自 _detect_adx_rollover）

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

    def support_scoring_factors(self) -> List[FactorName]:
        """
        Returns scoring factors
        """
        pass
    
    # --- 指标函数 ---
    def _momentum_confirm(self,
        rsi_val_history: Optional[List[Any]],
        macd_hist_val_history: Optional[List[Any]],
        prefer: Literal["long", "short", "neutral"]
    ) -> bool:
        # 简单动量确认：RSI or MACD hist 指向反转方向
        r_latest = rsi_val_history[-1] if rsi_val_history and len(rsi_val_history) > 0 else None
        macd_hist_latest = macd_hist_val_history[-1] if macd_hist_val_history and len(macd_hist_val_history) > 0 else None

        if prefer == "long":
            if r_latest is not None and r_latest > 30:
                return True
            if macd_hist_latest is not None and macd_hist_latest > 0:
                return True
            return False
        elif prefer == "short":
            if r_latest is not None and r_latest < 70:
                return True
            if macd_hist_latest is not None and macd_hist_latest < 0:
                return True
            return False
        else:
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
            # 确保有足够的数据：至少需要 window + 1 个数据（历史 window 个 + 当前 1 个）
            if len(vols) < window + 1:
                return False, None
            
            # 取出用于计算基准的历史数据（不包含当前最新的一根）
            # 例如：vols[-21:-1]
            history_vols = [v for v in vols[-(window + 1):-1] if v is not None]
            current_vol = vols[-1]

            if len(history_vols) >= 2 and current_vol is not None:
                mean_v = sum(history_vols) / len(history_vols)
                # 使用样本标准差 (stdev) 而不是总体标准差 (pstdev)，对于抽样统计更准确
                std_v = statistics.stdev(history_vols) if len(history_vols) > 1 else 0.0

                if std_v > 0:
                    volume_z = (current_vol - mean_v) / std_v
                    vol_ok = volume_z >= threshold
        except Exception:
            vol_ok = False

        return vol_ok, volume_z
    
    def _check_volatility(
        self,
        atr_history: List[Optional[float]],
        price_history: List[Optional[float]],
        window: int = 100,
        quantile: float = 0.8,
        base_factor: float = 1.0,
        min_history_for_quantile: int = 20,
        fallback_base_threshold: float = 0.002,
    ) -> Dict[str, Any]:
        """
        判断市场是否处于高波动状态（返回详细信息）：
        Two-step approach:
        1) Compute ATR/price ratio for history (nan-safe)
        2) Compare current ratio to a dynamic base threshold (20th percentile * base_factor)
        3) Confirm against a higher quantile (quantile) for "high volatility"
        Returns a dictionary with fields: signal (bool), reason, current_atr, current_ratio, threshold, base_threshold, recent_count
        """
        if not atr_history or not price_history:
            return {"signal": False, "reason": "Insufficient data", "current_atr": None, "current_ratio": None, "threshold": None, "base_threshold": None, "recent_count": 0}

        if len(atr_history) != len(price_history):
            return {"signal": False, "reason": "ATR and price history length mismatch", "current_atr": None, "current_ratio": None, "threshold": None, "base_threshold": None, "recent_count": 0}

        atr_arr = self._safe_array(atr_history)
        price_arr = self._safe_array(price_history)

        # Build ATR ratio history safely (atr / price), avoid divide-by-zero by treating tiny prices as nan
        safe_price = np.where(np.abs(price_arr) < 1e-8, np.nan, price_arr)
        atr_ratios = np.divide(atr_arr, safe_price, out=np.full_like(atr_arr, np.nan), where=~np.isnan(safe_price))

        # Current values
        current_atr = float(atr_arr[-1]) if not np.isnan(atr_arr[-1]) else None
        current_price = float(price_arr[-1]) if not np.isnan(price_arr[-1]) else None
        current_ratio = float(atr_ratios[-1]) if not np.isnan(atr_ratios[-1]) else None

        # Recent window
        recent = atr_ratios[-window:] if len(atr_ratios) >= window else atr_ratios
        recent_clean = recent[~np.isnan(recent)]
        recent_count = recent_clean.size

        # Base threshold: 20th percentile * base_factor (fallback when insufficient history)
        if recent_count >= min_history_for_quantile:
            base_threshold = float(np.nanquantile(recent_clean, 0.2)) * base_factor
        else:
            base_threshold = float(fallback_base_threshold) * base_factor

        # Quick reject if current ratio is missing
        if current_ratio is None or np.isnan(current_ratio):
            return {"signal": False, "reason": "Current ATR/price ratio is NaN", "current_atr": current_atr, "current_ratio": None, "threshold": None, "base_threshold": base_threshold, "recent_count": recent_count}

        if current_ratio < base_threshold:
            return {
                "signal": False,
                "reason": f"ATR ratio {current_ratio:.6f} < dynamic base {base_threshold:.6f}",
                "current_atr": current_atr,
                "current_ratio": current_ratio,
                "threshold": None,
                "base_threshold": base_threshold,
                "recent_count": recent_count,
            }

        # Dynamic quantile threshold for "high volatility"
        if recent_count >= 1:
            threshold_dynamic = float(np.nanquantile(recent_clean, quantile))
        else:
            threshold_dynamic = base_threshold  # degenerate case

        signal = current_ratio >= threshold_dynamic
        reason = "ATR ratio above dynamic threshold" if signal else "ATR ratio below dynamic threshold"

        return {
            "signal": bool(signal),
            "reason": reason,
            "current_atr": current_atr,
            "current_ratio": current_ratio,
            "threshold": threshold_dynamic,
            "base_threshold": base_threshold,
            "recent_count": recent_count,
        }

    def _check_trend_strength(
        self,
        adx_history: List[Optional[float]],
        window: int = 100,
        quantiles: Optional[List[float]] = None, # Fix
        min_adx: float = 20.0,
        min_history_for_quantile: int = 20,
        fallback_strong: float = 25.0,
        fallback_weak: float = 15.0,
        slope_window: int = 5,
        slope_threshold: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Enhanced ADX classifier using two quantiles:
        - weak_quantile: below this => 'weak'
        - strong_quantile: above this => 'strong'
        - in-between => 'moderate'
        Returns diagnostics: classification, signal (boolean for 'strong' + min_adx), thresholds, percentile, zscore, slope, di_info, etc.
        """
        # validate quantiles
        strong_quantile = quantiles[0]
        weak_quantile = quantiles[1]
        if strong_quantile < weak_quantile:
            strong_quantile = quantiles[1]
            weak_quantile = quantiles[0]
        if not (0.0 <= weak_quantile < strong_quantile <= 1.0):
            raise ValueError("Require 0 <= weak_quantile < strong_quantile <= 1")

        if not adx_history:
            return {"signal": False, "classification": "no_data", "reason": "No ADX history", "current_adx": None, "threshold_strong": None, "threshold_weak": None, "recent_count": 0}

        adx_arr = self._safe_array(adx_history)
        current_adx = float(adx_arr[-1]) if not np.isnan(adx_arr[-1]) else None
        if current_adx is None:
            return {"signal": False, "classification": "nan_current", "reason": "Current ADX is NaN", "current_adx": None, "threshold_strong": None, "threshold_weak": None, "recent_count": 0}

        # Build recent series
        recent = adx_arr[-window:] if adx_arr.size >= window else adx_arr
        recent_clean = recent[~np.isnan(recent)]
        recent_count = int(recent_clean.size)

        # Determine thresholds with fallback if not enough history
        if recent_count >= min_history_for_quantile:
            threshold_strong = float(np.nanquantile(recent_clean, strong_quantile))
            threshold_weak = float(np.nanquantile(recent_clean, weak_quantile))
            used_fallback = False
        else:
            threshold_strong = float(fallback_strong)
            threshold_weak = float(fallback_weak)
            used_fallback = True

        # Simple checks
        meets_min = current_adx >= min_adx

        # classification by comparing current adx to weak/strong thresholds
        if current_adx < threshold_weak:
            classification = "weak"
        elif current_adx >= threshold_strong:
            classification = "strong"
        else:
            classification = "moderate"

        # percentile and zscore for extra diagnostics
        percentile = float(np.sum(recent_clean < current_adx) / recent_count) if recent_count > 0 else None
        mean_recent = float(np.nanmean(recent_clean)) if recent_count > 0 else None
        std_recent = float(np.nanstd(recent_clean, ddof=0)) if recent_count > 0 else None
        zscore = (current_adx - mean_recent) / std_recent if (mean_recent is not None and std_recent and std_recent > 0) else None

        # slope estimate
        slope = None
        slope_positive = None
        if slope_window >= 2:
            last_valid = adx_arr[~np.isnan(adx_arr)]
            if last_valid.size >= 2:
                y = last_valid[-min(slope_window, last_valid.size):]
                if y.size >= 2:
                    x = np.arange(y.size, dtype=float)
                    p = np.polyfit(x, y, 1)
                    slope = float(p[0])
                    slope_positive = slope > slope_threshold

        # signal boolean: keep simple (strong classification AND meets min_adx)
        signal = bool(classification == "strong" and meets_min)

        reason = f"classification={classification}; current_adx={current_adx:.2f}; threshold_weak={threshold_weak:.2f}; threshold_strong={threshold_strong:.2f}"
        if used_fallback:
            reason += "; used_fallback"

        return {
            "signal": signal,
            "classification": classification,
            "reason": reason,
            "current_adx": current_adx,
            "threshold_strong": threshold_strong,
            "threshold_weak": threshold_weak,
            "percentile": percentile,
            "mean_recent": mean_recent,
            "std_recent": std_recent,
            "zscore": zscore,
            "slope": slope,
            "slope_positive": slope_positive,
            "meets_min": meets_min,
            "used_fallback_threshold": used_fallback,
            "recent_count": recent_count,
        }

    def _detect_adx_rollover(
        self,
        adx_history: List[Optional[float]],
        peak_window: int = 20,
        decline_window: int = 5,
        min_peak_prominence: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Detect if ADX recently peaked and is rolling over.
        Logic:
        - Find max ADX in the last 'peak_window' bars (or full history if shorter).
        - If the max occurred earlier than the most recent 'decline_window' bars and
            current ADX is lower than that peak by at least min_peak_prominence,
            signal a rollover (potential exhaustion).
        Returns dict with keys: rollover(bool), current_adx, peak_adx, peak_index_from_end, delta_from_peak
        """
        if not adx_history:
            return {"signal": False, "reason": "No ADX history", "current_adx": None, "peak_adx": None, "peak_index_from_end": None, "delta_from_peak": None}

        adx_arr = self._safe_array(adx_history)
        clean = adx_arr[~np.isnan(adx_arr)]
        if clean.size == 0:
            return {"signal": False, "reason": "ADX all NaN", "current_adx": None, "peak_adx": None, "peak_index_from_end": None, "delta_from_peak": None}

        # Work on last peak_window values
        recent_window = adx_arr[-peak_window:] if adx_arr.size >= peak_window else adx_arr
        recent_idx = np.arange(len(adx_arr) - len(recent_window), len(adx_arr))  # global indices
        # Mask NaNs
        mask = ~np.isnan(recent_window)
        if not mask.any():
            return {"signal": False, "reason": "Not enough valid ADX in peak window", "current_adx": float(adx_arr[-1]) if not np.isnan(adx_arr[-1]) else None, "peak_adx": None, "peak_index_from_end": None, "delta_from_peak": None}

        recent_valid = recent_window[mask]
        recent_valid_idx = recent_idx[mask]
        # Peak in recent window
        peak_pos = int(np.argmax(recent_valid))
        peak_adx = float(recent_valid[peak_pos])
        peak_global_idx = int(recent_valid_idx[peak_pos])
        # distance from end
        peak_index_from_end = len(adx_arr) - 1 - peak_global_idx

        current_adx = float(adx_arr[-1]) if not np.isnan(adx_arr[-1]) else None
        if current_adx is None:
            return {"signal": False, "reason": "Current ADX is NaN", "current_adx": None, "peak_adx": peak_adx, "peak_index_from_end": peak_index_from_end, "delta_from_peak": None}

        delta = peak_adx - current_adx

        # Consider rollover if the peak is not the last bar (i.e., peak occurred earlier) and the drop is meaningful
        if (peak_index_from_end >= decline_window) and (delta >= min_peak_prominence):
            return {"signal": True, "reason": "ADX peaked earlier and declined", "current_adx": current_adx, "peak_adx": peak_adx, "peak_index_from_end": peak_index_from_end, "delta_from_peak": delta}
        else:
            return {"signal": False, "reason": "No clear ADX rollover detected", "current_adx": current_adx, "peak_adx": peak_adx, "peak_index_from_end": peak_index_from_end, "delta_from_peak": delta}

    def _check_trend_and_volatility(
        self,
        atr_val_history: List[Optional[float]],
        adx_val_history: List[Optional[float]],
        price_history: List[Optional[float]],
        window: int = 100,
        mode: Literal["trend", "reversal", "exhaustion"] = "trend",
        # parameters for trend
        trend_quantiles: List[float] = [0.7, 0.3],
        # parameters for exhaustion detection
        adx_peak_window: int = 20,
        adx_decline_window: int = 5,
        adx_min_peak_prominence: float = 2.0,
    ) -> TrendStrength:
        """
        综合判断市场状态：'trend', 'reversal', 'exhaustion'
        - trend: strong ADX + high volatility
        - reversal: weak ADX + high volatility (good for mean-reversion if vol high? depends on strategy)
        - exhaustion: ADX peaked then rolled over + volatility spike (fade the exhaustion)
        Returns TrendStrength dataclass with detailed nested info.
        """
        vol_info = self._check_volatility(atr_val_history, price_history, window=window)
        trend_info = self._check_trend_strength(adx_val_history, window=window, quantiles=trend_quantiles)

        if mode == "trend":
            signal = vol_info["signal"] and trend_info["signal"]
            reason = "Strong trend + high volatility" if signal else "Conditions not met for trend"
        elif mode == "reversal":
            # Standard reversal: weak ADX (trend_info False because ADX < dynamic) AND volatility high
            signal = (not trend_info["signal"]) and vol_info["signal"]
            reason = "Weak trend + high volatility" if signal else "Conditions not met for reversal"
        elif mode == "exhaustion":
            # Exhaustion means ADX peaked then rolled down (adx_roll_info) AND volatility is high
            adx_roll_info = self._detect_adx_rollover(adx_val_history, peak_window=adx_peak_window, decline_window=adx_decline_window, min_peak_prominence=adx_min_peak_prominence)
            signal = bool(adx_roll_info.get("signal")) and vol_info["signal"]
            reason = "ADX rolled over after peak + high volatility (exhaustion)" if signal else "Conditions not met for exhaustion reversal"
            return TrendStrength(signal=signal, mode=mode, reason=reason, trend=trend_info, volatility=vol_info, adx_rollover=adx_roll_info) 
        else:
            signal = False
            reason = "Invalid mode"

        return TrendStrength(signal=signal, mode=mode, reason=reason, trend=trend_info, volatility=vol_info, adx_rollover=None) 

    # --- 工具函数 ---
    def _safe_array(self, x: List[Optional[float]]) -> np.ndarray:
        """Convert list to float np.array and coerce None to np.nan."""
        return np.array([np.nan if v is None else float(v) for v in x], dtype=float)

    def _compute_return_L(self, closes: List[float], L: int) -> Optional[float]:
        if len(closes) <= L:
            return None
        past = closes[-L - 1]
        curr = closes[-1]
        if abs(past) < EPS:
            return None
        return curr / past - 1.0
    
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
        """
        返回 value 在 arr 中的百分位(0-100)。
        使用 (less + 0.5*equal) 逻辑处理平局，统计更准确。
        """
        if not arr:
            # 安全返回 100.0，避免在数据不足时错误触发 Squeeze (低百分位) 信号
            return 100.0
        
        # 对于小窗口 (N < 500)，纯 Python 比 np.array() 转换更快
        less = sum(1 for x in arr if x < value)
        equal = sum(1 for x in arr if x == value)
        
        # 计算排名
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