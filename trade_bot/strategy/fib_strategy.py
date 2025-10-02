from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.strategy.signal_model import SignalModel

class FibonacciStrategy(TradingStrategy):
    """
    A trading strategy that uses Fibonacci retracement levels and MACD confirmation
    to generate buy/sell signals based on price behavior and momentum.

    Attributes:
        lookback (int): Number of candles to define swing high/low (default: 20)
        rsi_period (int): RSI period for confirmation (default: 14)
        macd_fast (int): Fast EMA for MACD (default: 12)
        macd_slow (int): Slow EMA for MACD (default: 26)
        macd_signal (int): Signal line for MACD (default: 9)
        volume_window (int): Volume window for spike detection (default: 5)
        data_provider (optional): Data provider for fetching market data
    """

    def __init__(self, 
                lookback=60, 
                rsi_period=14, 
                macd_fast=12, 
                macd_slow=26, 
                macd_signal=9, 
                volume_window=5, 
                data_provider=None):
        self.provider = data_provider
        self.lookback = lookback
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.volume_window = volume_window

    def get_name(self) -> str:
        return "Fibonacci Retracement with MACD"

    def generate_signal(self, symbol: str, candles: dict) -> SignalModel:
        print(f'Strategy[{self.get_name()}] generating signal for {symbol}...')
        signal = "hold"
        reasons = []
        details = {}

        if not self.provider or len(candles) < self.lookback + 1:
            return SignalModel(symbol, self.get_name(), signal, "Insufficient data or provider not set.", details)

        # Extract swing high/low
        highs = [candle.high for candle in candles[-self.lookback:]]
        lows = [candle.low for candle in candles[-self.lookback:]]
        swing_high = max(highs)
        swing_low = min(lows)

        # Calculate Fibonacci levels
        fib_levels = {
            '23.6%': swing_high - 0.236 * (swing_high - swing_low),
            '38.2%': swing_high - 0.382 * (swing_high - swing_low),
            '50.0%': swing_high - 0.500 * (swing_high - swing_low),
            '61.8%': swing_high - 0.618 * (swing_high - swing_low),
            '78.6%': swing_high - 0.786 * (swing_high - swing_low)
        }

        current_price = candles[-1].close

        # Fetch indicators
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd = self.provider.get_indicator("macd", candles, {
            "fast": self.macd_fast,
            "slow": self.macd_slow,
            "signal": self.macd_signal
        })
        volumes = [candle.volume for candle in candles]

        # RSI
        curr_rsi = rsi[-1].close_RSI_14 if rsi else None

        # Volume
        avg_vol = sum(volumes[-self.volume_window-1:-1]) / self.volume_window if len(volumes) >= self.volume_window + 1 else None
        curr_vol = volumes[-1] if volumes else None
        vol_rise = curr_vol > 1.2 * avg_vol if avg_vol else False

        # MACD confirmation
        if len(macd) >= 2:
            prev_macd = macd[-2]
            curr_macd = macd[-1]
            prev_macd_val = prev_macd.close_MACD_12_26_9
            prev_signal_val = prev_macd.close_MACDs_12_26_9
            curr_macd_val = curr_macd.close_MACD_12_26_9
            curr_signal_val = curr_macd.close_MACDs_12_26_9
            macd_bullish = prev_macd_val <= prev_signal_val and curr_macd_val > curr_signal_val
            macd_bearish = prev_macd_val >= prev_signal_val and curr_macd_val < curr_signal_val
        else:
            macd_bullish = macd_bearish = False

        # Signal logic
        if current_price > fib_levels['61.8%'] and current_price < fib_levels['50.0%']:
            reasons.append("Price bouncing between 61.8% and 50% (bullish zone)")
            if curr_rsi and curr_rsi > 50:
                reasons.append("RSI above 50")
            if macd_bullish:
                reasons.append("MACD bullish crossover")
            if vol_rise:
                reasons.append("Volume surge")
            if macd_bullish and curr_rsi and curr_rsi > 50:
                signal = "buy"

        elif current_price < fib_levels['78.6%']:
            reasons.append("Price broke below 78.6% (bearish continuation)")
            if curr_rsi and curr_rsi > 70:
                reasons.append("RSI overbought")
            if macd_bearish:
                reasons.append("MACD bearish crossover")
            if vol_rise:
                reasons.append("Volume surge")
            if macd_bearish and curr_rsi and curr_rsi > 70:
                signal = "sell"

        details = {
            "swing_high": swing_high,
            "swing_low": swing_low,
            "fib_levels": fib_levels,
            "current_price": current_price,
            "curr_rsi": curr_rsi,
            "avg_volume": avg_vol,
            "curr_volume": curr_vol,
            "macd_bullish": macd_bullish,
            "macd_bearish": macd_bearish,
            "curr_macd": curr_macd_val if 'curr_macd_val' in locals() else None,
            "curr_signal": curr_signal_val if 'curr_signal_val' in locals() else None
        }

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            reason="; ".join(reasons) if reasons else "No Signal Detected",
            details=details
        )
