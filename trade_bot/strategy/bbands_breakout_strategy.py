from typing import List, Optional, Dict, Any, Tuple
import math
import statistics
from datetime import datetime, timedelta

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

class BollingerBreakoutStrategy(TradingStrategy):
    """
    Bollinger Band Breakout 策略（生产就绪版）

    策略概述
    ----------
    - 波动率扩张策略：在“收缩(squeeze)”之后，价格突破布林带收盘即触发方向性入场，
      需满足趋势过滤（EMA快线/慢线）和前期摆动高/低位确认。
    - 提供 ATR 风险控制、Chandelier trailing stop、时间止损、以及均值回归失败保护（failsafe）。
    - 设计为基于日线（daily candles）识别短期趋势并执行基于 weekly pattern 的波段交易。
      通过 presets 可切换到中/长周期模式（mid-term / long-term）。

    关键参数与指标
    - BB: SMA(n), Upper = MA + k*STD, Lower = MA - k*STD
    - BW (Bandwidth) = (Upper - Lower) / MA
    - BW 百分位: 在 trailing_bw_window (默认100日) 内的百分位，用于判断 squeeze
    - EMA(fast), EMA(slow) : 趋势滤波
    - ATR : 风险与止损参考
    - ADX (可选) : 趋势强度过滤
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        trailing_bw_window: int = 100,
        bw_percentile_threshold: float = 30.0,  # percentile threshold (e.g. 30)
        ema_fast: int = 13,
        ema_slow: int = 34,
        atr_period: int = 14,
        adx_period: Optional[int] = None,
        prior_swing_bars: int = 5,
        entry_atr_mult: float = 1.8,
        chandelier_len: int = 22,
        chandelier_atr_mult: float = 3.0,
        time_stop_bars: int = 15,
        min_atr_price_ratio: float = 0.002,  # volatility guard: ATR / price
        score_threshold: float = 0.6,
        data_provider = None
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.trailing_bw_window = trailing_bw_window
        self.bw_percentile_threshold = bw_percentile_threshold
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.prior_swing_bars = prior_swing_bars
        self.entry_atr_mult = entry_atr_mult
        self.chandelier_len = chandelier_len
        self.chandelier_atr_mult = chandelier_atr_mult
        self.time_stop_bars = time_stop_bars
        self.min_atr_price_ratio = min_atr_price_ratio
        self.score_threshold = score_threshold
        self.provider = data_provider

    def get_name(self) -> str:
        return "BollingerBreakout"

    def get_lookback_window(self) -> int:
        # 需要的最少历史条数：用于计算 trailing_bw_window、chandelier、ATR、EMA 等
        return max(self.trailing_bw_window, self.chandelier_len, self.atr_period, self.ema_slow, self.prior_swing_bars) + 5

    # --- 工具函数 ---
    def _percentile_rank(self, arr: List[float], value: float) -> float:
        """返回 value 在 arr 中的百分位(0-100)；arr 长度应>0"""
        if not arr:
            return 100.0
        less = sum(1 for x in arr if x < value)
        equal = sum(1 for x in arr if x == value)
        rank = (less + 0.5 * equal) / len(arr) * 100.0
        return rank

    def _sma(self, vals: List[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    def _std(self, vals: List[float]) -> float:
        return statistics.pstdev(vals) if len(vals) > 0 else 0.0

    def _highest(self, vals: List[float], n: int) -> float:
        return max(vals[-n:]) if len(vals) >= n and n > 0 else max(vals)

    def _lowest(self, vals: List[float], n: int) -> float:
        return min(vals[-n:]) if len(vals) >= n and n > 0 else min(vals)

    # --- 主逻辑 ---
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        Input:
            symbol: 标的
            candles: 日线序列，按时间升序排列（old ... recent），每个元素需包含 high/low/open/close/volume/date
        Output:
            SignalModel with fields: signal in {'buy','sell','hold'}, confidence, reason, details
        """
        # 基本数据校验
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date if candles else None,
                reason="数据不足",
                confidence=0.0
            )

        # 获取指标（依赖 provider）
        bb = self.provider.get_indicator("bbands", candles, {"length": self.bb_period, "std": self.bb_std})
        ema_fast = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        adx = None
        if self.adx_period:
            adx = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        # 提取 recent 值（以 provider 返回的属性命名为近似格式）
        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]

        idx = len(candles) - 1
        close = closes[-1]

        # BB 当前值（根据 provider 字段命名可能不同，尝试常见字段名）
        bbu = getattr(bb[-1], f"close_BBU_{self.bb_period}_{self.bb_std}", None) if bb else None
        bbl = getattr(bb[-1], f"close_BBL_{self.bb_period}_{self.bb_std}", None) if bb else None
        bbm = getattr(bb[-1], f"close_BBM_{self.bb_period}_{self.bb_std}", None) if bb else None

        # 兼容不同provider字段名（常见）
        if bbu is None and bb:
            bbu = getattr(bb[-1], "upper", None) or getattr(bb[-1], "BBU", None)
            bbl = bbl or getattr(bb[-1], "lower", None) or getattr(bb[-1], "BBL", None)
            bbm = bbm or getattr(bb[-1], "middle", None) or getattr(bb[-1], "BBM", None)

        if None in (bbu, bbl, bbm):
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=dates[-1],
                reason="缺少BB指标",
                confidence=0.0
            )

        # 计算 BandWidth（当前）与 trailing BW 队列（用于百分位）
        curr_bw = (bbu - bbl) / (bbm if abs(bbm) > EPS else 1.0)
        bw_list = []
        # 从 provider 的 bb 历史中提取 bandwidth（兼容字段不足则自计算）
        for i in range(max(0, idx - self.trailing_bw_window + 1), idx + 1):
            # 尝试取 provider 中的上/下/中值
            try:
                bbi = bb[i]
                u = getattr(bbi, f"close_BBU_{self.bb_period}_{self.bb_std}", None) or getattr(bbi, "upper", None) or getattr(bbi, "BBU", None)
                l = getattr(bbi, f"close_BBL_{self.bb_period}_{self.bb_std}", None) or getattr(bbi, "lower", None) or getattr(bbi, "BBL", None)
                m = getattr(bbi, f"close_BBM_{self.bb_period}_{self.bb_std}", None) or getattr(bbi, "middle", None) or getattr(bbi, "BBM", None)
                if None not in (u, l, m) and abs(m) > EPS:
                    bw_list.append((u - l) / m)
                else:
                    # 备用：用 price slice 计算
                    window = closes[max(0, i - self.bb_period + 1):i+1]
                    if len(window) >= self.bb_period:
                        sma = self._sma(window)
                        std = self._std(window)
                        bw_list.append(( (sma + self.bb_std*std) - (sma - self.bb_std*std) ) / (sma if abs(sma)>EPS else 1.0))
            except Exception:
                continue

        bw_pct = self._percentile_rank(bw_list, curr_bw) if bw_list else 100.0
        in_squeeze = bw_pct <= self.bw_percentile_threshold

        # 趋势过滤（EMA）
        try:
            ema_f = float(getattr(ema_fast[-1], f"EMA_{self.ema_fast}") or getattr(ema_fast[-1], "ema", None) or ema_fast[-1])
            ema_s = float(getattr(ema_slow[-1], f"EMA_{self.ema_slow}") or getattr(ema_slow[-1], "ema", None) or ema_slow[-1])
        except Exception:
            # 退回到简单均线差
            ema_f = sum(closes[-self.ema_fast:]) / self.ema_fast
            ema_s = sum(closes[-self.ema_slow:]) / self.ema_slow

        trend_long = ema_f > ema_s
        trend_short = ema_f < ema_s

        # ATR 当前值
        try:
            atr_val = float(getattr(atr[-1], f"ATR_{self.atr_period}") or getattr(atr[-1], "atr", None) or atr[-1])
        except Exception:
            # 计算简单近似 ATR（高低振幅 SMA）
            trs = [abs(highs[i] - lows[i]) for i in range(max(0, idx - self.atr_period + 1), idx+1)]
            atr_val = self._sma(trs) if trs else 0.0

        # 波动性 guard
        vol_guard_ok = (atr_val / (close if abs(close)>EPS else 1.0)) >= self.min_atr_price_ratio

        # prior swing high/low over prior_swing_bars (exclude current)
        prior_range_high = max(highs[max(0, idx - self.prior_swing_bars): idx]) if idx - self.prior_swing_bars >= 0 else max(highs[:-1])
        prior_range_low = min(lows[max(0, idx - self.prior_swing_bars): idx]) if idx - self.prior_swing_bars >= 0 else min(lows[:-1])

        # 信号判定
        long_break = (close > bbu) and (close > prior_range_high) and trend_long and in_squeeze and vol_guard_ok
        short_break = (close < bbl) and (close < prior_range_low) and trend_short and in_squeeze and vol_guard_ok

        # ADX 趋势强度（可选）提高置信度
        adx_val = None
        if adx:
            try:
                adx_val = float(getattr(adx[-1], f"ADX_{self.adx_period}") or getattr(adx[-1], "ADX", None) or adx[-1])
            except Exception:
                adx_val = None

        # 评分 & 生成 signal
        confidence = 0.0
        reason_parts = []
        details: Dict[str, Any] = {
            "close": close,
            "bbu": bbu,
            "bbl": bbl,
            "bbm": bbm,
            "bw_pct": round(bw_pct, 2),
            "ema_fast": round(ema_f, 4),
            "ema_slow": round(ema_s, 4),
            "atr": round(atr_val, 6),
            "prior_high": prior_range_high,
            "prior_low": prior_range_low,
            "in_squeeze": in_squeeze,
            "vol_guard_ok": vol_guard_ok
        }

        signal = "hold"

        if long_break or short_break:
            # 基本信号分数由多条件累加
            score = 0.0
            # squeeze 强度（越小越好）
            score += max(0.0, (100.0 - bw_pct) / 100.0) * 0.4
            # EMA 趋势确认
            score += 0.3
            # ATR guard
            score += 0.15 if vol_guard_ok else 0.0
            # ADX 加权
            if adx_val is not None:
                score += 0.15 * (min(adx_val, 40.0) / 40.0)

            confidence = min(1.0, score)
            details["score"] = round(score, 3)

            # 计算入场止损与 trailing stop
            entry_price = close
            stop_loss = entry_price - self.entry_atr_mult * atr_val if long_break else entry_price + self.entry_atr_mult * atr_val
            # chandelier: for long use highest(high, L) - mult*ATR ; for short use lowest(low,L) + mult*ATR
            if long_break:
                chandelier = self._highest(highs, self.chandelier_len) - self.chandelier_atr_mult * atr_val
            else:
                chandelier = self._lowest(lows, self.chandelier_len) + self.chandelier_atr_mult * atr_val

            details.update({
                "entry_price": entry_price,
                "initial_stop": round(stop_loss, 6),
                "chandelier_stop": round(chandelier, 6),
                "entry_atr_mult": self.entry_atr_mult,
                "chandelier_atr_mult": self.chandelier_atr_mult,
                "time_stop_bars": self.time_stop_bars
            })

            # 生成具体信号类型
            if long_break and confidence >= self.score_threshold:
                signal = "buy"
                reason_parts.append("BB上破后收盘")
                reason_parts.append(f"Squeeze BW_pct={bw_pct:.1f}%")
                reason_parts.append("EMA 趋势向上")
                if adx_val:
                    reason_parts.append(f"ADX={adx_val:.1f}")
            elif short_break and confidence >= self.score_threshold:
                signal = "sell"
                reason_parts.append("BB下破后收盘")
                reason_parts.append(f"Squeeze BW_pct={bw_pct:.1f}%")
                reason_parts.append("EMA 趋势向下")
                if adx_val:
                    reason_parts.append(f"ADX={adx_val:.1f}")
            else:
                # 未达到阈值则观望
                signal = "hold"
                reason_parts.append("突破发生但置信度不足")
        else:
            reason_parts.append("无有效突破或不在squeeze/趋势不符/波动率不足")

        # 失败保护（mean-reversion failsafe）说明（仅作为出场规则，不直接在此刻触发）
        details["failsafe"] = (
            "如果入场后在 time_stop_bars 内出现价格回归到 BB 内并穿过 midline (BBM)，则考虑平仓（均值回归保护）"
        )

        reason = " | ".join(reason_parts)

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=dates[-1],
            confidence=round(confidence, 3),
            reason=reason,
            details=details
        )


