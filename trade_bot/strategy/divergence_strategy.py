from typing import List, Optional, Dict, Any, Tuple
import statistics
from datetime import datetime

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

class DivergenceStrategy(TradingStrategy):
    """
    Divergence 策略（Regular + Hidden）
    - 目标：在日线识别常规背离（regular divergence）与隐藏背离（hidden divergence），
      用于捕捉反转（regular）与趋势延续（hidden）。
    - 指标：默认 RSI（可选 MACD histogram）为主；可选 ADX/ATR 过滤。
    - 逻辑要点：
        * Regular Bearish: 价格做 HH，而指标未创新高（或下降） -> 顶背离 -> 做空/平多
        * Regular Bullish: 价格做 LL，而指标未创新低 -> 底背离 -> 做多/平空
        * Hidden Bullish: 价格做 higher-low，但指标做 lower-low -> 趋势延续多头
        * Hidden Bearish: 价格做 lower-high，但指标做 higher-high -> 趋势延续空头
    - 输出 SignalModel 包含 reason、confidence、建议止损/目标（基于最近 swing + ATR）
    - 以日线为主；通过 presets 可切换短/中/长周期敏感度
    """

    def __init__(
        self,
        swing_window: int = 5,             # N-bar fractal window
        lookback_swings: int = 60,
        rsi_period: int = 14,
        use_macd: bool = True,
        macd_params: Optional[Dict[str,int]] = None,
        atr_period: int = 14,
        stop_atr_mult: float = 1.5,
        require_momentum_confirm: bool = True,
        min_atr_price_ratio: float = 0.001,
        adx_period: Optional[int] = None,
        adx_threshold: float = 20.0,
        time_stop_bars: int = 12,
        score_threshold: float = 0.55,
        data_provider: Any = None
    ):
        self.swing_window = int(swing_window)
        self.lookback_swings = int(lookback_swings)
        self.rsi_period = int(rsi_period)
        self.use_macd = bool(use_macd)
        self.macd_params = macd_params or {"fast":12,"slow":26,"signal":9}
        self.atr_period = int(atr_period)
        self.stop_atr_mult = float(stop_atr_mult)
        self.require_momentum_confirm = bool(require_momentum_confirm)
        self.min_atr_price_ratio = float(min_atr_price_ratio)
        self.adx_period = int(adx_period) if adx_period else None
        self.adx_threshold = float(adx_threshold)
        self.time_stop_bars = int(time_stop_bars)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

    def get_name(self) -> str:
        return "DivergenceStrategy"

    def get_lookback_window(self) -> int:
        return max(self.lookback_swings, self.swing_window*2+5, self.rsi_period, self.atr_period, (self.adx_period or 0)) + 5

    # ---------- 工具 ----------
    def _sma(self, vals: List[float]) -> float:
        return sum(vals)/len(vals) if vals else 0.0

    def _std(self, vals: List[float]) -> float:
        return statistics.pstdev(vals) if vals else 0.0

    def _find_fractals(self, highs: List[float], lows: List[float], window:int) -> Tuple[List[Tuple[int,float]], List[Tuple[int,float]]]:
        """
        N-bar fractal 高/低点 (index, value)，index 相对整个序列起点
        window: 左右各比较 window 根 bar
        """
        H, L = len(highs), len(lows)
        high_pts, low_pts = [], []
        for i in range(window, H - window):
            left_h = highs[i-window:i]
            right_h = highs[i+1:i+window+1]
            if highs[i] > max(left_h + right_h):
                high_pts.append((i, highs[i]))
            left_l = lows[i-window:i]
            right_l = lows[i+1:i+window+1]
            if lows[i] < min(left_l + right_l):
                low_pts.append((i, lows[i]))
        return high_pts, low_pts

    def _extract_indicator_value(self, series: List[Any], attr_names: List[str]) -> Optional[float]:
        if not series:
            return None
        last = series[-1]
        if last is None:
            return None
        if isinstance(last, (int,float)):
            return float(last)
        for a in attr_names:
            v = getattr(last, a, None) if hasattr(last, a) else (last.get(a) if isinstance(last, dict) else None)
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    continue
        return None

    def _get_indicator_history(self, series: List[Any], key_names: List[str], length:int) -> List[Optional[float]]:
        """从 provider 指标序列中提取过去 length 条数值（兼容不同字段名）"""
        out = []
        for i in range(max(0, len(series)-length), len(series)):
            v = None
            item = series[i]
            if isinstance(item, (int,float)):
                v = float(item)
            else:
                for k in key_names:
                    v = getattr(item, k, None) if hasattr(item, k) else (item.get(k) if isinstance(item, dict) else None)
                    if v is not None:
                        try:
                            v = float(v)
                            break
                        except Exception:
                            v = None
            out.append(v)
        return out

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        输入:
          candles: 日线序列（old..new），每条需含 high/low/open/close/volume/date
        输出:
          SignalModel(signal ∈ {'buy','sell','hold'}, confidence, reason, details)
        """
        if not candles or not self.provider or len(candles) < self.get_lookback_window():
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=candles[-1].date if candles else None, confidence=0.0, reason="数据不足")

        highs = [float(getattr(c,"high", getattr(c,"High",0))) for c in candles]
        lows = [float(getattr(c,"low", getattr(c,"Low",0))) for c in candles]
        closes = [float(getattr(c,"close", getattr(c,"Close",0))) for c in candles]
        dates = [getattr(c,"date", None) for c in candles]
        idx_end = len(candles) - 1
        close = closes[-1]

        # indicators via provider
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params) if self.use_macd else None
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period}) if self.adx_period else None

        # extract latest numeric histories
        rsi_hist = self._get_indicator_history(rsi_series, [f"RSI_{self.rsi_period}", "rsi", "RSI"], self.lookback_swings + 10)
        macd_hist = None
        macd_hist_vals = None
        if macd_series:
            # we mainly use macd histogram
            macd_hist_vals = []
            for item in macd_series[-(self.lookback_swings+10):]:
                m = getattr(item, "macd", None) or getattr(item,"MACD",None) or (item.get("macd") if isinstance(item, dict) else None)
                s = getattr(item, "signal", None) or getattr(item,"SIGNAL",None) or (item.get("signal") if isinstance(item, dict) else None)
                if m is not None and s is not None:
                    try:
                        macd_hist_vals.append(float(m)-float(s))
                    except Exception:
                        macd_hist_vals.append(None)
                else:
                    macd_hist_vals.append(None)
            macd_hist = macd_hist_vals

        atr_hist = self._get_indicator_history(atr_series, [f"ATR_{self.atr_period}","atr","ATR"], self.lookback_swings+10)
        atr_val = atr_hist[-1] if atr_hist else None
        adx_val = None
        if adx_series:
            adx_val = self._extract_indicator_value(adx_series, [f"ADX_{self.adx_period}","ADX","adx"])

        # volatility guard
        vol_guard = (atr_val is not None) and (atr_val / max(abs(close), EPS) >= self.min_atr_price_ratio)

        # find fractals (use lookback window slice to reduce noise)
        use_highs = highs[-(self.lookback_swings+ self.swing_window*2 + 5):]
        use_lows = lows[-(self.lookback_swings+ self.swing_window*2 + 5):]
        high_pts, low_pts = self._find_fractals(use_highs, use_lows, self.swing_window)
        # rebase indices to full candles
        base = len(highs) - len(use_highs)
        high_pts = [(i+base, v) for (i,v) in high_pts]
        low_pts = [(i+base, v) for (i,v) in low_pts]

        # helper to get last two relevant swings (most recent two)
        def last_two(points: List[Tuple[int,float]]):
            if len(points) < 2:
                return None
            return points[-2], points[-1]

        sig = "hold"
        confidence = 0.0
        reasons = []
        details: Dict[str, Any] = {"close": close, "atr": atr_val, "vol_guard": vol_guard, "adx": adx_val}

        # ---- check bearish / bullish on regular & hidden using highs and lows ----
        found = False

        # Regular bearish / hidden bearish (use last two highs)
        h2 = last_two(high_pts)
        if h2:
            (i1,p1),(i2,p2) = h2
            if i2 > i1 and p2 > p1 + EPS:
                # price made higher high -> possible regular bearish if indicator did not make HH
                # locate indicator values at approx indices (map into rsi_hist slice)
                def pick(ind_series, idx):
                    # map idx relative to end
                    rel = idx - (len(candles) - len(ind_series))
                    try:
                        if rel >= 0:
                            return ind_series[rel]
                    except Exception:
                        return None
                    return None
                r1 = None; r2 = None
                # try fetch RSI values at the swing indices from provider histories
                if rsi_hist:
                    rel_base = len(candles) - len(rsi_hist)
                    try:
                        r1 = rsi_hist[i1 - rel_base] if 0 <= i1 - rel_base < len(rsi_hist) else None
                        r2 = rsi_hist[i2 - rel_base] if 0 <= i2 - rel_base < len(rsi_hist) else None
                    except Exception:
                        r1 = r2 = None
                macd1 = macd2 = None
                if macd_hist:
                    rel_base = len(candles) - len(macd_hist)
                    try:
                        macd1 = macd_hist[i1 - rel_base] if 0 <= i1 - rel_base < len(macd_hist) else None
                        macd2 = macd_hist[i2 - rel_base] if 0 <= i2 - rel_base < len(macd_hist) else None
                    except Exception:
                        macd1 = macd2 = None

                indicator_failed_to_confirm = False
                if r1 is not None and r2 is not None:
                    indicator_failed_to_confirm = r2 <= r1 + EPS
                elif macd1 is not None and macd2 is not None:
                    indicator_failed_to_confirm = macd2 <= macd1 + EPS
                else:
                    # if no historic indicator points, skip this check
                    indicator_failed_to_confirm = False

                if indicator_failed_to_confirm:
                    # regular bearish detected
                    reasons.append("regular bearish divergence (price HH but indicator failed)")
                    found = True
                    # momentum confirm: prefer RSI falling or macd hist negative
                    mom_ok = True
                    if self.require_momentum_confirm:
                        r_latest = self._extract_indicator_value(rsi_series, [f"RSI_{self.rsi_period}","rsi","RSI"])
                        macd_hist_latest = None
                        if macd_series:
                            macd_hist_latest = None
                            try:
                                m = getattr(macd_series[-1],"macd",None) or getattr(macd_series[-1],"MACD",None)
                                s = getattr(macd_series[-1],"signal",None) or getattr(macd_series[-1],"SIGNAL",None)
                                if m is not None and s is not None:
                                    macd_hist_latest = float(m)-float(s)
                            except Exception:
                                macd_hist_latest = None
                        mom_ok = ((r_latest is not None and r_latest < 70) or (macd_hist_latest is not None and macd_hist_latest < 0))
                    # ADX
                    adx_ok = True if (adx_val is None or adx_val >= self.adx_threshold) else False
                    # score
                    score = 0.5 + (0.2 if mom_ok else 0.0) + (0.15 if vol_guard else 0.0) + (0.15 if adx_ok else 0.0)
                    confidence = min(1.0, score)
                    # plan: short candidate
                    entry = close
                    stop = max(p2, p1) + (self.stop_atr_mult * (atr_val or 0.0))
                    target = min(closes[i1:i2+1]) if i2>i1 else closes[i1]
                    details.update({"type":"regular_bear","swing1":(i1,p1),"swing2":(i2,p2),"indicator_r1":r1,"indicator_r2":r2})
                    if confidence >= self.score_threshold and vol_guard:
                        sig = "sell"
                    else:
                        sig = "hold"

                    details.update({"entry": entry, "stop": round(stop,6), "target": target, "confidence_score": round(confidence,3)})
        # Regular bullish / hidden bullish (use last two lows)
        l2 = last_two(low_pts)
        if not found and l2:
            (j1,q1),(j2,q2) = l2
            if j2 > j1 and q2 < q1 - EPS:
                # price made lower low -> possible regular bullish if indicator did not make LL
                r1 = r2 = None
                if rsi_hist:
                    rel_base = len(candles) - len(rsi_hist)
                    try:
                        r1 = rsi_hist[j1 - rel_base] if 0 <= j1 - rel_base < len(rsi_hist) else None
                        r2 = rsi_hist[j2 - rel_base] if 0 <= j2 - rel_base < len(rsi_hist) else None
                    except Exception:
                        r1 = r2 = None
                macd1 = macd2 = None
                if macd_hist:
                    rel_base = len(candles) - len(macd_hist)
                    try:
                        macd1 = macd_hist[j1 - rel_base] if 0 <= j1 - rel_base < len(macd_hist) else None
                        macd2 = macd_hist[j2 - rel_base] if 0 <= j2 - rel_base < len(macd_hist) else None
                    except Exception:
                        macd1 = macd2 = None

                indicator_failed = False
                if r1 is not None and r2 is not None:
                    indicator_failed = r2 >= r1 - EPS
                elif macd1 is not None and macd2 is not None:
                    indicator_failed = macd2 >= macd1 - EPS
                else:
                    indicator_failed = False

                if indicator_failed:
                    reasons.append("regular bullish divergence (price LL but indicator failed)")
                    found = True
                    mom_ok = True
                    if self.require_momentum_confirm:
                        r_latest = self._extract_indicator_value(rsi_series, [f"RSI_{self.rsi_period}","rsi","RSI"])
                        macd_hist_latest = None
                        if macd_series:
                            try:
                                m = getattr(macd_series[-1],"macd",None) or getattr(macd_series[-1],"MACD",None)
                                s = getattr(macd_series[-1],"signal",None) or getattr(macd_series[-1],"SIGNAL",None)
                                if m is not None and s is not None:
                                    macd_hist_latest = float(m)-float(s)
                            except Exception:
                                macd_hist_latest = None
                        mom_ok = ((r_latest is not None and r_latest > 30) or (macd_hist_latest is not None and macd_hist_latest > 0))

                    adx_ok = True if (adx_val is None or adx_val >= self.adx_threshold) else False
                    score = 0.5 + (0.2 if mom_ok else 0.0) + (0.15 if vol_guard else 0.0) + (0.15 if adx_ok else 0.0)
                    confidence = min(1.0, score)
                    entry = close
                    stop = min(q1, q2) - (self.stop_atr_mult * (atr_val or 0.0))
                    target = max(closes[j1:j2+1]) if j2>j1 else closes[j1]
                    details.update({"type":"regular_bull","swing1":(j1,q1),"swing2":(j2,q2),"indicator_r1":r1,"indicator_r2":r2})
                    if confidence >= self.score_threshold and vol_guard:
                        sig = "buy"
                    else:
                        sig = "hold"
                    details.update({"entry": entry, "stop": round(stop,6), "target": target, "confidence_score": round(confidence,3)})

        # Hidden divergences: detect trend continuation signals
        if not found:
            # Hidden bullish: price makes higher-low (HL) while indicator makes lower-low
            if len(low_pts) >= 2:
                (a_idx,a_val),(b_idx,b_val) = low_pts[-2], low_pts[-1]
                if b_idx > a_idx and b_val > a_val + EPS:
                    # price HL -> check indicator made lower-low
                    r1 = r2 = None
                    if rsi_hist:
                        rel_base = len(candles) - len(rsi_hist)
                        try:
                            r1 = rsi_hist[a_idx - rel_base] if 0 <= a_idx - rel_base < len(rsi_hist) else None
                            r2 = rsi_hist[b_idx - rel_base] if 0 <= b_idx - rel_base < len(rsi_hist) else None
                        except Exception:
                            r1 = r2 = None
                    macd1 = macd2 = None
                    if macd_hist:
                        rel_base = len(candles) - len(macd_hist)
                        try:
                            macd1 = macd_hist[a_idx - rel_base] if 0 <= a_idx - rel_base < len(macd_hist) else None
                            macd2 = macd_hist[b_idx - rel_base] if 0 <= b_idx - rel_base < len(macd_hist) else None
                        except Exception:
                            macd1 = macd2 = None
                    indicator_lower = False
                    if r1 is not None and r2 is not None:
                        indicator_lower = r2 < r1 - EPS
                    elif macd1 is not None and macd2 is not None:
                        indicator_lower = macd2 < macd1 - EPS
                    if indicator_lower:
                        reasons.append("hidden bullish divergence (price HL but indicator lower-low) -> trend continuation")
                        found = True
                        mom_ok = True
                        if self.require_momentum_confirm:
                            r_latest = self._extract_indicator_value(rsi_series, [f"RSI_{self.rsi_period}","rsi","RSI"])
                            mom_ok = (r_latest is not None and r_latest > 40) or True
                        adx_ok = True if (adx_val is None or adx_val >= self.adx_threshold) else False
                        score = 0.4 + (0.2 if mom_ok else 0.0) + (0.15 if vol_guard else 0.0) + (0.15 if adx_ok else 0.0)
                        confidence = min(1.0, score)
                        entry = close
                        stop = min(a_val, b_val) - (self.stop_atr_mult * (atr_val or 0.0))
                        details.update({"type":"hidden_bull","swing_prev":(a_idx,a_val),"swing_latest":(b_idx,b_val)})
                        details.update({"entry": entry, "stop": round(stop,6), "confidence_score": round(confidence,3)})
                        if confidence >= self.score_threshold and vol_guard:
                            sig = "buy"
            # Hidden bearish
            if not found and len(high_pts) >= 2:
                (a_idx,a_val),(b_idx,b_val) = high_pts[-2], high_pts[-1]
                if b_idx > a_idx and b_val < a_val - EPS:
                    r1 = r2 = None
                    if rsi_hist:
                        rel_base = len(candles) - len(rsi_hist)
                        try:
                            r1 = rsi_hist[a_idx - rel_base] if 0 <= a_idx - rel_base < len(rsi_hist) else None
                            r2 = rsi_hist[b_idx - rel_base] if 0 <= b_idx - rel_base < len(rsi_hist) else None
                        except Exception:
                            r1 = r2 = None
                    macd1 = macd2 = None
                    if macd_hist:
                        rel_base = len(candles) - len(macd_hist)
                        try:
                            macd1 = macd_hist[a_idx - rel_base] if 0 <= a_idx - rel_base < len(macd_hist) else None
                            macd2 = macd_hist[b_idx - rel_base] if 0 <= b_idx - rel_base < len(macd_hist) else None
                        except Exception:
                            macd1 = macd2 = None
                    indicator_higher = False
                    if r1 is not None and r2 is not None:
                        indicator_higher = r2 > r1 + EPS
                    elif macd1 is not None and macd2 is not None:
                        indicator_higher = macd2 > macd1 + EPS
                    if indicator_higher:
                        reasons.append("hidden bearish divergence (price LH but indicator higher-high) -> trend continuation down")
                        found = True
                        mom_ok = True
                        if self.require_momentum_confirm:
                            r_latest = self._extract_indicator_value(rsi_series, [f"RSI_{self.rsi_period}","rsi","RSI"])
                            mom_ok = (r_latest is not None and r_latest < 60) or True
                        adx_ok = True if (adx_val is None or adx_val >= self.adx_threshold) else False
                        score = 0.4 + (0.2 if mom_ok else 0.0) + (0.15 if vol_guard else 0.0) + (0.15 if adx_ok else 0.0)
                        confidence = min(1.0, score)
                        entry = close
                        stop = max(a_val, b_val) + (self.stop_atr_mult * (atr_val or 0.0))
                        details.update({"type":"hidden_bear","swing_prev":(a_idx,a_val),"swing_latest":(b_idx,b_val)})
                        details.update({"entry": entry, "stop": round(stop,6), "confidence_score": round(confidence,3)})
                        if confidence >= self.score_threshold and vol_guard:
                            sig = "sell"

        # usage notes & failsafe
        details.setdefault("notes", "常规背离用于反转；隐藏背离用于趋势延续。建议结合多周期确认与新闻/流动性过滤；入场后使用 ATR 止损与 time-stop。")
        reason = " | ".join(reasons) if reasons else "no divergence found"

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=sig,
            date=dates[-1],
            confidence=round(confidence if isinstance(confidence, float) else 0.0, 3),
            reason=reason,
            details=details
        )

def make_divergence_presets() -> Dict[str, Dict[str, Any]]:
    """
    Presets: swing / intermediate / position
    - swing: 更灵敏、短期（1-2周）
    - intermediate: 中期（2-6周）
    - position: 更保守（多周到数月）
    """
    swing = {
        "swing_window": 4,
        "lookback_swings": 50,
        "rsi_period": 9,
        "use_macd": True,
        "atr_period": 10,
        "stop_atr_mult": 1.2,
        "require_momentum_confirm": True,
        "min_atr_price_ratio": 0.0008,
        "adx_period": 14,
        "adx_threshold": 16,
        "time_stop_bars": 10,
        "score_threshold": 0.5
    }
    intermediate = {
        "swing_window": 5,
        "lookback_swings": 80,
        "rsi_period": 14,
        "use_macd": True,
        "atr_period": 14,
        "stop_atr_mult": 1.5,
        "require_momentum_confirm": True,
        "min_atr_price_ratio": 0.0012,
        "adx_period": 14,
        "adx_threshold": 18,
        "time_stop_bars": 20,
        "score_threshold": 0.6
    }
    position = {
        "swing_window": 6,
        "lookback_swings": 150,
        "rsi_period": 21,
        "use_macd": False,
        "atr_period": 21,
        "stop_atr_mult": 2.0,
        "require_momentum_confirm": False,
        "min_atr_price_ratio": 0.0015,
        "adx_period": 21,
        "adx_threshold": 20,
        "time_stop_bars": 40,
        "score_threshold": 0.65
    }
    return {"swing": swing, "intermediate": intermediate, "position": position}