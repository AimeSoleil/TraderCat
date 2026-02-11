from typing import List, Dict, Any, Optional
from tradercat.core.strategy.trading_strategy import TradingStrategy
from tradercat.core.strategy.signal_model import SignalModel
from tradercat.core.strategy.exit_planner import ExitPlanner
from tradercat.core.strategy.signal_scorer import Factor, FactorName, ScoringEngine
from tradercat.logger.logger import get_logger

from tradercat.core.strategy.chart_pattern.pivot_utils import PivotFinder
from tradercat.core.strategy.chart_pattern.reversal import (
    DoubleBottomDetector,
    DoubleTopDetector,
    HeadAndShouldersTopDetector,
    HeadAndShouldersBottomDetector,
    TripleBottomDetector,
)
from tradercat.core.strategy.chart_pattern.continuation import (
    AscendingTriangleDetector,
    DescendingTriangleDetector,
    BullFlagDetector,
)
from tradercat.core.strategy.chart_pattern.base_detector import ChartData, PatternResult

logger = get_logger(__name__)


class ChartPatternStrategy(TradingStrategy):
    """
    Chart Pattern Strategy (Macro Structure) - Refactored OOP.
    Detects classic geometric price patterns based on Pivots.
    Integrated with ScoringEngine for quality assessment.
    """

    def __init__(
        self,
        # Pivot Config
        pivot_left_bars: int = 5,
        pivot_right_bars: int = 5,
        # Pattern Config
        price_similarity_threshold: float = 0.03,
        slope_tolerance: float = 0.1,
        # Confirmation
        require_volume_breakout: bool = True,
        # Indicators
        atr_period: int = 14,
        adx_period: int = 14,
        ema_trend_period: int = 200, 
        volatility_lookback_window: int = 20, # <--- [NEW] Configurable
        vol_zscore_window: int = 20,
        vol_score_threshold: float = 1.5,
        # Scoring
        score_threshold: float = 0.6,
        weights: Optional[Dict[str, float]] = None,

        data_provider: Any = None,
    ):
        self.require_vol = require_volume_breakout
        self.atr_period = int(atr_period)
        self.adx_period = int(adx_period)
        self.ema_trend_period = int(ema_trend_period)
        self.vol_lookback = int(volatility_lookback_window) # <--- [NEW]
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_score_threshold = float(vol_score_threshold)
        self.provider = data_provider

        self.atr_field = f"ATRr_{self.atr_period}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.ema_trend_field = f"close_EMA_{self.ema_trend_period}"

        self.score_threshold = score_threshold

        # Default Weights (Balanced Base)
        default_weights = {
            "pattern_quality": 0.30, 
            "volume_confirm": 0.25,  
            "trend_alignment": 0.20,
            "trend_strength": 0.15,
            "volatility_ok": 0.10
        }
        self.weights = {**default_weights, **(weights or {})}

        # Initialize Helper
        self.pivot_finder = PivotFinder(pivot_left_bars, pivot_right_bars)

        # Initialize Detectors
        args = (price_similarity_threshold, slope_tolerance)
        self.detectors = [
            # Reversals
            DoubleBottomDetector(*args),
            DoubleTopDetector(*args),
            HeadAndShouldersTopDetector(*args),
            HeadAndShouldersBottomDetector(*args),
            TripleBottomDetector(*args),
            # Continuations
            AscendingTriangleDetector(*args),
            DescendingTriangleDetector(*args),
            # Special
            BullFlagDetector(*args),
        ]

    def get_name(self) -> str:
        return "ChartPatterns"

    def get_lookback_window(self) -> int:
        return max(150, self.ema_trend_period + 20)

    def support_scoring_factors(self) -> List[FactorName]:
        return [
            FactorName.CHART_PATTERN_DETECTED,
            FactorName.VOLUME_CONFIRM,
            FactorName.EMA_ALIGNMENT,
            FactorName.TREND_STRENGTH,
            FactorName.VOLATILITY_HEALTH
        ]

    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(date=None, symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="Insufficient Data")

        # 1. Prepare Raw Data
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        closes = [float(c.close) for c in candles]
        close = closes[-1]
        vols = [float(c.volume) for c in candles if c.volume]
        dates = [c.date for c in candles]
        
        # Indicators & Helper Tools
        try:
            atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
            curr_atr = getattr(atr_series[-1], self.atr_field, 0.0) if atr_series else 0.0
            
            # Context: EMA 200
            ema_series = self.provider.get_indicator("ema", candles, {"length": self.ema_trend_period})
            curr_ema_trend = getattr(ema_series[-1], self.ema_trend_field, 0.0) if ema_series else 0.0
            
            # --- [NEW] Use Unified Trend & Volatility Check ---
            # This handles ADX calculation and volatility health internally
            adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})
            
            trend_strength = self._check_trend_and_volatility(
                atr_val_history=[getattr(x, self.atr_field, 0) for x in atr_series],
                adx_val_history=[getattr(x, self.adx_field, 0) for x in adx_series],
                price_history=closes,
                window=self.vol_lookback,
                mode='trend',
                ignore_volatility=True,       # [KEY CHANGE] Just want ADX status
                trend_quantiles=[0.5, 0.25]
            )
            
            raw_trend_signal = trend_strength.signal   
            
            # Use the volatility component independently for the "Environment" score
            is_vol_healthy = trend_strength.volatility.get('signal', False)

        except Exception as e:
            logger.error(f"Error checking trend/vol: {e}")
            curr_atr = 0.0
            curr_ema_trend = 0.0
            raw_trend_signal = False
            is_vol_healthy = True 

        # 2. Identify Pivots
        p_highs, p_lows = self.pivot_finder.find_pivots(highs, lows)
        
        # 3. Create Context Object
        chart_data = ChartData(
            current_close=close,
            pivots_high=p_highs,
            pivots_low=p_lows,
            highs_history=highs,
            lows_history=lows,
            atr=curr_atr
        )
        
        patterns: List[PatternResult] = []
        
        # 4. Pattern Detection
        for detector in self.detectors:
            if result := detector.detect(chart_data):
                patterns.append(result)

        if patterns:
            best_p = patterns[-1]
        else:
            best_p = PatternResult("", "hold", 0.0, 0.0, 0.0)
        
        # [CRITICAL LOGIC] Adapt Context based on Pattern Type
        # Continuations (Flags, Triangles) -> Require Trend Strength
        # Reversals (Bottoms, Tops) -> Ignore Trend Strength (or accept weak trend)
        is_continuation = "Flag" in best_p.name or "Triangle" in best_p.name
        
        if is_continuation:
            is_trend_good = raw_trend_signal # Must have trend
        else:
            is_trend_good = True # Reversals don't need strong trend props
        
        # 5. Factor Calculation
        
        # Volume Z-Score Logic: Check for a valid breakout volume
        if self.require_vol:
            # We check a small window around the breakout
            vol_breakout, vol_breakout_z = self._check_volume_zscore(vols, self.vol_zscore_window, self.vol_score_threshold)
        else:
            vol_breakout = True # If configured to ignore volume
        
        # Trend Alignment (EMA 200)
        is_aligned = (best_p.bias == "long" and close > curr_ema_trend) or \
                    (best_p.bias == "short" and close < curr_ema_trend)

        # 6. Scoring Engine
        factors = [
            Factor(
                FactorName.CHART_PATTERN_DETECTED, 
                f"{best_p.name}", 
                self.weights["pattern_quality"], 
                True
            ),
            Factor(
                FactorName.VOLUME_CONFIRM, 
                "Volume Surge", 
                self.weights["volume_confirm"], 
                vol_breakout
            ),
            Factor(
                FactorName.EMA_ALIGNMENT, 
                "Trend Aligned", 
                self.weights["trend_alignment"], 
                is_aligned
            ),
            Factor(
                FactorName.TREND_STRENGTH, 
                "Context (Trend/Struct)", 
                self.weights.get("trend_strength", 0.15), 
                is_trend_good
            ),
            # [NEW] Integrated Volatility Check
            Factor(
                FactorName.VOLATILITY_HEALTH, 
                "Healthy Volatility", 
                self.weights.get("volatility_ok", 0.10), 
                is_vol_healthy
            )
        ]
        
        engine = ScoringEngine(
            base_threshold=self.score_threshold,
            required_factors=self.support_scoring_factors(), 
            determined_factors=[FactorName.CHART_PATTERN_DETECTED],
            is_volatility_ok=is_vol_healthy, # Gatekeeper usage
            volatility_penalty=0.05
        )
        score_res = engine.compute_score(factors, side=best_p.bias)

        # 7. Construct Result
        # Calculate extra technical context for professional analysis
        current_adx = getattr(adx_series[-1], self.adx_field, 0.0) if adx_series else 0.0
        avg_vol = sum(vols[-self.vol_zscore_window:]) / self.vol_zscore_window if len(vols) >= self.vol_zscore_window else 0.0 
        rel_vol = (vols[-1] / avg_vol) if avg_vol > 0 else 0.0
        atr_pct = (curr_atr / close * 100.0) if close > 0 else 0.0
        ema_dist_pct = ((close - curr_ema_trend) / curr_ema_trend * 100.0) if curr_ema_trend > 0 else 0.0
        vol_z_val = vol_breakout_z if vol_breakout_z is not None else 0.0
        
        # Calculate Reward/Risk Ratio based on Pattern Targets
        risk = abs(close - best_p.stop)
        reward = abs(best_p.target - close)
        rr_ratio = (reward / risk) if risk > 0 else 0.0

        details: Dict[str, Any] = {
            # OHLCV & Volume Context
            "open": round(float(candles[-1].open), 2),
            "high": round(highs[-1], 2),
            "low": round(lows[-1], 2),
            "close": round(close, 2),
            "volume": round(vols[-1], 0),
            f"avg_volume_{self.vol_zscore_window}": round(avg_vol, 0),
            f"rel_volume_{self.vol_zscore_window}": round(rel_vol, 2),
            f"vol_zscore_{self.vol_zscore_window}": round(vol_z_val, 2),

            # Pattern Geometry & Trade Logic
            "pattern": best_p.name,
            "target_price": round(best_p.target, 2),
            "stop_price": round(best_p.stop, 2),
            "reward_risk_ratio": round(rr_ratio, 2),
            
            # Trend Context
            f"adx_{self.adx_period}": round(current_adx, 1),
            f"ema_trend_{self.ema_trend_period}": round(curr_ema_trend, 2),
            "ema_dist_pct": round(ema_dist_pct, 2),
            "trend_aligned": is_aligned,
            
            # Volatility Environment
            f"atr_{self.atr_period}": round(curr_atr, 4),
            "atr_pct": round(atr_pct, 2),
        }

        if not patterns:
            return SignalModel(date=dates[-1], symbol=symbol, strategy=self.get_name(), signal="hold", confidence=0.0, reason="No patterns detected", details=details)
        
        # Only generating exit plan if signal is valid
        if score_res.signal != "hold":
            plan = ExitPlanner(
                highs=highs,
                lows=lows,
                atr=curr_atr,
                close_price=close
            ).make_exit_plan(best_p.bias)

            plan["stop_loss"] = best_p.stop
            plan["take_profit"] = best_p.target
            details["plan"] = plan

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=score_res.signal,
            date=dates[-1],
            confidence=round(score_res.score, 2),
            reason=f"{best_p.name} | {', '.join(score_res.reasons) if score_res.reasons else ''}",
            details=details
        )


