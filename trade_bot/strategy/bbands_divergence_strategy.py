from typing import List, Optional, Dict, Any, Tuple
import statistics
from datetime import datetime

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
        macd_params: Optional[Dict[str,int]] = None,
        atr_period: int = 14,
        stop_atr_mult: float = 1.5,
        max_time_bars: int = 12,
        min_atr_price_ratio: float = 0.001,   # 波动性门槛，避免超低波动环境
        require_momentum_confirm: bool = True,
        score_threshold: float = 0.6,
        data_provider = None
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.swing_window = swing_window
        self.bw_shrink_pct = bw_shrink_pct
        self.lookback_bw_window = lookback_bw_window
        self.rsi_period = rsi_period
        self.macd_params = macd_params or {"fast":12,"slow":26,"signal":9}
        self.atr_period = atr_period
        self.stop_atr_mult = stop_atr_mult
        self.max_time_bars = max_time_bars
        self.min_atr_price_ratio = min_atr_price_ratio
        self.require_momentum_confirm = require_momentum_confirm
        self.score_threshold = score_threshold
        self.provider = data_provider

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
        rsi = None
        macd = None
        if self.rsi_period:
            rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        if self.macd_params:
            macd = self.provider.get_indicator("macd", candles, self.macd_params)

        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        dates = [getattr(c,"date",None) for c in candles]
        idx = len(candles)-1
        close = closes[-1]

        # 提取 BB 历史 bandwidth（兼容 provider 字段名）
        def _extract_bb_fields(bbi):
            u = getattr(bbi, f"close_BBU_{self.bb_period}_{self.bb_std}", None) or getattr(bbi,"upper",None) or getattr(bbi,"BBU",None)
            l = getattr(bbi, f"close_BBL_{self.bb_period}_{self.bb_std}", None) or getattr(bbi,"lower",None) or getattr(bbi,"BBL",None)
            m = getattr(bbi, f"close_BBM_{self.bb_period}_{self.bb_std}", None) or getattr(bbi,"middle",None) or getattr(bbi,"BBM",None)
            return u,l,m

        bb_hist_bw = []
        bb_upper_hist = []
        bb_lower_hist = []
        bb_mid_hist = []
        for i in range(max(0, idx-self.lookback_bw_window+1), idx+1):
            try:
                u,l,m = _extract_bb_fields(bb[i])
                if None not in (u,l,m) and abs(m)>EPS:
                    bw = (u-l)/m
                    bb_hist_bw.append(bw)
                    bb_upper_hist.append(u)
                    bb_lower_hist.append(l)
                    bb_mid_hist.append(m)
                else:
                    # fallback：用 close slice 自行计算
                    window = closes[max(0,i-self.bb_period+1):i+1]
                    if len(window)>=self.bb_period:
                        sma = self._sma(window)
                        std = self._std(window)
                        u_ = sma + self.bb_std*std
                        l_ = sma - self.bb_std*std
                        bb_hist_bw.append((u_-l_)/(sma if abs(sma)>EPS else 1.0))
                        bb_upper_hist.append(u_)
                        bb_lower_hist.append(l_)
                        bb_mid_hist.append(sma)
            except Exception:
                continue

        if not bb_hist_bw:
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=dates[-1], reason="BB 数据不足", confidence=0.0)

        # 当前 band 值
        try:
            u_curr,l_curr,m_curr = _extract_bb_fields(bb[-1])
            if None in (u_curr,l_curr,m_curr):
                raise Exception("缺少当前BB字段")
        except Exception:
            # fallback 计算
            window = closes[-self.bb_period:]
            sma = self._sma(window)
            std = self._std(window)
            m_curr = sma
            u_curr = sma + self.bb_std*std
            l_curr = sma - self.bb_std*std

        curr_bw = (u_curr - l_curr) / (m_curr if abs(m_curr)>EPS else 1.0)
        recent_max_bw = max(bb_hist_bw) if bb_hist_bw else curr_bw
        bw_shrunk = curr_bw < recent_max_bw * self.bw_shrink_pct

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
            atr_val = float(getattr(atr[-1], f"ATR_{self.atr_period}") or getattr(atr[-1],"atr",None) or atr[-1])
        except Exception:
            trs = [abs(highs[i]-lows[i]) for i in range(max(0, idx-self.atr_period+1), idx+1)]
            atr_val = self._sma(trs) if trs else 0.0
        vol_guard_ok = (atr_val / (close if abs(close)>EPS else 1.0)) >= self.min_atr_price_ratio
        details["atr"] = round(atr_val,6)
        details["vol_guard_ok"] = vol_guard_ok

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

        # 动量确认（可选）
        momentum_ok = False
        momentum_detail = ""
        if (bear_divergence or bull_divergence) and self.require_momentum_confirm:
            # 使用 RSI 或 MACD 判断动量背离/反转倾向
            rsi_val = None
            macd_hist = None
            try:
                if rsi:
                    rsi_val = float(getattr(rsi[-1], f"RSI_{self.rsi_period}") or getattr(rsi[-1],"rsi",None) or rsi[-1])
                if macd:
                    m = getattr(macd[-1],"macd", None) or getattr(macd[-1],"MACD",None) or None
                    s = getattr(macd[-1],"signal", None) or getattr(macd[-1],"SIGNAL",None) or None
                    if m is not None and s is not None:
                        macd_hist = m - s
            except Exception:
                rsi_val = None; macd_hist = None

            # 简单规则：bear_divergence 需 RSI < 70 或 MACD histogram 转负；bull_divergence 需 RSI > 30 或 MACD hist 转正
            if bear_divergence:
                if (rsi_val is not None and rsi_val < 70) or (macd_hist is not None and macd_hist < 0):
                    momentum_ok = True
                    momentum_detail = f"momentum confirm rsi={rsi_val} macd_hist={macd_hist}"
            if bull_divergence:
                if (rsi_val is not None and rsi_val > 30) or (macd_hist is not None and macd_hist > 0):
                    momentum_ok = True
                    momentum_detail = f"momentum confirm rsi={rsi_val} macd_hist={macd_hist}"
        else:
            # 不强制动量确认则默认为通过
            momentum_ok = True

        details["momentum_ok"] = momentum_ok
        if momentum_detail:
            details["momentum_detail"] = momentum_detail

        # 生成交易信号：要求背离发现、动量确认（如配置）、波动性 guard
        if vol_guard_ok and (bear_divergence or bull_divergence) and momentum_ok:
            score = 0.0
            score += 0.5  # 背离基础权重
            score += 0.2 if bw_shrunk else 0.0
            score += 0.15 if not self.require_momentum_confirm else 0.0
            score += 0.15 if (self.require_momentum_confirm and momentum_ok) else 0.0
            confidence = min(1.0, score)
            details["score"] = round(score,3)

            # stop / targets
            entry_price = close
            if bear_divergence:
                # 做空信号：在上带附近寻找反转蜡烛或可在回落到 mid 线处开仓（根据偏好）
                stop = max(self._highest(highs, self.swing_window+1), entry_price) + self.stop_atr_mult * atr_val
                target1 = m_curr  # midline
                target2 = l_curr  # lower band
                signal_candidate = "sell"
                reason_parts.append("顶部背离（价格新高但上轨未确认）")
            else:
                stop = min(self._lowest(lows, self.swing_window+1), entry_price) - self.stop_atr_mult * atr_val
                target1 = m_curr
                target2 = u_curr
                signal_candidate = "buy"
                reason_parts.append("底部背离（价格新低但下轨未确认）")

            details.update({
                "entry_price": entry_price,
                "stop_loss": round(stop,6),
                "target_mid": round(target1,6),
                "target_band": round(target2,6),
                "stop_atr_mult": self.stop_atr_mult,
                "max_time_bars": self.max_time_bars
            })

            # 进一步要求价格接近对应带位或出现反转蜡烛：近似规则（可由执行层调整为更严格的 candle pattern）
            near_upper = abs(close - u_curr) / (u_curr if abs(u_curr)>EPS else 1.0) <= 0.02
            near_lower = abs(close - l_curr) / (l_curr if abs(l_curr)>EPS else 1.0) <= 0.02
            if (bear_divergence and near_upper) or (bull_divergence and near_lower):
                if confidence >= self.score_threshold:
                    signal = signal_candidate
                    reason_parts.append("价格位于对应带附近 -> 触发入场")
                else:
                    signal = "hold"
                    reason_parts.append("背离成立但置信度不足")
            else:
                # 允许在带附近或在穿越 midline 的反转点入场；若当前不在带附近则建议等待回调 / 反转确认
                signal = "hold"
                reason_parts.append("背离成立，但价格未靠近带位或未出现明显反转，等待更好入场点")

        else:
            # 否则保持观望
            reason_parts.append("未符合背离/动量/波动性条件或数据不足")

        # 使用建议与场景（附加到 details 以便上层 UI/日志使用）
        details["usage_notes"] = (
            "策略目标：在波段顶部/底部背离时做均值回归。\n"
            "- 适用：趋势后出现延续乏力且带宽没有确认新极值的反转机会；日线为主，持仓以周为单位。\n"
            "- 不适用：重大新闻驱动、极低流动性或极端波动市况。\n"
            "- 止损按 recent swing 或 ATR 计算；目标先中轨再对侧带；建议配置仓位控制（每笔风险 0.25-0.5% 账户）。"
        )

        reason = " | ".join(reason_parts)

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=dates[-1],
            confidence=round(confidence if 'confidence' in locals() else 0.0,3),
            reason=reason,
            details=details
        )

