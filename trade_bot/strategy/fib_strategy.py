from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

class FibonacciStrategy(TradingStrategy):
    def __init__(
        self,
        data_provider,
        rsi_period=14,
        rsi_midline=50,
        rsi_overbought=70,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        volume_window=5,
        volume_spike_ratio=1.2,
        confirmation_threshold=0.6
    ):
        self.provider = data_provider
        self.rsi_period = rsi_period
        self.rsi_midline = rsi_midline
        self.rsi_overbought = rsi_overbought
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.volume_window = volume_window
        self.volume_spike_ratio = volume_spike_ratio
        self.confirmation_threshold = confirmation_threshold

    def get_name(self) -> str:
        return "Fibonacci Retracement"

    def get_lookback_window(self) -> int:
        return 60

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f'Strategy[{self.get_name()}] generating signal for {symbol}...')
        signal = "hold"
        details = {}

        if not self.provider or len(candles) < self.get_lookback_window():
            return SignalModel(symbol, self.get_name(), signal, "Insufficient data or provider not set.", details)

        recent = candles[-self.get_lookback_window():]
        swing_high = max(c.high for c in recent)
        swing_low = min(c.low for c in recent)
        current_price = candles[-1].close
        current_volume = candles[-1].volume

        # Fibonacci levels
        diff = swing_high - swing_low
        fib_levels = {
            '23.6%': swing_high - 0.236 * diff,
            '38.2%': swing_high - 0.382 * diff,
            '50.0%': swing_high - 0.500 * diff,
            '61.8%': swing_high - 0.618 * diff,
            '78.6%': swing_high - 0.786 * diff
        }

        # Indicators
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd = self.provider.get_indicator("macd", candles, {
            "fast": self.macd_fast, "slow": self.macd_slow, "signal": self.macd_signal
        })

        if not rsi or not macd or len(macd) < 2:
            return SignalModel(symbol, self.get_name(), signal, "Indicator data unavailable or too short.", details)

        curr_rsi = rsi[-1].close_RSI_14
        prev_macd = macd[-2]
        curr_macd = macd[-1]
        macd_bullish = prev_macd.close_MACD_12_26_9 <= prev_macd.close_MACDs_12_26_9 and curr_macd.close_MACD_12_26_9 > curr_macd.close_MACDs_12_26_9
        macd_bearish = prev_macd.close_MACD_12_26_9 >= prev_macd.close_MACDs_12_26_9 and curr_macd.close_MACD_12_26_9 < curr_macd.close_MACDs_12_26_9

        # Volume spike
        volumes = [c.volume for c in candles[-self.volume_window - 1:]]
        avg_vol = sum(volumes[:-1]) / self.volume_window
        vol_spike = current_volume > avg_vol * self.volume_spike_ratio

        # Scoring system to evaluate
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)
        # Bullish setup
        if fib_levels['61.8%'] < current_price < fib_levels['50.0%']:
            scorer.add(True, "Price in bullish retracement zone (61.8%–50%)")
            scorer.add(curr_rsi > self.rsi_midline, "RSI above midline")
            scorer.add(macd_bullish, "MACD bullish crossover")
            scorer.add(vol_spike, "Volume spike")
            signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Bearish setup
        elif current_price < fib_levels['78.6%']:
            scorer.add(True, "Price broke below 78.6% (bearish continuation)")
            scorer.add(curr_rsi > self.rsi_overbought, "RSI overbought")
            scorer.add(macd_bearish, "MACD bearish crossover")
            scorer.add(vol_spike, "Volume spike")
            signal, confidence, reasons = scorer.evaluate(direction="bearish")

        else:
            signal, confidence, reasons = "hold", 0, ["No strong signal"]

        details = {
            "swing_high": swing_high,
            "swing_low": swing_low,
            "fib_levels": fib_levels,
            "current_price": current_price,
            "current_rsi": curr_rsi,
            "current_volume": current_volume,
            "avg_volume": avg_vol,
            "macd_bullish": macd_bullish,
            "macd_bearish": macd_bearish,
            "macd_value": curr_macd.close_MACD_12_26_9,
            "macd_signal": curr_macd.close_MACDs_12_26_9,
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