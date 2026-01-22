import statistics
from typing import List, Dict

class TechUtils:
    """
    Pure Python Technical Analysis Library.
    Implementation of standard trading indicators.
    Refactored to match standard financial math (Wilder's Smoothing, Recursive KDJ, etc.).
    """

    # --- BASIC HELPERS ---
    
    @staticmethod
    def tr_series(highs: List[float], lows: List[float], closes: List[float]) -> List[float]:
        """Calculates True Range series used for ATR, ADX, SuperTrend."""
        if not closes: return []
        # First TR is High - Low
        tr = [highs[0] - lows[0]]
        for i in range(1, len(closes)):
            h, l, c_prev = highs[i], lows[i], closes[i-1]
            val = max(h - l, abs(h - c_prev), abs(l - c_prev))
            tr.append(val)
        return tr

    @staticmethod
    def rma(series: List[float], period: int) -> List[float]:
        """
        Wilder's Moving Average (RMA).
        Crucial for RSI, ADX, and ATR to match TradingView standards.
        """
        if len(series) < period: return []
        # First value is simple SMA to seed the series
        ema = [sum(series[:period]) / period]
        alpha = 1 / period
        for val in series[period:]:
            # RMA formula: (Previous * (n-1) + Current) / n
            new_val = (val * alpha) + (ema[-1] * (1 - alpha))
            ema.append(new_val)
        return ema

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
        alpha = 2 / (period + 1)
        ema = [sum(data[:period]) / period] # Start with SMA
        for price in data[period:]:
            new_val = (price - ema[-1]) * alpha + ema[-1]
            ema.append(new_val)
        return ema

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
        
        # Calculate full series to ensure convergence
        ema_f = TechUtils.ema(prices, fast)
        ema_s = TechUtils.ema(prices, slow)
        
        # Trim arrays to match length (EMA slow is shorter)
        diff = len(ema_f) - len(ema_s)
        macd_line = []
        for i in range(len(ema_s)):
            macd_line.append(ema_f[i+diff] - ema_s[i])
            
        if len(macd_line) < signal: return {"macd": 0, "signal": 0, "hist": 0}
        
        sig_series = TechUtils.ema(macd_line, signal)
        
        return {
            "macd": round(macd_line[-1], 2),
            "signal": round(sig_series[-1], 2),
            "hist": round(macd_line[-1] - sig_series[-1], 2)
        }

    @staticmethod
    def supertrend(highs, lows, closes, period=10, multiplier=3.0) -> Dict[str, float]:
        """
        SuperTrend (ATR Based).
        ALGO USAGE: 
        - Excellent for Trailing Stop Loss.
        - Trend Change Detection (Flip from Bullish to Bearish).
        """
        if len(closes) < period + 1: return {}
        
        # FIXED: Use TR Series helper
        tr_data = TechUtils.tr_series(highs, lows, closes)
        
        # Note: Standard SuperTrend uses Reference ATR (often SMA of TR for simplicity, or RMA for precision)
        # We use simple mean of last N here for a robust snapshot without full recursion overhead
        atr = sum(tr_data[-period:]) / period
        
        hl2 = (highs[-1] + lows[-1]) / 2
        basic_upper = hl2 + (multiplier * atr)
        basic_lower = hl2 - (multiplier * atr)
        
        trend = "BULLISH" if closes[-1] > basic_lower else "BEARISH"
        
        return {
            "value": round(basic_lower if trend == "BULLISH" else basic_upper, 2),
            "trend": trend
        }

    @staticmethod
    def adx(highs, lows, closes, period=14) -> float:
        """
        Average Directional Index (Trend Strength).
        ALGO USAGE:
        - ADX > 25: Trend is strong (Good for Moving Average strat).
        - ADX < 20: Market is Ranging (Good for RSI/Bollinger Band strat).
        
        CRITICAL FIX: Implemented proper Wilder's Smoothing based ADX.
        Previously was a simple directional ratio which provided incorrect info.
        """
        if len(closes) < period * 2: return 0.0
        
        # 1. Calculate TR and Directional Movements (+DM, -DM)
        tr = []
        dm_plus = []
        dm_minus = []
        
        # Need to align indices (starts from index 1)
        # Using First TR as High-Low handled in loop logic below relative to prev close
        tr.append(highs[0] - lows[0])
        dm_plus.append(0)
        dm_minus.append(0)

        for i in range(1, len(closes)):
            h, l, c_prev = highs[i], lows[i], closes[i-1]
            
            # TR
            tr.append(max(h - l, abs(h - c_prev), abs(l - c_prev)))
            
            # Directional Movement
            up = highs[i] - highs[i-1]
            down = lows[i-1] - lows[i]
            
            if up > down and up > 0: dm_plus.append(up)
            else: dm_plus.append(0.0)
            
            if down > up and down > 0: dm_minus.append(down)
            else: dm_minus.append(0.0)

        # 2. Smooth the series using Wilder's RMA
        tr_smooth = TechUtils.rma(tr, period)
        plus_smooth = TechUtils.rma(dm_plus, period)
        minus_smooth = TechUtils.rma(dm_minus, period)
        
        min_len = min(len(tr_smooth), len(plus_smooth), len(minus_smooth))
        if min_len < 1: return 0.0

        # 3. Calculate DX
        dx_list = []
        for i in range(min_len):
            # Align from end
            val_tr = tr_smooth[-(min_len-i)]
            val_plus = plus_smooth[-(min_len-i)]
            val_minus = minus_smooth[-(min_len-i)]
            
            if val_tr == 0: 
                dx_list.append(0)
                continue

            di_plus = (val_plus / val_tr) * 100
            di_minus = (val_minus / val_tr) * 100
            
            denom = di_plus + di_minus
            if denom == 0: 
                dx_list.append(0)
            else: 
                dx_list.append(abs(di_plus - di_minus) / denom * 100)
            
        # 4. Final ADX is the RMA of DX
        adx_series = TechUtils.rma(dx_list, period)
        return round(adx_series[-1], 2) if adx_series else 0.0

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

    # --- CHANNELS ---

    @staticmethod
    def donchian(highs: List[float], lows: List[float], period: int = 20) -> Dict[str, float]:
        """Donchian Channel: Upper/Lower bounds of N period."""
        if len(highs) < period: return {}
        # Simple Max/Min of N period
        upper = max(highs[-period:])
        lower = min(lows[-period:])
        return {"upper": round(upper, 2), "lower": round(lower, 2), "mid": round((upper+lower)/2, 2)}

    @staticmethod
    def keltner(highs: List[float], lows: List[float], closes: List[float], period: int = 20, atr_mult: float = 2.0) -> Dict[str, float]:
        """Keltner Channel: EMA +/- ATR * multiplier."""
        if len(closes) < period: return {}
        ema_series = TechUtils.ema(closes, period)
        if not ema_series: return {}
        mid = ema_series[-1]
        
        # Calculate ATR for the period using helper
        atr = TechUtils.atr(highs, lows, closes, period)
        
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
        
        CRITICAL FIX: Updated to use Wilder's Smoothing (Standard RSI).
        Previous Simple Avg method reacts too fast/jaggedly compared to standard charts.
        """
        if len(prices) < period + 1: return 50.0
        
        deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
        
        avg_gain = 0.0
        avg_loss = 0.0
        
        # 1. Initial SMA for the first period
        for i in range(period):
            if deltas[i] > 0: avg_gain += deltas[i]
            else: avg_loss += abs(deltas[i])
        avg_gain /= period
        avg_loss /= period
        
        # 2. Smooth subsequent values (Wilder's approach)
        for i in range(period, len(deltas)):
            delta = deltas[i]
            gain = delta if delta > 0 else 0.0
            loss = abs(delta) if delta < 0 else 0.0
            
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
            
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
        
        CRITICAL FIX: Implemented recursive calculation.
        K and D must depend on their previous values to "settle" correctly.
        """
        if len(closes) < period: return {"k": 50, "d": 50, "j": 50}
        
        k, d = 50.0, 50.0
        
        # Lookback further than just 'period' to stabilize the recursive EMA of K and D
        start_idx = max(0, len(closes) - (period * 5)) 
        
        for i in range(start_idx, len(closes)):
            # RSV Calculation
            current_window_lows = lows[max(0, i-period+1):i+1]
            current_window_highs = highs[max(0, i-period+1):i+1]
            
            if not current_window_lows: continue
            
            min_l = min(current_window_lows)
            max_h = max(current_window_highs)
            close = closes[i]
            
            if max_h == min_l:
                rsv = 50
            else:
                rsv = ((close - min_l) / (max_h - min_l)) * 100
            
            # Standard Weights: 2/3 Prev + 1/3 Current
            k = (2/3) * k + (1/3) * rsv
            d = (2/3) * d + (1/3) * k
            
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
        
        # Calculate last point relative to SMA
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
            
        if neg == 0: return 100.0
        mfi_val = 100 - (100 / (1 + (pos/neg)))
        return round(mfi_val, 2)

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
        sma = sum(closes[-period:]) / period
        try:
            std = statistics.stdev(closes[-period:])
        except: return {}
        
        u = sma + (std_dev * std)
        l = sma - (std_dev * std)
        width_val = (u - l) / sma if sma != 0 else 0
        
        return {
            "upper": round(u, 2), 
            "lower": round(l, 2), 
            "width_pct": round(width_val, 3)
        }

    @staticmethod
    def atr(highs, lows, closes, period=14) -> float:
        """
        Average True Range.
        ALGO USAGE:
        - Position Sizing (Risk Management).
        - Volatility Stop Loss placement (e.g., 2 * ATR).
        
        FIX: Uses proper Wilder's Smoothing for ATR.
        """
        if len(closes) < period + 1: return 0.0
        
        tr_data = TechUtils.tr_series(highs, lows, closes)
        # Use RMA (Wilder's) for ATR to match standard definition
        rma_tr = TechUtils.rma(tr_data, period)
        
        return round(rma_tr[-1], 2) if rma_tr else 0.0

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
        try:
            pv = sum(c*v for c,v in zip(closes[-period:], volumes[-period:]))
            v = sum(volumes[-period:])
            return round(pv / v, 2) if v > 0 else 0
        except: return closes[-1]

    @staticmethod
    def volume_z_score(volumes: List[float], period: int = 30) -> float:
        """
        Volume Z-Score (Standard Score of Volume).
        ALGO USAGE:
        - Quantifies specific volume anomalies in Standard Deviations (Sigma).
        - Z > 3.0: Volume Climax / Panic Selling (Potential Reversal).
        - Z < -1.0: Extreme apathy / Liquidity dry-up.
        """
        if len(volumes) < period: return 0.0
        
        # Use the last N periods for statistics to establish "Normal"
        window = volumes[-period:]
        if len(window) < 2: return 0.0
        
        try:
            mu = statistics.mean(window)
            sigma = statistics.stdev(window)
            
            # Avoid division by zero if volume is flat
            if sigma == 0: return 0.0
            
            return round((window[-1] - mu) / sigma, 2)
        except: return 0.0

    @staticmethod
    def liquidity_ratio(closes: List[float], volumes: List[float]) -> float:
        """Simple Liquidity proxy."""
        try:
            ret = abs((closes[-1] - closes[-2])/closes[-2])
            if ret == 0: return 1000.0
            # Volume ($M) per 1% move
            vol_m = (volumes[-1] * closes[-1]) / 1_000_000 
            return round(vol_m / (ret * 100), 2)
        except: return