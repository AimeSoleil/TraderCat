from typing import List, Optional, Dict, Any, Tuple
import math
import statistics

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

class FibonacciRetracementStrategy(TradingStrategy):
    """
    Fibonacci Retracement + Breakout 策略（生产就绪）

    概要:
      - 在一次冲击波（impulse）后，等待价格回撤至 Fib 38.2–61.8% 区间，
        当价格在该区间确认回撤后出现突破（突破区间高位或突破上一个摆动高点）则入场顺势；
      - 使用 EMA 快慢线作为趋势滤波；ATR 用于止损与仓位基准；支持时间止损与多种保护；
      - 以日线为主，持仓以周为单位；通过 presets 可切换为中/长期模式。

    使用建议（简短）:
      - 适用: 趋势明显的品种，流动性充足，波段持仓（数日到数周）
      - 不适用: 新闻驱动价差，低流动性或持续震荡盤
    """

    def __init__(
        self,
        lookback_swings: int = 30,
        swing_window: int = 4,
        fib_zone: Tuple[float, float] = (0.382, 0.618),
        stop_fib: float = 0.786,
        ema_fast: int = 13,
        ema_slow: int = 34,
        atr_period: int = 14,
        rsi_period: int = 14,
        macd_params: Optional[Dict[str,int]] = None,
        adx_period: int = 14,
        adx_threshold: float = 25.0,
        stop_atr_mult: float = 1.5,
        tp_atr_mult: float = 2.5,
        time_stop_bars: int = 20,
        min_atr_price_ratio: float = 0.0015,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.6,
        data_provider: Any = None,
    ):
        self.lookback_swings = int(lookback_swings)
        self.swing_window = max(1, int(swing_window))
        self.fib_low = float(fib_zone[0])
        self.fib_high = float(fib_zone[1])
        self.stop_fib = float(stop_fib)
        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.atr_period = int(atr_period)
        self.rsi_period = int(rsi_period)
        self.macd_params = macd_params or {"fast":12,"slow":26,"signal":9}
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.stop_atr_mult = float(stop_atr_mult)
        self.tp_atr_mult = float(tp_atr_mult)
        self.time_stop_bars = int(time_stop_bars)
        self.min_atr_price_ratio = float(min_atr_price_ratio)
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # 指标字段命名（集中在构造函数定义，方便后续修改）
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"

    def get_name(self) -> str:
        return "FibonacciRetracement"

    def get_lookback_window(self) -> int:
        return max(self.lookback_swings, self.ema_slow, self.atr_period) + 10

    # ---------- helpers ----------
    def _sma(self, vals: List[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    def _std(self, vals: List[float]) -> float:
        return statistics.pstdev(vals) if len(vals) > 0 else 0.0

    def _is_finite(self, v: Any) -> bool:
        try:
            return v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
        except Exception:
            return False

    def _find_fractal_swings(self, highs: List[float], lows: List[float], window: int) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
        """
        N-bar fractal swings: 返回 (index, value) 列表, index 相对于传入数组起点
        """
        highs_pts = []
        lows_pts = []
        n = len(highs)
        if n < window * 2 + 1:
            return highs_pts, lows_pts
        for i in range(window, n - window):
            left_h = highs[i - window : i]
            right_h = highs[i + 1 : i + window + 1]
            if all(self._is_finite(x) for x in left_h + right_h) and highs[i] > max(left_h + right_h):
                highs_pts.append((i, highs[i]))
            left_l = lows[i - window : i]
            right_l = lows[i + 1 : i + window + 1]
            if all(self._is_finite(x) for x in left_l + right_l) and lows[i] < min(left_l + right_l):
                lows_pts.append((i, lows[i]))
        return highs_pts, lows_pts

    def _calc_fib_levels(self, swing_high: float, swing_low: float) -> Dict[float, float]:
        diff = swing_high - swing_low
        levels = {
            0.0: swing_high,
            0.236: swing_high - 0.236 * diff,
            0.382: swing_high - 0.382 * diff,
            0.5: swing_high - 0.5 * diff,
            0.618: swing_high - 0.618 * diff,
            0.786: swing_high - 0.786 * diff,
            1.0: swing_low,
        }
        return levels

    def _extract_latest_indicator_value(self, series: Optional[List[Any]], keys: List[str]) -> Optional[float]:
        """
        兼容封装：从 provider 的指标序列中提取最后一条数值（兼容对象属性或 dict 字段或直接数值）。
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
                v = getattr(last, k, None) if hasattr(last, k) else (last.get(k) if isinstance(last, dict) else None)
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
        从 provider 的历史指标序列中按全局索引提取对应值（若不可用返回 None）。
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

    def _momentum_confirmation(self, macd_series: Optional[List[Any]], rsi_series: Optional[List[Any]], prefer: str = "bull") -> bool:
        """
        简单动量确认：用最新 RSI / MACD-hist 判断是否支持方向（bear 或 bull）。
        """
        r_latest = self._extract_latest_indicator_value(rsi_series, [self.rsi_field]) if rsi_series else None
        macd_hist_latest = None
        if macd_series:
            last = macd_series[-1]
            macd_hist_latest = getattr(last, self.macd_hist_field, None)

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

    def _make_exit_plan(self, side: str, entry_price: float, atr: Optional[float], stop_atr_mult: float, tp_atr_mult: float, stop_fib_level: Optional[float] = None) -> Dict[str, Any]:
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

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        输入:
            - candles: 日线列表，按时间升序（旧->新），每条需包含 high/low/open/close/volume/date
        输出:
            - SignalModel: signal in {'buy','sell','hold'} + details 包含入场/止损/目标计划与诊断信息
        """
        if not candles or not self.provider or len(candles) < self.get_lookback_window():
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=candles[-1].date if candles else None, confidence=0.0, reason="insufficient data or provider", details={})

        # extract OHLCV windows
        N = min(len(candles), max(self.lookback_swings, self.ema_slow, self.atr_period) + 5)
        base = len(candles) - N
        highs = [float(getattr(c, "high", None)) for c in candles[base:]]
        lows = [float(getattr(c, "low", None)) for c in candles[base:]]
        closes = [float(getattr(c, "close", None)) for c in candles[base:]]
        volumes = [float(getattr(c, "volume", None)) for c in candles[base:]]
        dates = [getattr(c, "date", None) for c in candles[base:]]
        curr_close = closes[-1]

        # 指标 via provider（使用构造函数中定义的 period/field）
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params)
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        ema_fast_val = self._extract_latest_indicator_value(ema_fast_series, [self.ema_fast_field])
        ema_slow_val = self._extract_latest_indicator_value(ema_slow_series, [self.ema_slow_field])
        atr_val = self._extract_latest_indicator_value(atr_series, [self.atr_field])
        adx_val = self._extract_latest_indicator_value(adx_series, [self.adx_field])

        # trend filter
        trend_up = ema_fast_val is not None and ema_slow_val is not None and ema_fast_val > ema_slow_val
        trend_down = ema_fast_val is not None and ema_slow_val is not None and ema_fast_val < ema_slow_val

        # swings detection on lookback window
        swings_highs, swings_lows = self._find_fractal_swings(highs[-self.lookback_swings:], lows[-self.lookback_swings:], self.swing_window)

        # convert local indices to global (relative to full candles)
        # pick most recent impulse: last pair of opposite swing (e.g., low->high for bullish impulse)
        signal = "hold"
        confidence = 0.0
        reasons: List[str] = []
        details: Dict[str, Any] = {"date": dates[-1], "curr_close": curr_close}

        if not swings_highs and not swings_lows:
            reasons.append("no swings")
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=dates[-1], confidence=0.0, reason="no swing points", details=details)

        # default: treat impulse as high->low or low->high depending on which is more recent
        # choose swing pair to compute fib base: for long we want an impulse low->high, for short high->low
        # find last completed impulse (use the two most recent opposite swings)
        long_candidate = None
        short_candidate = None
        if len(swings_lows) >= 2:
            # possible long impulse: earlier low -> later high
            # find latest low preceding a later high
            for i in range(len(swings_lows) - 1, -1, -1):
                low_idx, low_val = swings_lows[i]
                # find next high after low
                nxt_highs = [h for h in swings_highs if h[0] > low_idx]
                if nxt_highs:
                    high_idx, high_val = nxt_highs[-1]
                    long_candidate = (low_idx, low_val, high_idx, high_val)
                    break

        if len(swings_highs) >= 2:
            # possible short impulse: earlier high -> later low
            for i in range(len(swings_highs) - 1, -1, -1):
                high_idx, high_val = swings_highs[i]
                nxt_lows = [l for l in swings_lows if l[0] > high_idx]
                if nxt_lows:
                    low_idx, low_val = nxt_lows[-1]
                    short_candidate = (high_idx, high_val, low_idx, low_val)
                    break

        # ADX 趋势强度
        adx_ok = True if adx_val >= self.adx_threshold else False # 突破趋势强度
        # 成交量 z-score 确认（vol_ok）：用最近 vol_zscore_window 样本计算 z-score
        vol_ok = False
        volume_z = None
        recent_window = max(1, min(self.vol_zscore_window, len(volumes)))
        recent_vols = [v for v in volumes[-recent_window:] if v is not None]
        try:
            if recent_vols and len(recent_vols) >= 2 and volumes[-1] is not None:
                mean_v = sum(recent_vols) / len(recent_vols)
                std_v = statistics.pstdev(recent_vols) if len(recent_vols) > 1 else 0.0
                if std_v > 0:
                    volume_z = (volumes[-1] - mean_v) / std_v
                    vol_ok = volume_z >= self.vol_zscore_threshold
        except Exception:
            vol_ok = False
        # volatility guard
        vol_guard = (atr_val is not None) and (atr_val / max(abs(curr_close), EPS) >= self.min_atr_price_ratio)

        # evaluate long candidate
        entry_plan = None
        if long_candidate:
            _, swing_low_val, _, swing_high_val = long_candidate
            # compute fib levels from swing_high (impulse top) and swing_low (impulse low)
            fib_levels = self._calc_fib_levels(swing_high_val, swing_low_val)
            zone_high = fib_levels[self.fib_low]  # e.g., 0.382 level value is above 0.618 in price space since mapping from high->low
            zone_low = fib_levels[self.fib_high]
            # check price is inside fib zone (between zone_high and zone_low)
            in_zone = zone_low - EPS <= curr_close <= zone_high + EPS
            # breakout confirmation: close above zone_high (i.e., price moves back above the upper zone boundary) OR close above recent swing high
            prior_swing_high = swing_high_val
            breakout_confirm = (curr_close > zone_high + EPS) or (curr_close > prior_swing_high + EPS)
            mom_ok = self._momentum_confirmation(macd_series, rsi_series, prefer="bull")
            
            # score: 重点强调 in_zone + breakout_confirm + volume/momentum 共振，并适度降低辅助因子权重
            score = 0.0
            reasons = []
            # 回撤区间确认
            if in_zone:
                score += 0.25
                reasons.append("价格进入Fibonacci回撤区间")
            # 突破确认
            if breakout_confirm:
                score += 0.25
                reasons.append("突破确认")
            # 成交量确认
            if vol_ok:
                score += 0.15
                reasons.append("成交量放大")
            # 动量确认
            if mom_ok:
                score += 0.15
                reasons.append("动量确认")
            # 趋势强度
            if adx_ok:
                score += 0.10
                reasons.append("趋势强度确认")
            # 波动率过滤
            if vol_guard:
                score += 0.05
                reasons.append("波动率过滤通过")
            # EMA 趋势方向一致
            if trend_up:
                score += 0.05
                reasons.append("趋势方向一致")
            # 共振加分
            if vol_ok and mom_ok and adx_ok:
                score += 0.1
                reasons.append("三重共振加分")

            confidence = min(1.0, score)
            reasons.append(f"long_candidate in_zone={in_zone} breakout={breakout_confirm} vol_ok={vol_ok} mom_ok={mom_ok} vol_guard={vol_guard}")
            if confidence >= self.score_threshold and (in_zone and breakout_confirm):
                # prepare entry and exits
                entry_price = curr_close
                stop_fib_level = fib_levels.get(self.stop_fib)
                exit_plan = self._make_exit_plan("long", entry_price, atr_val, self.stop_atr_mult, self.tp_atr_mult, stop_fib_level)
                entry_plan = {"side": "long", "entry": entry_price, "exit_plan": exit_plan, "time_stop": self.time_stop_bars, "fib_levels": fib_levels}
                signal = "buy"
                details.update({"entry_plan": entry_plan, "confidence_score": round(confidence, 3)})
            else:
                signal = "hold"

        # evaluate short candidate
        if short_candidate and trend_down:
            _, swing_high_val, _, swing_low_val = short_candidate
            fib_levels = self._calc_fib_levels(swing_high_val, swing_low_val)
            zone_high = fib_levels[self.fib_low]
            zone_low = fib_levels[self.fib_high]
            in_zone = zone_low - EPS <= curr_close <= zone_high + EPS
            prior_swing_low = swing_low_val
            breakout_confirm = (curr_close < zone_low - EPS) or (curr_close < prior_swing_low - EPS)
            mom_ok = self._momentum_confirmation(macd_series, rsi_series, prefer="bear")
            
            # score: 重点强调 in_zone + breakout_confirm + volume/momentum 共振，并适度降低辅助因子权重
            score = 0.0
            reasons = []
            # 回撤区间确认
            if in_zone:
                score += 0.25
                reasons.append("价格进入Fibonacci回撤区间")
            # 突破确认
            if breakout_confirm:
                score += 0.25
                reasons.append("突破确认")
            # 成交量确认
            if vol_ok:
                score += 0.15
                reasons.append("成交量放大")
            # 动量确认
            if mom_ok:
                score += 0.15
                reasons.append("动量确认")
            # 趋势强度
            if adx_ok:
                score += 0.10
                reasons.append("趋势强度确认")
            # 波动率过滤
            if vol_guard:
                score += 0.05
                reasons.append("波动率过滤通过")
            # EMA 趋势方向一致
            if trend_up:
                score += 0.05
                reasons.append("趋势方向一致")
            # 共振加分
            if vol_ok and mom_ok and adx_ok:
                score += 0.1
                reasons.append("三重共振加分")

            confidence = min(1.0, score)
            reasons.append(f"short_candidate in_zone={in_zone} breakout={breakout_confirm} vol_ok={vol_ok} mom_ok={mom_ok} vol_guard={vol_guard}")
            if confidence >= self.score_threshold and (in_zone and breakout_confirm):
                entry_price = curr_close
                stop_fib_level = fib_levels.get(self.stop_fib)
                exit_plan = self._make_exit_plan("short", entry_price, atr_val, self.stop_atr_mult, self.tp_atr_mult, stop_fib_level)
                entry_plan = {"side": "short", "entry": entry_price, "exit_plan": exit_plan, "time_stop": self.time_stop_bars, "fib_levels": fib_levels}
                signal = "sell"
                details.update({"entry_plan": entry_plan, "confidence_score": round(confidence, 3)})
            else:
                # if we already set signal to buy above, keep buy; else hold
                if signal != "buy":
                    signal = "hold"

        details.update({"reasons": reasons})
        return SignalModel(symbol=symbol, strategy=self.get_name(), signal=signal, date=dates[-1], confidence=round(confidence, 3), reason=" | ".join(reasons), details=details)

