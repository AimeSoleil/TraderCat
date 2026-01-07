from typing import List, Optional, Dict, Any
import statistics

from tradercat.strategy.exit_planner import ExitPlanner
from tradercat.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from tradercat.strategy.trading_strategy import TradingStrategy
from tradercat.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class MomentumTrendStrategy(TradingStrategy):
    """
    Momentum Trend Strategy (Refactored)
    
    Core Logic:
    - Risk-Adjusted Momentum: Returns normalized by volatility.
    - Dual Timeframe Trend: Daily EMA + Weekly (Aggregated) EMA.
    - ADX Filter: Avoid trading in choppy markets.
    """

    def __init__(
        self,
        L: int = 63,  # momentum lookback (approx 1 quarter)
        ema_fast: int = 13,
        ema_slow: int = 34,
        ht_ema_fast: int = 8,  # Higher Timeframe EMA fast
        ht_ema_slow: int = 21,  # Higher Timeframe EMA slow
        adx_period: int = 14,
        atr_period: int = 14,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.6,
        data_provider: Any = None,
    ):
        self.L = int(L)
        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.ht_ema_fast = int(ht_ema_fast)
        self.ht_ema_slow = int(ht_ema_slow)
        self.adx_period = int(adx_period)
        self.atr_period = int(atr_period)
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # Fields
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.atr_field = f"ATRr_{self.atr_period}"

    def get_name(self) -> str:
        return "MomentumTrend"

    def get_lookback_window(self) -> int:
        return (
            max(
                self.L,
                self.ema_slow,
                self.ht_ema_slow * 5, # Approx conversion for HT bars
                self.atr_period,
                self.adx_period,
            )
            + 10
        )

    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.MOMENTUM_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.DAILY_TREND_CONFIRM,
            FactorName.HIGHER_TIMEFRAME_TREND_CONFIRM,
            FactorName.VOLUME_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

    # ---------- Helpers ----------
    def _compute_ema_manual(self, prices: List[float], period: int) -> Optional[float]:
        """Calculates the *last* EMA value for a list of prices."""
        if not prices or len(prices) < period:
            return None
        k = 2.0 / (period + 1.0)
        ema = sum(prices[:period]) / period # Simple MA initialization
        for p in prices[period:]:
            ema = p * k + ema * (1 - k)
        return ema

    def _compute_risk_adjusted_momentum(self, closes: List[float], lookback: int) -> float:
        """
        Calculates Risk-Adjusted Momentum: Total Return / Volatility
        """
        if len(closes) <= lookback:
            return 0.0
        
        # 1. Total Return
        start_price = closes[-lookback - 1]
        end_price = closes[-1]
        if start_price == 0: return 0.0
        total_ret = (end_price - start_price) / start_price
        
        # 2. Volatility (Standard Deviation of daily returns)
        # Extract slice for the period
        period_closes = closes[-lookback-1:]
        daily_rets = []
        for i in range(1, len(period_closes)):
            if period_closes[i-1] != 0:
                daily_rets.append((period_closes[i] / period_closes[i-1]) - 1)
            else:
                daily_rets.append(0.0)
        
        if not daily_rets: return 0.0
        
        vol = statistics.stdev(daily_rets) if len(daily_rets) > 1 else 0.0
        
        # Avoid division by zero
        if vol < 1e-9: return 0.0
        
        # Annualize volatility? Not strictly necessary for ranking, but good for standardizing.
        # Here we just return the ratio (Sharpe-like).
        return total_ret / vol

    def _aggregate_higher_timeframe(self, candles: List[Any], days: int = 5) -> List[Dict[str, Any]]:
        """Aggregates daily candles into chunks (e.g., Weekly)."""
        if days <= 1 or len(candles) < days:
            return []
        agg = []
        buf = []
        for i, c in enumerate(candles):
            buf.append(c)
            # Aggregate when buffer is full or at end of list
            if (i + 1) % days == 0 or i == len(candles) - 1:
                opens = float(getattr(buf[0], "open", 0))
                closes = float(getattr(buf[-1], "close", 0))
                highs = max(float(getattr(x, "high", 0)) for x in buf)
                lows = min(float(getattr(x, "low", 0)) for x in buf)
                vols = sum(float(getattr(x, "volume", 0)) for x in buf)
                agg.append({
                    "open": opens, "high": highs, "low": lows, "close": closes,
                    "volume": vols, "date": getattr(buf[-1], "date", None)
                })
                buf = []
        return agg

    # ---------- Main Logic ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        logger.info(f"🔍 Generating Momentum Trend signal for {symbol} at {candles[-1].date if candles else 'N/A'}...")
        
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="Data insufficient")

        closes = [float(getattr(c, "close")) for c in candles]
        highs = [float(getattr(c, "high")) for c in candles]
        lows = [float(getattr(c, "low")) for c in candles]
        vols = [float(getattr(c, "volume")) for c in candles]
        dates = [getattr(c, "date") for c in candles]
        curr_close = closes[-1]

        # 1. Momentum Calculation (Risk Adjusted)
        # [Optimization] Use risk-adjusted momentum instead of raw return
        mom_score = self._compute_risk_adjusted_momentum(closes, self.L)

        # 2. Indicators
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        
        current_atr_val = atr_val_history[-1] if atr_val_history else 0.0
        current_adx_val = adx_val_history[-1] if adx_val_history else 0.0
        
        curr_ema_fast = getattr(ema_fast_series[-1], self.ema_fast_field, None)
        curr_ema_slow = getattr(ema_slow_series[-1], self.ema_slow_field, None)

        # 3. Higher Timeframe (HT) EMA
        agg = self._aggregate_higher_timeframe(candles, days=5)
        agg_closes = [x["close"] for x in agg]
        
        ht_fast = self._compute_ema_manual(agg_closes, self.ht_ema_fast)
        ht_slow = self._compute_ema_manual(agg_closes, self.ht_ema_slow)
        ht_ema_ok = (ht_fast is not None and ht_slow is not None)

        # 4. Trend Logic
        trend_strength = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=adx_val_history,
            price_history=closes,
            window=100,
            mode='trend'
        )

        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

        # Daily Trend
        trend_day_up = (curr_ema_fast > curr_ema_slow) if (curr_ema_fast and curr_ema_slow) else False
        trend_day_down = (curr_ema_fast < curr_ema_slow) if (curr_ema_fast and curr_ema_slow) else False
        
        # [Optimization] Price Location Check (Avoid buying below slow EMA)
        price_above_slow = (curr_close > curr_ema_slow) if curr_ema_slow else False
        price_below_slow = (curr_close < curr_ema_slow) if curr_ema_slow else False

        # HT Trend
        trend_ht_up = (ht_fast > ht_slow) if ht_ema_ok else True # Fallback to True if not enough data
        trend_ht_down = (ht_fast < ht_slow) if ht_ema_ok else True

        # Conditions
        # Long: Positive Mom + Daily Up + Price > Slow EMA + HT Up
        long_cond = (mom_score > 0) and trend_day_up and price_above_slow and trend_ht_up
        
        # Short: Negative Mom + Daily Down + Price < Slow EMA + HT Down
        short_cond = (mom_score < 0) and trend_day_down and price_below_slow and trend_ht_down

        details = {
            "mom_score": round(mom_score, 4),
            "ema_fast": curr_ema_fast,
            "ema_slow": curr_ema_slow,
            "ht_fast": ht_fast,
            "ht_slow": ht_slow,
            "adx": current_adx_val,
            "atr": current_atr_val
        }

        # 5. Scoring
        # [Fix] Passed correct booleans to factors instead of generic trend_strength.signal
        factors = [
            Factor(FactorName.MOMENTUM_CONFIRM, f"Risk-Adj Momentum ({mom_score:.2f})", 0.3, long_cond or short_cond),
            Factor(FactorName.TREND_STRENGTH, "ADX Strength", 0.20, trend_strength.signal),
            Factor(FactorName.DAILY_TREND_CONFIRM, "Daily EMA Alignment", 0.20, (long_cond and trend_day_up) or (short_cond and trend_day_down)),
            Factor(FactorName.HIGHER_TIMEFRAME_TREND_CONFIRM, "Weekly EMA Alignment", 0.15, (long_cond and trend_ht_up) or (short_cond and trend_ht_down)),
            Factor(FactorName.VOLUME_CONFIRM, "Volume", 0.05, vol_ok),
            Factor(FactorName.CONFLUENCE_BONUS, "Full Confluence", 0.10, (long_cond and trend_ht_up and trend_strength.signal) or (short_cond and trend_ht_down and trend_strength.signal))
        ]

        engine = ScoringEngine(
            base_threshold=self.score_threshold, 
            required_factors=[FactorName.MOMENTUM_CONFIRM],
            determined_factors=[FactorName.MOMENTUM_CONFIRM],
            is_volatility_ok=trend_strength.volatility['signal']
        )
        
        side = "long" if long_cond else "short" if short_cond else "neutral"
        result: ScoringResult = engine.compute_score(factors, side=side)

        if result and result.signal != 'hold':
            planner = ExitPlanner(highs=highs, lows=lows, atr=current_atr_val, close_price=curr_close)
            plan = planner.make_exit_plan(trading_signal=result.signal)
            details.update({"plan": plan})

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            date=dates[-1],
            confidence=round(result.score, 3),
            reason=" | ".join(result.reasons),
            details=details,
        )

