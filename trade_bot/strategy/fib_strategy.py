from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

# Quick tuning suggestions
# Increase sensitivity: reduce atr_k to 0.7, shorten ema_fast to 5, lower confirmation_threshold to 0.50.
# Reduce noise: increase atr_k to 1.5, require ema_cross + ATR expansion together, raise confirmation_threshold to 0.60.
# Map signals to options: breakout → buy 30–40 delta calls/puts or debit spreads; fade near fib without ATR expansion → credit spreads.
# Risk rules: max 1–2 weekly positions, 0.5–1% risk per trade.
class FibStrategy(TradingStrategy):
    """
    Fibonacci + ATR breakout + short EMA crossover strategy tuned for weekly option trades.
    Replaces Bollinger Bands with ATR-based breakout detection and EMA(8,21) crossover for direction.
    Keeps SignalScorer unchanged; strategy defines weights.
    """

    def __init__(
        self,
        data_provider,
        fib_lookback=60,
        swing_window=5,
        rsi_period=7,
        ema_fast=8,
        ema_slow=21,
        atr_period=14,
        atr_k=1.0,  # breakout sensitivity multiplier
        bw_median_window=20,  # used as ATR median window proxy
        volume_window=5,
        volume_spike_ratio=1.2,
        confirmation_threshold=0.55,
        weights=None
    ):
        self.provider = data_provider
        self.fib_lookback = fib_lookback
        self.swing_window = swing_window
        self.rsi_period = rsi_period
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period
        self.atr_k = atr_k
        self.bw_median_window = bw_median_window
        self.volume_window = volume_window
        self.volume_spike_ratio = volume_spike_ratio
        self.confirmation_threshold = confirmation_threshold

        # Strategy-defined default weights (tunable)
        self.weights = weights or {
            "structure": 0.40,     # Fibonacci / ATR structural trigger
            "rsi": 0.25,           # RSI divergence / midline
            "momentum": 0.15,      # ATR / EMA confirmation
            "volume": 0.12,        # volume catalyst
            "ema": 0.08            # EMA crossover confirmation
        }

    def get_name(self) -> str:
        return "Fib + ATR/EMA"

    def get_lookback_window(self) -> int:
        return max(self.fib_lookback, self.atr_period + self.bw_median_window + self.ema_slow + 5)

    def _safe_get(self, series, idx, attr, default=None):
        try:
            return getattr(series[idx], attr)
        except Exception:
            return default

    def _find_swing(self, candles, direction="high"):
        n = len(candles)
        w = max(2, self.swing_window)
        for i in range(n - w - 1, w, -1):
            if direction == "low":
                left_ok = all(candles[i].low < candles[i - j].low for j in range(1, w))
                right_ok = all(candles[i].low < candles[i + j].low for j in range(1, w))
                if left_ok and right_ok:
                    return i
            else:
                left_ok = all(candles[i].high > candles[i - j].high for j in range(1, w))
                right_ok = all(candles[i].high > candles[i + j].high for j in range(1, w))
                if left_ok and right_ok:
                    return i
        return None

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f"Strategy[{self.get_name()}] generating signal for {symbol}...")
        signal, confidence, details = "hold", 0.0, {}
        current_close_date = candles[-1].date if candles else None

        if not self.provider or len(candles) < self.get_lookback_window() + 1:
            return SignalModel(date=current_close_date, symbol=symbol, strategy=self.get_name(),
                               signal=signal, confidence=confidence, reason="Insufficient data", details=details)

        # Indicators: ATR, RSI, EMAs, (optional MACD)
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        ema_fast = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        macd = None
        try:
            macd = self.provider.get_indicator("macd", candles, {"fast": 12, "slow": 26, "signal": 9})
        except Exception:
            macd = None

        if not atr or not rsi or not ema_fast or not ema_slow:
            return SignalModel(date=current_close_date, symbol=symbol, strategy=self.get_name(),
                               signal=signal, confidence=confidence, reason="Indicator missing", details=details)

        cur = candles[-1]
        prev = candles[-2]
        close = cur.close
        volume = cur.volume

        # Recent extremes for Fibonacci and ATR breakout reference
        recent = candles[-self.fib_lookback:]
        swing_high = max(c.high for c in recent)
        swing_low = min(c.low for c in recent)
        diff = (swing_high - swing_low) if (swing_high > swing_low) else 1e-9
        fib = {
            "23.6": swing_high - 0.236 * diff,
            "38.2": swing_high - 0.382 * diff,
            "50.0": swing_high - 0.5 * diff,
            "61.8": swing_high - 0.618 * diff,
            "78.6": swing_high - 0.786 * diff,
        }

        # ATR values and median (volatility reference)
        cur_atr = self._safe_get(atr, -1, f'ATRr_{self.atr_period}', None)
        atr_hist = [self._safe_get(atr, i, f'ATRr_{self.atr_period}', 0) for i in range(-self.bw_median_window, 0)]
        atr_median = sorted(atr_hist)[len(atr_hist)//2] if atr_hist else 0.0
        atr_expanding = (cur_atr is not None and cur_atr > atr_median)

        # EMA crossover (short, low-latency)
        cur_ema_fast = self._safe_get(ema_fast, -1, f'close_EMA_{self.ema_fast}', None)
        cur_ema_slow = self._safe_get(ema_slow, -1, f'close_EMA_{self.ema_slow}', None)
        prev_ema_fast = self._safe_get(ema_fast, -2, f'close_EMA_{self.ema_fast}', None)
        prev_ema_slow = self._safe_get(ema_slow, -2, f'close_EMA_{self.ema_slow}', None)
        ema_cross_up = (prev_ema_fast is not None and prev_ema_slow is not None and prev_ema_fast <= prev_ema_slow and cur_ema_fast > cur_ema_slow)
        ema_cross_down = (prev_ema_fast is not None and prev_ema_slow is not None and prev_ema_fast >= prev_ema_slow and cur_ema_fast < cur_ema_slow)

        # Volume spike
        vols = [c.volume for c in candles[-self.volume_window - 1:]]
        avg_vol = (sum(vols[:-1]) / self.volume_window) if self.volume_window > 0 else volume
        vol_spike = volume > avg_vol * self.volume_spike_ratio

        # Recent high/low for ATR breakout channel (short lookback)
        breakout_lookback = max(10, int(self.fib_lookback / 6))
        recent_h = max(c.high for c in candles[-breakout_lookback:])
        recent_l = min(c.low for c in candles[-breakout_lookback:])

        # ATR-based breakout checks
        up_breakout = (close > recent_h + self.atr_k * cur_atr) if cur_atr is not None else False
        dn_breakout = (close < recent_l - self.atr_k * cur_atr) if cur_atr is not None else False

        # EMA direction filter
        ema_bull = cur_ema_fast is not None and cur_ema_slow is not None and cur_ema_fast > cur_ema_slow
        ema_bear = cur_ema_fast is not None and cur_ema_slow is not None and cur_ema_fast < cur_ema_slow

        # RSI
        cur_rsi = self._safe_get(rsi, -1, f'close_RSI_{self.rsi_period}', None)

        # Scoring
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)

        # 1) ATR breakout + EMA confirmation => directional breakout trade (buy calls/puts)
        if up_breakout and (ema_bull or ema_cross_up) and atr_expanding:
            scorer.add(True, "ATR breakout above recent high", weight=self.weights["structure"])
            scorer.add(ema_bull or ema_cross_up, "EMA confirms bullish direction", weight=self.weights["ema"])
            scorer.add(cur_rsi is not None and cur_rsi > 50, "RSI > 50", weight=self.weights["rsi"])
            scorer.add(atr_expanding, "ATR expanding vs median", weight=self.weights["momentum"])
            scorer.add(vol_spike, "Volume spike", weight=self.weights["volume"])
            # optional MACD small confirmation
            if macd:
                prev_m = macd[-2]
                cur_m = macd[-1]
                macd_bull = getattr(prev_m, f'close_MACD_12_26_9', 0) <= getattr(prev_m, f'close_MACDs_12_26_9', 0) and getattr(cur_m, f'close_MACD_12_26_9', 0) > getattr(cur_m, f'close_MACDs_12_26_9', 0)
                scorer.add(macd_bull, "MACD bullish crossover", weight=0.03)
            sig, confidence, reasons = scorer.evaluate(direction="bullish")

        # 2) Down breakout => bearish directional
        elif dn_breakout and (ema_bear or ema_cross_down) and atr_expanding:
            scorer.add(True, "ATR breakdown below recent low", weight=self.weights["structure"])
            scorer.add(ema_bear or ema_cross_down, "EMA confirms bearish direction", weight=self.weights["ema"])
            scorer.add(cur_rsi is not None and cur_rsi < 50, "RSI < 50", weight=self.weights["rsi"])
            scorer.add(atr_expanding, "ATR expanding vs median", weight=self.weights["momentum"])
            scorer.add(vol_spike, "Volume spike", weight=self.weights["volume"])
            if macd:
                prev_m = macd[-2]
                cur_m = macd[-1]
                macd_bear = getattr(prev_m, f'close_MACD_12_26_9', 0) >= getattr(prev_m, f'close_MACDs_12_26_9', 0) and getattr(cur_m, f'close_MACD_12_26_9', 0) < getattr(cur_m, f'close_MACDs_12_26_9', 0)
                scorer.add(macd_bear, "MACD bearish crossover", weight=0.03)
            sig, confidence, reasons = scorer.evaluate(direction="bearish")

        # 3) Fibonacci retracement zone + EMA fade conditions => mean-reversion fade (credit spreads)
        else:
            # Buy zone: price sitting in 61.8-50 retracement and EMA suggests short-term bullish bounce
            if fib["61.8"] < close <= fib["50.0"]:
                scorer.add(True, "Price in bullish fib retracement zone (61.8-50)", weight=self.weights["structure"])
                scorer.add((cur_ema_fast is not None and cur_ema_slow is not None and cur_ema_fast > cur_ema_slow), "EMA indicates short bullish edge", weight=self.weights["ema"] * 0.8)
                scorer.add(cur_rsi is not None and cur_rsi > 45, "RSI > 45 favors bounce", weight=self.weights["rsi"])
                scorer.add(not atr_expanding, "No ATR expansion (safe to fade)", weight=self.weights["momentum"])
                scorer.add(vol_spike, "Volume spike", weight=self.weights["volume"])
                sig, confidence, reasons = scorer.evaluate(direction="bullish")

            # Sell / deep retrace zone: below 78.6 or strong re-entry fail near fib deeper zone
            elif close < fib["78.6"]:
                scorer.add(True, "Price below deep fib (78.6) - continuation risk", weight=self.weights["structure"])
                scorer.add(cur_rsi is not None and cur_rsi < 50, "RSI < 50", weight=self.weights["rsi"])
                scorer.add(atr_expanding, "ATR expanding (momentum to continue)", weight=self.weights["momentum"])
                scorer.add(vol_spike, "Volume spike", weight=self.weights["volume"])
                sig, confidence, reasons = scorer.evaluate(direction="bearish")
            else:
                sig, confidence, reasons = "hold", 0.0, ["No strong ATR/EMA/Fib setup"]

        # final normalization: translate scorer signal to 'buy'/'sell'/'hold' consistent with Score design
        final_signal = sig
        final_confidence = round(confidence, 2)

        details = {
            "swing_high": swing_high,
            "swing_low": swing_low,
            "fib_levels": fib,
            "close": close,
            "recent_high": recent_h,
            "recent_low": recent_l,
            "atr": cur_atr,
            "atr_median": atr_median,
            "ema_fast": cur_ema_fast,
            "ema_slow": cur_ema_slow,
            "ema_cross_up": ema_cross_up,
            "ema_cross_down": ema_cross_down,
            "vol": volume,
            "avg_vol": avg_vol,
            "confidence": final_confidence,
            "reasons": reasons
        }

        return SignalModel(
            date=current_close_date,
            symbol=symbol,
            strategy=self.get_name(),
            signal=final_signal,
            confidence=final_confidence,
            reason="; ".join(reasons),
            details=details
        )
