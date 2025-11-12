from typing import List, Optional, Dict, Any, Tuple
import statistics

import numpy as np

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
    - ADX (可选) : 趋势强度过滤，判断趋势，反正

    Long/bull, filter: in_squeeze, adx, atr, volume, trend(ema/sma), momentum 
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
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        rsi_period: Optional[int] = 14,
        prior_swing_bars: int = 5,
        entry_atr_mult: float = 1.8,
        chandelier_len: int = 22,
        chandelier_atr_mult: float = 3.0,
        time_stop_bars: int = 15,
        min_atr_price_ratio: float = 0.002,  # volatility guard: ATR / price
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
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
        self.adx_threshold = adx_threshold
        self.rsi_period = rsi_period
        self.prior_swing_bars = prior_swing_bars
        self.entry_atr_mult = entry_atr_mult
        self.chandelier_len = chandelier_len
        self.chandelier_atr_mult = chandelier_atr_mult
        self.time_stop_bars = time_stop_bars
        self.min_atr_price_ratio = min_atr_price_ratio
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = score_threshold
        self.provider = data_provider

        # 指标字段命名（对应 provider 返回的属性）
        self.bb_bw_field = f"close_BBB_{self.bb_period}_{self.bb_std}"
        self.bb_up_field = f"close_BBU_{self.bb_period}_{self.bb_std}"
        self.bb_low_field = f"close_BBL_{self.bb_period}_{self.bb_std}"
        self.bb_mid_field = f"close_BBM_{self.bb_period}_{self.bb_std}"
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"

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

    def _highest(self, vals: List[float], n: int) -> float:
        return max(vals[-n:]) if len(vals) >= n and n > 0 else max(vals)

    def _lowest(self, vals: List[float], n: int) -> float:
        return min(vals[-n:]) if len(vals) >= n and n > 0 else min(vals)

    def _read_provider_bandwidth(self, bb: Any, closes: List[float], idx: int) -> Tuple[Optional[float], List[float], Optional[float], Optional[float], Optional[float]]:
        """
        统一读取 provider 提供的 bandwidth 字段及上/中/下带（若可用）。
        返回: (curr_bw, bw_list, u_curr, l_curr, m_curr)
        """
        curr_bw = None
        u_curr = l_curr = m_curr = None
        if not bb:
            return None, [], None, None, None
        # 尝试读取 upper/mid/lower（用于止损/显示）
        try:
            curr_bw = getattr(bb[-1], self.bb_bw_field, None)
            u_curr = getattr(bb[-1], self.bb_up_field, None)
            l_curr = getattr(bb[-1], self.bb_low_field, None)
            m_curr = getattr(bb[-1], self.bb_mid_field, None)
        except Exception:
            u_curr = l_curr = m_curr = None
        # 构建历史 bandwidth 列表：仅从 provider 的 bandwidth 字段收集
        bw_list: List[float] = []
        start = max(0, idx - self.trailing_bw_window + 1)
        for i in range(start, idx + 1):
            try:
                bbi = bb[i] if bb and i < len(bb) else None
                if bbi is None:
                    continue
                v = getattr(bbi, self.bb_bw_field, None)
                if v is not None:
                    bw_list.append(float(v))
            except Exception:
                continue
        return curr_bw, bw_list, u_curr, l_curr, m_curr

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
        adx = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        # 提取 recent 值（以 provider 返回的属性命名为近似格式）
        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        vols = [float(c.volume) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]

        idx = len(candles) - 1
        close = closes[-1]

        # 使用独立函数从 provider 读取 bandwidth（并获取历史 bandwidth 列表与 BBU/BBL/BBM）
        curr_bw, bw_list, bbu, bbl, bbm = self._read_provider_bandwidth(bb, closes, idx)
        if curr_bw is None or not bw_list:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=dates[-1],
                reason=f"缺少 BB bandwidth",
                confidence=0.0
            )
        bw_pct = self._percentile_rank(bw_list, curr_bw)
        # 值越小表示相对于历史越窄（更“收缩”）。用 ≤ threshold 表示“在历史最窄的 X% 范围内视为 squeeze”
        in_squeeze = bw_pct <= self.bw_percentile_threshold

        # 趋势过滤（EMA），使用封装的提取函数（兼容 provider 命名）
        ema_f = self._extract_latest_indicator_value(ema_fast, [self.ema_fast_field])
        ema_s = self._extract_latest_indicator_value(ema_slow, [self.ema_slow_field])
        trend_long = ema_f > ema_s
        trend_short = ema_f < ema_s
        # ATR 当前值
        atr_val = self._extract_latest_indicator_value(atr, [self.atr_field])
        # 波动性 guard
        vol_guard_ok = (atr_val / (close if abs(close)>EPS else 1.0)) >= self.min_atr_price_ratio
        # 成交量 z-score 确认（vol_ok）：用最近 vol_zscore_window 样本计算 z-score
        vol_ok = False
        volume_z = None
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        recent_vols = [v for v in vols[-recent_window:] if v is not None]
        try:
            if recent_vols and len(recent_vols) >= 2 and vols[-1] is not None:
                mean_v = sum(recent_vols) / len(recent_vols)
                std_v = statistics.pstdev(recent_vols) if len(recent_vols) > 1 else 0.0
                if std_v > 0:
                    volume_z = (vols[-1] - mean_v) / std_v
                    vol_ok = volume_z >= self.vol_zscore_threshold
        except Exception:
            vol_ok = False

        # prior swing high/low over prior_swing_bars (exclude current)
        prior_range_high = max(highs[max(0, idx - self.prior_swing_bars): idx]) if idx - self.prior_swing_bars >= 0 else max(highs[:-1])
        prior_range_low = min(lows[max(0, idx - self.prior_swing_bars): idx]) if idx - self.prior_swing_bars >= 0 else min(lows[:-1])

        # ADX 趋势强度
        adx_val = self._extract_latest_indicator_value(adx, [self.adx_field]) if adx else None
        adx_ok = True if adx_val >= self.adx_threshold else False # 突破趋势强度

        # 信号判定
        long_break = (close > bbu) and (close > prior_range_high)
        short_break = (close < bbl) and (close < prior_range_low)

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
        
        # 评分 & 生成 signal
        score = 0.0
        reasons = []
        confidence = 0.0
        signal = "hold"
        # 强调 squeeze 和成交量的共振效应
        if long_break or short_break:
            # 基础突破信号
            score += 0.25
            reasons.append("突破触发")
            # squeeze 强度（非线性）
            if in_squeeze:
                score += 0.25
                reasons.append("Squeeze 确认")
            # ATR 波动率过滤
            if vol_guard_ok:
                score += 0.10
                reasons.append("波动率过滤通过")
            # ADX 趋势强度
            if adx_ok:
                score += 0.15
                reasons.append("趋势强度确认")
            # 成交量确认
            if vol_ok:
                score += 0.15
                reasons.append("成交量放大")
            # EMA 趋势方向一致
            if (long_break and trend_long) or (short_break and trend_short):
                score += 0.10
                reasons.append("趋势方向一致")
            # 共振加分
            if vol_ok and adx_ok and ((long_break and trend_long) or (short_break and trend_short)):
                score += 0.1
                reasons.append("三重共振加分")

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
                
            elif short_break and confidence >= self.score_threshold:
                signal = "sell"
            else:
                # 未达到阈值则观望
                signal = "hold"
                reasons.append("突破发生但置信度不足")
        else:
            reasons.append("无有效突破或不在squeeze/趋势不符/波动率不足")

        # 失败保护（mean-reversion failsafe）说明（仅作为出场规则，不直接在此刻触发）
        details["failsafe"] = (
            f"如果入场后在 time_stop_bars({self.time_stop_bars}) 内出现价格回归到 BB 内并穿过 midline (BBM)，则考虑平仓（均值回归保护）"
        )

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=dates[-1],
            confidence=round(confidence, 3),
            reason=" | ".join(reasons),
            details=details
        )

