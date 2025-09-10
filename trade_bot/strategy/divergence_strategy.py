from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.signal_model import SignalModel

class DivergenceStrategy(TradingStrategy):
    def __init__(
        self,
        bb_period=20,
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        kdj_fast_k_period=14,
        kdj_slow_d_period=3,
        kdj_slow_k_period=3
    ):
        self.provider = OpenBBProvider()
        self.bb_period = bb_period
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.kdj_fast_k_period = kdj_fast_k_period
        self.kdj_slow_d_period = kdj_slow_d_period
        self.kdj_slow_k_period = kdj_slow_k_period

    def get_name(self) -> str:
        return "Divergence"

    def generate_signal(self, data: dict) -> SignalModel:
        details = {}
        signal = "hold"
        reasons = []

        if len(data) < 3:
            details["reason"] = "Insufficient data for divergence analysis"
            return SignalModel(strategy=self.get_name(), signal=signal, details=details)

        # Fetch indicators
        bb = self.provider.get_indicator("bbands", data, {"length": self.bb_period})
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

        # Extract recent price and indicator values
        previous_close = data[-2].close
        current_close = data[-1].close

        previous_rsi = rsi[-2].close_RSI_14 if rsi else None
        current_rsi = rsi[-1].close_RSI_14 if rsi else None

        previous_macd = macd[-2].close_MACD_12_26_9 if macd else None
        current_macd = macd[-1].close_MACD_12_26_9 if macd else None

        previous_kdj_k = kdj[-2].STOCHk_14_3_3 if kdj else None
        previous_kdj_d = kdj[-2].STOCHd_14_3_3 if kdj else None
        previous_kdj_j = 3 * previous_kdj_k - 2 * previous_kdj_d if previous_kdj_k is not None and previous_kdj_d is not None else None

        current_kdj_k = kdj[-1].STOCHk_14_3_3 if kdj else None
        current_kdj_d = kdj[-1].STOCHd_14_3_3 if kdj else None
        current_kdj_j = 3 * current_kdj_k - 2 * current_kdj_d if current_kdj_k is not None and current_kdj_d is not None else None

        # Detect bullish divergence
        if current_close < previous_close:
            if current_rsi > previous_rsi and current_rsi < 40:
                reasons.append("Bullish RSI divergence")
            if current_macd > previous_macd and current_macd < 0:
                reasons.append("Bullish MACD divergence")
            if current_kdj_j > previous_kdj_j and current_kdj_j < 20:
                reasons.append("Bullish KDJ divergence")

            if len(reasons) >= 2:
                signal = "buy"

        # Detect bearish divergence
        elif current_close > previous_close:
            if current_rsi < previous_rsi and current_rsi > 60:
                reasons.append("Bearish RSI divergence")
            if current_macd < previous_macd and current_macd > 0:
                reasons.append("Bearish MACD divergence")
            if current_kdj_j < previous_kdj_j and current_kdj_j > 80:
                reasons.append("Bearish KDJ divergence")

            if len(reasons) >= 2:
                signal = "sell"

        if not reasons:
            signal = "hold"

        details["reason"] = "; ".join(reasons) if reasons else "No divergence detected"

        return SignalModel(
            strategy=self.get_name(),
            signal=signal,
            details=details
        )