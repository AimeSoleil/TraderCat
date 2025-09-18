from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.signal_model import SignalModel

class MAStrategy(TradingStrategy):
    """
    A trading strategy that utilizes moving average crossovers, MACD, RSI, 
    and volume analysis to generate buy or sell signals.

    The strategy employs the following indicators:
    - EMA (Exponential Moving Average) with a short-term period of 10.
    - SMA (Simple Moving Average) with a medium-term period of 20.
    - MACD (Moving Average Convergence Divergence) using standard parameters of 12, 26, and 9.
    - RSI (Relative Strength Index) with a standard period of 14, using thresholds of 
    70 for overbought and 30 for oversold conditions.
    - Volume analysis using a 5-period moving average to identify significant volume spikes.

    The strategy looks for:
    - Bullish signals when the EMA crosses above the SMA, confirmed by MACD crossovers, 
    RSI levels above 50, and volume spikes.
    - Bearish signals when the EMA crosses below the SMA, confirmed by MACD crossovers, 
    RSI levels above 70, and volume spikes.

    The strategy aims for short-term trades, exiting on opposite signals or key levels,
    and avoids trading in low volume or sideways markets.

    Attributes:
        ema_period (int): The period for the EMA calculation (default: 10).
        sma_period (int): The period for the SMA calculation (default: 20).
        rsi_period (int): The period for RSI calculation (default: 14).
        macd_fast (int): The short-term EMA period for MACD (default: 12).
        macd_slow (int): The long-term EMA period for MACD (default: 26).
        macd_signal (int): The signal line period for MACD (default: 9).
        volume_window (int): The period for calculating average volume to identify spikes (default: 5).
        data_provider (optional): The data provider instance for fetching market data.
    """

    def __init__(
        self,
        ema_period=10,
        sma_period=20,
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        volume_window=5,
        data_provider=None
    ):
        """
        Initializes the MAStrategy with the specified parameters.

        Args:
            ema_period (int): Period for EMA calculation (default: 10).
            sma_period (int): Period for SMA calculation (default: 20).
            rsi_period (int): Period for RSI calculation (default: 14).
            macd_fast (int): Short-term EMA period for MACD (default: 12).
            macd_slow (int): Long-term EMA period for MACD (default: 26).
            macd_signal (int): Signal line period for MACD (default: 9).
            volume_window (int): Period for calculating average volume (default: 5).
            data_provider (optional): Data provider for fetching market data.
        """
        self.provider = data_provider
        self.ema_period = ema_period
        self.sma_period = sma_period
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.volume_window = volume_window

    def get_name(self) -> str:
        """Returns the name of the trading strategy."""
        return "Moving Average"

    def generate_signal(self, symbol: str, candles: dict) -> SignalModel:
        """
        Generates a trading signal based on moving average crossovers, MACD, RSI, and volume analysis.

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

        if not self.provider:
            reason_str = "Data provider not set."
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(), 
                signal=signal,
                reason=reason_str,
                details=details
            )
        
        # Fetch indicators
        ema = self.provider.get_indicator("ema", candles, {"length": self.ema_period})
        sma = self.provider.get_indicator("sma", candles, {"length": self.sma_period})
        macd = self.provider.get_indicator("macd", candles, {
            "fast": self.macd_fast,
            "slow": self.macd_slow,
            "signal": self.macd_signal
        })
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        volumes = [candle.volume for candle in candles]

        # Moving Average crossover detection
        if len(ema) >= 2 and len(sma) >= 2:
            prev_ema, curr_ema = ema[-2].close_EMA_10, ema[-1].close_EMA_10
            prev_sma, curr_sma = sma[-2].close_SMA_20, sma[-1].close_SMA_20
            ema_sma_bullish = prev_ema < prev_sma and curr_ema > curr_sma  # Bullish crossover
            ema_sma_bearish = prev_ema > prev_sma and curr_ema < curr_sma  # Bearish crossover
        else:
            ema_sma_bullish = ema_sma_bearish = False

        # MACD crossover detection
        if len(macd) >= 2:
            prev_macd, curr_macd = macd[-2], macd[-1]
            prev_macd_val = prev_macd.close_MACD_12_26_9
            prev_signal_val = prev_macd.close_MACDs_12_26_9
            curr_macd_val = curr_macd.close_MACD_12_26_9
            curr_signal_val = curr_macd.close_MACDs_12_26_9
            macd_bullish = prev_macd_val <= prev_signal_val and curr_macd_val > curr_signal_val
            macd_bearish = prev_macd_val >= prev_signal_val and curr_macd_val < curr_signal_val
        else:
            macd_bullish = macd_bearish = False

        # RSI value
        curr_rsi = rsi[-1].close_RSI_14 if rsi else None

        # Volume analysis
        if len(volumes) >= self.volume_window + 1:
            avg_vol = sum(volumes[-self.volume_window-1:-1]) / self.volume_window
            curr_vol = volumes[-1]
            vol_rise = curr_vol > 1.2 * avg_vol  # Check for volume surge
        else:
            vol_rise = False

        # Bullish signal conditions
        if ema_sma_bullish:
            reasons.append("EMA crosses above SMA (bullish)")
        if macd_bullish:
            reasons.append("MACD bullish crossover")
        if curr_rsi is not None and curr_rsi > 50:
            reasons.append("RSI above 50")
        if vol_rise:
            reasons.append("Volume surge")

        if ema_sma_bullish and macd_bullish and curr_rsi is not None and curr_rsi < 30 and vol_rise:
            signal = "buy"
        # Bearish signal conditions
        elif ema_sma_bearish and macd_bearish and curr_rsi is not None and curr_rsi > 70 and vol_rise:
            signal = "sell"
        else:
            signal = "hold"

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            reason="; ".join(reasons) if reasons else "No Signal Detected",
            details=details
        )