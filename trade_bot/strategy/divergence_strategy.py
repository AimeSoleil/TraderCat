from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

class DivergenceStrategy(TradingStrategy):
    def __init__(
        self,
        data_provider,
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        kdj_fast_k_period=14,
        kdj_slow_d_period=3,
        kdj_slow_k_period=3,
        rsi_overbought=70,
        rsi_oversold=30,
        kdj_upper=80,
        kdj_lower=20,
        swing_window=5,
        volume_ratio_threshold=1.2,
        confirmation_threshold=0.6
    ):
        self.provider = data_provider
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.kdj_fast_k_period = kdj_fast_k_period
        self.kdj_slow_d_period = kdj_slow_d_period
        self.kdj_slow_k_period = kdj_slow_k_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.kdj_upper = kdj_upper
        self.kdj_lower = kdj_lower
        self.swing_window = swing_window
        self.volume_ratio_threshold = volume_ratio_threshold
        self.confirmation_threshold = confirmation_threshold

    def get_name(self) -> str:
        return "Divergence"

    def get_lookback_window(self) -> int:
        return 40

    def find_recent_swing(self, candles, direction="low"):
        for i in range(len(candles) - self.swing_window - 1, 0, -1):
            if direction == "low":
                if all(candles[i].low < candles[i - j].low and candles[i].low < candles[i + j].low for j in range(1, self.swing_window)):
                    return i
            else:
                if all(candles[i].high > candles[i - j].high and candles[i].high > candles[i + j].high for j in range(1, self.swing_window)):
                    return i
        return None

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f'Strategy[{self.get_name()}] generating signal for {symbol}...')
        signal = "hold"
        confidence = 0.0
        details = {}

        if not self.provider or len(candles) < self.get_lookback_window() + 1:
            return SignalModel(symbol, self.get_name(), signal, "Insufficient data or provider not set.", details, confidence)

        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd = self.provider.get_indicator("macd", candles, {
            "fast": self.macd_fast,
            "slow": self.macd_slow,
            "signal": self.macd_signal
        })
        kdj = self.provider.get_indicator("stoch", candles, {
            "fast_k_period": self.kdj_fast_k_period,
            "slow_d_period": self.kdj_slow_d_period,
            "slow_k_period": self.kdj_slow_k_period
        })

        if not rsi or not macd or not kdj or len(rsi) < 2 or len(macd) < 2 or len(kdj) < 2:
            return SignalModel(symbol, self.get_name(), signal, "Indicator data too short or unavailable.", details, confidence)

        current_close = candles[-1].close
        current_volume = candles[-1].volume

        swing_low_idx = self.find_recent_swing(candles, "low")
        swing_high_idx = self.find_recent_swing(candles, "high")

        if swing_low_idx is None or swing_high_idx is None:
            return SignalModel(symbol, self.get_name(), signal, "No valid swing points found.", details, confidence)

        swing_low_price = candles[swing_low_idx].close
        swing_high_price = candles[swing_high_idx].close
        swing_low_volume = candles[swing_low_idx].volume
        swing_high_volume = candles[swing_high_idx].volume

        swing_rsi_low = rsi[swing_low_idx].close_RSI_14
        swing_rsi_high = rsi[swing_high_idx].close_RSI_14
        current_rsi = rsi[-1].close_RSI_14

        swing_macd = macd[swing_low_idx].close_MACD_12_26_9
        current_macd = macd[-1].close_MACD_12_26_9
        swing_macd_signal = macd[swing_low_idx].close_MACDs_12_26_9
        current_macd_signal = macd[-1].close_MACDs_12_26_9

        swing_kdj_k = kdj[swing_low_idx].STOCHk_14_3_3
        swing_kdj_d = kdj[swing_low_idx].STOCHd_14_3_3
        current_kdj_k = kdj[-1].STOCHk_14_3_3
        current_kdj_d = kdj[-1].STOCHd_14_3_3

        # Scoring system to evaluate
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)
        # Bullish divergence: price higher low, indicator lower low
        if current_close > swing_low_price:
            scorer.add(True, "Bullish: Price forming higher low vs swing")
            scorer.add(current_rsi < swing_rsi_low and current_rsi < self.rsi_oversold, "RSI divergence")
            scorer.add(current_macd > current_macd_signal and current_macd < swing_macd, "MACD crossover divergence")
            scorer.add(current_kdj_k > current_kdj_d and current_kdj_k < swing_kdj_k, "KDJ crossover divergence")
            scorer.add(current_volume > swing_low_volume * self.volume_ratio_threshold, "Volume spike")
            signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Bearish divergence: price lower high, indicator higher high
        elif current_close < swing_high_price:
            scorer.add(True, "Bearish: BPrice forming lower high vs swing")
            scorer.add(current_rsi > swing_rsi_high and current_rsi > self.rsi_overbought, "RSI divergence")
            scorer.add(current_macd < current_macd_signal and current_macd > swing_macd, "MACD crossover divergence")
            scorer.add(current_kdj_k < current_kdj_d and current_kdj_k > swing_kdj_k, "KDJ crossover divergence")
            scorer.add(current_volume > swing_high_volume * self.volume_ratio_threshold, "Volume spike")
            signal, confidence, reasons = scorer.evaluate(direction="bearish")

        else:
            signal, confidence, reasons = "hold", 0.0, ["No strong signal"]

        details = {
            "current_close": current_close,
            "swing_low_price": swing_low_price,
            "swing_high_price": swing_high_price,
            "current_volume": current_volume,
            "swing_low_volume": swing_low_volume,
            "swing_high_volume": swing_high_volume,
            "current_rsi": current_rsi,
            "swing_rsi_low": swing_rsi_low,
            "swing_rsi_high": swing_rsi_high,
            "current_macd": current_macd,
            "swing_macd": swing_macd,
            "current_macd_signal": current_macd_signal,
            "swing_macd_signal": swing_macd_signal,
            "current_kdj_k": current_kdj_k,
            "current_kdj_d": current_kdj_d,
            "swing_kdj_k": swing_kdj_k,
            "swing_kdj_d": swing_kdj_d,
            "confidence": confidence
        }

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            reason="; ".join(reasons),
            details=details,
            confidence=confidence
        )