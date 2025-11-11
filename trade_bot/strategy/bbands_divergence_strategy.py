from typing import List, Optional, Dict, Any, Tuple
import statistics

import numpy as np

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

class BBandsDivergenceStrategy(TradingStrategy):
    """
    Bollinger Band Divergence 策略（生产就绪版）

    策略概述
    ----------
    - 逆势/均值回归策略：检测价格极值与布林带行为不一致（Band 未确认新高/新低 或 BandWidth 缩窄）
    - 在发现背离后，结合动量或反转蜡烛在带附近做反向开仓（做空在顶部背离，做多在底部背离）
    - 使用 ATR 作为止损/仓位尺度，包含时间止损与目标（中轨/对侧带）
    - 设计风格：基于日线识别短期趋势、执行基于 weekly pattern 的波段反转；通过 presets 支持中/长期模式

    主要指标与逻辑
    - BB: SMA(n), Upper/Lower = MA ± k*STD(n)
    - BandWidth (BW) = (Upper - Lower) / MA
    - Swing detection: N-bar fractal（默认 5 棒）用于识别局部高点/低点
    - Divergence rules:
        * Bearish divergence: price higher-high but BB.upper 不创新高（或 BB width 收缩）
        * Bullish divergence: price lower-low but BB.lower 不创新低（或 BB width 收缩）
    - 可选动量确认：RSI/MACD 背离或动量反转
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        swing_window: int = 5,                # 用于识别局部高低点（N-bar fractal）
        bw_shrink_pct: float = 0.85,          # 若当前 BW < recent_peak_bw * bw_shrink_pct 视为带缩窄（可用于加强背离判定）
        lookback_bw_window: int = 100,        # 计算 bandwidth 历史用于比较
        rsi_period: Optional[int] = 14,
        macd_params: Optional[Dict[str,int]] = {"fast":12,"slow":26,"signal":9},
        atr_period: int = 14,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        stop_atr_mult: float = 1.5,
        max_time_bars: int = 12,
        min_atr_price_ratio: float = 0.001,   # 波动性门槛，避免超低波动环境
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.6,
        data_provider = None
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.swing_window = swing_window
        self.bw_shrink_pct = bw_shrink_pct
        self.lookback_bw_window = lookback_bw_window
        self.rsi_period = rsi_period
        self.macd_params = macd_params
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.stop_atr_mult = stop_atr_mult
        self.max_time_bars = max_time_bars
        self.min_atr_price_ratio = min_atr_price_ratio
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = score_threshold
        self.provider = data_provider

        # 指标字段命名（对应 provider 返回的属性）
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.bb_bw_field = f"close_BBB_{self.bb_period}_{self.bb_std}"
        self.bb_up_field = f"close_BBU_{self.bb_period}_{self.bb_std}"
        self.bb_low_field = f"close_BBL_{self.bb_period}_{self.bb_std}"
        self.bb_mid_field = f"close_BBM_{self.bb_period}_{self.bb_std}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.adx_field = f"ADX_{self.adx_period}"

    def get_name(self) -> str:
        return "BBandsDivergence"

    def get_lookback_window(self) -> int:
        return max(self.lookback_bw_window, self.bb_period, self.swing_window, self.atr_period, (self.rsi_period or 0)) + 5

    # ---------- 基础工具 ----------
    def _sma(self, vals: List[float]) -> float:
        return sum(vals)/len(vals) if vals else 0.0

    def _std(self, vals: List[float]) -> float:
        return statistics.pstdev(vals) if len(vals)>0 else 0.0

    def _highest(self, vals: List[float], n: int) -> float:
        return max(vals[-n:]) if len(vals) >= n and n>0 else max(vals)

    def _lowest(self, vals: List[float], n: int) -> float:
        return min(vals[-n:]) if len(vals) >= n and n>0 else min(vals)

    def _find_fractal_points(self, highs: List[float], lows: List[float], window:int) -> Tuple[List[Tuple[int,float]], List[Tuple[int,float]]]:
        """
        简单 N-bar fractal: 返回高点列表与低点列表 (index, value)
        window 表示左右各 window 个棒比较（总宽度 2*window+1）
        """
        highs_pts, lows_pts = [], []
        L = len(highs)
        for i in range(window, L-window):
            left_h = highs[i-window:i]
            right_h = highs[i+1:i+window+1]
            if highs[i] > max(left_h) and highs[i] > max(right_h):
                highs_pts.append((i, highs[i]))
            left_l = lows[i-window:i]
            right_l = lows[i+1:i+window+1]
            if lows[i] < min(left_l) and lows[i] < min(right_l):
                lows_pts.append((i, lows[i]))
        return highs_pts, lows_pts

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
        start = max(0, idx - self.lookback_bw_window + 1)
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
        """从 provider 返回的指标序列中提取最后一条数值，兼容不同字段命名或直接数值列表。"""
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

    def _get_indicator_values_at_indices(self, series: List[Optional[float]], indices: List[int], total_candles_len: int) -> List[Optional[float]]:
        """
        从 provider 的指标 history 列表（series，长度可能小于 total_candles_len）中，
        按全局索引列表 indices 返回对应值列表（顺序与 indices 对应）。
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

    def _momentum_confirmation(self, rsi_series: Optional[List[Any]], macd_series: Optional[List[Any]], prefer: str = "bear") -> bool:
        """
        简单的动量确认：检查最新 RSI / MACD-hist 是否支持方向
        prefer: "bear" 或 "bull"
        """
        r_latest = self._extract_latest_indicator_value(rsi_series, [self.rsi_field, "rsi", "RSI"]) if rsi_series else None
        macd_hist_latest = None
        if macd_series:
            try:
                m = getattr(macd_series[-1], self.macd_field, None) or getattr(macd_series[-1], "macd", None)
                s = getattr(macd_series[-1], self.macd_signal_field, None) or getattr(macd_series[-1], "signal", None)
                if m is not None and s is not None:
                    macd_hist_latest = float(m) - float(s)
            except Exception:
                macd_hist_latest = None

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

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        输出 SignalModel:
          signal: 'buy' / 'sell' / 'hold'
          confidence: [0..1]
          reason, details 包含触发背离、动量确认、止损/目标建议等
        """
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=candles[-1].date if candles else None, reason="数据不足", confidence=0.0)

        # 指标
        bb = self.provider.get_indicator("bbands", candles, {"length": self.bb_period, "std": self.bb_std})
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd = self.provider.get_indicator("macd", candles, self.macd_params)
        adx = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        vols = [float(c.volume) for c in candles]
        dates = [getattr(c,"date",None) for c in candles]
        idx = len(candles)-1
        close = closes[-1]
        prev_close = closes[-2]

        # 使用 provider 提供的 bandwidth 字段（close_BBB_{period}_{std}）进行判定和历史比较
        curr_bw, bb_hist_bw, u_curr, l_curr, m_curr = self._read_provider_bandwidth(bb, closes, idx)
        if curr_bw is None or not bb_hist_bw:
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=dates[-1], reason=f"缺少历史 bandwidth", confidence=0.0)

        # 如果 u/l/m 未提供，则尽量用价格窗口回退计算以便后续止损/near-band 判定
        if None in (u_curr, l_curr, m_curr):
            window = closes[-self.bb_period:]
            if len(window) >= self.bb_period:
                sma = self._sma(window)
                std = self._std(window)
                m_curr = sma
                u_curr = sma + self.bb_std * std
                l_curr = sma - self.bb_std * std
        recent_max_bw = max(bb_hist_bw)
        bw_shrunk = curr_bw < recent_max_bw * self.bw_shrink_pct

        # 构建历史 upper/lower/mid 列表（与 bb_hist_bw 时间对齐），供后续索引使用
        start = max(0, idx - self.lookback_bw_window + 1)
        bb_upper_hist: List[Optional[float]] = []
        bb_lower_hist: List[Optional[float]] = []
        bb_mid_hist: List[Optional[float]] = []
        for i in range(start, idx + 1):
            try:
                bbi = bb[i] if bb and i < len(bb) else None
                if bbi is None:
                    bb_upper_hist.append(None); 
                    bb_lower_hist.append(None); 
                    bb_mid_hist.append(None)
                    continue
                u = getattr(bbi, self.bb_up_field, None)
                l = getattr(bbi, self.bb_low_field, None)
                m = getattr(bbi, self.bb_mid_field, None)
                bb_upper_hist.append(u); bb_lower_hist.append(l); bb_mid_hist.append(m)
            except Exception:
                bb_upper_hist.append(None); bb_lower_hist.append(None); bb_mid_hist.append(None)

        # 找到局部高低点（fractal）
        highs_pts, lows_pts = self._find_fractal_points(highs, lows, self.swing_window)

        signal = "hold"
        confidence = 0.0
        reason_parts = []
        details: Dict[str,Any] = {
            "close": close, "upper": u_curr, "lower": l_curr, "mid": m_curr,
            "curr_bw": round(curr_bw,6), "recent_max_bw": round(recent_max_bw,6), "bw_shrunk": bw_shrunk
        }

        # ATR guard
        try:
            atr_val = float(getattr(atr[-1], self.atr_field))
        except Exception:
            trs = [abs(highs[i]-lows[i]) for i in range(max(0, idx-self.atr_period+1), idx+1)]
            atr_val = self._sma(trs) if trs else 0.0
        vol_guard_ok = (atr_val / (close if abs(close)>EPS else 1.0)) >= self.min_atr_price_ratio
        details["atr"] = round(atr_val,6)
        details["vol_guard_ok"] = vol_guard_ok

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
        
        # ADX 趋势强度
        adx_val = self._extract_latest_indicator_value(adx, [self.adx_field]) if adx else None
        adx_ok = True if adx_val <= self.adx_threshold else False # 反转适合震荡行情，避免强趋势

        # 识别可能的背离对：比较最近两个显著 swing（若存在）
        def _latest_two(points: List[Tuple[int,float]]) -> Optional[Tuple[Tuple[int,float],Tuple[int,float]]]:
            if len(points) < 2:
                return None
            return (points[-2], points[-1])

        bear_divergence = False
        bull_divergence = False
        divergence_info = {}

        # Bearish: price HH but upper band not HH (或 BW 收缩)
        latest_highs = _latest_two(highs_pts)
        if latest_highs:
            (i1,p1),(i2,p2) = latest_highs
            if p2 > p1:  # price made HH
                # 对应的 BB upper 在相应索引附近
                try:
                    u1 = bb_upper_hist[i1 - max(0, idx-self.lookback_bw_window+1)]
                    u2 = bb_upper_hist[i2 - max(0, idx-self.lookback_bw_window+1)]
                except Exception:
                    # fallback 从原 highs 索引附近计算
                    u1 = None; u2 = None
                upper_failed = False
                if u1 is not None and u2 is not None:
                    upper_failed = u2 <= u1 + EPS
                else:
                    # 若无法拿到 upper 历史，用 bw_shrunk 作为替代加强条件
                    upper_failed = bw_shrunk
                if upper_failed:
                    bear_divergence = True
                    divergence_info = {"type":"bear","price_h1":p1,"price_h2":p2,"upper_failed":upper_failed}
        # Bullish: price LL but lower band not LL (或 BW 收缩)
        latest_lows = _latest_two(lows_pts)
        if latest_lows:
            (j1,q1),(j2,q2) = latest_lows
            if q2 < q1:  # price made LL
                try:
                    l1 = bb_lower_hist[j1 - max(0, idx-self.lookback_bw_window+1)]
                    l2 = bb_lower_hist[j2 - max(0, idx-self.lookback_bw_window+1)]
                except Exception:
                    l1 = None; l2 = None
                lower_failed = False
                if l1 is not None and l2 is not None:
                    lower_failed = l2 >= l1 - EPS
                else:
                    lower_failed = bw_shrunk
                if lower_failed:
                    bull_divergence = True
                    divergence_info = {"type":"bull","price_l1":q1,"price_l2":q2,"lower_failed":lower_failed}

        details["divergence_snap"] = divergence_info

        # 动量确认（可选），使用封装函数 _momentum_confirmation
        if bear_divergence or bull_divergence:
            if bear_divergence:
                momentum_ok = self._momentum_confirmation(rsi, macd, prefer="bear")
            else:
                momentum_ok = self._momentum_confirmation(rsi, macd, prefer="bull")
            details["momentum_ok"] = momentum_ok

        # 生成交易信号：要求背离发现、动量确认（如配置）、波动性 guard
        # 强调趋势强度和布林带收缩的共振
        score = 0.0
        reasons = []
        signal_candidate = "hold"
        if bear_divergence or bull_divergence:
            # 背离触发
            score += 0.25
            reasons.append("背离触发")
            # 趋势强度确认
            if adx_ok:
                score += 0.20
                reasons.append("趋势强度确认")
            # 波动率过滤
            if vol_guard_ok:
                score += 0.15
                reasons.append("波动率过滤通过")
            # 布林带收缩评分（非线性）
            if bw_shrunk:
                bw_factor = min(1.0, (recent_max_bw - curr_bw) / (recent_max_bw if abs(recent_max_bw)>EPS else 1.0))
                score += 0.20 * bw_factor
                reasons.append(f"带宽收缩确认（因子 {bw_factor:.3f}）")
            # 成交量确认
            if vol_ok:
                score += 0.15
                reasons.append("成交量放大")
            # 动量确认
            if momentum_ok:
                score += 0.10
                reasons.append("动量确认")
            # 共振加分
            if adx_ok and vol_ok and momentum_ok:
                score += 0.1
                reasons.append("三重共振加分")

            confidence = min(1.0, score)
            details["score"] = round(score, 3)
            # stop / targets
            entry_price = close
            if bear_divergence:
                stop = max(self._highest(highs, self.swing_window+1), entry_price) + self.stop_atr_mult * atr_val
                signal_candidate = "sell"
                reasons.append("顶部背离（价格新高但上轨未确认）")
            elif bull_divergence:
                stop = min(self._lowest(lows, self.swing_window+1), entry_price) - self.stop_atr_mult * atr_val
                signal_candidate = "buy"
                reasons.append("底部背离（价格新低但下轨未确认）")

            details.update({
                "entry_price": entry_price,
                "stop_loss": round(stop,6),
                "stop_atr_mult": self.stop_atr_mult,
                "max_time_bars": self.max_time_bars
            })

            # 进一步要求价格接近对应带位或出现反转蜡烛：近似规则（可由执行层调整为更严格的 candle pattern）
            near_upper = abs(close - u_curr) / (u_curr if abs(u_curr)>EPS else 1.0) <= 0.05
            near_lower = abs(close - l_curr) / (l_curr if abs(l_curr)>EPS else 1.0) <= 0.05
            mid_cross_up = prev_close < m_curr and close > m_curr
            mid_cross_down = prev_close > m_curr and close < m_curr
            mid_cross = (bull_divergence and mid_cross_up) or (bear_divergence and mid_cross_down)

            if (bear_divergence and near_upper) or (bull_divergence and near_lower) or mid_cross:
                if confidence >= self.score_threshold:
                    signal = signal_candidate
                    reasons.append("价格位于对应带附近 -> 触发入场")
                else:
                    signal = "hold"
                    reasons.append("背离成立但置信度不足")
            else:
                # 允许在带附近或在穿越 midline 的反转点入场；若当前不在带附近则建议等待回调 / 反转确认
                signal = "hold"
                reasons.append("背离成立，但价格未靠近带位或未出现明显反转，等待更好入场点")
        else:
            # 否则保持观望
            reasons.append("未符合背离/动量/波动性条件或数据不足")

        # 使用建议与场景（附加到 details 以便上层 UI/日志使用）
        details["usage_notes"] = r"""
            策略目标：在波段顶部/底部背离时做均值回归。
            - 适用：趋势后出现延续乏力且带宽没有确认新极值的反转机会；日线为主，持仓以周为单位。
            - 不适用：重大新闻驱动、极低流动性或极端波动市况。
            - 止损按 recent swing 或 ATR 计算；目标先中轨再对侧带；
        """
        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=dates[-1],
            confidence=round(confidence, 3),
            reason=" | ".join(reason_parts),
            details=details
        )

def make_bbands_divergence_presets() -> Dict[str, Dict[str, Any]]:
    """
    专业调优的 BBands Divergence 预设（基于资深 algo trader 的实践）
    说明（统一三档）：
        - swing: 短波段（1-2周），更灵敏的背离/带宽缩窄检测、较低成交量阈值与较小止损
        - intermediate: 中波段（2-6周），平衡稳健（默认回测合适）
        - position: 中长线（1-3月），严格过滤、更大止损与更高成交量门槛
    设计原则：
        - 使用较短 lookback 与小 swing_window 提高短线信号频率（swing 档）
        - position 档延长 lookback/atr 以减少噪声与假信号
        - 成交量用 z-score 过滤，结合 ATR / price 做波动性 guard
    """
    swing = {
        "bb_period": 20,
        "bb_std": 2.0,
        "swing_window": 3,
        "bw_shrink_pct": 0.60,
        "lookback_bw_window": 60,
        "rsi_period": 9,
        "macd_params": {"fast": 8, "slow": 17, "signal": 9},
        "atr_period": 14,
        "adx_period": 7,
        "adx_threshold": 18.0,          # 背离偏好震荡，降低 ADX 要求
        "stop_atr_mult": 1.25,
        "max_time_bars": 8,
        "min_atr_price_ratio": 0.001,
        "vol_zscore_window": 10,
        "vol_zscore_threshold": 0.8,
        "score_threshold": 0.7
    }

    intermediate = {
        "bb_period": 20,
        "bb_std": 2.0,
        "swing_window": 4,
        "bw_shrink_pct": 0.75,
        "lookback_bw_window": 100,
        "rsi_period": 14,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "atr_period": 14,
        "adx_period": 14,
        "adx_threshold": 25.0,
        "stop_atr_mult": 1.5,
        "max_time_bars": 12,
        "min_atr_price_ratio": 0.0015,
        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.0,
        "score_threshold": 0.75
    }

    position = {
        "bb_period": 20,
        "bb_std": 2.0,
        "swing_window": 6,
        "bw_shrink_pct": 0.85,
        "lookback_bw_window": 200,
        "rsi_period": 21,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "atr_period": 21,
        "adx_period": 20,
        "adx_threshold": 30.0,          # 更严格的趋势强度过滤（减少趋势主导下的反转）
        "stop_atr_mult": 2.0,
        "max_time_bars": 30,
        "min_atr_price_ratio": 0.002,
        "vol_zscore_window": 40,
        "vol_zscore_threshold": 1.2,
        "score_threshold": 0.8
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}