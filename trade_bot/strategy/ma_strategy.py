from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

# Tuning guidance (one-line rules)
# More sensitive: ema_fast -> 5, sma_slow -> 13, confirmation_threshold -> 0.50, bb_period -> 8.
# Less noisy: ema_fast -> 10, sma_slow -> 34, confirmation_threshold -> 0.60, require atr_expanding True in addition to crossover.
# Options mapping: crossover + ATR expansion + volume spike → buy debit spreads (directional); crossover without ATR expansion but near band → consider credit spreads or wait.
class MAStrategy(TradingStrategy):
    """
    Simplified, weekly-sensitive MA strategy using EMA/SMA crossover + Bollinger context + ATR.
    Uses the existing SignalScorer unchanged; strategy supplies weights.
    """

    def __init__(
        self,
        data_provider,
        ema_fast=8,
        sma_slow=21,
        bb_period=10,
        bb_std=2.0,
        rsi_period=7,
        atr_period=14,
        volume_window=5,
        volume_spike_ratio=1.2,
        confirmation_threshold=0.55,
        weights=None
    ):
        self.provider = data_provider
        self.ema_fast = ema_fast
        self.sma_slow = sma_slow
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.volume_window = volume_window
        self.volume_spike_ratio = volume_spike_ratio
        self.confirmation_threshold = confirmation_threshold

        # Strategy-defined weights (tunable). MACD/KDJ intentionally low.
        self.weights = weights or {
            "structure": 0.45,   # EMA/SMA crossover primary
            "bb": 0.20,          # Bollinger context (price near band or breakout)
            "atr": 0.12,         # ATR expansion confirms move size
            "rsi": 0.10,         # RSI momentum / midline
            "volume": 0.06,      # volume catalyst
            "macd": 0.04,        # MACD low-weight confirmation
            "kdj": 0.03          # KDJ very low-weight confirmation
        }

    def get_name(self) -> str:
        return "MA (EMA/SMA)"

    def get_lookback_window(self) -> int:
        # ensure enough bars for EMA, SMA, BB, ATR, and volume window
        return max(60, self.sma_slow + self.bb_period + self.atr_period + self.volume_window)

    def _safe_get(self, series, idx, attr, default=None):
        try:
            return getattr(series[idx], attr)
        except Exception:
            return default

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f"Strategy[{self.get_name()}] generating signal for {symbol}...")
        
        current_date = candles[-1].date if candles else None
        if not self.provider or len(candles) < self.get_lookback_window() + 1:
            return SignalModel(date=current_date, symbol=symbol, strategy=self.get_name(),
                            signal="hold", confidence=0.0, reason="Insufficient data", details={})

        # Fetch indicators
        ema = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        sma = self.provider.get_indicator("sma", candles, {"length": self.sma_slow})
        bb = self.provider.get_indicator("bbands", candles, {"length": self.bb_period, "std": self.bb_std})
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})

        # Optional confirmations
        try:
            macd = self.provider.get_indicator("macd", candles, {"fast": 12, "slow": 26, "signal": 9})
        except Exception:
            macd = None
        try:
            kdj = self.provider.get_indicator("stoch", candles, {"fast_k_period": 14, "slow_d_period": 3, "slow_k_period": 3})
        except Exception:
            kdj = None

        # Basic availability checks
        if not all([ema, sma, bb, rsi, atr]) or len(ema) < 2 or len(sma) < 2:
            return SignalModel(date=current_date, symbol=symbol, strategy=self.get_name(),
                               signal="hold", confidence=0.0, reason="Indicator data unavailable", details={})

        cur = candles[-1]
        prev = candles[-2]
        close = cur.close
        volume = cur.volume

        # MA crossover (fast reaction)
        prev_ema = self._safe_get(ema, -2, f'close_EMA_{self.ema_fast}', None)
        curr_ema = self._safe_get(ema, -1, f'close_EMA_{self.ema_fast}', None)
        prev_sma = self._safe_get(sma, -2, f'close_SMA_{self.sma_slow}', None)
        curr_sma = self._safe_get(sma, -1, f'close_SMA_{self.sma_slow}', None)

        if None in (prev_ema, curr_ema, prev_sma, curr_sma):
            return SignalModel(date=current_date, symbol=symbol, strategy=self.get_name(),
                               signal="hold", confidence=0.0, reason="MA fields missing", details={})

        ema_cross_up = (prev_ema <= prev_sma and curr_ema > curr_sma)
        ema_cross_down = (prev_ema >= prev_sma and curr_ema < curr_sma)

        # Bollinger band context (short period)
        bbu = self._safe_get(bb, -1, f'close_BBU_{self.bb_period}_{self.bb_std}')
        bbl = self._safe_get(bb, -1, f'close_BBL_{self.bb_period}_{self.bb_std}')
        bb_mid = self._safe_get(bb, -1, f'close_BBM_{self.bb_period}_{self.bb_std}', None)

        near_upper_bb = (bbu is not None and close >= (bbu - (bbu - bb_mid) * 0.25)) if (bbu and bb_mid) else False
        near_lower_bb = (bbl is not None and close <= (bbl + (bb_mid - bbl) * 0.25)) if (bbl and bb_mid) else False
        breakout_upper = (bbu is not None and close > bbu)
        breakdown_lower = (bbl is not None and close < bbl)

        # ATR expansion check
        cur_atr = self._safe_get(atr, -1, f'ATRr_{self.atr_period}', None)
        atr_hist = [self._safe_get(atr, i, f'ATRr_{self.atr_period}', 0) for i in range(-self.bb_period - self.atr_period, 0)]
        atr_median = sorted(atr_hist)[len(atr_hist)//2] if atr_hist else 0.0
        atr_expanding = (cur_atr is not None and cur_atr > atr_median)

        # RSI
        curr_rsi = self._safe_get(rsi, -1, f'close_RSI_{self.rsi_period}', None)

        # Volume spike
        vols = [c.volume for c in candles[-self.volume_window - 1:]]
        avg_vol = (sum(vols[:-1]) / self.volume_window) if self.volume_window > 0 else volume
        vol_spike = volume > avg_vol * self.volume_spike_ratio

        # MACD & KDJ lightweight confirmations
        macd_confirm_up = macd_confirm_down = False
        if macd and len(macd) >= 2:
            prev_m = macd[-2]; cur_m = macd[-1]
            prev_val = self._safe_get(macd, -2, 'close_MACD_12_26_9', None)
            prev_sig = self._safe_get(macd, -2, 'close_MACDs_12_26_9', None)
            cur_val = self._safe_get(macd, -1, 'close_MACD_12_26_9', None)
            cur_sig = self._safe_get(macd, -1, 'close_MACDs_12_26_9', None)
            if None not in (prev_val, prev_sig, cur_val, cur_sig):
                macd_confirm_up = prev_val <= prev_sig and cur_val > cur_sig
                macd_confirm_down = prev_val >= prev_sig and cur_val < cur_sig

        kdj_up = kdj_down = False
        if kdj and len(kdj) >= 1:
            cur_k = self._safe_get(kdj, -1, 'STOCHk_14_3_3', None)
            cur_d = self._safe_get(kdj, -1, 'STOCHd_14_3_3', None)
            if cur_k is not None and cur_d is not None:
                kdj_up = cur_k > cur_d
                kdj_down = cur_k < cur_d

        # Scoring with your SignalScorer (weights from strategy)
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)

        # Bullish scenario: EMA crosses above SMA
        if ema_cross_up:
            scorer.add(True, "Structure: EMA crossed above SMA", weight=self.weights["structure"])
            scorer.add(breakout_upper or near_lower_bb or near_upper_bb, "BB context (breakout/near band)", weight=self.weights["bb"])
            scorer.add(curr_rsi is not None and curr_rsi > 50, "RSI > 50", weight=self.weights["rsi"])
            scorer.add(atr_expanding, "ATR expanding", weight=self.weights["atr"])
            scorer.add(vol_spike, "Volume spike", weight=self.weights["volume"])
            scorer.add(macd_confirm_up, "MACD confirms (low weight)", weight=self.weights["macd"])
            scorer.add(kdj_up, "KDJ cue (very low weight)", weight=self.weights["kdj"])
            signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Bearish scenario: EMA crosses below SMA
        elif ema_cross_down:
            scorer.add(True, "Structure: EMA crossed below SMA", weight=self.weights["structure"])
            scorer.add(breakdown_lower or near_upper_bb or near_lower_bb, "BB context (breakdown/near band)", weight=self.weights["bb"])
            scorer.add(curr_rsi is not None and curr_rsi < 50, "RSI < 50", weight=self.weights["rsi"])
            scorer.add(atr_expanding, "ATR expanding", weight=self.weights["atr"])
            scorer.add(vol_spike, "Volume spike", weight=self.weights["volume"])
            scorer.add(macd_confirm_down, "MACD confirms (low weight)", weight=self.weights["macd"])
            scorer.add(kdj_down, "KDJ cue (very low weight)", weight=self.weights["kdj"])
            signal, confidence, reasons = scorer.evaluate(direction="bearish")

        else:
            signal, confidence, reasons = "hold", 0.0, ["No strong MA crossover"]

        details = {
            "prev_ema": prev_ema, "curr_ema": curr_ema,
            "prev_sma": prev_sma, "curr_sma": curr_sma,
            "bb_upper": bbu, "bb_lower": bbl,
            "curr_rsi": curr_rsi,
            "atr": cur_atr, "atr_median": atr_median, "atr_expanding": atr_expanding,
            "volume": volume, "avg_vol": avg_vol,
            "macd_up": macd_confirm_up, "macd_down": macd_confirm_down,
            "kdj_up": kdj_up, "kdj_down": kdj_down,
            "confidence": confidence
        }

        return SignalModel(
            date=current_date,
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            confidence=round(confidence, 2),
            reason="; ".join(reasons),
            details=details
        )