def make_bbands_breakout_presets() -> Dict[str, Dict[str, Any]]:
    """
    预设：便于在不同持仓周期间快速切换（基于资深 algo trader 的经验调优）
    - swing: 短波段（1-2周），更灵敏的入场、更短的历史窗口、更低的成交量 z-score 阈值
    - intermediate: 中波段（2-6周），平衡的参数（回测默认）
    - position: 中长线（1-3月），更保守、更严格的趋势/成交量/波动性门槛
    """
    swing = {
        "bb_period": 20,
        "bb_std": 2.0,
        "trailing_bw_window": 60,          # 较短历史窗口，更灵敏识别 squeeze
        "bw_percentile_threshold": 20.0,   # 更严格的 squeeze 要求
        "ema_fast": 8,
        "ema_slow": 21,
        "atr_period": 14,
        "adx_period": 7,
        "adx_threshold": 18.0,             # 放低 ADX 要求以提高入场频率
        "rsi_period": 9,
        "prior_swing_bars": 3,
        "entry_atr_mult": 1.2,
        "chandelier_len": 14,
        "chandelier_atr_mult": 2.5,
        "time_stop_bars": 8,
        "min_atr_price_ratio": 0.001,
        "vol_zscore_window": 10,           # 短窗口用于更快响应成交量变化
        "vol_zscore_threshold": 0.8,       # 较低阈值，允许轻微放量确认
        "score_threshold": 0.7
    }

    intermediate = {
        "bb_period": 20,
        "bb_std": 2.0,
        "trailing_bw_window": 100,         # 平衡窗口
        "bw_percentile_threshold": 30.0,
        "ema_fast": 13,
        "ema_slow": 34,
        "atr_period": 14,
        "adx_period": 14,
        "adx_threshold": 25.0,             # 标准 ADX 门槛
        "rsi_period": 14,
        "prior_swing_bars": 8,
        "entry_atr_mult": 1.6,
        "chandelier_len": 22,
        "chandelier_atr_mult": 3.0,
        "time_stop_bars": 15,
        "min_atr_price_ratio": 0.0015,
        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.0,       # 常用阈值：成交量 >=1σ 放大确认
        "score_threshold": 0.75
    }

    position = {
        "bb_period": 20,
        "bb_std": 2.0,
        "trailing_bw_window": 200,         # 长窗口，减少假突破
        "bw_percentile_threshold": 40.0,   # 更宽容的历史百分位（更少信号但更稳）
        "ema_fast": 34,
        "ema_slow": 89,
        "atr_period": 21,
        "adx_period": 20,
        "adx_threshold": 30.0,             # 严格 ADX 要求，确认趋势强度
        "rsi_period": 21,
        "prior_swing_bars": 20,
        "entry_atr_mult": 2.0,
        "chandelier_len": 55,
        "chandelier_atr_mult": 3.5,
        "time_stop_bars": 40,
        "min_atr_price_ratio": 0.0025,
        "vol_zscore_window": 40,           # 更长窗口平滑成交量噪声
        "vol_zscore_threshold": 1.2,       # 更高阈值要求更强的成交量确认
        "score_threshold": 0.8
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}