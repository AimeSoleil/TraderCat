from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

class BollingerBandStrategy(TradingStrategy):
    def __init__(
        self,
        data_provider,
        bb_period=20,
        bb_std=2,
        rsi_period=14,
        rsi_overbought=70,
        rsi_oversold=30,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        kdj_fast_k_period=14,
        kdj_slow_d_period=3,
        kdj_slow_k_period=3,
        kdj_upper=80,
        kdj_lower=20,
        volume_window=5,
        volume_spike_ratio=1.2,
        confirmation_threshold=0.6
    ):
        self.provider = data_provider
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.kdj_fast_k_period = kdj_fast_k_period
        self.kdj_slow_d_period = kdj_slow_d_period
        self.kdj_slow_k_period = kdj_slow_k_period
        self.kdj_upper = kdj_upper
        self.kdj_lower = kdj_lower
        self.volume_window = volume_window
        self.volume_spike_ratio = volume_spike_ratio
        self.confirmation_threshold = confirmation_threshold

    def get_name(self) -> str:
        return "Bollinger Bands"

    def get_lookback_window(self) -> int:
        return max(40, self.bb_period + self.volume_window)

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f'Strategy[{self.get_name()}] generating signal for {symbol}...')
        signal = "hold"
        confidence = 0.0
        details = {}

        if not self.provider or len(candles) < self.get_lookback_window():
            return SignalModel(symbol, self.get_name(), signal, "Insufficient data or provider not set.", details, confidence)

        # Fetch indicators
        bb = self.provider.get_indicator("bbands", candles, {"length": self.bb_period, "std": self.bb_std})
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd = self.provider.get_indicator("macd", candles, {
            "fast": self.macd_fast, "slow": self.macd_slow, "signal": self.macd_signal
        })
        kdj = self.provider.get_indicator("stoch", candles, {
            "fast_k_period": self.kdj_fast_k_period,
            "slow_d_period": self.kdj_slow_d_period,
            "slow_k_period": self.kdj_slow_k_period
        })

        if not all([bb, rsi, macd, kdj]):
            return SignalModel(symbol, self.get_name(), signal, "Indicator data unavailable.", details, confidence)

        # Extract latest values
        current = candles[-1]
        previous = candles[-2]
        current_close = current.close
        current_volume = current.volume

        bb_last = bb[-1]
        bb_upper = getattr(bb_last, f'close_BBU_{self.bb_period}_{self.bb_std}', None)
        bb_lower = getattr(bb_last, f'close_BBL_{self.bb_period}_{self.bb_std}', None)

        current_rsi = rsi[-1].close_RSI_14
        previous_macd = macd[-2].close_MACD_12_26_9
        current_macd = macd[-1].close_MACD_12_26_9
        previous_macd_signal = macd[-2].close_MACDs_12_26_9
        current_macd_signal = macd[-1].close_MACDs_12_26_9

        previous_kdj_k = kdj[-2].STOCHk_14_3_3
        previous_kdj_d = kdj[-2].STOCHd_14_3_3
        current_kdj_k = kdj[-1].STOCHk_14_3_3
        current_kdj_d = kdj[-1].STOCHd_14_3_3

        # Volume spike detection
        volumes = [c.volume for c in candles[-self.volume_window - 1:]]
        avg_vol = sum(volumes[:-1]) / self.volume_window
        vol_spike = current_volume > avg_vol * self.volume_spike_ratio

        # Scoring system to evaluate
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)
        # Bullish setup
        if bb_lower and current_close < bb_lower:
            scorer.add(current_close < bb_lower, "Bullish: Price below lower Bollinger Band")
            scorer.add(current_rsi < self.rsi_oversold, "RSI oversold")
            scorer.add(previous_macd <= previous_macd_signal and current_macd > current_macd_signal, "MACD bullish crossover")
            scorer.add(previous_kdj_k <= previous_kdj_d and current_kdj_k > current_kdj_d and current_kdj_k < self.kdj_lower, "KDJ bullish crossover in oversold zone")
            scorer.add(vol_spike, "Volume spike")
            signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Bearish setup
        elif bb_upper and current_close > bb_upper:
            scorer.add(current_close > bb_upper, "Bearish: Price above upper Bollinger Band")
            scorer.add(current_rsi > self.rsi_overbought, "RSI overbought")
            scorer.add(previous_macd >= previous_macd_signal and current_macd < current_macd_signal, "MACD bearish crossover")
            scorer.add(previous_kdj_k >= previous_kdj_d and current_kdj_k < current_kdj_d and current_kdj_k > self.kdj_upper, "KDJ bearish crossover in overbought zone")
            scorer.add(vol_spike, "Volume spike")
            signal, confidence, reasons = scorer.evaluate(direction="bearish")

        else:
            signal, confidence, reasons = "hold", 0.0, ["No strong signal"]

        details = {
            "current_close": current_close,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "current_rsi": current_rsi,
            "current_macd": current_macd,
            "current_macd_signal": current_macd_signal,
            "current_kdj_k": current_kdj_k,
            "current_kdj_d": current_kdj_d,
            "current_volume": current_volume,
            "avg_volume": avg_vol,
            "confidence": confidence
        }

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            confidence=confidence,
            reason="; ".join(reasons),
            details=details
        )