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
        entry_atr_mult: float = 1.5,
        stop_atr_mult: float = 1.5,
        tp_atr_mult: float = 2.5,
        time_stop_bars: int = 20,
        min_atr_price_ratio: float = 0.0015,
        require_volume: bool = True,
        require_momentum: bool = True,
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
        self.entry_atr_mult = float(entry_atr_mult)
        self.stop_atr_mult = float(stop_atr_mult)
        self.tp_atr_mult = float(tp_atr_mult)
        self.time_stop_bars = int(time_stop_bars)
        self.min_atr_price_ratio = float(min_atr_price_ratio)
        self.require_volume = bool(require_volume)
        self.require_momentum = bool(require_momentum)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

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

    def _compute_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int) -> Optional[float]:
        if len(closes) < period + 1:
            return None
        trs = []
        for i in range(-period, 0):
            h = highs[i]
            l = lows[i]
            pc = closes[i - 1]
            if not (self._is_finite(h) and self._is_finite(l) and self._is_finite(pc)):
                return None
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return sum(trs) / len(trs) if trs else None

    def _extract_indicator_latest(self, series: List[Any], attr_names: List[str]) -> Optional[float]:
        """尝试从指标对象列表中获取一个数字字段"""
        if not series:
            return None
        last = series[-1]
        if last is None:
            return None
        if isinstance(last, (int, float)):
            return float(last)
        for a in attr_names:
            val = getattr(last, a, None) if hasattr(last, a) else (last.get(a) if isinstance(last, dict) else None)
            if val is not None:
                try:
                    return float(val)
                except Exception:
                    continue
        return None

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
        highs = [float(getattr(c, "high", getattr(c, "High", None))) for c in candles[base:]]
        lows = [float(getattr(c, "low", getattr(c, "Low", None))) for c in candles[base:]]
        closes = [float(getattr(c, "close", getattr(c, "Close", None))) for c in candles[base:]]
        volumes = [float(getattr(c, "volume", getattr(c, "Volume", 0))) for c in candles[base:]]
        dates = [getattr(c, "date", None) for c in candles[base:]]
        curr_close = closes[-1]

        # indicators (via provider)
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        macd_series = self.provider.get_indicator("macd", candles, {"fast": 12, "slow": 26, "signal": 9})
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": 14})

        ema_fast_val = self._extract_indicator_latest(ema_fast_series, [f"EMA_{self.ema_fast}", "ema", "EMA"])
        ema_slow_val = self._extract_indicator_latest(ema_slow_series, [f"EMA_{self.ema_slow}", "ema", "EMA"])
        atr_val = self._extract_indicator_latest(atr_series, [f"ATR_{self.atr_period}", "atr", "ATR"]) or self._compute_atr(highs, lows, closes, self.atr_period)

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

        # determine recent impulse: look for most recent swing high and swing low
        last_high = swings_highs[-1] if swings_highs else None
        last_low = swings_lows[-1] if swings_lows else None

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

        # evaluate long candidate
        entry_plan = None
        if long_candidate and trend_up:
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
            # volume / momentum checks
            vol_ok = True
            if self.require_volume:
                vol_ma = sum(volumes[-min(len(volumes), 20):]) / max(1, min(len(volumes), 20))
                vol_ok = volumes[-1] >= vol_ma * 0.8
            mom_ok = True
            if self.require_momentum:
                # use macd histogram as simple momentum
                try:
                    m = getattr(macd_series[-1], "macd", None) or getattr(macd_series[-1], "MACD", None)
                    s = getattr(macd_series[-1], "signal", None) or getattr(macd_series[-1], "SIGNAL", None)
                    hist = float(m) - float(s) if m is not None and s is not None else 0.0
                    mom_ok = hist > 0
                except Exception:
                    mom_ok = True
            # volatility guard
            vol_guard = (atr_val is not None) and (atr_val / max(abs(curr_close), EPS) >= self.min_atr_price_ratio)
            # score
            score = 0.0
            if in_zone:
                score += 0.4
            if breakout_confirm:
                score += 0.35
            if vol_ok:
                score += 0.1
            if mom_ok:
                score += 0.1
            if vol_guard:
                score += 0.05
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
            vol_ok = True
            if self.require_volume:
                vol_ma = sum(volumes[-min(len(volumes), 20):]) / max(1, min(len(volumes), 20))
                vol_ok = volumes[-1] >= vol_ma * 0.8
            mom_ok = True
            if self.require_momentum:
                try:
                    m = getattr(macd_series[-1], "macd", None) or getattr(macd_series[-1], "MACD", None)
                    s = getattr(macd_series[-1], "signal", None) or getattr(macd_series[-1], "SIGNAL", None)
                    hist = float(m) - float(s) if m is not None and s is not None else 0.0
                    mom_ok = hist < 0
                except Exception:
                    mom_ok = True
            vol_guard = (atr_val is not None) and (atr_val / max(abs(curr_close), EPS) >= self.min_atr_price_ratio)
            score = 0.0
            if in_zone:
                score += 0.4
            if breakout_confirm:
                score += 0.35
            if vol_ok:
                score += 0.1
            if mom_ok:
                score += 0.1
            if vol_guard:
                score += 0.05
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
        return SignalModel(symbol=symbol, strategy=self.get_name(), signal=signal, date=dates[-1], confidence=round(confidence if isinstance(confidence, float) else 0.0, 3), reason=" | ".join(reasons), details=details)


def make_fib_retracement_presets() -> Dict[str, Dict[str, Any]]:
    """
    Presets:
      - swing: 1-2 week hold, 灵敏
      - intermediate: 2-6 week
      - position: 1-3 month, 更守旧
    """
    swing = {
        "lookback_swings": 24,
        "swing_window": 3,
        "fib_zone": (0.382, 0.618),
        "stop_fib": 0.786,
        "ema_fast": 8,
        "ema_slow": 21,
        "atr_period": 10,
        "entry_atr_mult": 1.2,
        "stop_atr_mult": 1.2,
        "tp_atr_mult": 2.0,
        "time_stop_bars": 10,
        "min_atr_price_ratio": 0.001,
        "require_volume": True,
        "require_momentum": True,
        "score_threshold": 0.55,
    }
    intermediate = {
        "lookback_swings": 40,
        "swing_window": 4,
        "fib_zone": (0.382, 0.618),
        "stop_fib": 0.786,
        "ema_fast": 13,
        "ema_slow": 34,
        "atr_period": 14,
        "entry_atr_mult": 1.5,
        "stop_atr_mult": 1.5,
        "tp_atr_mult": 2.5,
        "time_stop_bars": 20,
        "min_atr_price_ratio": 0.0015,
        "require_volume": True,
        "require_momentum": True,
        "score_threshold": 0.6,
    }
    position = {
        "lookback_swings": 80,
        "swing_window": 5,
        "fib_zone": (0.382, 0.618),
        "stop_fib": 0.786,
        "ema_fast": 21,
        "ema_slow": 55,
        "atr_period": 21,
        "entry_atr_mult": 2.0,
        "stop_atr_mult": 2.0,
        "tp_atr_mult": 3.0,
        "time_stop_bars": 40,
        "min_atr_price_ratio": 0.002,
        "require_volume": False,
        "require_momentum": False,
        "score_threshold": 0.65,
    }
    return {"swing": swing, "intermediate": intermediate, "position": position}