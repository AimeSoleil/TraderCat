from typing import List, Optional, Dict, Any, Tuple

from tradercat.core.strategy.exit_planner import ExitPlanner
from tradercat.core.strategy.signal_scorer import Factor, FactorName, ScoringEngine
from tradercat.core.strategy.trading_strategy import TradingStrategy
from tradercat.core.strategy.signal_model import SignalModel
from tradercat.logger import get_logger

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
        
        # [UPDATED] Robust Volume Z-Score checking
        # Handling potential tuple return (bool, z_score) from base class or simple bool
        _vol_res = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)
        if isinstance(_vol_res, tuple):
            vol_ok, vol_z = _vol_res
        else:
            vol_ok, vol_z = _vol_res, 0.0

        # [UPDATED] Trend/Vol Logic for Breakouts
        # mode='breakout' checks for: Volatility Spike AND (Strong Trend OR Rising ADX)
        # This handles the "Waking Up" phase automatically.

        trend_strength = self._check_trend_and_volatility(
            atr_val_history=atr_history,
            adx_val_history=adx_history,
            price_history=closes,
            window=100,
            mode='breakout',            # [KEY CHANGE] Dedicated breakout logic
            vol_quantile=0.85           # Require significant volatility expansion
        )

        # The signal encapsulates the "Vol Spike + Momentum Context" logic
        is_trend_context_good = trend_strength.signal

        # 计算额外的技术指标用于详情
        current_adx = adx_history[-1] if adx_history else 0.0
        prev_adx = adx_history[-2] if len(adx_history) > 1 else current_adx
        adx_slope = current_adx - prev_adx
        
        avg_vol = sum(vols[-recent_window:]) / recent_window if recent_window > 0 else 0.0
        rel_vol = (vols[-1] / avg_vol) if avg_vol > 0 else 0.0

        # Advanced Metrics
        # %B: 1.0 = Upper Band, 0.0 = Lower Band. Breakout > 1.0
        pct_b = (close - bbl) / (bbu - bbl) if (bbu - bbl) != 0 else 0.5
        
        # Candle Conviction: Body size relative to full range (0.0 - 1.0)
        open_price = float(candles[idx].open)
        bar_range = high - low
        body_size = abs(close - open_price)
        candle_conviction = (body_size / bar_range) if bar_range > 0 else 0.0
        
        # Extension: Distance from Slow EMA (Mean Reversion Risk)
        ema_extension_pct = ((close - ema_s) / ema_s * 100) if ema_s else 0.0
        
        # EMA Spread: Divergence between fast and slow (Trend Maturity)
        ema_spread_pct = ((ema_f - ema_s) / ema_s * 100) if ema_s else 0.0

        # 构造详情 - OHLCV market data
        ohlcv: Dict[str, Any] = {
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(vols[-1], 0),
            f"avg_volume_{self.vol_zscore_window}": round(avg_vol, 0),
            f"rel_volume_{self.vol_zscore_window}": round(rel_vol, 2),
            f"vol_zscore_{self.vol_zscore_window}": round(vol_z or 0.0, 2),
        }

        # Technical indicators
        indicators: Dict[str, Any] = {
            # 布林带深度数据
            f"bbu_{self.bb_period}": round(bbu or 0.0, 2),
            f"bbl_{self.bb_period}": round(bbl or 0.0, 2),
            f"bbm_{self.bb_period}": round(bbm or 0.0, 2),
            f"bandwidth_{self.bb_period}": round(curr_bw or 0.0, 2),
            f"bw_pct_{self.bb_period}": round(bw_pct or 0.0, 1),
            f"pct_b_{self.bb_period}": round(pct_b or 0.0, 2),     # Key for breakout triggers
            "squeeze": in_squeeze,
            
            # 趋势与均线分析
            f"ema_fast_{self.ema_fast}": round(ema_f or 0.0, 2),
            f"ema_slow_{self.ema_slow}": round(ema_s or 0.0, 2),
            "ema_spread_pct": round(ema_spread_pct, 2),
            "ema_extension_pct": round(ema_extension_pct, 2),
            
            # 动量深度数据
            f"adx_{self.adx_period}": round(current_adx, 1),
            f"adx_slope_{self.adx_period}": round(adx_slope, 2),
            f"rsi_{self.rsi_period}": round(current_rsi, 1),
            
            # 波动率与蜡烛形态
            f"atr_{self.atr_period}": round(current_atr, 4),
            "atr_pct": round(atr_pct, 2),
            "candle_conviction": round(candle_conviction, 2),
            "candle_range_atr": round(bar_range / current_atr, 2) if current_atr > 0 else 0.0,
        }

        if atr_pct < self.min_atr_percent:
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=dates[-1], reason=f"Low Volatility ({atr_pct:.2f}%)", confidence=0.0, ohlcv=ohlcv, indicators=indicators)
        
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
            # Factor 3: Momentum Context
            Factor(
                FactorName.TREND_STRENGTH, 
                "Momentum Context (RSI/ADX Slope)", 
                self.weights["trend"], 
                rsi_ok and is_trend_context_good # Updated logic
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
            required_factors=self.support_scoring_factors(), 
            determined_factors=[FactorName.BREAKOUT_TRIGGER], # Strict requirement: Must have valid candle
            is_volatility_ok=True 
        )
        
        side = "long" if is_long else "short" if is_short else "neutral"
        result = engine.compute_score(factors, side=side)

        # --- Exit Planning ---
        if result and result.signal != "hold":
            planner = ExitPlanner(
                highs=highs,
                lows=lows,
                atr=current_atr,
                close_price=close
            )
            plan = planner.make_exit_plan(result.signal)
            
            # Dynamic Stop Loss based on Band
            if bbm:
                plan['trailing_stop_ref'] = round(bbm or 0.0, 2)
                plan['stop_loss_type'] = 'mean_reversion_band'
            
            indicators["plan"] = plan

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            date=dates[-1],
            # Ensure confidence never exceeds 1.0
            confidence=round(min(1.0, result.score), 3),
            reason=" | ".join(result.reasons),
            ohlcv=ohlcv,
            indicators=indicators,
        )

