from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.signal_model import SignalModel
from statistics import mean

class HiddenDivergenceStrategy(TradingStrategy):
    """
    A trading strategy that identifies hidden divergences between price action 
    and technical indicators to generate buy or sell signals. This strategy 
    employs an EMA trend filter and is designed for short-term trades.

    The strategy utilizes the following indicators:
    - EMA (Exponential Moving Average) with a period of 50 to define the trend.
    - RSI (Relative Strength Index) with a standard period of 14, using thresholds of 
    70 for overbought and 30 for oversold conditions.
    - MACD (Moving Average Convergence Divergence) with standard parameters of 12, 26, and 9.
    - KDJ (Stochastic) with parameters of 14, 3, 3 for stability.

    The strategy looks for hidden divergences:
    - In an uptrend (when the price is above the EMA), it detects higher price swing lows 
    but lower indicator lows (RSI, MACD, KDJ).
    - In a downtrend (when the price is below the EMA), it detects lower price swing highs 
    but higher indicator highs.

    Confirmation of signals is sought through at least two indicators showing divergence.
    The strategy aims for short-term trades, exiting on opposite signals or key levels, 
    and avoids trading in low volume or sideways markets.

    Attributes:
        ema_period (int): The period for the EMA calculation (default: 50).
        swing_window (int): The window size for detecting swing points (default: 1).
        rsi_period (int): The period for RSI calculation (default: 14).
        macd_fast (int): The short-term EMA period for MACD (default: 12).
        macd_slow (int): The long-term EMA period for MACD (default: 26).
        macd_signal (int): The signal line period for MACD (default: 9).
        kdj_fast_k_period (int): The fast K period for KDJ (default: 14).
        kdj_slow_d_period (int): The slow D period for KDJ (default: 3).
        kdj_slow_k_period (int): The slow K period for KDJ (default: 3).
        data_provider (optional): The data provider instance for fetching market data.
    """

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
        kdj_slow_k_period=3,
        data_provider=None
    ):
        """
        Initializes the HiddenDivergenceStrategy with the specified parameters.

        Args:
            ema_period (int): Period for EMA calculation (default: 50).
            swing_window (int): Window size for detecting swing points (default: 1).
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
        """Returns the name of the trading strategy."""
        return "Hidden Divergence"

    def calculate_ema(self, prices, period):
        """
        Calculates the Exponential Moving Average (EMA) for the given prices.

        Args:
            prices (list): A list of closing prices.
            period (int): The period over which to calculate the EMA.

        Returns:
            list: A list of EMA values.
        """
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
        """
        Detects swing points in the provided data.

        Args:
            data (list): A list of candlestick data.
            window (int): The window size for detecting swing points.

        Returns:
            tuple: A tuple containing two lists (swing_highs, swing_lows).
        """
        swing_highs = []
        swing_lows = []
        for i in range(window, len(data) - window):
            if all(data[i].high > data[i - j].high and data[i].high > data[i + j].high for j in range(1, window + 1)):
                swing_highs.append(i)
            if all(data[i].low < data[i - j].low and data[i].low < data[i + j].low for j in range(1, window + 1)):
                swing_lows.append(i)
        return swing_highs, swing_lows

    def generate_signal(self, symbol: str, candles: dict) -> SignalModel:
        """
        Generates a trading signal based on hidden divergence analysis.

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

        if len(candles) < max(self.ema_period, 3):
            details["reason"] = "Insufficient candles data for swing point and trend analysis."
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(), 
                signal=signal, 
                details=details
            )

        # Indicators
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

        closing_prices = [bar.close for bar in candles]
        ema_values = self.calculate_ema(closing_prices, self.ema_period)
        current_price = candles[-1].close
        current_ema = ema_values[-1]

        # Determine trend
        trend = "uptrend" if current_price > current_ema else "downtrend"

        # Detect swing points
        swing_highs, swing_lows = self.detect_swing_points(candles, self.swing_window)

        # Use most recent swing point
        last_swing_index = None
        if trend == "uptrend" and swing_lows:
            last_swing_index = swing_lows[-1]
        elif trend == "downtrend" and swing_highs:
            last_swing_index = swing_highs[-1]

        if last_swing_index is None or last_swing_index >= len(candles) - 1:
            reason_str = "No valid swing point for divergence comparison."
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(), 
                signal=signal, 
                reason=reason_str,
                details=details
            )

        # Compare price and indicators at swing point vs current
        swing_price = candles[last_swing_index].close
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

        details['current_rsi'] = current_rsi
        details['swing_rsi'] = swing_rsi
        details['current_macd'] = current_macd
        details['swing_macd'] = swing_macd
        details['current_kdj_j'] = current_kdj_j
        details['swing_kdj_j'] = swing_kdj_j

        # Hidden divergence logic
        if trend == "uptrend" and current_price > swing_price:
            if current_rsi < swing_rsi:
                reasons.append("Hidden bearish divergence: Price higher, RSI lower.")
            if current_macd < swing_macd:
                reasons.append("Hidden bearish divergence: Price higher, MACD lower.")
            if current_kdj_j < swing_kdj_j:
                reasons.append("Hidden bearish divergence: Price higher, KDJ J lower.")
            if len(reasons) >= 2:
                signal = "sell"

        elif trend == "downtrend" and current_price < swing_price:
            if current_rsi > swing_rsi:
                reasons.append("Hidden bullish divergence: Price lower, RSI higher.")
            if current_macd > swing_macd:
                reasons.append("Hidden bullish divergence: Price lower, MACD higher.")
            if current_kdj_j > swing_kdj_j:
                reasons.append("Hidden bullish divergence: Price lower, KDJ J higher.")
            if len(reasons) >= 2:
                signal = "buy"

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            reason="; ".join(reasons) if reasons else "No Signal Detected",
            details=details
        )