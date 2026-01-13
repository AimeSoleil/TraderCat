from typing import List, Optional, Dict, Any, Tuple, Callable

from tradercat.strategy.exit_planner import ExitPlanner
from tradercat.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from tradercat.strategy.trading_strategy import TradingStrategy
from tradercat.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class DivergenceStrategy(TradingStrategy):
    """
    Divergence Strategy (Optimized).
    Detects Regular Divergence (Reversal) and Hidden Divergence (Trend Continuation)
    using Pivot/Fractal analysis on Price vs RSI/MACD.
    """

    def __init__(
        self,
        swing_window: int = 5,
        lookback_swings: int = 60,
        rsi_period: int = 14,
        macd_params: Optional[Dict[str, int]] = None,
        atr_period: int = 14,
        adx_period: int = 14,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.70,
        # [NEW] Dynamic Weights
        weights: Optional[Dict[str, float]] = None,
        data_provider: Any = None,
    ):
        self.swing_window = int(swing_window)
        self.lookback_swings = int(lookback_swings)
        self.rsi_period = int(rsi_period)
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.atr_period = int(atr_period)
        self.adx_period = int(adx_period)
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        
        # [NEW] Dynamic Weights configuration
        default_weights = {
            "divergence": 0.40,     # The core signal
            "trend_context": 0.20,  # Is the trend exhausted?
            "momentum": 0.15,       # Momentum hook confirmation
            "volume": 0.15,         # Volume expanding on reversal
            "confluence": 0.10      # Price action confirmation
        }
        self.weights = {**default_weights, **(weights or {})}
        
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
                self.adx_period,
                (self.macd_params["slow"] or 0),
            )
            + 10
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
        
        # We look at the last two confirmed swing points
        (i1, p1), (i2, p2) = pts[-2], pts[-1]
        
        # 1. Freshness Check
        # The pivot i2 is confirmed only after 'swing_window' bars.
        # We want to trade AS SOON AS it is confirmed.
        current_idx = candles_len - 1
        confirmation_idx = i2 + freshness_threshold
        
        # If current_idx < confirmation_idx, the pivot i2 isn't "locked in" yet.
        if current_idx < confirmation_idx:
            return False, None, None, -1, -1 
        
        # Signal Window: Allow signal within 1-2 bars of confirmation
        if current_idx > confirmation_idx + 2:
            return False, None, None, -1, -1 

        # 2. Price Comparison
        if not compare_price(p2, p1):
            return False, None, None, -1, -1

        # 3. Indicator Comparison
        hist_len = len(indicator_history)
        offset = candles_len - hist_len
        
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
    
    # --- Helper: Price Action Confirmation ---
    def _check_price_confirmation(self, candle: Any, side: str) -> bool:
        """
        Does the current candle confirm the reversal?
        """
        open_p = float(candle.open)
        close_p = float(candle.close)
        
        if side == "long":
            # Bullish candle (Green)
            return close_p > open_p
        elif side == "short":
            # Bearish candle (Red)
            return close_p < open_p
        return False

    # ---------- Main Logic ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(date=None, symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="Data insufficient")

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
        # Use a slice to speed up
        slice_start = max(0, len(highs) - self.lookback_swings - 50)
        high_pts, low_pts = self._find_fractal_swings(highs[slice_start:], lows[slice_start:], self.swing_window)
        # Rebase indices to global scope
        high_pts = [(i + slice_start, v) for i, v in high_pts]
        low_pts = [(i + slice_start, v) for i, v in low_pts]

        # 4. Detect Divergences
        check_configs = [
            # Regular Bear: Price HH, Ind Lower
            ("regular_bear", high_pts, lambda p2, p1: p2 > p1, lambda i2, i1: i2 <= i1, "short"),
            # Regular Bull: Price LL, Ind Higher
            ("regular_bull", low_pts,  lambda p2, p1: p2 < p1, lambda i2, i1: i2 >= i1, "long"),
            # Hidden Bear:  Price LH, Ind Higher
            ("hidden_bear",  high_pts, lambda p2, p1: p2 < p1, lambda i2, i1: i2 > i1,  "short"),
            # Hidden Bull:  Price HL, Ind Lower
            ("hidden_bull",  low_pts,  lambda p2, p1: p2 > p1, lambda i2, i1: i2 < i1,  "long"),
        ]

        best_result = None
        best_div_details = None
        
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
                # [Optimization] RSI Context Filter
                rsi_val = rsi_hist[-1] if rsi_hist else 50
                
                # Context Logic:
                # Regular divergences are REVERSALS -> Require Extreme RSI
                # Hidden divergences are CONTINUATIONS -> Require Trending RSI
                
                if name == "regular_bear" and rsi_val < 55: continue # Too weak
                if name == "regular_bull" and rsi_val > 45: continue 
                if name == "hidden_bull" and rsi_val < 40: continue # Bearish zone
                if name == "hidden_bear" and rsi_val > 60: continue # Bullish zone

                # === Scoring ===
                mom_ok = self._momentum_confirm(rsi_hist, macd_hist, prefer=side)
                
                # Trend check: Regular div needs exhaustion (Weak Trend), Hidden needs Strong Trend
                trend_mode = 'reversal' if 'regular' in name else 'trend'
                trend_strength = self._check_trend_and_volatility(
                    atr_hist, adx_hist, closes, 100, mode=trend_mode
                )
                
                # Price Action Confirmation
                price_confirmed = self._check_price_confirmation(candles[-1], side)

                factors = [
                    Factor(FactorName.DIVERGENCE, f"{name} Triggered", self.weights["divergence"], True),
                    Factor(FactorName.TREND_STRENGTH, "Trend Context", self.weights["trend_context"], trend_strength.signal),
                    Factor(FactorName.MOMENTUM_CONFIRM, "Momentum Hook", self.weights["momentum"], mom_ok),
                    Factor(FactorName.VOLUME_CONFIRM, "Volume OK", self.weights["volume"], vol_ok),
                    Factor(FactorName.CONFLUENCE_BONUS, "Price Action Confirmed", self.weights["confluence"], price_confirmed)
                ]
                
                engine = ScoringEngine(
                    base_threshold=self.score_threshold,
                    required_factors=[FactorName.DIVERGENCE],
                    determined_factors=[FactorName.DIVERGENCE],
                    is_volatility_ok=bool(trend_strength.volatility.get('signal', True))
                )
                
                res: ScoringResult = engine.compute_score(factors, side=side)
                
                # Save first valid result, prioritize Regular
                if not best_result or ('regular' in name and 'regular' not in best_result[1]):
                    best_result = (res, name)
                    best_div_details = {
                        "type": name,
                        "swing_indices": (idx1, idx2),
                        "indicator_vals": (v1, v2),
                        "atr": curr_atr,
                        "vol_z": vol_z,
                        "rsi": rsi_val
                    }
                    if 'regular' in name: break # Found strongest signal

        # 5. Final Output
        if not best_result or best_result[0].signal == 'hold':
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=dates[-1], confidence=0.0, reason="No valid divergence")

        res, d_name = best_result
        
        if res.signal != 'hold':
            planner = ExitPlanner(highs=highs, lows=lows, atr=curr_atr, close_price=close)
            plan = planner.make_exit_plan(trading_signal=res.signal)
            # Divergence trades can have looser stops if confirmed by structure
            best_div_details["plan"] = plan

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=res.signal,
            date=dates[-1],
            confidence=round(res.score, 3),
            reason=" | ".join(res.reasons),
            details=best_div_details,
        )

