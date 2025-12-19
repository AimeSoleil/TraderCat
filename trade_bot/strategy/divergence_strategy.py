from typing import List, Optional, Dict, Any, Tuple, Callable
import statistics

from trade_bot.strategy.exit_planner import ExitPlanner
from trade_bot.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class DivergenceStrategy(TradingStrategy):
    """
    Divergence Strategy (Refactored for Production)
    - Fix: Added 'freshness' check to ensure signals are traded immediately upon fractal confirmation.
    - Fix: Consolidated logic to reduce code duplication.
    - Improvement: Added RSI context filters (Overbought/Oversold).
    """

    def __init__(
        self,
        swing_window: int = 5,
        lookback_swings: int = 60,
        rsi_period: int = 14,
        macd_params: Optional[Dict[str, int]] = None,
        atr_period: int = 14,
        adx_period: int = None,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.75,
        data_provider: Any = None,
    ):
        self.swing_window = int(swing_window)
        self.lookback_swings = int(lookback_swings)
        self.rsi_period = int(rsi_period)
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.atr_period = int(atr_period)
        self.adx_period = int(adx_period) if adx_period else None
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # Fields
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.adx_field = f"ADX_{self.adx_period}"

    def get_name(self) -> str:
        return "DivergenceStrategy"

    def get_lookback_window(self) -> int:
        return (
            max(
                self.lookback_swings,
                self.swing_window * 2 + 5,
                self.rsi_period,
                self.atr_period,
                (self.adx_period or 0),
                (self.macd_params["slow"] or 0),
            )
            + 5
        )

    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.DIVERGENCE,
            FactorName.TREND_STRENGTH,
            FactorName.VOLUME_CONFIRM,
            FactorName.MOMENTUM_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

    # --- Helper: Core Divergence Logic ---
    def _check_divergence_logic(
        self,
        pts: List[Tuple[int, float]],
        indicator_history: List[float],
        candles_len: int,
        compare_price: Callable[[float, float], bool],     # e.g. lambda p2, p1: p2 > p1
        compare_indicator: Callable[[float, float], bool], # e.g. lambda i2, i1: i2 <= i1
        freshness_threshold: int
    ) -> Tuple[bool, Optional[float], Optional[float], int, int]:
        """
        Generic detector for divergence.
        Returns: (found, val1, val2, idx1, idx2)
        """
        if len(pts) < 2:
            return False, None, None, -1, -1
        
        (i1, p1), (i2, p2) = pts[-2], pts[-1]
        
        # 1. Freshness Check (Critical Fix)
        # The pivot i2 is confirmed only after 'swing_window' bars.
        # So the signal is valid if current_bar is exactly (or very close to) i2 + swing_window.
        # We allow a small buffer (e.g., 1 bar) in case of calculation delays.
        current_idx = candles_len - 1
        confirmation_idx = i2 + self.swing_window
        
        if current_idx < confirmation_idx:
            return False, None, None, -1, -1 # Pivot not confirmed yet (shouldn't happen if find_fractal is correct)
        
        if current_idx > confirmation_idx + 1:
            return False, None, None, -1, -1 # Signal is stale (happened >1 bar ago)

        # 2. Price Comparison
        if not compare_price(p2, p1):
            return False, None, None, -1, -1

        # 3. Indicator Comparison
        # Handle indicator alignment safely
        hist_len = len(indicator_history)
        offset = candles_len - hist_len
        
        # Map candle indices i1, i2 to indicator indices
        ind_i1 = i1 - offset
        ind_i2 = i2 - offset
        
        if ind_i1 < 0 or ind_i2 < 0 or ind_i2 >= hist_len:
            return False, None, None, -1, -1
            
        val1 = indicator_history[ind_i1]
        val2 = indicator_history[ind_i2]
        
        if val1 is None or val2 is None:
            return False, None, None, -1, -1

        if compare_indicator(val2, val1):
            return True, val1, val2, i1, i2
            
        return False, None, None, -1, -1

    # ---------- Main Logic ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="Data insufficient")

        # 1. Data Prep
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params)
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        closes = [float(c.close) for c in candles]
        vols = [float(c.volume) for c in candles]
        dates = [c.date for c in candles]
        close = closes[-1]

        atr_hist = [getattr(x, self.atr_field, None) for x in atr_series]
        adx_hist = [getattr(x, self.adx_field, None) for x in adx_series]
        rsi_hist = [getattr(x, self.rsi_field, None) for x in rsi_series]
        macd_hist = [getattr(x, self.macd_hist_field, None) for x in macd_series] if macd_series else []
        
        curr_atr = atr_hist[-1] if atr_hist else 0.0

        # 2. Volume Check
        vol_ok, vol_z = self._check_volume_zscore(vols, self.vol_zscore_window, self.vol_zscore_threshold)

        # 3. Find Fractals
        # Use a slice to speed up, but ensure enough buffer
        slice_start = max(0, len(highs) - self.lookback_swings - 50)
        high_pts, low_pts = self._find_fractal_swings(highs[slice_start:], lows[slice_start:], self.swing_window)
        # Rebase indices
        high_pts = [(i + slice_start, v) for i, v in high_pts]
        low_pts = [(i + slice_start, v) for i, v in low_pts]

        # 4. Detect Divergences
        # We check all 4 types, but prioritize Regular > Hidden
        
        div_type = None
        found = False
        ind_vals = (None, None)
        swing_dates = (None, None)
        
        # Logic Definitions
        # Regular Bear: Price HH, Ind Lower
        # Regular Bull: Price LL, Ind Higher
        # Hidden Bear:  Price LH, Ind Higher
        # Hidden Bull:  Price HL, Ind Lower
        
        check_configs = [
            # (Type, Points, PriceComp, IndComp, Side)
            ("regular_bear", high_pts, lambda p2, p1: p2 > p1, lambda i2, i1: i2 <= i1, "short"),
            ("regular_bull", low_pts,  lambda p2, p1: p2 < p1, lambda i2, i1: i2 >= i1, "long"),
            ("hidden_bear",  high_pts, lambda p2, p1: p2 < p1, lambda i2, i1: i2 > i1,  "short"),
            ("hidden_bull",  low_pts,  lambda p2, p1: p2 > p1, lambda i2, i1: i2 < i1,  "long"),
        ]

        best_result = None
        
        for name, pts, p_comp, i_comp, side in check_configs:
            # Try RSI first
            is_div, v1, v2, idx1, idx2 = self._check_divergence_logic(
                pts, rsi_hist, len(candles), p_comp, i_comp, self.swing_window
            )
            
            # If no RSI div, try MACD Hist
            if not is_div and macd_hist:
                is_div, v1, v2, idx1, idx2 = self._check_divergence_logic(
                    pts, macd_hist, len(candles), p_comp, i_comp, self.swing_window
                )
            
            if is_div:
                # [Optimization] RSI Context Filter (Enhanced for Swing)
                rsi_val = rsi_hist[-1] if rsi_hist else 50
                
                # Regular Bear (Top Reversal): Ideally RSI should be Overbought (>60) to be significant.
                # If RSI is 52 and diverging, it's weak.
                if name == "regular_bear" and rsi_val < 60: continue 
                
                # Regular Bull (Bottom Reversal): Ideally RSI should be Oversold (<40).
                if name == "regular_bull" and rsi_val > 40: continue 

                # Hidden Divergence (Trend Continuation):
                # Hidden Bull: Price HL, RSI Lower. Ideally happens in Bull Trend (RSI > 40).
                if name == "hidden_bull" and rsi_val < 40: continue
                
                # Hidden Bear: Price LH, RSI Higher. Ideally happens in Bear Trend (RSI < 60).
                if name == "hidden_bear" and rsi_val > 60: continue

                found = True
                div_type = name
                ind_vals = (v1, v2)
                swing_dates = (dates[idx1], dates[idx2])
                
                # Calculate Score
                mom_ok = self._momentum_confirm(rsi_hist, macd_hist, prefer=side)
                trend_strength = self._check_trend_and_volatility(
                    atr_hist, adx_hist, closes, 100, 
                    mode='reversal' if 'regular' in name else 'trend'
                )
                
                factors = [
                    Factor(FactorName.DIVERGENCE, f"{name} Triggered", 0.4, True),
                    Factor(FactorName.TREND_STRENGTH, "Trend/Vol OK", 0.2, trend_strength.signal),
                    Factor(FactorName.MOMENTUM_CONFIRM, "Momentum OK", 0.2, mom_ok),
                    Factor(FactorName.VOLUME_CONFIRM, "Volume OK", 0.15, vol_ok),
                    Factor(FactorName.CONFLUENCE_BONUS, "Bonus", 0.05, mom_ok and trend_strength.signal)
                ]
                
                engine = ScoringEngine(
                    base_threshold=self.score_threshold,
                    required_factors=[FactorName.DIVERGENCE],
                    determined_factors=[FactorName.DIVERGENCE],
                    is_volatility_ok=trend_strength.volatility['signal']
                )
                
                res: ScoringResult = engine.compute_score(factors, side=side)
                
                # Priority: Regular > Hidden. If we found Regular, stop.
                if 'regular' in name:
                    best_result = (res, name, swing_dates, ind_vals)
                    break
                else:
                    # Keep hidden result but continue checking for regular
                    if best_result is None:
                        best_result = (res, name, swing_dates, ind_vals)

        # 5. Final Output
        if not best_result or best_result[0].signal == 'hold':
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=dates[-1], confidence=0.0, reason="No divergence")

        res, d_type, s_dates, i_vals = best_result
        
        details = {
            "type": d_type,
            "swing_dates": s_dates,
            "indicator_vals": i_vals,
            "atr": curr_atr,
            "vol_z": vol_z
        }

        if res.signal != 'hold':
            planner = ExitPlanner(highs=highs, lows=lows, atr=curr_atr, close_price=close)
            plan = planner.make_exit_plan(trading_signal=res.signal)
            details["plan"] = plan

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=res.signal,
            date=dates[-1],
            confidence=round(res.score, 3),
            reason=" | ".join(res.reasons),
            details=details,
        )

def make_divergence_presets() -> Dict[str, Dict[str, Any]]:
    """
    Divergence strategy presets based on algo trading best practices:
    - swing: Optimized for catching trend reversals (Regular) and trend continuations (Hidden).
    """

    # ---------------- SWING TRADING (Optimized) ----------------
    swing = {
        # --- Pivot Detection ---
        # 5 bars left/right is standard for identifying significant swing points.
        "swing_window": 5,                  
        "lookback_swings": 60,              # Look back ~3 months for context.

        # --- Indicators ---
        "rsi_period": 14,                   # Standard RSI.
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        
        # --- Context Filters ---
        "atr_period": 14,
        "adx_period": 14,                   
        # Note: In code logic, we should ideally ignore Regular Divergence if ADX > 40 (Strong Trend).

        # --- Volume Confirmation ---
        # Divergence needs volume validation to confirm the momentum shift.
        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.5,        

        # --- Scoring ---
        # Divergence is subjective and prone to false signals. 
        # We set a high bar (0.70) to ensure multiple factors align.
        "score_threshold": 0.70             
    }

    return {
        "swing": swing
    }
