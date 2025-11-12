import logging
from typing import List, Optional, Dict, Any

import numpy as np

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

class CandlestickReversalStrategy(TradingStrategy):
    """
    基于蜡烛图的反转策略（中文注释）
    要点：
      - 检测常见反转烛形：锤子/倒锤子、吞没、十字/十字星、刺透/乌云（此处实现为常见子集）
      - 使用 EMA 作为趋势过滤，ATR 作为止损尺度，RSI/MACD/成交量作为确认项
      - 返回 SignalModel，details 包含 entry/stop/target 与评分细节
    """
    def __init__(
        self,
        ema_fast: int = 13,
        ema_slow: int = 34,
        atr_period: int = 14,
        atr_mult_sl: float = 1.5,
        target_rr: float = 2.0,
        rsi_period: int = 14,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        macd_params: Optional[Dict[str,int]] = None,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.6,
        data_provider: Any = None
    ):
        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.atr_period = int(atr_period)
        self.atr_mult_sl = float(atr_mult_sl)
        self.target_rr = float(target_rr)
        self.rsi_period = int(rsi_period)
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # 指标字段名约定（provider 兼容）
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"

    def get_name(self) -> str:
        return "CandlestickReversal"
    
    def get_lookback_window(self) -> int:
        """
        返回此策略需要的最小回溯 candle 数（用于判断是否有足够数据）。
        计算逻辑（经验规则）：
            - 至少包括慢速 EMA、ATR、RSI 与 MACD 的周期长度中的最大者
            - 再加少量安全边际
        这样在回测/实盘中能保证 provider 指标序列包含所需历史数据。
        """
        # 安全读取各指标周期（若未设置则使用合理默认）
        macd_max = max(int(self.macd_params.get("fast", 0) or 0),
                        int(self.macd_params.get("slow", 0) or 0),
                        int(self.macd_params.get("signal", 0) or 0))
        # 基础窗口取上述最大者
        base = max(self.ema_slow, self.atr_period, self.rsi_period, macd_max, 3)
        # 最后加上小的安全边际
        lookback = base + 3
        return int(lookback)

    # ---------- 烛形模式检测 ----------
    def _is_bullish_engulfing(self, prev_open, prev_close, open_, close_) -> bool:
        return (prev_close < prev_open) and (close_ > open_) and (close_ > prev_open) and (open_ < prev_close)

    def _is_bearish_engulfing(self, prev_open, prev_close, open_, close_) -> bool:
        return (prev_close > prev_open) and (close_ < open_) and (close_ < prev_open) and (open_ > prev_close)

    def _is_hammer(self, open_, high, low, close_) -> bool:
        body = abs(close_ - open_)
        lower_wick = min(open_, close_) - low
        upper_wick = high - max(open_, close_)
        return lower_wick >= 2 * body and upper_wick <= body

    def _is_shooting_star(self, open_, high, low, close_) -> bool:
        body = abs(close_ - open_)
        upper_wick = high - max(open_, close_)
        lower_wick = min(open_, close_) - low
        return upper_wick >= 2 * body and lower_wick <= body

    def _is_doji(self, open_, close_, tol: float = 0.03) -> bool:
        return abs(open_ - close_) <= tol * max(abs(open_), abs(close_), 1.0)

    # ---------- 通用指标提取与动量确认 ----------
    def _extract_latest_indicator_value(self, series: Optional[List[Any]], keys: List[str]) -> Optional[float]:
        """兼容 provider 返回对象/字典/直接数值，提取最后一条数值字段"""
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
                v = getattr(last, k, None) if hasattr(last, k) else (last.get(k) if isinstance(last, dict) else None)
            except Exception:
                v = None
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    continue
        return None

    def _momentum_confirmation(self, rsi_series: Optional[List[Any]], macd_series: Optional[List[Any]], prefer: str = "bull") -> bool:
        """
        简单动量确认：
          - prefer="bull": 期待 MACD hist > 0 或 RSI > 30
          - prefer="bear": 期待 MACD hist < 0 或 RSI < 70
        """
        r_latest = self._extract_latest_indicator_value(rsi_series, [self.rsi_field]) if rsi_series else None
        macd_hist_latest = None
        if macd_series:
            macd_hist_latest = getattr(macd_series[-1], self.macd_hist_field, None)

        if prefer == "bear":
            if r_latest is not None and r_latest < 70:
                return True
            if macd_hist_latest is not None and macd_hist_latest < 0:
                return True
            return False
        else:
            if r_latest is not None and r_latest > 30:
                return True
            if macd_hist_latest is not None and macd_hist_latest > 0:
                return True
            return False

    # ---------- 主决策逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        # 数据校验
        if not candles or len(candles) < max(self.ema_slow, self.atr_period, 3):
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=None, reason="insufficient data", confidence=0.0)

        # 提取 OHLCV 与日期
        closes = [float(getattr(c, "close")) for c in candles]
        highs = [float(getattr(c, "high")) for c in candles]
        lows = [float(getattr(c, "low")) for c in candles]
        opens = [float(getattr(c, "open")) for c in candles]
        vols = [getattr(c, "volume", None) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]
        close = closes[-1]

        # 从 provider 获取指标（尽量使用 provider，再 fallback）
        ema_fast_s = self.provider.get_indicator("ema", candles, {"length": self.ema_fast}) if self.provider else None
        ema_slow_s = self.provider.get_indicator("ema", candles, {"length": self.ema_slow}) if self.provider else None
        atr_s = self.provider.get_indicator("atr", candles, {"length": self.atr_period}) if self.provider else None
        rsi_s = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period}) if self.provider else None
        macd_s = self.provider.get_indicator("macd", candles, self.macd_params) if (self.provider and self.macd_params) else None
        adx_s = self.provider.get_indicator("adx", candles, {"length": self.adx_period}) if self.provider else None

        ema_f = self._extract_latest_indicator_value(ema_fast_s, [self.ema_fast_field])
        ema_slow = self._extract_latest_indicator_value(ema_slow_s, [self.ema_slow_field])
        atr_val = self._extract_latest_indicator_value(atr_s, [self.atr_field]) or 0.0
        rsi_val = self._extract_latest_indicator_value(rsi_s, [self.rsi_field])
        adx_val = self._extract_latest_indicator_value(adx_s, [self.adx_field])

        # 检测烛形（使用最后 1-2 根烛）
        pattern = None
        # 优先识别由倒数第二根发起的两根组合（如吞没），否则单根形态以最后一根为参考
        if len(candles) >= 2 and self._is_bullish_engulfing(opens[-2], closes[-2], opens[-1], closes[-1]):
            pattern = "bullish_engulfing"; 
        elif len(candles) >= 2 and self._is_bearish_engulfing(opens[-2], closes[-2], opens[-1], closes[-1]):
            pattern = "bearish_engulfing"; 
        else:
            if self._is_hammer(opens[-1], highs[-1], lows[-1], closes[-1]):
                pattern = "hammer"; 
            elif self._is_shooting_star(opens[-1], highs[-1], lows[-1], closes[-1]):
                pattern = "shooting_star"; 
            elif self._is_doji(opens[-1], closes[-1]):
                pattern = "doji"; 

        # 趋势判断
        trend_long = (ema_f is not None and ema_slow is not None and ema_f > ema_slow)
        trend_short = (ema_f is not None and ema_slow is not None and ema_f < ema_slow)
        # 趋势强度
        adx_ok = True if adx_val <= self.adx_threshold else False
        
        # 成交量确认（使用 z-score）
        vol_ok = False
        z_score = None
        vol_window = min(self.vol_zscore_window, len(vols)) if vols else 0
        if vols and vols[-1] is not None and vol_window >= 2:
            recent_vols = [v for v in vols[-vol_window:] if v is not None]
            mean_vol = float(np.mean(recent_vols))
            std_vol = float(np.std(recent_vols, ddof=0))
            if std_vol > 0:
                z_score = (vols[-1] - mean_vol) / std_vol
                vol_ok = z_score > 1.0

        # 动量确认（MACD / RSI）
        mom_ok = self._momentum_confirmation(rsi_s, macd_s, prefer="bull" if pattern in ("bullish_engulfing","hammer") else "bear")

        # 评分系统：简单加权，若要求确认且未确认则降低初始权重
        # 强调形态 + 成交量 + 趋势共振
        score = 0.0; reasons = []; entry = None; stop_loss = None; target = None
        if pattern:
            # 形态识别
            score += 0.25
            reasons.append(f"形态:{pattern}")
            # 成交量评分（非线性）
            if vol_ok:
                score += 0.20
                reasons.append(f"成交量确认")
            # 动量确认
            if mom_ok:
                score += 0.15
                reasons.append("动量确认")
            # 趋势强度确认
            if adx_ok:
                score += 0.15
                reasons.append("趋势强度确认")
            # EMA 趋势方向一致
            if (pattern in ("bullish_engulfing", "hammer") and trend_long) or \
            (pattern in ("bearish_engulfing", "shooting_star") and trend_short):
                score += 0.15
                reasons.append("趋势方向一致")
            # 共振加分
            if mom_ok and adx_ok and ((pattern in ("bullish_engulfing", "hammer") and trend_long) or \
                                    (pattern in ("bearish_engulfing", "shooting_star") and trend_short)):
                score += 0.1
                reasons.append("三重共振加分")

            confidence = min(1.0, score)
            # 确定方向并计算 stop/target（用 ATR 缩放）
            if confidence >= self.score_threshold:
                if pattern in ("bullish_engulfing", "hammer"):
                    entry = close
                    recent_low = min(lows[-3:]) if len(lows) >= 3 else lows[-1]
                    stop_loss = recent_low - (self.atr_mult_sl * atr_val)
                    target = entry + max(self.target_rr * (entry - stop_loss), 2 * atr_val)
                    signal = "buy"
                elif pattern in ("bearish_engulfing", "shooting_star"):
                    entry = close
                    recent_high = max(highs[-3:]) if len(highs) >= 3 else highs[-1]
                    stop_loss = recent_high + (self.atr_mult_sl * atr_val)
                    target = entry - max(self.target_rr * (stop_loss - entry), 2 * atr_val)
                    signal = "sell"
                else:
                    signal = "hold"
                    reasons.append("unsupported pattern for trade")
            else:
                signal = "hold"
                reasons.append("score below threshold")
        else:
            confidence = 0.0
            signal = "hold"
            reasons.append("no_pattern")

        details = {
            "pattern": pattern,
            "ema_fast": ema_f,
            "ema_slow": ema_slow,
            "atr": atr_val,
            "rsi": rsi_val,
            "macd_present": bool(macd_s),
            "vol_zscore": round(z_score, 3) if z_score is not None else None,
            "entry": round(entry, 6) if entry is not None else None,
            "stop_loss": round(stop_loss, 6) if stop_loss is not None else None,
            "target": round(target, 6) if target is not None else None,
            "score": round(score, 3),
            "reasons": reasons
        }

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=dates[-1],
            confidence=round(confidence, 3),
            reason=" | ".join(reasons),
            details=details
        )

