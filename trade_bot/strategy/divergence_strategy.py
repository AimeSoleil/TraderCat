from typing import List, Optional, Dict, Any, Tuple
import statistics

from trade_bot.strategy.trading_strategy import TradingStrategy, EPS
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

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
        swing_window: int = 5,  # N-bar fractal window
        lookback_swings: int = 60,
        rsi_period: int = 14,
        macd_params: Optional[Dict[str, int]] = None,
        atr_period: int = 14,
        stop_atr_mult: float = 1.5,
        min_atr_price_ratio: float = 0.001,
        adx_period: int = None,
        adx_threshold: float = 25.0,
        time_stop_bars: int = 12,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.55,
        data_provider: Any = None,
    ):
        self.swing_window = int(swing_window)
        self.lookback_swings = int(lookback_swings)
        self.rsi_period = int(rsi_period)
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.atr_period = int(atr_period)
        self.stop_atr_mult = float(stop_atr_mult)
        self.min_atr_price_ratio = float(min_atr_price_ratio)
        self.adx_period = int(adx_period) if adx_period else None
        self.adx_threshold = float(adx_threshold)
        self.time_stop_bars = int(time_stop_bars)
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # 指标字段命名（对应 provider 返回的属性）
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.adx_field = f"ADX_{self.adx_period}"

    def get_name(self) -> str:
        return "DivergenceStrategy"

    def get_lookback_window(self) -> int:
        return (
            max(
                self.lookback_swings,
                self.swing_window * 2 + 5,
                self.rsi_period,
                self.atr_period,
                (self.adx_period or 0),
                (self.macd_params["slow"] or 0),
            )
            + 5
        )

    # ---------- 工具 ----------
    def _sma(self, vals: List[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    def _std(self, vals: List[float]) -> float:
        return statistics.pstdev(vals) if vals else 0.0

    def _find_fractals(
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

    def _extract_indicator_value(
        self, series: List[Any], attr_names: List[str]
    ) -> Optional[float]:
        if not series:
            return None
        last = series[-1]
        if last is None:
            return None
        if isinstance(last, (int, float)):
            return float(last)
        for a in attr_names:
            v = (
                getattr(last, a, None)
                if hasattr(last, a)
                else (last.get(a) if isinstance(last, dict) else None)
            )
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    continue
        return None

    def _get_indicator_history(
        self, series: List[Any], key_names: List[str], length: int
    ) -> List[Optional[float]]:
        """从 provider 指标序列中提取过去 length 条数值（兼容不同字段名）"""
        out = []
        if series:
            for i in range(max(0, len(series) - length), len(series)):
                v = None
                item = series[i]
                if isinstance(item, (int, float)):
                    v = float(item)
                else:
                    for k in key_names:
                        v = (
                            getattr(item, k, None)
                            if hasattr(item, k)
                            else (item.get(k) if isinstance(item, dict) else None)
                        )
                        if v is not None:
                            try:
                                v = float(v)
                                break
                            except Exception:
                                v = None
                out.append(v)
        return out

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

    def _momentum_confirmation(
        self,
        rsi_series: List[Any],
        macd_series: Optional[List[Any]],
        prefer: str = "bear",
    ) -> bool:
        """
        简单的动量确认：检查最新 RSI / MACD hist 是否支持方向
        prefer: "bear" or "bull"
        返回 True 表示通过（支持当前方向）
        """
        try:
            r_latest = (
                self._extract_indicator_value(rsi_series, [self.rsi_field])
                if rsi_series
                else None
            )
        except Exception:
            r_latest = None
        macd_hist_latest = None
        if macd_series:
            try:
                macd_item = macd_series[-1]
                macd_hist_latest = getattr(macd_item, self.macd_hist_field, None)
            except Exception:
                macd_hist_latest = None

        if prefer == "bear":
            # 支持空头的动量：RSI 不处于极端超买 或 MACD hist 负
            if r_latest is not None and r_latest < 70:
                return True
            if macd_hist_latest is not None and macd_hist_latest < 0:
                return True
            return False
        else:
            # 支持多头的动量：RSI 不处于极端超卖 或 MACD hist 正
            if r_latest is not None and r_latest > 30:
                return True
            if macd_hist_latest is not None and macd_hist_latest > 0:
                return True
            return False

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        输入:
            candles: 日线序列（old..new），每条需含 high/low/open/close/volume/date
        输出:
            SignalModel(signal ∈ {'buy','sell','hold'}, confidence, reason, details)
        """
        if (
            not candles
            or not self.provider
            or len(candles) < self.get_lookback_window()
        ):
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date if candles else None,
                confidence=0.0,
                reason="数据不足",
            )

        highs = [float(getattr(c, "high", 0)) for c in candles]
        lows = [float(getattr(c, "low", 0)) for c in candles]
        closes = [float(getattr(c, "close", 0)) for c in candles]
        vols = [float(getattr(c, "volume", 0)) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]
        close = closes[-1]

        # indicators via provider
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params)
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})
        
        # Get history data
        rsi_hist = self._get_indicator_history(rsi_series, [self.rsi_field], self.lookback_swings + 10)
        macd_hist = self._get_indicator_history(macd_series, [self.macd_hist_field], self.lookback_swings + 10)
        atr_hist = self._get_indicator_history(atr_series, [self.atr_field], self.lookback_swings + 10)
        
        # volatility guard
        atr_val = atr_hist[-1]
        vol_guard = (atr_val is not None) and (
            atr_val / max(abs(close), EPS) >= self.min_atr_price_ratio
        )

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

        # find fractals (use lookback window slice to reduce noise)
        use_highs = highs[-(self.lookback_swings + self.swing_window * 2 + 5) :]
        use_lows = lows[-(self.lookback_swings + self.swing_window * 2 + 5) :]
        high_pts, low_pts = self._find_fractals(use_highs, use_lows, self.swing_window)
        # rebase indices to full candles
        base = len(highs) - len(use_highs)
        high_pts = [(i + base, v) for (i, v) in high_pts]
        low_pts = [(i + base, v) for (i, v) in low_pts]

        # helper to get last two relevant swings (most recent two)
        def last_two(points: List[Tuple[int, float]]):
            if len(points) < 2:
                return None
            return points[-2], points[-1]

        sig = "hold"
        score = 0.0
        confidence = 0.0
        reasons = []
        details: Dict[str, Any] = {
            "close": close,
            "atr": atr_val,
            "vol_guard": vol_guard,
            "vol_z": volume_z
        }

        # ---- check bearish / bullish on regular & hidden using highs and lows ----
        found = False

        # Regular bearish / hidden bearish (use last two highs)
        h2 = last_two(high_pts)
        if h2:
            (i1, p1), (i2, p2) = h2
            if i2 > i1 and p2 > p1 + EPS:
                # price made higher high -> possible regular bearish if indicator did not make HH
                # locate indicator values at approx indices (map into rsi_hist slice)
                r1, r2 = self._get_indicator_values_at_indices(
                    rsi_hist, [i1, i2], len(candles)
                )
                macd1, macd2 = (None, None)
                if macd_hist:
                    macd1, macd2 = self._get_indicator_values_at_indices(
                        macd_hist, [i1, i2], len(candles)
                    )

                indicator_failed_to_confirm = False
                if r1 is not None and r2 is not None:
                    indicator_failed_to_confirm = r2 <= r1 + EPS
                elif macd1 is not None and macd2 is not None:
                    indicator_failed_to_confirm = macd2 <= macd1 + EPS
                else:
                    indicator_failed_to_confirm = False

                if indicator_failed_to_confirm:
                    # regular bearish detected
                    reasons.append(
                        "regular bearish divergence (price HH but indicator failed)"
                    )
                    found = True
                    # momentum confirm: prefer RSI falling or macd hist negative
                    mom_ok = self._momentum_confirmation(rsi_series, macd_series, prefer="bear")
                    # ADX 趋势强度
                    adx_val = self._extract_indicator_value(adx_series, [self.adx_field])
                    adx_ok = True if adx_val <= self.adx_threshold else False

                    # score
                    # 背离触发
                    score += 0.40
                    reasons.append("Bearish背离触发")
                    # 动量确认
                    if mom_ok:
                        score += 0.20
                        reasons.append("动量确认")
                    # 成交量确认
                    if vol_ok:
                        score += 0.15
                        reasons.append("成交量放大")
                    # 波动率过滤
                    if vol_guard:
                        score += 0.15
                        reasons.append("波动率过滤通过")
                    # 趋势强度确认
                    if adx_ok:
                        score += 0.10
                        reasons.append("趋势强度确认")
                    # 共振加分
                    if mom_ok and vol_ok and adx_ok:
                        score += 0.1
                        reasons.append("三重共振加分")

                    confidence = min(1.0, score)
                    # plan: short candidate
                    entry = close
                    stop = max(p2, p1) + (self.stop_atr_mult * (atr_val or 0.0))
                    target = min(closes[i1 : i2 + 1]) if i2 > i1 else closes[i1]
                    details.update(
                        {
                            "type": "regular_bear",
                            "swing1": (dates[i1], p1),
                            "swing2": (dates[i2], p2),
                            "indicator_r1": r1,
                            "indicator_r2": r2,
                        }
                    )
                    if confidence >= self.score_threshold:
                        sig = "sell"
                    else:
                        sig = "hold"

                    details.update(
                        {
                            "entry": entry,
                            "stop": round(stop, 6),
                            "target": target,
                            "confidence_score": round(confidence, 3),
                        }
                    )
        # Regular bullish / hidden bullish (use last two lows)
        l2 = last_two(low_pts)
        if not found and l2:
            (j1, q1), (j2, q2) = l2
            if j2 > j1 and q2 < q1 - EPS:
                # price made lower low -> possible regular bullish if indicator did not make LL
                r1 = r2 = None
                if rsi_hist:
                    rel_base = len(candles) - len(rsi_hist)
                    try:
                        r1 = (
                            rsi_hist[j1 - rel_base]
                            if 0 <= j1 - rel_base < len(rsi_hist)
                            else None
                        )
                        r2 = (
                            rsi_hist[j2 - rel_base]
                            if 0 <= j2 - rel_base < len(rsi_hist)
                            else None
                        )
                    except Exception:
                        r1 = r2 = None
                macd1 = macd2 = None
                if macd_hist:
                    rel_base = len(candles) - len(macd_hist)
                    try:
                        macd1 = (
                            macd_hist[j1 - rel_base]
                            if 0 <= j1 - rel_base < len(macd_hist)
                            else None
                        )
                        macd2 = (
                            macd_hist[j2 - rel_base]
                            if 0 <= j2 - rel_base < len(macd_hist)
                            else None
                        )
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
                    reasons.append(
                        "regular bullish divergence (price LL but indicator failed)"
                    )
                    found = True
                    mom_ok = self._momentum_confirmation(rsi_series, macd_series, prefer="bull")
                    # ADX 趋势强度
                    adx_val = self._extract_indicator_value(adx_series, [self.adx_field])
                    adx_ok = True if adx_val <= self.adx_threshold else False

                    # 背离触发
                    score += 0.40
                    reasons.append("Bullish背离触发")
                    # 动量确认
                    if mom_ok:
                        score += 0.20
                        reasons.append("动量确认")
                    # 成交量确认
                    if vol_ok:
                        score += 0.15
                        reasons.append("成交量放大")
                    # 波动率过滤
                    if vol_guard:
                        score += 0.15
                        reasons.append("波动率过滤通过")
                    # 趋势强度确认
                    if adx_ok:
                        score += 0.10
                        reasons.append("趋势强度确认")
                    # 共振加分
                    if mom_ok and vol_ok and adx_ok:
                        score += 0.1
                        reasons.append("三重共振加分")
                    confidence = min(1.0, score)
                    entry = close
                    stop = min(q1, q2) - (self.stop_atr_mult * (atr_val or 0.0))
                    target = max(closes[j1 : j2 + 1]) if j2 > j1 else closes[j1]
                    details.update(
                        {
                            "type": "regular_bull",
                            "swing1": (dates[j1], q1),
                            "swing2": (dates[j2], q2),
                            "indicator_r1": r1,
                            "indicator_r2": r2,
                        }
                    )
                    if confidence >= self.score_threshold:
                        sig = "buy"
                    else:
                        sig = "hold"
                    details.update(
                        {
                            "entry": entry,
                            "stop": round(stop, 6),
                            "target": target,
                            "confidence_score": round(confidence, 3),
                        }
                    )

        # Hidden divergences: detect trend continuation signals
        if not found:
            # Hidden bullish: price makes higher-low (HL) while indicator makes lower-low
            if len(low_pts) >= 2:
                (a_idx, a_val), (b_idx, b_val) = low_pts[-2], low_pts[-1]
                if b_idx > a_idx and b_val > a_val + EPS:
                    # price HL -> check indicator made lower-low
                    r1, r2 = self._get_indicator_values_at_indices(
                        rsi_hist, [a_idx, b_idx], len(candles)
                    )
                    macd1, macd2 = (None, None)
                    if macd_hist:
                        macd1, macd2 = self._get_indicator_values_at_indices(
                            macd_hist, [a_idx, b_idx], len(candles)
                        )
                    indicator_lower = False
                    if r1 is not None and r2 is not None:
                        indicator_lower = r2 < r1 - EPS
                    elif macd1 is not None and macd2 is not None:
                        indicator_lower = macd2 < macd1 - EPS
                    if indicator_lower:
                        reasons.append(
                            "hidden bullish divergence (price HL but indicator lower-low) -> trend continuation"
                        )
                        found = True
                        mom_ok = self._momentum_confirmation(rsi_series, macd_series, prefer="bull")
                        # ADX 趋势强度 - 趋势强度持续
                        adx_val = self._extract_indicator_value(adx_series, [self.adx_field])
                        adx_ok = True if adx_val > self.adx_threshold else False
                        # 背离触发
                        score += 0.35
                        reasons.append("隐藏Bullish背离触发")
                        # 趋势强度确认
                        if adx_ok:
                            score += 0.20
                            reasons.append("趋势强度确认")
                        # 成交量确认
                        if vol_ok:
                            score += 0.15
                            reasons.append("成交量放大")
                        # 波动率过滤
                        if vol_guard:
                            score += 0.15
                            reasons.append("波动率过滤通过")
                        # 动量确认
                        if mom_ok:
                            score += 0.15
                            reasons.append("动量确认")
                        # 共振加分
                        if adx_ok and vol_ok and mom_ok:
                            score += 0.1
                            reasons.append("三重共振加分")

                        confidence = min(1.0, score)
                        entry = close
                        stop = min(a_val, b_val) - (
                            self.stop_atr_mult * (atr_val or 0.0)
                        )
                        details.update(
                            {
                                "type": "hidden_bull",
                                "swing_prev": (dates[a_idx], a_val),
                                "swing_latest": (dates[b_idx], b_val),
                            }
                        )
                        details.update(
                            {
                                "entry": entry,
                                "stop": round(stop, 6),
                                "confidence_score": round(confidence, 3),
                            }
                        )
                        if confidence >= self.score_threshold:
                            sig = "buy"
            # Hidden bearish
            if not found and len(high_pts) >= 2:
                (a_idx, a_val), (b_idx, b_val) = high_pts[-2], high_pts[-1]
                if b_idx > a_idx and b_val < a_val - EPS:
                    r1, r2 = self._get_indicator_values_at_indices(
                        rsi_hist, [a_idx, b_idx], len(candles)
                    )
                    macd1, macd2 = (None, None)
                    if macd_hist:
                        macd1, macd2 = self._get_indicator_values_at_indices(
                            macd_hist, [a_idx, b_idx], len(candles)
                        )
                    indicator_higher = False
                    if r1 is not None and r2 is not None:
                        indicator_higher = r2 > r1 + EPS
                    elif macd1 is not None and macd2 is not None:
                        indicator_higher = macd2 > macd1 + EPS
                    if indicator_higher:
                        reasons.append(
                            "hidden bearish divergence (price LH but indicator higher-high) -> trend continuation down"
                        )
                        found = True
                        mom_ok = self._momentum_confirmation(rsi_series, macd_series, prefer="bear")
                        # ADX 趋势强度 - 趋势强度持续
                        adx_val = self._extract_indicator_value(adx_series, [self.adx_field])
                        adx_ok = True if adx_val > self.adx_threshold else False
                        # 背离触发
                        score += 0.35
                        reasons.append("隐藏Bearish背离触发")
                        # 趋势强度确认
                        if adx_ok:
                            score += 0.20
                            reasons.append("趋势强度确认")
                        # 成交量确认
                        if vol_ok:
                            score += 0.15
                            reasons.append("成交量放大")
                        # 波动率过滤
                        if vol_guard:
                            score += 0.15
                            reasons.append("波动率过滤通过")
                        # 动量确认
                        if mom_ok:
                            score += 0.15
                            reasons.append("动量确认")
                        # 共振加分
                        if adx_ok and vol_ok and mom_ok:
                            score += 0.1
                            reasons.append("三重共振加分")
                        confidence = min(1.0, score)
                        entry = close
                        stop = max(a_val, b_val) + (
                            self.stop_atr_mult * (atr_val or 0.0)
                        )
                        details.update(
                            {
                                "type": "hidden_bear",
                                "swing_prev": (dates[a_idx], a_val),
                                "swing_latest": (dates[b_idx], b_val),
                            }
                        )
                        details.update(
                            {
                                "entry": entry,
                                "stop": round(stop, 6),
                                "confidence_score": round(confidence, 3),
                            }
                        )
                        if confidence >= self.score_threshold:
                            sig = "sell"

        # usage notes & failsafe
        details.setdefault(
            "notes",
            "常规背离用于反转；隐藏背离用于趋势延续。建议结合多周期确认与新闻/流动性过滤；入场后使用 ATR 止损与 time-stop。",
        )
        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=sig,
            date=dates[-1],
            confidence=round(confidence, 3),
            reason=" | ".join(reasons) if reasons else "no divergence found",
            details=details,
        )

def make_divergence_presets() -> Dict[str, Dict[str, Any]]:
    """
    Divergence 策略预设（资深 algo trader 推荐）
    说明（统一三档/四档可选）：
        - swing: 短波段（1-2 周），更灵敏的背离检测、较低成交量阈值与较短确认窗口
        - intermediate: 中波段（2-6 周），平衡参数（回测默认）
        - position/long_term: 中长线（1-3 月），更严格的过滤、更长的回溯与更高成交量阈值
    """
    base = {
        "swing_window": 4,
        "lookback_swings": 30,
        "rsi_period": 14,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "atr_period": 14,
        "stop_atr_mult": 1.5,
        "min_atr_price_ratio": 0.001,
        "adx_period": 14,
        "adx_threshold": 25.0,
        "time_stop_bars": 12,
        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.0,
        "score_threshold": 0.75,
    }

    swing = {
        **base,
        "swing_window": 3,
        "lookback_swings": 18,
        "rsi_period": 9,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "atr_period": 14,
        "stop_atr_mult": 1.25,
        "min_atr_price_ratio": 0.0009,
        "adx_period": 7,
        "adx_threshold": 18.0,
        "time_stop_bars": 8,
        "vol_zscore_window": 10,
        "vol_zscore_threshold": 0.8,
        "score_threshold": 0.7,
    }

    intermediate = {
        **base,
        # 使用 base 即为中性配置
    }

    long_term = {
        **base,
        "swing_window": 6,
        "lookback_swings": 60,
        "rsi_period": 21,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "atr_period": 21,
        "stop_atr_mult": 2.0,
        "min_atr_price_ratio": 0.002,
        "adx_period": 20,
        "adx_threshold": 30.0,
        "time_stop_bars": 30,
        "vol_zscore_window": 40,
        "vol_zscore_threshold": 1.2,
        "score_threshold": 0.8,
    }

    return {"swing": swing, "intermediate": intermediate, "long_term": long_term}