def make_divergence_presets() -> Dict[str, Dict[str, Any]]:
    return {
        "swing": {
            # ---------------- SWING TRADING ----------------
            "swing_window": 5,
            "lookback_swings": 60,
            "rsi_period": 14,
            "macd_params": {"fast": 12, "slow": 26, "signal": 9},
            "atr_period": 14,
            "adx_period": 14,
            "vol_zscore_window": 20,
            "vol_zscore_threshold": 1.5,
            "score_threshold": 0.70,
            
            # [NEW] Tuned Weights
            "weights": {
                "divergence": 0.40,
                "trend_context": 0.20,
                "momentum": 0.15,
                "volume": 0.15,
                "confluence": 0.10
            }
        },
    
        "position": {
            # ---------------- POSITION TRADING ----------------
            "swing_window": 8,                 # Significant pivots only
            "lookback_swings": 120,            # Deep history
            "rsi_period": 14,
            "macd_params": {"fast": 12, "slow": 26, "signal": 9},
            "atr_period": 14,
            "adx_period": 14,
            "vol_zscore_window": 50,
            "vol_zscore_threshold": 1.2,       # Lower volume threshold for macro moves
            "score_threshold": 0.75,           # Higher conviction needed
            
            # [NEW] Tuned Weights
            "weights": {
                "divergence": 0.35,
                "trend_context": 0.25,         # Macro trend failure is key
                "momentum": 0.20,
                "volume": 0.10,
                "confluence": 0.10
            }
        }
    }
