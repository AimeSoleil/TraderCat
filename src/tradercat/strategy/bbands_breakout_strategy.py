from typing import List, Optional, Dict, Any, Tuple

from tradercat.strategy.exit_planner import ExitPlanner
from tradercat.strategy.signal_scorer import Factor, FactorName, ScoringEngine
from tradercat.strategy.trading_strategy import TradingStrategy
from tradercat.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class BollingerBreakoutStrategy(TradingStrategy):

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        trailing_bw_window: int = 60,
        bw_percentile_threshold: float = 20.0,
        ema_fast: int = 8,
        ema_slow: int = 21,
        atr_period: int = 14,
        adx_period: int = 14,
        rsi_period: Optional[int] = 14,
        prior_swing_bars: int = 5,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 2.0,
        score_threshold: float = 0.6,
        min_atr_percent: float = 0.5,
        breakout_margin_atr: float = 0.2,
        weights: Optional[Dict[str, float]] = None,
        data_provider=None,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.trailing_bw_window = trailing_bw_window
        self.bw_percentile_threshold = bw_percentile_threshold
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.rsi_period = rsi_period
        self.prior_swing_bars = prior_swing_bars
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = score_threshold
        self.min_atr_percent = min_atr_percent
        self.breakout_margin_atr = breakout_margin_atr
        
        # [NEW] Dynamic Weights configuration
        default_weights = {
            "breakout": 0.35,
            "squeeze": 0.20,
            "trend": 0.20,
            "volume": 0.15,
            "alignment": 0.10
        }
        # Merge provided weights with defaults
        self.weights = {**default_weights, **(weights or {})}
        
        self.provider = data_provider

        # Field Naming
        self.bb_bw_field = f"close_BBB_{self.bb_period}_{self.bb_std}"
        self.bb_up_field = f"close_BBU_{self.bb_period}_{self.bb_std}"
        self.bb_low_field = f"close_BBL_{self.bb_period}_{self.bb_std}"
        self.bb_mid_field = f"close_BBM_{self.bb_period}_{self.bb_std}"
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"

    def get_name(self) -> str:
        return "BollingerBreakout"

    def get_lookback_window(self) -> int:
        return (
            max(
                self.trailing_bw_window,
                self.adx_period,
                self.atr_period,
                self.ema_slow,
                self.prior_swing_bars,
            )
            + 10  # Added extra buffer
        )
    
    def support_scoring_factors(self) -> List[FactorName]:
        # Removed unused CONFLUENCE_BONUS
        return  [
            FactorName.BREAKOUT_TRIGGER,
            FactorName.SQUEEZE_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.VOLUME_CONFIRM,
            FactorName.EMA_ALIGNMENT
        ]

    # --------- Helper Functions ---------

    # Note: _percentile_rank removed to use base class implementation (TradingStrategy)

    def _read_provider_bandwidth(self, bb_series: Any, idx: int) -> Tuple[
        Optional[float], List[float], Optional[float], Optional[float], Optional[float]
    ]:
        curr_bw = None
        u_curr = l_curr = m_curr = None
        
        # Safety Check
        if not bb_series or idx >= len(bb_series):
            return None, [], None, None, None
            
        try:
            item = bb_series[idx]
            curr_bw = float(getattr(item, self.bb_bw_field, 0))
            u_curr = float(getattr(item, self.bb_up_field, 0))
            l_curr = float(getattr(item, self.bb_low_field, 0))
            m_curr = float(getattr(item, self.bb_mid_field, 0))
        except (AttributeError, TypeError):
            return None, [], None, None, None

        # Build History safely
        bw_list: List[float] = []
        # Ensure start index is valid
        start = max(0, idx - self.trailing_bw_window)
        
        for i in range(start, idx): # Exclude current bar from history comparison usually
            try:
                val = getattr(bb_series[i], self.bb_bw_field, None)
                if val is not None:
                    bw_list.append(float(val))
            except:
                continue
                
        return curr_bw, bw_list, u_curr, l_curr, m_curr

    # --- 主逻辑 ---
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:   
        # 数据校验
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=None, reason="数据不足", confidence=0.0)
        
        # 获取指标
        bb_series = self.provider.get_indicator("bbands", candles, {"length": self.bb_period, "std": self.bb_std})
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})

        # 解析当前K线数据
        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        vols = [float(c.volume) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]
        
        idx = len(candles) - 1
        close = closes[idx]
        high = highs[idx]
        low = lows[idx]

        # 提取指标值
        atr_history = [getattr(a, self.atr_field, None) for a in atr_series]
        current_atr = atr_history[-1] if atr_history else 0
        
        adx_history = [getattr(a, self.adx_field, None) for a in adx_series]
        # ADX not explicitly used for filter here but kept for context/trend_strength helper
        
        rsi_history = [getattr(a, self.rsi_field, None) for a in rsi_series]
        current_rsi = rsi_history[-1] if rsi_history else 50

        # BB数据
        curr_bw, bw_list, bbu, bbl, bbm = self._read_provider_bandwidth(bb_series, idx)
        if curr_bw is None or not bw_list:
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=dates[-1], reason="BB Data Error", confidence=0.0)

        # 1. 波动率检查 (Dead Stock Filter)
        atr_pct = (current_atr / close) * 100.0
        if atr_pct < self.min_atr_percent:
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=dates[-1], reason=f"Low Volatility ({atr_pct:.2f}%)", confidence=0.0)
        
        # 2. Squeeze 计算 (Using Base Class _percentile_rank)
        bw_pct = self._percentile_rank(bw_list, curr_bw)
        in_squeeze = (bw_pct <= self.bw_percentile_threshold)

        # 3. 趋势过滤
        ema_f = self._extract_latest_indicator_value(ema_fast_series, [self.ema_fast_field])
        ema_s = self._extract_latest_indicator_value(ema_slow_series, [self.ema_slow_field])
        
        # 4. Breakout Check (With Margin)
        margin = current_atr * self.breakout_margin_atr
        long_break_trigger = close >= (bbu + margin)
        short_break_trigger = close <= (bbl - margin)
        
        # NEW: Candle Shape Validation (Bar Close)
        # We want strong closes (no massive wicks against the move)
        candle_range = high - low        
        valid_candle_shape = False
        
        if long_break_trigger:
            # Wick check: (Close - Low) takes up most of the range -> High close
            if candle_range > 0 and (close - low) / candle_range > 0.7:
                valid_candle_shape = True
        elif short_break_trigger:
            # Wick check: (High - Close) takes up most of the range -> Low close
            if candle_range > 0 and (high - close) / candle_range > 0.7:
                valid_candle_shape = True

        # NEW: RSI Filter
        # Breakout is valid if RSI supports momentum but isn't totally exhausted (>85)
        rsi_ok = False
        if long_break_trigger:
            # Bullish but not insane
            rsi_ok = 50 < current_rsi < 85 
        elif short_break_trigger:
            # Bearish but not insane
            rsi_ok = 15 < current_rsi < 50

        # 5. Volume Check
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok = self._check_volume_zscore(
            vols, recent_window, self.vol_zscore_threshold
        )

        trend_strength = self._check_trend_and_volatility(
            atr_val_history=atr_history,
            adx_val_history=None, # Passed None if not explicitly needing separate ADX check logic inside helper
            price_history=closes,
            window=100,
            mode='trend',
            trend_quantiles=[0.6, 0.4]
        )

        # 构造详情
        details: Dict[str, Any] = {
            "close": close,
            "bbu": bbu,
            "bbl": bbl,
            "bw_pct": round(bw_pct, 1),
            "squeeze": in_squeeze,
            "atr_pct": round(atr_pct, 2),
            "rsi": round(current_rsi, 1),
            "valid_candle": valid_candle_shape
        }

        # --- SCORING ENGINE ---
        is_long = long_break_trigger
        is_short = short_break_trigger
        
        # Use simple boolean for Trend Alignment
        trend_aligned = (is_long and ema_f > ema_s) or (is_short and ema_f < ema_s)

        factors = [
            # Factor 1: The Trigger (Must be a clean break)
            Factor(
                FactorName.BREAKOUT_TRIGGER, 
                "Clean Breakout Candle", 
                self.weights["breakout"], 
                (is_long or is_short) and valid_candle_shape
            ),
            # Factor 2: The Setup (Squeeze -> Explosion)
            Factor(
                FactorName.SQUEEZE_CONFIRM, 
                "Volatility Expansion", 
                self.weights["squeeze"], 
                in_squeeze or bw_pct < 40 # Allow some expansion already if move is strong
            ),
            # Factor 3: Momentum Context (RSI & Trend Strength)
            Factor(
                FactorName.TREND_STRENGTH, 
                "Momentum Context (RSI/Trend)", 
                self.weights["trend"], 
                rsi_ok and trend_strength.signal
            ),
            # Factor 4: Volume
            Factor(
                FactorName.VOLUME_CONFIRM, 
                "Volume Surge", 
                self.weights["volume"], 
                vol_ok
            ),
            # Factor 5: Trend Alignment
            Factor(
                FactorName.EMA_ALIGNMENT, 
                "Trend Alignment", 
                self.weights["alignment"], 
                trend_aligned
            )
        ]

        engine = ScoringEngine(
            base_threshold=self.score_threshold, 
            required_factors=[], 
            determined_factors=[FactorName.BREAKOUT_TRIGGER], # Strict requirement: Must have valid candle
            is_volatility_ok=True 
        )
        
        side = "long" if is_long else "short" if is_short else "neutral"
        result = engine.compute_score(factors, side=side)

        # --- Exit Planning ---
        if result and result.signal != "hold":
            planner = ExitPlanner(highs, lows, current_atr, close)
            plan = planner.make_exit_plan(result.signal)
            
            # Dynamic Stop Loss based on Band
            if bbm:
                plan['trailing_stop_ref'] = bbm
                plan['stop_loss_type'] = 'mean_reversion_band'
            
            details["plan"] = plan

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            date=dates[-1],
            # Ensure confidence never exceeds 1.0
            confidence=round(min(1.0, result.score), 3),
            reason=" | ".join(result.reasons),
            details=details,
        )

