from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
import pandas as pd


class HiddenDivergenceStrategy(TradingStrategy):
    """
    Simplified Hidden Divergence strategy (BB + EMA + ATR + RSI) with low-weight MACD and KDJ confirmations.
    Uses the existing SignalScorer unchanged; weights are defined in the strategy.
    """

    def __init__(
        self,
        data_provider,
        bb_period=10,
        bb_std=2.0,
        ema_period=21,
        swing_window=5,
        rsi_period=7,
        atr_period=14,
        volume_window=5,
        volume_spike_ratio=1.2,
        confirmation_threshold=0.55,
        weights=None
    ):
        self.provider = data_provider
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.ema_period = ema_period
        self.swing_window = max(2, swing_window)
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.volume_window = volume_window
        self.volume_spike_ratio = volume_spike_ratio
        self.confirmation_threshold = confirmation_threshold

        # Strategy-defined weights (macd/kdj are intentionally low)
        self.weights = weights or {
            "structure": 0.40,   # primary hidden divergence / price structure
            "rsi": 0.25,         # RSI divergence confirmation
            "atr": 0.15,         # volatility confirmation
            "volume": 0.10,      # volume catalyst
            "ema": 0.05,         # EMA trend confirmation (light)
            "macd": 0.03,        # MACD confirmation (low weight)
            "kdj": 0.02          # KDJ confirmation (very low weight)
        }

    def get_name(self) -> str:
        return "Hidden Divergence"

    def get_lookback_window(self) -> int:
        return max(60, self.bb_period + self.atr_period + self.ema_period + self.swing_window)

    def _safe_get(self, series, idx, attr, default=None):
        try:
            return getattr(series[idx], attr)
        except Exception:
            return default

    def _calc_ema(self, prices, period):
        return pd.Series(prices).ewm(span=period, adjust=False).mean().tolist()

    def _find_last_swing(self, candles, direction="low"):
        n = len(candles)
        w = self.swing_window
        for i in range(n - w - 1, w, -1):
            if direction == "low":
                if all(candles[i].low < candles[i - j].low for j in range(1, w + 1)) and \
                   all(candles[i].low < candles[i + j].low for j in range(1, w + 1)):
                    return i
            else:
                if all(candles[i].high > candles[i - j].high for j in range(1, w + 1)) and \
                   all(candles[i].high > candles[i + j].high for j in range(1, w + 1)):
                    return i
        return None

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f"Strategy[{self.get_name()}] generating signal for {symbol}...")
        date_now = candles[-1].date if candles else None
        if not self.provider or len(candles) < self.get_lookback_window() + 1:
            return SignalModel(date=date_now, symbol=symbol, strategy=self.get_name(),
                               signal="hold", confidence=0.0, reason="Insufficient data", details={})

        # Indicators: BB, RSI, ATR, EMA, MACD (optional), KDJ (optional)
        bb = self.provider.get_indicator("bbands", candles, {"length": self.bb_period, "std": self.bb_std})
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        ema_vals = self._calc_ema([c.close for c in candles], self.ema_period)

        # Optional indicators: MACD and KDJ (attempt to fetch; if missing, their checks skip)
        try:
            macd = self.provider.get_indicator("macd", candles, {"fast": 12, "slow": 26, "signal": 9})
        except Exception:
            macd = None
        try:
            kdj = self.provider.get_indicator("stoch", candles, {"fast_k_period": 14, "slow_d_period": 3, "slow_k_period": 3})
        except Exception:
            kdj = None

        if not bb or not rsi or not atr or not ema_vals:
            return SignalModel(date=date_now, symbol=symbol, strategy=self.get_name(),
                               signal="hold", confidence=0.0, reason="Indicator missing", details={})

        cur = candles[-1]
        close = cur.close
        volume = cur.volume

        # BB latest
        bbu = self._safe_get(bb, -1, f'close_BBU_{self.bb_period}_{self.bb_std}')
        bbl = self._safe_get(bb, -1, f'close_BBL_{self.bb_period}_{self.bb_std}')
        if bbu is None or bbl is None:
            return SignalModel(date=date_now, symbol=symbol, strategy=self.get_name(),
                               signal="hold", confidence=0.0, reason="BB fields missing", details={})

        # ATR and median
        cur_atr = self._safe_get(atr, -1, f'ATRr_{self.atr_period}', None)
        atr_hist = [self._safe_get(atr, i, f'ATRr_{self.atr_period}', 0) for i in range(-self.bb_period - self.atr_period, 0)]
        atr_median = sorted(atr_hist)[len(atr_hist)//2] if atr_hist else 0.0
        atr_expanding = (cur_atr is not None and cur_atr > atr_median)

        # EMA trend
        cur_ema = ema_vals[-1]
        trend_up = close > cur_ema

        # Swing indexes
        swing_low_idx = self._find_last_swing(candles, "low")
        swing_high_idx = self._find_last_swing(candles, "high")

        # RSI current and swing
        cur_rsi = self._safe_get(rsi, -1, f'close_RSI_{self.rsi_period}', None)

        # Volume baseline
        vols = [c.volume for c in candles[-self.volume_window - 1:]]
        avg_vol = (sum(vols[:-1]) / self.volume_window) if self.volume_window > 0 else volume
        vol_spike = volume > avg_vol * self.volume_spike_ratio

        # Prepare optional MACD/KDJ values for confirmations
        macd_confirm_up = False
        macd_confirm_down = False
        if macd and len(macd) >= 2:
            prev_m = macd[-2]
            cur_m = macd[-1]
            # fields assumed: close_MACD_{fast}_{slow}_{signal} and close_MACDs_{fast}_{slow}_{signal}
            prev_macd_val = self._safe_get(macd, -2, f'close_MACD_12_26_9', None)
            prev_macd_sig = self._safe_get(macd, -2, f'close_MACDs_12_26_9', None)
            cur_macd_val = self._safe_get(macd, -1, f'close_MACD_12_26_9', None)
            cur_macd_sig = self._safe_get(macd, -1, f'close_MACDs_12_26_9', None)
            macd_confirm_up = (prev_macd_val is not None and prev_macd_sig is not None and cur_macd_val is not None and cur_macd_sig is not None and prev_macd_val <= prev_macd_sig and cur_macd_val > cur_macd_sig)
            macd_confirm_down = (prev_macd_val is not None and prev_macd_sig is not None and cur_macd_val is not None and cur_macd_sig is not None and prev_macd_val >= prev_macd_sig and cur_macd_val < cur_macd_sig)

        kdj_confirm_up = False
        kdj_confirm_down = False
        if kdj and len(kdj) >= 1:
            cur_k = self._safe_get(kdj, -1, 'STOCHk_14_3_3', None)
            cur_d = self._safe_get(kdj, -1, 'STOCHd_14_3_3', None)
            if cur_k is not None and cur_d is not None:
                kdj_confirm_up = cur_k > cur_d  # lightweight directional hint
                kdj_confirm_down = cur_k < cur_d

        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)

        # Hidden bullish divergence (trend up)
        if trend_up and swing_low_idx is not None and swing_low_idx < len(candles) - 1:
            swing_price = candles[swing_low_idx].close
            swing_rsi = self._safe_get(rsi, swing_low_idx, f'close_RSI_{self.rsi_period}', None)

            price_higher_low = close > swing_price
            rsi_lower_low = (cur_rsi is not None and swing_rsi is not None and cur_rsi < swing_rsi)

            scorer.add(price_higher_low, "Structure: price higher low (hidden bullish)", weight=self.weights["structure"])
            scorer.add(rsi_lower_low, "RSI lower low (divergence)", weight=self.weights["rsi"])
            scorer.add(atr_expanding, "ATR expanding (volatility)", weight=self.weights["atr"])
            scorer.add(vol_spike, "Volume spike", weight=self.weights["volume"])
            scorer.add(trend_up, "EMA/price trend up", weight=self.weights["ema"])
            # Optional low-weight confirmations
            scorer.add(macd_confirm_up, "MACD bullish crossover (low weight)", weight=self.weights["macd"])
            scorer.add(kdj_confirm_up, "KDJ bullish cue (low weight)", weight=self.weights["kdj"])

            signal, confidence, reasons = scorer.evaluate(direction="bullish")

            # If strong breakout beyond upper BB with ATR expanding, add tiny extra weight
            if close > bbu and atr_expanding:
                scorer.add(True, "Breakout above upper BB (tiny boost)", weight=0.01)
                signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Hidden bearish divergence (trend down)
        elif (not trend_up) and swing_high_idx is not None and swing_high_idx < len(candles) - 1:
            swing_price = candles[swing_high_idx].close
            swing_rsi = self._safe_get(rsi, swing_high_idx, f'close_RSI_{self.rsi_period}', None)

            price_lower_high = close < swing_price
            rsi_higher_high = (cur_rsi is not None and swing_rsi is not None and cur_rsi > swing_rsi)

            scorer.add(price_lower_high, "Structure: price lower high (hidden bearish)", weight=self.weights["structure"])
            scorer.add(rsi_higher_high, "RSI higher high (divergence)", weight=self.weights["rsi"])
            scorer.add(atr_expanding, "ATR expanding (volatility)", weight=self.weights["atr"])
            scorer.add(vol_spike, "Volume spike", weight=self.weights["volume"])
            scorer.add(not trend_up, "EMA/price trend down", weight=self.weights["ema"])
            # Optional low-weight confirmations
            scorer.add(macd_confirm_down, "MACD bearish crossover (low weight)", weight=self.weights["macd"])
            scorer.add(kdj_confirm_down, "KDJ bearish cue (low weight)", weight=self.weights["kdj"])

            signal, confidence, reasons = scorer.evaluate(direction="bearish")

            if close < bbl and atr_expanding:
                scorer.add(True, "Breakdown below lower BB (tiny boost)", weight=0.01)
                signal, confidence, reasons = scorer.evaluate(direction="bearish")

        else:
            signal, confidence, reasons = "hold", 0.0, ["No strong hidden-divergence signal"]

        details = {
            "trend_up": trend_up,
            "close": close,
            "ema": cur_ema,
            "bb_upper": bbu,
            "bb_lower": bbl,
            "cur_rsi": cur_rsi,
            "swing_low_idx": swing_low_idx,
            "swing_high_idx": swing_high_idx,
            "atr": cur_atr,
            "atr_median": atr_median,
            "atr_expanding": atr_expanding,
            "volume": volume,
            "avg_volume": avg_vol,
            "confidence": confidence,
            "reasons": reasons
        }

        return SignalModel(
            date=date_now,
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            confidence=round(confidence, 2),
            reason="; ".join(reasons),
            details=details
        )