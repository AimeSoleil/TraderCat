from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
import pandas as pd

class HiddenDivergenceStrategy(TradingStrategy):
    def __init__(
        self,
        data_provider,
        ema_period=50,
        swing_window=5,
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        kdj_fast_k_period=14,
        kdj_slow_d_period=3,
        kdj_slow_k_period=3,
        confirmation_threshold=0.6
    ):
        self.provider = data_provider
        self.ema_period = ema_period
        self.swing_window = swing_window
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.kdj_fast_k_period = kdj_fast_k_period
        self.kdj_slow_d_period = kdj_slow_d_period
        self.kdj_slow_k_period = kdj_slow_k_period
        self.confirmation_threshold = confirmation_threshold

    def get_name(self) -> str:
        return "Hidden Divergence"

    def get_lookback_window(self) -> int:
        return 60

    def calculate_ema(self, prices, period):
        return pd.Series(prices).ewm(span=period, adjust=False).mean().tolist()

    def detect_swing_points(self, candles, window):
        swing_highs, swing_lows = [], []
        for i in range(window, len(candles) - window):
            if all(candles[i].high > candles[i - j].high and candles[i].high > candles[i + j].high for j in range(1, window + 1)):
                swing_highs.append(i)
            if all(candles[i].low < candles[i - j].low and candles[i].low < candles[i + j].low for j in range(1, window + 1)):
                swing_lows.append(i)
        return swing_highs, swing_lows

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f'Strategy[{self.get_name()}] generating signal for {symbol}...')
        signal = "hold"
        confidence = 0.0
        details = {}

        if not self.provider or len(candles) < self.get_lookback_window() + 1:
            return SignalModel(symbol, self.get_name(), signal, "Insufficient data or provider not set.", details, confidence)

        closing_prices = [bar.close for bar in candles]
        ema_values = self.calculate_ema(closing_prices, self.ema_period)
        current_price = candles[-1].close
        current_ema = ema_values[-1]
        trend = "uptrend" if current_price > current_ema else "downtrend"

        swing_highs, swing_lows = self.detect_swing_points(candles, self.swing_window)
        last_swing_index = swing_lows[-1] if trend == "uptrend" and swing_lows else (
            swing_highs[-1] if trend == "downtrend" and swing_highs else None
        )

        if last_swing_index is None or last_swing_index >= len(candles) - 1:
            return SignalModel(symbol, self.get_name(), signal, "No valid swing point for divergence comparison.", details, confidence)

        # Fetch indicators
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

        if not rsi or not macd or not kdj:
            return SignalModel(symbol, self.get_name(), signal, "Indicator data unavailable.", details, confidence)

        try:
            swing_price = candles[last_swing_index].close
            current_rsi = rsi[-1].close_RSI_14
            swing_rsi = rsi[last_swing_index].close_RSI_14
            current_macd = macd[-1].close_MACD_12_26_9
            swing_macd = macd[last_swing_index].close_MACD_12_26_9
            current_kdj_k = kdj[-1].STOCHk_14_3_3
            current_kdj_d = kdj[-1].STOCHd_14_3_3
            swing_kdj_k = kdj[last_swing_index].STOCHk_14_3_3
            swing_kdj_d = kdj[last_swing_index].STOCHd_14_3_3
            current_kdj_j = 3 * current_kdj_k - 2 * current_kdj_d
            swing_kdj_j = 3 * swing_kdj_k - 2 * swing_kdj_d
        except (IndexError, AttributeError, TypeError):
            return SignalModel(symbol, self.get_name(), signal, "Indicator values missing or malformed.", details, confidence)

        # Scoring system to evaluate
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)
        if trend == "downtrend" and current_price < swing_price:
            scorer.add(True, "Hidden bearish divergence: Price forming lower high vs swing")
            scorer.add(current_rsi > swing_rsi, "RSI makes higher high")
            scorer.add(current_macd > swing_macd, "MACD makes higher high")
            scorer.add(current_kdj_j > swing_kdj_j, "KDJ J makes higher high")
            signal, confidence, reasons = scorer.evaluate(direction="bearish")

        elif trend == "uptrend" and current_price > swing_price:
            scorer.add(True, "Hidden bullish divergence: Price forming higher low vs swing")
            scorer.add(current_rsi < swing_rsi, "RSI makes lower low")
            scorer.add(current_macd < swing_macd, "MACD makes lower low")
            scorer.add(current_kdj_j < swing_kdj_j, "KDJ J makes lower low")
            signal, confidence, reasons = scorer.evaluate(direction="bullish")

        else:
            signal, confidence, reasons = "hold", 0.0, ["No strong signal"]

        details = {
            "trend": trend,
            "current_price": current_price,
            "current_ema": current_ema,
            "swing_price": swing_price,
            "current_rsi": current_rsi,
            "swing_rsi": swing_rsi,
            "current_macd": current_macd,
            "swing_macd": swing_macd,
            "current_kdj_j": current_kdj_j,
            "swing_kdj_j": swing_kdj_j,
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