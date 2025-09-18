from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

class BollingerBandStrategy(TradingStrategy):
    """
    Bollinger Bands Strategy

    This strategy integrates Bollinger Bands, RSI, MACD, KDJ, and volume analysis to identify
    high-probability trading opportunities. It is designed for short-term trades and aims to
    generate signals only when multiple indicators align, thereby reducing false positives in 
    sideways or low-volume markets.

    Parameters
    ----------
    bb_period : int, default=20
        The period for Bollinger Bands calculation, determining the number of periods to use 
        for the moving average.
    bb_std : int or float, default=2
        The standard deviation multiplier for Bollinger Bands, controlling the width of the bands.
    rsi_period : int, default=14
        The period for the Relative Strength Index (RSI), used to identify overbought or oversold 
        conditions.
    macd_fast : int, default=12
        The fast EMA period for MACD calculation, influencing the responsiveness of the MACD line.
    macd_slow : int, default=26
        The slow EMA period for MACD calculation, providing a longer-term trend perspective.
    macd_signal : int, default=9
        The signal line EMA period for MACD, used to generate buy/sell signals.
    kdj_fast_k_period : int, default=14
        The period for the fast %K line in KDJ (Stochastic), determining the sensitivity of the 
        KDJ indicator.
    kdj_slow_d_period : int, default=3
        The period for the slow %D line in KDJ (Stochastic), used to smooth the %K line.
    kdj_slow_k_period : int, default=3
        The period for the slow %K line in KDJ (Stochastic), influencing the overall calculation.
    volume_window : int, default=5
        The window size for calculating average volume to detect volume spikes, helping confirm 
        the strength of signals.
    data_provider : object, optional
        The data provider instance used to fetch indicator values.

    Strategy Logic
    --------------
    - Buy signal: Triggered when the price closes below the lower Bollinger Band, RSI is 
    oversold (<30), MACD and KDJ show bullish crossovers, and a volume spike is detected.
    - Sell signal: Triggered when the price closes above the upper Bollinger Band, RSI is 
    overbought (>70), MACD and KDJ show bearish crossovers, and a volume spike is detected.
    - Hold: No strong confluence of signals, indicating a lack of clear trading opportunity.
    """

    def __init__(
        self,
        bb_period=20,
        bb_std=2,
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        kdj_fast_k_period=14,
        kdj_slow_d_period=3,
        kdj_slow_k_period=3,
        volume_window=5,
        data_provider=None
    ):
        """
        Initializes the BollingerBandStrategy with the specified parameters.

        Args:
            bb_period (int): The period for Bollinger Bands calculation (default: 20).
            bb_std (int or float): The standard deviation multiplier for Bollinger Bands (default: 2).
            rsi_period (int): The period for RSI calculation (default: 14).
            macd_fast (int): The fast EMA period for MACD (default: 12).
            macd_slow (int): The slow EMA period for MACD (default: 26).
            macd_signal (int): The signal line period for MACD (default: 9).
            kdj_fast_k_period (int): The fast %K period for KDJ (default: 14).
            kdj_slow_d_period (int): The slow %D period for KDJ (default: 3).
            kdj_slow_k_period (int): The slow %K period for KDJ (default: 3).
            volume_window (int): The window size for calculating average volume (default: 5).
            data_provider (optional): Data provider for fetching market data.
        """
        self.provider = data_provider
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.kdj_fast_k_period = kdj_fast_k_period
        self.kdj_slow_d_period = kdj_slow_d_period
        self.kdj_slow_k_period = kdj_slow_k_period
        self.volume_window = volume_window

    def get_name(self) -> str:
        """Returns the name of the trading strategy."""
        return "Bollinger Bands"

    def generate_signal(self, symbol: str, candles: dict) -> SignalModel:
        """
        Generates a trading signal based on Bollinger Bands, RSI, MACD, KDJ, and volume analysis.

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

        if len(candles) < max(self.bb_period, self.rsi_period, self.macd_slow, self.kdj_fast_k_period, self.volume_window) + 2:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal=signal,
                reason="Insufficient candles data",
                details=details
            )

        if not self.provider:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal=signal,
                reason="Data provider not set",
                details=details
            )

        # Fetch indicators
        bb = self.provider.get_indicator("bbands", candles, {"length": self.bb_period, "std": self.bb_std})
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
        current_close = candles[-1].close
        current_volume = candles[-1].volume

        current_rsi = rsi[-1].close_RSI_14 if rsi else None

        previous_macd = macd[-2].close_MACD_12_26_9 if macd else None
        current_macd = macd[-1].close_MACD_12_26_9 if macd else None
        previous_macd_signal = macd[-2].close_MACDs_12_26_9 if macd else None
        current_macd_signal = macd[-1].close_MACDs_12_26_9 if macd else None

        previous_kdj_k = kdj[-2].STOCHk_14_3_3 if kdj else None
        previous_kdj_d = kdj[-2].STOCHd_14_3_3 if kdj else None
        current_kdj_k = kdj[-1].STOCHk_14_3_3 if kdj else None
        current_kdj_d = kdj[-1].STOCHd_14_3_3 if kdj else None

        # Bollinger Bands
        # close_BBL_20_2.0=223.0175783123, 
        # close_BBM_20_2.0=231.166, 
        # close_BBU_20_2.0=239.3144216877, 
        # getattr(bb_last, 'close_BBL_20_2.0', None)
        bb_last = bb[-1] if bb else None
        bb_upper = getattr(bb_last, 'close_BBU_20_2.0', None)
        bb_lower = getattr(bb_last, 'close_BBL_20_2.0', None)

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

        # Volume spike detection
        volumes = [c.volume for c in candles[-self.volume_window-1:]]
        avg_vol = sum(volumes[:-1]) / self.volume_window if len(volumes) > self.volume_window else None
        vol_spike = avg_vol and current_volume > 1.2 * avg_vol

        # --- Buy signal logic ---
        if (
            bb_lower is not None and current_close < bb_lower and
            current_rsi is not None and current_rsi < 30 and
            macd_bullish_cross and
            kdj_bullish_cross and
            vol_spike
        ):
            signal = "buy"
            reasons.append("Price below BB lower, RSI oversold, MACD/KDJ bullish cross, volume spike")

        # --- Sell signal logic ---
        elif (
            bb_upper is not None and current_close > bb_upper and
            current_rsi is not None and current_rsi > 70 and
            macd_bearish_cross and
            kdj_bearish_cross and
            vol_spike
        ):
            signal = "sell"
            reasons.append("Price above BB upper, RSI overbought, MACD/KDJ bearish cross, volume spike")

        else:
            signal = "hold"
            if bb_lower and current_close < bb_lower:
                reasons.append("Price below BB lower")
            if bb_upper and current_close > bb_upper:
                reasons.append("Price above BB upper")
            if current_rsi is not None and current_rsi < 30:
                reasons.append("RSI oversold")
            if current_rsi is not None and current_rsi > 70:
                reasons.append("RSI overbought")
            if macd_bullish_cross:
                reasons.append("MACD bullish cross")
            if macd_bearish_cross:
                reasons.append("MACD bearish cross")
            if kdj_bullish_cross:
                reasons.append("KDJ bullish cross")
            if kdj_bearish_cross:
                reasons.append("KDJ bearish cross")
            if vol_spike:
                reasons.append("Volume spike")
            if not reasons:
                reasons.append("No strong signal")

        details["bb"] = bb_last
        details["rsi"] = current_rsi
        details["macd"] = current_macd
        details["macd_signal"] = current_macd_signal
        details["kdj_k"] = current_kdj_k
        details["kdj_d"] = current_kdj_d
        details["volume"] = current_volume
        details["avg_volume"] = avg_vol
        details["reasons"] = reasons

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            reason="; ".join(reasons) if reasons else "No Signal Detected",
            details=details
        )