def make_fibonacci_presets() -> Dict[str, Dict[str, Any]]:
    """
    为 FibonacciRetracementStrategy 设计的专业预设（swing / intermediate / position）
    说明：
        - 值基于经验与风险管理最佳实践，便于快速在不同周期间切换和回测比较。
    """
    swing = {
        # 回溯与形态识别
        "lookback_swings": 20,
        "swing_window": 3,
        "fib_zone": (0.382, 0.618),
        "stop_fib": 0.786,

        # 趋势/指标
        "ema_fast": 8,
        "ema_slow": 21,
        "atr_period": 14,
        "rsi_period": 9,
        "macd_params": {"fast": 8, "slow": 17, "signal": 9},
        "adx_period": 7,
        "adx_threshold": 18.0,

        # 风控与目标
        "stop_atr_mult": 1.2,
        "tp_atr_mult": 2.0,
        "time_stop_bars": 10,
        "min_atr_price_ratio": 0.001,

        # 成交量与置信度
        "vol_zscore_window": 10,
        "vol_zscore_threshold": 0.8,
        "score_threshold": 0.7,
    }

    intermediate = {
        "lookback_swings": 30,
        "swing_window": 4,
        "fib_zone": (0.382, 0.618),
        "stop_fib": 0.786,

        "ema_fast": 13,
        "ema_slow": 34,
        "atr_period": 14,
        "rsi_period": 14,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "adx_period": 14,
        "adx_threshold": 25.0,

        "stop_atr_mult": 1.5,
        "tp_atr_mult": 2.5,
        "time_stop_bars": 20,
        "min_atr_price_ratio": 0.0015,

        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.0,
        "score_threshold": 0.75,
    }

    position = {
        "lookback_swings": 45,
        "swing_window": 6,
        "fib_zone": (0.382, 0.618),
        "stop_fib": 0.786,

        "ema_fast": 21,
        "ema_slow": 55,
        "atr_period": 21,
        "rsi_period": 21,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "adx_period": 20,
        "adx_threshold": 30.0,

        # 更保守的止损与更大的目标
        "stop_atr_mult": 2.0,
        "tp_atr_mult": 3.0,
        "time_stop_bars": 40,
        "min_atr_price_ratio": 0.002,

        "vol_zscore_window": 40,
        "vol_zscore_threshold": 1.2,
        "score_threshold": 0.8,
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}