def make_bbands_breakout_presets() -> Dict[str, Dict[str, Any]]:
    """
    Returns a dictionary of all available presets for Bollinger Breakout Strategy.
    Key: Preset Name (e.g., 'swing')
    Value: Dictionary of constructor arguments.
    """
    return {
        "swing": {
            # ---------------- SWING TRADING (Optimized) ----------------
            # Timeframe: Daily charts mostly. Holding: Days to Weeks.
            # Goal: Catch standard volatility expansions.
            
            # --- Core BB Settings ---
            "bb_period": 20,
            "bb_std": 2.0,                  # Standard 2 sigmas covers 95% of PA.

            # --- Squeeze Logic ---
            "trailing_bw_window": 120,      # Look back 6 months to define "tight".
            "bw_percentile_threshold": 15.0,# Bottom 15% width is a valid squeeze.

            # --- Trend Filter ---
            "ema_fast": 9,
            "ema_slow": 21,                 # Modern "Trader's Zone" EMAs.

            # --- Indicators ---
            "atr_period": 14,
            "adx_period": 14,
            "rsi_period": 14,
            "prior_swing_bars": 5,

            # --- Volume Confirmation ---
            "vol_zscore_window": 20,
            "vol_zscore_threshold": 2.0,    # Require distinct volume spike (2 std devs).

            # --- Scoring ---
            "score_threshold": 0.65,        # Balanced conviction.

            # --- Weights (Tunable) ---
            "weights": {
                "breakout": 0.35, # Trigger is king
                "squeeze": 0.20,
                "trend": 0.15,
                "volume": 0.20,   # Volume is crucial for 3-5 day moves
                "alignment": 0.10
            },

            # --- Filters ---
            "min_atr_percent": 1.0,         # Filter out dead stocks (<1% daily move).
            "breakout_margin_atr": 0.2,     # Valid break must be 0.2 ATR above the band.
        },
        
        "position": {
            # ---------------- POSITION TRADING (Trend Following) ----------------
            # Timeframe: Weekly/Daily. Holding: Weeks to Months.
            # Goal: Capture major structural breakouts, ignoring noise.
            
            "bb_period": 50,                # Slower aggregation (Institutions use 50/200).
            "bb_std": 2.5,                  # Wider bands (99% coverage). Breakout here is RARE and POWERFUL.
            
            # --- Squeeze Logic ---
            "trailing_bw_window": 200,      # High context (approx 1 year).
            "bw_percentile_threshold": 20.0,

            # --- Trend Filter ---
            "ema_fast": 20,                 # Monthly trend.
            "ema_slow": 50,                 # Quarterly trend.

            # --- Indicators ---
            "atr_period": 20,               # Smoother ATR.
            "adx_period": 14,
            "rsi_period": 21,               # Slower RSI to avoid false oversold signals.
            "prior_swing_bars": 10,

            # --- Volume Confirmation ---
            "vol_zscore_window": 60,        # 3-month volume baseline.
            "vol_zscore_threshold": 1.5,    # Less explosive, just needs to be healthy.

            # --- Scoring ---
            "score_threshold": 0.75,        # High conviction required for long holds.

            # --- Weights (Tunable) ---
            "weights": {
                "breakout": 0.25, # Entry precise timing matters less
                "squeeze": 0.15,
                "trend": 0.25,    # Momentum context is key
                "volume": 0.10,
                "alignment": 0.25 # Macro trend alignment is vital
            },

            # --- Filters ---
            "min_atr_percent": 0.5
        }
    }