def make_bbands_breakout_presets() -> Dict[str, Dict[str, Any]]:
    """
    Returns a dictionary of all available presets for Bollinger Breakout Strategy.
    Optimized for OPTIONS TRADING logic (Theta, Delta, Vega sensitivity).
    """
    return {
        "gamma": {
            # ---------------- GAMMA SNIPER (The "Squeeze & Pop") ----------------
            # Ideal Strategy: Long Calls/Puts or Straddles (7-21 DTE)
            # Goal: Catch the immediate explosive move from a "TIGHT" coil.
            # Failure Mode: False breakout (Theta burn). Needs strict Stops.
            
            "bb_period": 20,
            "bb_std": 2.0,

            # --- Squeeze Logic (STRICT) ---
            "trailing_bw_window": 60,       # Look back 3 months
            "bw_percentile_threshold": 10.0,# Top 10% tightest consolidation only. Coiled spring.

            # --- Trend Filter (LOOSE) ---
            # We don't care about long term trend as much as immediate momentum impulse
            "ema_fast": 9,
            "ema_slow": 21,

            # --- Indicators ---
            "atr_period": 14,
            "adx_period": 14,
            "rsi_period": 14,
            "prior_swing_bars": 3,          # Quick pivot check

            # --- Volume Confirmation (CRITICAL) ---
            "vol_zscore_window": 20,
            "vol_zscore_threshold": 2.5,    # Needs MASSIVE participation to expand IV.

            # --- Scoring ---
            "score_threshold": 0.70,        # High conviction only.

            # --- Weights (Gamma Focused) ---
            "weights": {
                "breakout": 0.30,
                "squeeze": 0.35,  # Squeeze quality is paramount for Gamma trades
                "trend": 0.10,    # Less concern for macro trend
                "volume": 0.25,   # Volume creates the sustaining fuel
                "alignment": 0.00
            },

            # --- Filters ---
            "min_atr_percent": 1.5,         # Must be volatile. <1.5% moves won't pay for the premium fast enough.
            "breakout_margin_atr": 0.15,    # Get in early once margin breached.
        },

        "swing": {
            # ---------------- DEBIT SPREAD SWING (The "Standard") ----------------
            # Ideal Strategy: Vertical Spreads (21-45 DTE)
            # Goal: Ride a sustainable multi-day/week move.
            # Logic: Balance between trend confirmation and entry price.
            
            "bb_period": 20,
            "bb_std": 2.0,

            # --- Squeeze Logic ---
            "trailing_bw_window": 120,
            "bw_percentile_threshold": 25.0,# Accept looser squeezes if trend is strong.

            # --- Trend Filter ---
            "ema_fast": 9,
            "ema_slow": 21,                 # Standard alignment required.

            # --- Indicators ---
            "atr_period": 14,
            "adx_period": 14,
            "rsi_period": 14,
            "prior_swing_bars": 5,

            # --- Volume Confirmation ---
            "vol_zscore_window": 20,
            "vol_zscore_threshold": 1.8,    # Standard institutional accumulation.

            # --- Scoring ---
            "score_threshold": 0.65,

            # --- Weights (Balanced) ---
            "weights": {
                "breakout": 0.30,
                "squeeze": 0.15,
                "trend": 0.25,    # Trend strength matters more for swings
                "volume": 0.15,
                "alignment": 0.15
            },

            # --- Filters ---
            "min_atr_percent": 1.2,         # <1.2% ATR stocks are dead money for options swings.
            "breakout_margin_atr": 0.25,    # Require clearer confirmation to avoid "wicks".
        },
        
        "leaps": {
            # ---------------- LEAPS POSITION (The "Macro Trend") ----------------
            # Ideal Strategy: LEAPS (>180 DTE) or PMCC
            # Goal: Institutional trend following.
            # Logic: Avoid false signals by using slower, wider bands.
            
            "bb_period": 50,                # Institutional timeframe.
            "bb_std": 2.2,                  # Reduce false positives (Widowmaker filter).
            
            # --- Squeeze Logic ---
            "trailing_bw_window": 200,      # Yearly context.
            "bw_percentile_threshold": 30.0,

            # --- Trend Filter ---
            "ema_fast": 20,
            "ema_slow": 50,                 # Golden Cross zone.

            # --- Indicators ---
            "atr_period": 20,
            "adx_period": 14,
            "rsi_period": 21,
            "prior_swing_bars": 10,

            # --- Volume Confirmation ---
            "vol_zscore_window": 60,        # Quarterly volume baseline.
            "vol_zscore_threshold": 1.2,    # Just steady buying, no need for explosion.

            # --- Scoring ---
            "score_threshold": 0.75,

            # --- Weights (Trend Focused) ---
            "weights": {
                "breakout": 0.20,
                "squeeze": 0.10,
                "trend": 0.30,    # ADX/Trend is King for LEAPS
                "volume": 0.10,
                "alignment": 0.30 # Major EMA Alignment is mandatory
            },

            # --- Filters ---
            "min_atr_percent": 1.0          # Even for LEAPS, avoid zombies.
        }
    }