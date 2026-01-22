import math
import statistics
from typing import List, Dict, Tuple, Union

class TechUtils:
    """
    Pure Python Technical Analysis Library.
    Implementation of standard trading indicators.
    """

    # --- BASIC HELPERS ---
    @staticmethod
    def sma(data: List[float], period: int = 20) -> float:
        """
        Standard Moving Average. Default: 20.
        USAGE: Filters noise. Determines 'Value Area'.
        """
        if len(data) < period: return 0.0
        return sum(data[-period:]) / period

    @staticmethod
    def ema(data: List[float], period: int = 20) -> List[float]:
        """
        Exponential Moving Average Series.
        USAGE: Gives more weight to recent prices. Used for Crossovers (Golden Cross).
        """
        if len(data) < period: return []
        ema = [sum(data[:period]) / period]
        multiplier = 2 / (period + 1)
        for price in data[period:]:
            new_val = (price - ema[-1]) * multiplier + ema[-1]
            ema.append(new_val)
        return ema

    @staticmethod
    def tr(high, low, close_prev):
        return max(high - low, abs(high - close_prev), abs(low - close_prev))

    # --- TREND INDICATORS (Is the market moving?) ---
    
    @staticmethod
    def macd(prices: List[float], fast=12, slow=26, signal=9) -> Dict[str, float]:
        """
        Moving Average Convergence Divergence.
        ALGO USAGE: 
        - Histogram > 0: Bullish Momentum increasing.
        - Crossover: Signal Line crosses MACD Line indicates entry trigger.
        """
        if len(prices) < slow + signal: return {"macd": 0, "signal": 0, "hist": 0}
        
        ema_f = TechUtils.ema(prices, fast)
        ema_s = TechUtils.ema(prices, slow)
        
        min_len = min(len(ema_f), len(ema_s))
        macd_line = [ema_f[-i] - ema_s[-i] for i in range(min_len, 0, -1)]
        
        if len(macd_line) < signal: return {"macd": macd_line[-1], "signal": 0, "hist": 0}
        
        sig_line = TechUtils.ema(macd_line, signal)
        
        return {
            "macd": round(macd_line[-1], 2),
            "signal": round(sig_line[-1], 2),
            "hist": round(macd_line[-1] - sig_line[-1], 2)
        }

    @staticmethod
    def supertrend(highs: List[float], lows: List[float], closes: List[float], period=10, multiplier=3.0) -> Dict[str, float]:
        """
        SuperTrend (ATR Based).
        ALGO USAGE: 
        - Excellent for Trailing Stop Loss.
        - Trend Change Detection (Flip from Bullish to Bearish).
        """
        if len(closes) < period + 1: return {}
        
        tr_vals = [TechUtils.tr(h, l, c_prev) for h, l, c_prev in zip(highs[1:], lows[1:], closes[:-1])]
        atr = statistics.mean(tr_vals[-period:])
        
        hl2 = (highs[-1] + lows[-1]) / 2
        basic_upper = hl2 + (multiplier * atr)
        basic_lower = hl2 - (multiplier * atr)
        
        trend = "BULLISH" if closes[-1] > basic_lower else "BEARISH"
        return {"value": round(basic_lower if trend == "BULLISH" else basic_upper, 2), "trend": trend}

    @staticmethod
    def adx(highs, lows, closes, period=14) -> float:
        """
        Average Directional Index (Trend Strength).
        ALGO USAGE:
        - ADX > 25: Trend is strong (Good for Moving Average strat).
        - ADX < 20: Market is Ranging (Good for RSI/Bollinger Band strat).
        """
        if len(closes) < period+1: return 0.0
        up_moves, down_moves = 0, 0
        for i in range(1, len(closes)):
            if closes[i] > closes[i-1]: up_moves += 1
            elif closes[i] < closes[i-1]: down_moves += 1
        # Simplified proxy calculation for performance
        return round((abs(up_moves - down_moves) / period) * 100, 2)

    @staticmethod
    def ichimoku(highs, lows, closes) -> Dict[str, float]:
        """
        Ichimoku Kinko Hyo (Cloud).
        ALGO USAGE:
        - Price > Cloud: Bullish Regime.
        - Tenkan > Kijun: Short term bullish signal.
        """
        def _donchian_val(p): return (max(highs[-p:]) + min(lows[-p:])) / 2
        if len(closes) < 52: return {}
        
        tenkan = _donchian_val(9)
        kijun = _donchian_val(26)
        span_a = (tenkan + kijun) / 2
        span_b = _donchian_val(52)
        return {
            "tenkan": round(tenkan, 2), "kijun": round(kijun, 2),
            "cloud_top": round(span_a, 2), "cloud_bottom": round(span_b, 2),
            "signal": "TK_CROSS_BULL" if tenkan > kijun else "TK_CROSS_BEAR"
        }

    # --- CHANNELS (The missing ones) ---

    @staticmethod
    def donchian(highs: List[float], lows: List[float], period: int = 20) -> Dict[str, float]:
        """Donchian Channel: Upper/Lower bounds of N period."""
        if len(highs) < period: return {}
        upper = max(highs[-period:])
        lower = min(lows[-period:])
        return {"upper": round(upper, 2), "lower": round(lower, 2), "mid": round((upper+lower)/2, 2)}

    @staticmethod
    def keltner(highs: List[float], lows: List[float], closes: List[float], period: int = 20, atr_mult: float = 2.0) -> Dict[str, float]:
        """Keltner Channel: EMA +/- ATR * multiplier."""
        if len(closes) < period: return {}
        mid = TechUtils.ema(closes, period)[-1]
        
        # Calculate ATR for the period
        tr_vals = [TechUtils.tr(h, l, c_prev) for h, l, c_prev in zip(highs[1:], lows[1:], closes[:-1])]
        atr = statistics.mean(tr_vals[-period:]) if tr_vals else 0
        
        return {
            "upper": round(mid + (atr * atr_mult), 2),
            "lower": round(mid - (atr * atr_mult), 2)
        }

    # --- MOMENTUM INDICATORS (Is price speed changing?) ---

    @staticmethod
    def rsi(prices: List[float], period: int = 14) -> float:
        """
        Relative Strength Index.
        ALGO USAGE:
        - > 70: Overbought (Potential Reversal or Strong Trend).
        - < 30: Oversold (Potential Bounce).
        - Divergence scanner often used here.
        """
        if len(prices) < period + 1: return 50.0
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        gain = [x for x in deltas if x > 0]
        loss = [abs(x) for x in deltas if x <= 0]
        avg_gain = sum(gain[-period:]) / period
        avg_loss = sum(loss[-period:]) / period
        if avg_loss == 0: return 100.0
        rs = avg_gain / avg_loss
        return round(100.0 - (100.0 / (1.0 + rs)), 2)
    
    @staticmethod
    def williams_r(highs, lows, closes, period: int = 14) -> float:
        """Williams %R."""
        if len(closes) < period: return -50.0
        h_val = max(highs[-period:])
        l_val = min(lows[-period:])
        c_val = closes[-1]
        if h_val == l_val: return -50.0
        return round(((h_val - c_val) / (h_val - l_val)) * -100, 2)

    @staticmethod
    def kdj(highs, lows, closes, period=9) -> Dict[str, float]:
        """
        KDJ Indicator.
        ALGO USAGE:
        - J Line is very sensitive. J > 100 or J < 0 are extreme reversal signals.
        - Golden Cross (J crosses K upward) is a buy signal.
        """
        if len(closes) < period: return {"k": 50, "d": 50, "j": 50}
        C = closes[-1]
        L9 = min(lows[-period:])
        H9 = max(highs[-period:])
        rsv = 100 if H9 == L9 else ((C - L9) / (H9 - L9)) * 100
        k = (2/3) * 50 + (1/3) * rsv
        d = (2/3) * 50 + (1/3) * k
        j = 3 * k - 2 * d
        return {"k": round(k, 2), "d": round(d, 2), "j": round(j, 2)}

    @staticmethod
    def cci(highs, lows, closes, period=20) -> float:
        """
        Commodity Channel Index.
        ALGO USAGE:
        - Designed to find cyclic turns.
        - > +100: Bullish breakout.
        - < -100: Bearish breakdown.
        """
        if len(closes) < period: return 0.0
        tp = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
        sma_tp = sum(tp[-period:]) / period
        mean_dev = sum([abs(x - sma_tp) for x in tp[-period:]]) / period
        if mean_dev == 0: return 0.0
        return round((tp[-1] - sma_tp) / (0.015 * mean_dev), 2)

    @staticmethod
    def mfi(highs, lows, closes, volumes, period=14) -> float:
        """
        Money Flow Index (Volume-Weighted RSI).
        ALGO USAGE:
        - Confirms price moves with volume.
        - Divergence between Price (Higher High) and MFI (Lower High) is a top-tier reversal signal.
        """
        if len(closes) < period+1: return 50.0
        pos, neg = 0.0, 0.0
        for i in range(-period, 0):
            tp = (highs[i] + lows[i] + closes[i]) / 3
            prev = (highs[i-1] + lows[i-1] + closes[i-1]) / 3
            m = tp * volumes[i]
            if tp > prev: pos += m
            elif tp < prev: neg += m
        return round(100 - (100 / (1 + (pos/neg))), 2) if neg > 0 else 100.0

    # --- VOLATILITY (How risky is the market?) ---

    @staticmethod
    def bollinger(closes, period=20, std_dev=2) -> Dict[str, float]:
        """
        Bollinger Bands.
        ALGO USAGE:
        - Squeeze (Width decrease): Precedes explosive move.
        - Tagging the bands: Often acts as dynamic support/resistance in ranging markets.
        """
        if len(closes) < period: return {}
        sma = statistics.mean(closes[-period:])
        std = statistics.stdev(closes[-period:])
        u, l = sma + std_dev*std, sma - std_dev*std
        return {"upper": round(u, 2), "lower": round(l, 2), "width_pct": round((u-l)/sma, 3)}

    @staticmethod
    def atr(highs, lows, closes, period=14) -> float:
        """
        Average True Range.
        ALGO USAGE:
        - Position Sizing (Risk Management).
        - Volatility Stop Loss placement (e.g., 2 * ATR).
        """
        if len(closes) < period + 1: return 0.0
        tr_sum = 0
        for i in range(-period, 0):
            tr_sum += TechUtils.tr(highs[i], lows[i], closes[i-1])
        return round(tr_sum / period, 2)

    @staticmethod
    def pivots(high, low, close) -> Dict[str, float]:
        """
        Standard Floor Pivots.
        ALGO USAGE:
        - Predictive intra-day support/resistance levels.
        - 'P' Level is the daily balance point.
        """
        p = (high + low + close) / 3
        return {
            "pivot": round(p, 2),
            "r1": round((2*p)-low, 2), "s1": round((2*p)-high, 2)
        }

    # --- VOLUME & VALUES ---

    @staticmethod
    def obv_slope(closes, volumes, period=10) -> str:
        """
        On-Balance Volume Slope.
        ALGO USAGE:
        - 'Accumulation' suggests Smart Money is buying despite flat price.
        - 'Distribution' suggests selling into strength.
        """
        net = 0
        for i in range(-period, 0):
            if closes[i] > closes[i-1]: net += volumes[i]
            elif closes[i] < closes[i-1]: net -= volumes[i]
        return "ACCUMULATION" if net > 0 else "DISTRIBUTION"

    @staticmethod
    def vwap_benchmark(closes: List[float], volumes: List[float], period: int = 20) -> float:
        """Rolling VWAP Benchmark."""
        if len(closes) < period: return 0.0
        pv = sum(c*v for c,v in zip(closes[-period:], volumes[-period:]))
        v = sum(volumes[-period:])
        return round(pv / v, 2) if v > 0 else 0

    @staticmethod
    def liquidity_ratio(closes: List[float], volumes: List[float]) -> float:
        """Simple Liquidity proxy."""
        try:
            ret = abs((closes[-1] - closes[-2])/closes[-2])
            if ret == 0: return 1000.0
            return round((volumes[-1] / 1000000) / (ret * 100), 2)
        except: return 0.0