def make_momentum_presets() -> Dict[str, Dict[str, Any]]:
    """
    Returns a dictionary of all available presets for Momentum Trend Strategy.
    """
    return {
        "swing": {
            # ---------------- MID-TERM TREND (Optimized for Months) ----------------
            # Goal: Capture Quarterly (3-month) to Semi-Annual trends.
            # Holding Period: 4 weeks to 12 weeks.
            # --- Momentum Lookback ---
            # 63 trading days = ~1 Quarter. 
            # We want stocks that have outperformed over the last quarter.
            "L": 63,                           

            # --- Daily Trend Filter ---
            # 20 EMA (approx 1 month) vs 50 EMA (approx 1 quarter).
            # The 20/50 cross is the classic "Intermediate Trend" signal.
            # It filters out short-term noise better than 9/21.
            "ema_fast": 20,                     
            "ema_slow": 50,                    

            # --- Higher Timeframe (Weekly) Filter ---
            # Aggregated 5-day bars (Weekly).
            # 13 Weekly EMA (~1 Quarter) vs 26 Weekly EMA (~2 Quarters).
            # Ensures the "Big Picture" is bullish.
            "ht_ema_fast": 13,                  
            "ht_ema_slow": 26,                 

            # --- Filters ---
            "adx_period": 14,                  
            "atr_period": 14,                  

            # --- Volume ---
            # For mid-term trends, we don't need a massive explosion (Z > 2.0).
            # We just need healthy volume (Z > 1.0) to confirm participation.
            "vol_zscore_window": 20,           
            "vol_zscore_threshold": 1.0,       

            # --- Scoring ---
            # High threshold. We are looking for the "Best of the Best" leaders.
            "score_threshold": 0.70             
        },

        "position": {
            # ---------------- LONG-TERM POSITION ----------------
            # Goal: Capture Annual trends (Golden Cross).
            "L": 126,                          # 6 Months (Half-Year) Momentum
            "ema_fast": 50,                    # Institutional Support
            "ema_slow": 200,                   # The "Bull/Bear" Line
            "ht_ema_fast": 21,                 # Weekly ~ 100 days
            "ht_ema_slow": 52,                 # Weekly ~ 1 Year
            "adx_period": 14,
            "atr_period": 14,
            "vol_zscore_window": 40,           
            "vol_zscore_threshold": 1.0,       
            "score_threshold": 0.80            
        },
        
        "scalp": {
            # ---------------- MOMENTUM SCALPING (Day Trading) ----------------
            # Goal: Ride the intraday gappers / movers.
            "L": 10,                           # 10 bars momentum
            "ema_fast": 5,
            "ema_slow": 13,
            "ht_ema_fast": 8,                  # Higher timeframe proxy
            "ht_ema_slow": 21,
            "adx_period": 7,
            "atr_period": 5,
            "vol_zscore_window": 10,
            "vol_zscore_threshold": 2.0,       # High volume demand
            "score_threshold": 0.60
        }
    }