def make_candlestick_reversal_presets() -> Dict[str, Dict[str, Any]]:
    """
    CandlestickReversal 策略预设（基于资深 algo trader 经验）
    三档：
        - swing: 短波段（1-2 周），更灵敏、更短的确认窗口、较低成交量门槛与较小止损
        - intermediate: 中波段（2-6 周），平衡设置（回测默认）
        - position: 中长线（1-3 月），更保守、更严格的趋势/成交量/止损设置
    """
    swing = {
        # 指标与周期
        "ema_fast": 8,
        "ema_slow": 21,
        "atr_period": 14,
        "rsi_period": 9,
        "adx_period": 7,
        "adx_threshold": 18.0,
        "macd_params": {"fast": 8, "slow": 17, "signal": 9},

        # 风险 / 止损 / 目标
        "atr_mult_sl": 1.2,
        "target_rr": 1.8,
        "score_threshold": 0.70,

        # 确认与成交量
        "vol_zscore_window": 10,
        "vol_zscore_threshold": 0.8,
    }

    intermediate = {
        "ema_fast": 13,
        "ema_slow": 34,
        "atr_period": 14,
        "rsi_period": 14,
        "adx_period": 14,
        "adx_threshold": 25.0,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},

        "atr_mult_sl": 1.5,
        "target_rr": 2.0,
        "score_threshold": 0.75,

        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.0
    }

    position = {
        "ema_fast": 21,
        "ema_slow": 55,
        "atr_period": 21,
        "rsi_period": 21,
        "adx_period": 20,
        "adx_threshold": 30.0,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},

        "atr_mult_sl": 2.0,
        "target_rr": 2.5,
        "score_threshold": 0.8,

        # 更长期通常放宽短期确认，但要求更强量能
        "vol_zscore_window": 40,
        "vol_zscore_threshold": 1.2
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}