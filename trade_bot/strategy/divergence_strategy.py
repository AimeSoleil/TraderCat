from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

class DivergenceStrategy(TradingStrategy):
    """
    A trading strategy that identifies divergences between price action 
    and technical indicators to generate buy or sell signals. This strategy
    is designed for swing trading and utilizes daily candlestick data.

    The strategy employs the following indicators:
    - KDJ (K, D, J) with periods of 14, 3, 3 for more stable signals.
    - MACD (Moving Average Convergence Divergence) with standard windows of 12, 26, and 9.
    - RSI (Relative Strength Index) with a standard window of 14, using thresholds of 
      70 for overbought and 30 for oversold conditions.

    The strategy aims for hold periods of 1 to 3 days, exiting on opposite signals 
    or key support/resistance levels. It avoids trading in low volume or sideways markets. 
    Confirmation of signals is sought through volume spikes at breakout points, 
    and the strategy looks for divergences between price action and indicators.

    Attributes:
        bb_period (int): The period for Bollinger Bands, default is 20.
        rsi_period (int): The period for RSI calculation, default is 14.
        macd_fast (int): The short-term EMA period for MACD, default is 12.
        macd_slow (int): The long-term EMA period for MACD, default is 26.
        macd_signal (int): The signal line period for MACD, default is 9.
        kdj_fast_k_period (int): The fast K period for KDJ, default is 14.
        kdj_slow_d_period (int): The slow D period for KDJ, default is 3.
        kdj_slow_k_period (int): The slow K period for KDJ, default is 3.
        data_provider (optional): The data provider instance for fetching market data.
    """

    def __init__(
        self,
        bb_period=20,
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        kdj_fast_k_period=14,
        kdj_slow_d_period=3,
        kdj_slow_k_period=3,
        data_provider=None
    ):
        """
        Initializes the DivergenceStrategy with the specified parameters.

        Args:
            bb_period (int): Period for Bollinger Bands (default: 20).
            rsi_period (int): Period for RSI calculation (default: 14).
            macd_fast (int): Short-term EMA period for MACD (default: 12).
            macd_slow (int): Long-term EMA period for MACD (default: 26).
            macd_signal (int): Signal line period for MACD (default: 9).
            kdj_fast_k_period (int): Fast K period for KDJ (default: 14).
            kdj_slow_d_period (int): Slow D period for KDJ (default: 3).
            kdj_slow_k_period (int): Slow K period for KDJ (default: 3).
            data_provider (optional): Data provider for fetching market data.
        """
        self.provider = data_provider
        self.bb_period = bb_period
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.kdj_fast_k_period = kdj_fast_k_period
        self.kdj_slow_d_period = kdj_slow_d_period
        self.kdj_slow_k_period = kdj_slow_k_period

    def get_name(self) -> str:
        """Returns the name of the trading strategy."""
        return "Divergence"

    def generate_signal(self, symbol: str, candles: dict) -> SignalModel:
        """
        Generates a trading signal based on price action and indicator divergences.

        Args:
            symbol (str): The trading symbol (e.g., 'AAPL').
            candles (dict): Historical market data in candlestick format.

        Returns:
            SignalModel: An object containing the trading signal, reasons for the signal,
                          and additional details.
        """
        print(f'Strategy[{self.get_name()}] generating signal for {symbol}...')
        details = {}
        signal = "hold"
        reasons = []

        if len(candles) < 3:
            reason_str = "Insufficient candles data for divergence analysis."
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(), 
                signal=signal,
                reason=reason_str,
                details=details
            )

        # Fetch indicators
        if not self.provider:
            reason_str = "Data provider not set."
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(), 
                signal=signal,
                reason=reason_str,
                details=details
            )
        
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

        # Extract recent price and indicator values
        previous_close = candles[-2].close
        current_close = candles[-1].close

        # Extract previous and current volumes
        previous_volume = candles[-2].volume
        current_volume = candles[-1].volume

        previous_rsi = rsi[-2].close_RSI_14 if rsi else None
        current_rsi = rsi[-1].close_RSI_14 if rsi else None

        previous_macd = macd[-2].close_MACD_12_26_9 if macd else None
        current_macd = macd[-1].close_MACD_12_26_9 if macd else None
        previous_macd_signal = macd[-2].close_MACDs_12_26_9 if macd else None
        current_macd_signal = macd[-1].close_MACDs_12_26_9 if macd else None

        previous_kdj_k = kdj[-2].STOCHk_14_3_3 if kdj else None
        previous_kdj_d = kdj[-2].STOCHd_14_3_3 if kdj else None
        current_kdj_k = kdj[-1].STOCHk_14_3_3 if kdj else None
        current_kdj_d = kdj[-1].STOCHd_14_3_3 if kdj else None

        # MACD cross-over detection
        macd_bullish_cross = (
            previous_macd is not None and previous_macd_signal is not None and
            current_macd is not None and current_macd_signal is not None and
            previous_macd <= previous_macd_signal and current_macd > current_macd_signal
        )
        macd_bearish_cross = (
            previous_macd is not None and previous_macd_signal is not None and
            current_macd is not None and current_macd_signal is not None and
            previous_macd >= previous_macd_signal and current_macd < current_macd_signal
        )

        # KDJ cross-over detection (K and D)
        kdj_bullish_cross = (
            previous_kdj_k is not None and previous_kdj_d is not None and
            current_kdj_k is not None and current_kdj_d is not None and
            previous_kdj_k <= previous_kdj_d and current_kdj_k > current_kdj_d
        )
        kdj_bearish_cross = (
            previous_kdj_k is not None and previous_kdj_d is not None and
            current_kdj_k is not None and current_kdj_d is not None and
            previous_kdj_k >= previous_kdj_d and current_kdj_k < current_kdj_d
        )

        # Detect bullish divergence
        if current_close < previous_close:
            if current_rsi > previous_rsi and current_rsi < 30:
                reasons.append("Bullish RSI divergence")
            if macd_bullish_cross and current_macd < 0:
                reasons.append("Bullish MACD cross-over")
            if kdj_bullish_cross and current_kdj_k < 20:
                reasons.append("Bullish KDJ cross-over")
            if len(reasons) >= 2 and current_volume >= 1.2 * previous_volume:
                signal = "buy"

        # Detect bearish divergence
        elif current_close > previous_close:
            if current_rsi < previous_rsi and current_rsi > 70:
                reasons.append("Bearish RSI divergence")
            if macd_bearish_cross and current_macd > 0:
                reasons.append("Bearish MACD cross-over")
            if kdj_bearish_cross and current_kdj_k > 80:
                reasons.append("Bearish KDJ cross-over")
            if len(reasons) >= 2:
                signal = "sell"

        if not reasons:
            signal = "hold"

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            reason="; ".join(reasons) if reasons else "No Signal Detected",
            details=details
        )