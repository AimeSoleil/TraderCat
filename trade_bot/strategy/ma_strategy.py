from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

class MAStrategy(TradingStrategy):
    def __init__(
        self,
        data_provider,
        ema_period=10,
        sma_period=20,
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        volume_window=5,
        volume_spike_ratio=1.2,
        confirmation_threshold=0.6
    ):
        self.provider = data_provider
        self.ema_period = ema_period
        self.sma_period = sma_period
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.volume_window = volume_window
        self.volume_spike_ratio = volume_spike_ratio
        self.confirmation_threshold = confirmation_threshold

    def get_name(self) -> str:
        return "Moving Average"

    def get_lookback_window(self) -> int:
        return 40

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f'Strategy[{self.get_name()}] generating signal for {symbol}...')
        signal = "hold"
        confidence = 0.0
        details = {}

        if not self.provider or len(candles) < self.get_lookback_window() + 1:
            return SignalModel(symbol, self.get_name(), signal, "Insufficient data or provider not set.", details, confidence)

        # Fetch indicators
        ema = self.provider.get_indicator("ema", candles, {"length": self.ema_period})
        sma = self.provider.get_indicator("sma", candles, {"length": self.sma_period})
        macd = self.provider.get_indicator("macd", candles, {
            "fast": self.macd_fast, "slow": self.macd_slow, "signal": self.macd_signal
        })
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        volumes = [c.volume for c in candles]

        if not ema or not sma or not macd or not rsi or len(ema) < 2 or len(sma) < 2 or len(macd) < 2:
            return SignalModel(symbol, self.get_name(), signal, "Indicator data unavailable or too short.", details, confidence)

        # Moving Average crossover detection
        prev_ema, curr_ema = ema[-2].close_EMA_10, ema[-1].close_EMA_10
        prev_sma, curr_sma = sma[-2].close_SMA_20, sma[-1].close_SMA_20
        ema_sma_bullish = prev_ema < prev_sma and curr_ema > curr_sma
        ema_sma_bearish = prev_ema > prev_sma and curr_ema < curr_sma

        # MACD crossover detection
        prev_macd = macd[-2]
        curr_macd = macd[-1]
        prev_macd_val = prev_macd.close_MACD_12_26_9
        prev_signal_val = prev_macd.close_MACDs_12_26_9
        curr_macd_val = curr_macd.close_MACD_12_26_9
        curr_signal_val = curr_macd.close_MACDs_12_26_9
        macd_bullish = prev_macd_val <= prev_signal_val and curr_macd_val > curr_signal_val
        macd_bearish = prev_macd_val >= prev_signal_val and curr_macd_val < curr_signal_val

        # RSI value
        curr_rsi = rsi[-1].close_RSI_14

        # Volume analysis
        avg_vol = sum(volumes[-self.volume_window-1:-1]) / self.volume_window
        curr_vol = volumes[-1]
        vol_spike = curr_vol > avg_vol * self.volume_spike_ratio

        # Scoring system to evaluate
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)
        # Bullish setup
        if ema_sma_bullish:
            scorer.add(True, "Bullish: EMA crosses above SMA")
            scorer.add(macd_bullish, "MACD bullish crossover")
            scorer.add(curr_rsi > 50, "RSI above 50")
            scorer.add(vol_spike, "Volume spike")
            signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Bearish setup
        elif ema_sma_bearish:
            scorer.add(True, "Bearish: EMA crosses below SMA")
            scorer.add(macd_bearish, "MACD bearish crossover")
            scorer.add(curr_rsi > 70, "RSI overbought")
            scorer.add(vol_spike, "Volume spike")
            signal, confidence, reasons = scorer.evaluate(direction="bearish")

        else:
            signal, confidence, reasons = "hold", 0.0, ["No strong signal"]

        details = {
            'prev_ema': prev_ema,
            'curr_ema': curr_ema,
            'prev_sma': prev_sma,
            'curr_sma': curr_sma,
            'prev_macd': prev_macd_val,
            'curr_macd': curr_macd_val,
            'prev_signal': prev_signal_val,
            'curr_signal': curr_signal_val,
            'curr_rsi': curr_rsi,
            'avg_volume': avg_vol,
            'curr_volume': curr_vol,
            'confidence': confidence
        }

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            reason="; ".join(reasons),
            details=details,
            confidence=confidence
        )