from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

# How this maps to weekly option trades (practical notes)
# Breakout-style divergence with bandwidth/ATR expansion → buy directionally (calls/puts); prefer debit spreads to control theta.
# Divergence with re-entry near band and no bandwidth expansion → consider credit spreads (fading extremes).
# Use max 1–2 concurrent weekly trades; risk 0.5–1% capital per trade.
# Quick sensitivity tuning: lower confirmation_threshold to 0.5 and raise rsi weight to 0.30 for faster triggers; raise structure to 0.5 to reduce false positives.
class DivergenceStrategy(TradingStrategy):
    """
    Simplified divergence strategy tuned for weekly option trading.
    Uses Bollinger band context, RSI divergence, ATR and volume filters.
    Keeps SignalScorer unchanged; weights defined here in strategy.
    """

    def __init__(
        self,
        data_provider,
        bb_period=10,
        bb_std=2.0,
        rsi_period=7,
        atr_period=14,
        swing_window=5,
        bw_median_window=20,
        volume_ratio_threshold=1.2,
        confirmation_threshold=0.55,
        weights=None
    ):
        self.provider = data_provider
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.swing_window = swing_window
        self.bw_median_window = bw_median_window
        self.volume_ratio_threshold = volume_ratio_threshold
        self.confirmation_threshold = confirmation_threshold

        # Strategy-defined default weights (override via constructor)
        self.weights = weights or {
            "structure": 0.40,     # price swing structure (primary)
            "rsi": 0.25,           # RSI divergence / extreme
            "momentum_mag": 0.10,  # magnitude or bandwidth/ATR partial credit
            "volume": 0.15,        # volume confirmation
            "adx": 0.05,           # optional ADX confirmation (small)
            "macd": 0.05           # optional MACD confirmation (small)
        }

    def get_name(self) -> str:
        return "Divergence"

    def get_lookback_window(self) -> int:
        # ensure enough history for swings + bw median + indicators
        return max(60, self.swing_window + self.bw_median_window + self.atr_period)

    def find_recent_swing(self, candles, direction="low"):
        n = len(candles)
        # search backward for a clear swing (must have swing_window bars on each side)
        for i in range(n - self.swing_window - 1, self.swing_window, -1):
            if direction == "low":
                left_ok = all(candles[i].low < candles[i - j].low for j in range(1, self.swing_window))
                right_ok = all(candles[i].low < candles[i + j].low for j in range(1, self.swing_window))
                if left_ok and right_ok:
                    return i
            else:
                left_ok = all(candles[i].high > candles[i - j].high for j in range(1, self.swing_window))
                right_ok = all(candles[i].high > candles[i + j].high for j in range(1, self.swing_window))
                if left_ok and right_ok:
                    return i
        return None

    def _safe_get(self, series, idx, attr, default=None):
        try:
            return getattr(series[idx], attr)
        except Exception:
            return default

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f"Strategy[{self.get_name()}] generating signal for {symbol}...")
        signal, confidence, details = "hold", 0.0, {}
        current_close_date = candles[-1].date if candles else None

        if not self.provider or len(candles) < self.get_lookback_window() + 1:
            return SignalModel(date=current_close_date, symbol=symbol, strategy=self.get_name(),
                            signal=signal, confidence=confidence,
                            reason="Insufficient data or provider not set.", details=details)

        # Required indicators
        bb = self.provider.get_indicator("bbands", candles, {"length": self.bb_period, "std": self.bb_std})
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})

        if not all([bb, rsi, atr]) or len(bb) < self.bw_median_window + 2:
            return SignalModel(date=current_close_date, symbol=symbol, strategy=self.get_name(),
                            signal=signal, confidence=confidence,
                            reason="Indicator data unavailable or too short.", details=details)

        cur = candles[-1]
        prev = candles[-2]
        close = cur.close
        volume = cur.volume

        # BB fields
        bb_last = bb[-1]
        ma = self._safe_get(bb, -1, f'close_BBM_{self.bb_period}_{self.bb_std}')
        bbu = self._safe_get(bb, -1, f'close_BBU_{self.bb_period}_{self.bb_std}')
        bbl = self._safe_get(bb, -1, f'close_BBL_{self.bb_period}_{self.bb_std}')
        if not all([ma, bbu, bbl]):
            return SignalModel(date=current_close_date, symbol=symbol, strategy=self.get_name(),
                            signal=signal, confidence=confidence,
                            reason="BB fields missing", details=details)

        # Derived metrics
        band_width = (bbu - bbl) if (bbu is not None and bbl is not None) else 0.0
        pct_b = (close - bbl) / band_width if band_width > 0 else 0.5
        bw = (band_width / ma) if ma else 0.0

        # bandwidth median reference
        recent_bb = bb[-self.bw_median_window:]
        recent_bw = []
        for x in recent_bb:
            up = self._safe_get(recent_bb, recent_bb.index(x), f'close_BBU_{self.bb_period}_{self.bb_std}', 0)
            lo = self._safe_get(recent_bb, recent_bb.index(x), f'close_BBL_{self.bb_period}_{self.bb_std}', 0)
            mm = self._safe_get(recent_bb, recent_bb.index(x), f'close_BBM_{self.bb_period}_{self.bb_std}', 0)
            recent_bw.append(((up - lo) / mm) if mm else 0)
        bw_median = sorted(recent_bw)[len(recent_bw)//2] if recent_bw else 0.0

        # ATR median
        atr_vals = [self._safe_get(atr, i, f'ATRr_{self.atr_period}', 0) for i in range(-self.bw_median_window, 0, 1)]
        atr_median = sorted(atr_vals)[len(atr_vals)//2] if atr_vals else 0.0
        cur_atr = self._safe_get(atr, -1, f'ATRr_{self.atr_period}', None)

        # swings
        swing_low_idx = self.find_recent_swing(candles, "low")
        swing_high_idx = self.find_recent_swing(candles, "high")

        if swing_low_idx is None and swing_high_idx is None:
            return SignalModel(date=current_close_date, symbol=symbol, strategy=self.get_name(),
                            signal="hold", confidence=0.0,
                            reason="No swing points found", details=details)

        outcomes = []

        # Evaluate bullish divergence (price higher-low vs RSI lower-low)
        if swing_low_idx is not None:
            sl_price = candles[swing_low_idx].close
            sl_vol = candles[swing_low_idx].volume
            sl_rsi = self._safe_get(rsi, swing_low_idx, f'close_RSI_{self.rsi_period}', None)
            cur_rsi = self._safe_get(rsi, -1, f'close_RSI_{self.rsi_period}', None)

            # Basic divergence condition
            price_higher_low = close > sl_price
            rsi_lower_low = (cur_rsi is not None and sl_rsi is not None and cur_rsi < sl_rsi)

            scorer = SignalScorer(threshold_percent=self.confirmation_threshold)
            # Primary structure
            scorer.add(price_higher_low, "Structure: price higher low vs swing", weight=self.weights["structure"])
            # RSI divergence (prefer also being relatively low)
            scorer.add(rsi_lower_low and (cur_rsi is not None and cur_rsi < 50), "RSI lower low (divergence)", weight=self.weights["rsi"])
            # Vol catalyst vs swing
            scorer.add(volume > sl_vol * self.volume_ratio_threshold, "Volume spike vs swing low", weight=self.weights["volume"])
            # Band & ATR context: favor setups where ATR or BW expands (sensitivity to weekly volatility)
            scorer.add(bw > bw_median, "Bandwidth expansion", weight=self.weights["momentum_mag"])
            scorer.add(cur_atr is not None and cur_atr > atr_median, "ATR above median (range confirms)", weight=self.weights["momentum_mag"])
            # Optional small MACD/ADX checks if available (provider-dependent)
            # scorer.add(macd_condition, "MACD confirmation", weight=self.weights["macd"])
            # scorer.add(adx_condition, "ADX confirms trend", weight=self.weights["adx"])

            sig, conf, reasons = scorer.evaluate(direction="bullish")
            outcomes.append(("buy", sig, conf, reasons))

        # Evaluate bearish divergence (price lower-high vs RSI higher-high)
        if swing_high_idx is not None:
            sh_price = candles[swing_high_idx].close
            sh_vol = candles[swing_high_idx].volume
            sh_rsi = self._safe_get(rsi, swing_high_idx, f'close_RSI_{self.rsi_period}', None)
            cur_rsi = self._safe_get(rsi, -1, f'close_RSI_{self.rsi_period}', None)

            price_lower_high = close < sh_price
            rsi_higher_high = (cur_rsi is not None and sh_rsi is not None and cur_rsi > sh_rsi)

            scorer_b = SignalScorer(threshold_percent=self.confirmation_threshold)
            scorer_b.add(price_lower_high, "Structure: price lower high vs swing", weight=self.weights["structure"])
            scorer_b.add(rsi_higher_high and (cur_rsi is not None and cur_rsi > 50), "RSI higher high (divergence)", weight=self.weights["rsi"])
            scorer_b.add(volume > sh_vol * self.volume_ratio_threshold, "Volume spike vs swing high", weight=self.weights["volume"])
            scorer_b.add(bw > bw_median, "Bandwidth expansion", weight=self.weights["momentum_mag"])
            scorer_b.add(cur_atr is not None and cur_atr > atr_median, "ATR above median (range confirms)", weight=self.weights["momentum_mag"])

            sig_b, conf_b, reasons_b = scorer_b.evaluate(direction="bearish")
            outcomes.append(("sell", sig_b, conf_b, reasons_b))

        # Choose best outcome by highest confidence and non-hold
        chosen = ("hold", 0.0, ["No strong signal"])
        for tag, sig, conf, rs in outcomes:
            if sig != "hold" and conf > chosen[1]:
                chosen = (sig, conf, rs)

        signal, confidence, reasons = chosen[0], round(chosen[1], 2), chosen[2]

        details = {
            "close": close,
            "bbu": bbu,
            "bbl": bbl,
            "pct_b": pct_b,
            "bw": bw,
            "bw_median": bw_median,
            "atr": cur_atr,
            "atr_median": atr_median,
            "swing_low_idx": swing_low_idx,
            "swing_high_idx": swing_high_idx,
            "volume": volume,
            "confidence": confidence
        }

        return SignalModel(
            date=current_close_date,
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            confidence=confidence,
            reason="; ".join(reasons),
            details=details
        )