def make_chart_pattern_presets() -> Dict[str, Dict[str, Any]]:
    """
    Returns preset configurations for ChartPatternStrategy (OPTIONS OPTIMIZED).
    Focus: Explosive breakouts (Vega Expansion) & Trend Continuation (Delta).
    """
    return {
        "macro_breakout": {
            # ---------------- MACRO STRUCTURE BREAKOUT (LEAPS / 60+ DTE) ----------------
            # Ideal Strategy: Buying LEAPS or Bull Call Spreads (Long Duration)
            # Goal: Catching major trend shifts (Checking Weekly/Monthly pivots).
            # Logic: "The Bigger the Base, the Higher in Space."
            
            "pivot_left_bars": 10,
            "pivot_right_bars": 10,         # Needs significant structure (months).
            "price_similarity_threshold": 0.05, # Allow some noise in macro patterns.
            "slope_tolerance": 0.05,
            
            "require_volume_breakout": True, # Institutional sponsorship MANDATORY for macro moves.
            
            "score_threshold": 0.75,        # High conviction only. Capital tie-up is high.
            
            "ema_trend_period": 200,        # The ultimate Bull/Bear line.
            "atr_period": 14,
            "adx_period": 14,
            "volatility_lookback_window": 50, # Quarterly volatility check.
            "vol_score_threshold": 2.0,     # [CHANGED] Require STRONG institutional confirmation
            "vol_zscore_window": 60,        # [CHANGED] Use longer window (3 months daily / 12 weeks weekly)
            # Rationale: Head & Shoulders, Double Bottoms take MONTHS to form.
            # Breakout volume must be CLEARLY above the base-building phase.
            # Using 60 bars ensures we're comparing against the ENTIRE consolidation period.
            
            "weights": {
                "pattern_quality": 0.25,    # Is it actually a Head & Shoulders?
                "volume_confirm": 0.20,     # Did institutions buy the breakout?
                "trend_alignment": 0.35,    # Don't fight the 200 EMA on macro trades.
                "trend_strength": 0.15,     # ADX matters less at the *start* of a new trend.
                "volatility_ok": 0.05
            }
        },

        "momentum_pattern": {
            # ---------------- MOMENTUM CONTINUATION (Swing / 21-45 DTE) ----------------
            # Ideal Strategy: Long Calls/Puts (Directional Gamma)
            # Goal: Trading Flags, Pennants, and Ascending Triangles mid-trend.
            # Logic: Trend is established; we are just buying the pause/breakout.
            
            "pivot_left_bars": 3,
            "pivot_right_bars": 3,          # Fast, tight structures (Flags).
            "price_similarity_threshold": 0.02, # Must be TIGHT consolidation.
            "slope_tolerance": 0.15,        # Allow steeper flags.
            
            "require_volume_breakout": True,
            
            "score_threshold": 0.65,
            
            "ema_trend_period": 50,         # Align with medium-term trend.
            "atr_period": 14,
            "adx_period": 14,
            "volatility_lookback_window": 20,
            "vol_score_threshold": 1.2,     # [CHANGED] Lower threshold for swing trades
            "vol_zscore_window": 20,        # [CHANGED] Match volatility_lookback_window
            # Rationale: Flags/Pennants form in 5-15 bars. We want to detect:
            # 1. Volume DRYING UP during consolidation (< 0.8 Z-Score)
            # 2. Volume EXPLOSION on breakout (> 1.2 Z-Score is enough for confirmation)
            # Using 20-bar window matches the "recent momentum context" perfectly.
            # This is NOT about institutional accumulation (that's macro).
            # This is about "retail FOMO + algorithmic breakout buying" kicking in.
            
            "weights": {
                "pattern_quality": 0.20,    # A flag is a flag.
                "volume_confirm": 0.30,     # Breakout VOLUME is the signal.
                "trend_alignment": 0.10,    # Less weight on EMA 200, more on flow.
                "trend_strength": 0.30,     # ADX MUST be high (>25) to buy flags.
                "volatility_ok": 0.10       # Avoid dead stocks.
            }
        },
        
        # --- [NEW PRESET] Intraday Scalping (0-7 DTE Options) ---
        "intraday_breakout": {
            # ---------------- INTRADAY VOLATILITY EXPLOSION (Scalp / 0-7 DTE) ----------------
            # Ideal Strategy: 0DTE Calls/Puts, Ratio Spreads
            # Goal: Catching intraday squeezes, news reactions, or opening range breakouts.
            # Logic: Speed & Volume are EVERYTHING. Technical patterns are loose.
            
            "pivot_left_bars": 2,
            "pivot_right_bars": 2,          # Micro-pivots (5-15min charts)
            "price_similarity_threshold": 0.03,
            "slope_tolerance": 0.20,        # Allow messy structures
            
            "require_volume_breakout": True,
            
            "score_threshold": 0.55,        # Lower bar (speed matters more than perfection)
            
            "ema_trend_period": 20,         # Intraday trend proxy
            "atr_period": 14,
            "adx_period": 14,
            "volatility_lookback_window": 10,
            
            # --- [AGGRESSIVE] Volume Parameters for INTRADAY ---
            "vol_score_threshold": 1.8,     # Must see CLEAR spike (FOMO/News)
            "vol_zscore_window": 10,        # ONLY compare to last 2 hours (if 5min chart)
            # Rationale: Intraday volume patterns are VERY different.
            # Opening 30min has 3x volume of midday.
            # We need RELATIVE to RECENT context, not daily average.
            # 1.8 Z-Score on a 10-bar window = "This bar is HOT right now"
            
            "weights": {
                "pattern_quality": 0.10,    # Pattern doesn't matter much intraday
                "volume_confirm": 0.40,     # Volume is 40% of decision (MOST important)
                "trend_alignment": 0.05,    # EMA 20 is weak on 5min charts
                "trend_strength": 0.35,     # ADX spike = momentum explosion
                "volatility_ok": 0.10
            }
        }
    }