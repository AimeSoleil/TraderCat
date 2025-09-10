from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.signal_model import SignalModel
from statistics import mean

class HiddenDivergenceStrategy(TradingStrategy):
    def __init__(
        self,
        ema_period=50,
        swing_window=1,
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        kdj_fast_k_period=14,
        kdj_slow_d_period=3,
        kdj_slow_k_period=3
    ):
        self.provider = OpenBBProvider()
        self.ema_period = ema_period
        self.swing_window = swing_window
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.kdj_fast_k_period = kdj_fast_k_period
        self.kdj_slow_d_period = kdj_slow_d_period
        self.kdj_slow_k_period = kdj_slow_k_period

    def get_name(self) -> str:
        return "Hidden Divergence"

    def calculate_ema(self, prices, period):
        ema = []
        multiplier = 2 / (period + 1)
        for i in range(len(prices)):
            if i < period - 1:
                ema.append(None)
            elif i == period - 1:
                sma = mean(prices[:period])
                ema.append(sma)
            else:
                ema.append((prices[i] - ema[-1]) * multiplier + ema[-1])
        return ema

    def detect_swing_points(self, data, window):
        swing_highs = []
        swing_lows = []
        for i in range(window, len(data) - window):
            if all(data[i].high > data[i - j].high and data[i].high > data[i + j].high for j in range(1, window + 1)):
                swing_highs.append(i)
            if all(data[i].low < data[i - j].low and data[i].low < data[i + j].low for j in range(1, window + 1)):
                swing_lows.append(i)
        return swing_highs, swing_lows

    def generate_signal(self, data: dict) -> SignalModel:
        details = {}
        signal = "hold"
        reasons = []

        if len(data) < max(self.ema_period, 3):
            details["reason"] = "Insufficient data for swing point and trend analysis"
            return SignalModel(strategy=self.get_name(), signal=signal, details=details)

        # Indicators
        rsi = self.provider.get_indicator("rsi", data, {"length": self.rsi_period})
        macd = self.provider.get_indicator("macd", data, {
            "fast": self.macd_fast,
            "slow": self.macd_slow,
            "signal": self.macd_signal
        })
        kdj = self.provider.get_indicator("stoch", data, {
            "fast_k_period": self.kdj_fast_k_period,
            "slow_d_period": self.kdj_slow_d_period,
            "slow_k_period": self.kdj_slow_k_period
        })

        closing_prices = [bar.close for bar in data]
        ema_values = self.calculate_ema(closing_prices, self.ema_period)
        current_price = data[-1].close
        current_ema = ema_values[-1]

        # Determine trend
        trend = "uptrend" if current_price > current_ema else "downtrend"

        # Detect swing points
        swing_highs, swing_lows = self.detect_swing_points(data, self.swing_window)

        # Use most recent swing point
        last_swing_index = None
        if trend == "uptrend" and swing_lows:
            last_swing_index = swing_lows[-1]
        elif trend == "downtrend" and swing_highs:
            last_swing_index = swing_highs[-1]

        if last_swing_index is None or last_swing_index >= len(data) - 1:
            details["reason"] = "No valid swing point for divergence comparison"
            return SignalModel(strategy=self.get_name(), signal=signal, details=details)

        # Compare price and indicators at swing point vs current
        swing_price = data[last_swing_index].close
        current_rsi = rsi[-1].close_RSI_14 if rsi else None
        swing_rsi = rsi[last_swing_index].close_RSI_14 if rsi else None

        current_macd = macd[-1].close_MACD_12_26_9 if macd else None
        swing_macd = macd[last_swing_index].close_MACD_12_26_9 if macd else None

        current_kdj_k = kdj[-1].STOCHk_14_3_3 if kdj else None
        current_kdj_d = kdj[-1].STOCHd_14_3_3 if kdj else None
        current_kdj_j = 3 * current_kdj_k - 2 * current_kdj_d if current_kdj_k and current_kdj_d else None

        swing_kdj_k = kdj[last_swing_index].STOCHk_14_3_3 if kdj else None
        swing_kdj_d = kdj[last_swing_index].STOCHd_14_3_3 if kdj else None
        swing_kdj_j = 3 * swing_kdj_k - 2 * swing_kdj_d if swing_kdj_k and swing_kdj_d else None

        # Hidden divergence logic
        if trend == "uptrend" and current_price > swing_price:
            if current_rsi < swing_rsi:
                reasons.append("Hidden bearish divergence: Price higher, RSI lower")
            if current_macd < swing_macd:
                reasons.append("Hidden bearish divergence: Price higher, MACD lower")
            if current_kdj_j < swing_kdj_j:
                reasons.append("Hidden bearish divergence: Price higher, KDJ J lower")
            if len(reasons) >= 2:
                signal = "sell"

        elif trend == "downtrend" and current_price < swing_price:
            if current_rsi > swing_rsi:
                reasons.append("Hidden bullish divergence: Price lower, RSI higher")
            if current_macd > swing_macd:
                reasons.append("Hidden bullish divergence: Price lower, MACD higher")
            if current_kdj_j > swing_kdj_j:
                reasons.append("Hidden bullish divergence: Price lower, KDJ J higher")
            if len(reasons) >= 2:
                signal = "buy"

        details["reason"] = "; ".join(reasons) if reasons else "No hidden divergence detected"

        return SignalModel(
            strategy=self.get_name(),
            signal=signal,
            details=details
        )