def make_bbands_divergence_presets() -> Dict[str, Dict[str, Any]]:
    """
    预设：支持快速切换模式
    - swing: 短波段（1-2周），更灵敏的 swing_window、较低的 bw_shrink_pct
    - intermediate: 中波段（2-6周）
    - position: 中长线（1-3月），更保守
    """
    swing = {
        "bb_period": 20,
        "bb_std": 2.0,
        "swing_window": 4,
        "bw_shrink_pct": 0.9,
        "lookback_bw_window": 80,
        "rsi_period": 10,
        "macd_params": {"fast":8,"slow":17,"signal":9},
        "atr_period": 14,
        "stop_atr_mult": 1.5,
        "max_time_bars": 10,
        "min_atr_price_ratio": 0.001,
        "require_momentum_confirm": True,
        "score_threshold": 0.55
    }
    intermediate = {
        "bb_period": 20,
        "bb_std": 2.0,
        "swing_window": 5,
        "bw_shrink_pct": 0.85,
        "lookback_bw_window": 100,
        "rsi_period": 14,
        "macd_params": {"fast":12,"slow":26,"signal":9},
        "atr_period": 14,
        "stop_atr_mult": 1.75,
        "max_time_bars": 15,
        "min_atr_price_ratio": 0.0015,
        "require_momentum_confirm": True,
        "score_threshold": 0.6
    }
    position = {
        "bb_period": 20,
        "bb_std": 2.0,
        "swing_window": 6,
        "bw_shrink_pct": 0.8,
        "lookback_bw_window": 150,
        "rsi_period": 21,
        "macd_params": {"fast":12,"slow":26,"signal":9},
        "atr_period": 21,
        "stop_atr_mult": 2.0,
        "max_time_bars": 30,
        "min_atr_price_ratio": 0.002,
        "require_momentum_confirm": False,
        "score_threshold": 0.65
    }
    return {"swing": swing, "intermediate": intermediate, "position": position}