def make_bbands_breakout_presets() -> Dict[str, Dict[str, Any]]:
    """
    预设配置（用于快速切换策略参数）

    - swing: 主要用于 1-2 周波段
    - intermediate: 主要用于 2-6 周波段
    - position: 主要用于 1-3 月持仓
    """
    swing = {
        "bb_period": 20,
        "bb_std": 2.0,
        "trailing_bw_window": 80,
        "bw_percentile_threshold": 30.0,
        "ema_fast": 13,
        "ema_slow": 34,
        "atr_period": 14,
        "prior_swing_bars": 5,
        "entry_atr_mult": 1.6,
        "chandelier_len": 22,
        "chandelier_atr_mult": 3.0,
        "time_stop_bars": 12,
        "min_atr_price_ratio": 0.0015,
        "score_threshold": 0.6
    }

    intermediate = {
        "bb_period": 20,
        "bb_std": 2.0,
        "trailing_bw_window": 100,
        "bw_percentile_threshold": 30.0,
        "ema_fast": 21,
        "ema_slow": 55,
        "atr_period": 14,
        "prior_swing_bars": 8,
        "entry_atr_mult": 1.8,
        "chandelier_len": 34,
        "chandelier_atr_mult": 3.0,
        "time_stop_bars": 20,
        "min_atr_price_ratio": 0.002,
        "score_threshold": 0.65
    }

    position = {
        "bb_period": 20,
        "bb_std": 2.0,
        "trailing_bw_window": 150,
        "bw_percentile_threshold": 35.0,
        "ema_fast": 34,
        "ema_slow": 89,
        "atr_period": 21,
        "prior_swing_bars": 13,
        "entry_atr_mult": 2.0,
        "chandelier_len": 55,
        "chandelier_atr_mult": 3.5,
        "time_stop_bars": 40,
        "min_atr_price_ratio": 0.0025,
        "score_threshold": 0.7
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}