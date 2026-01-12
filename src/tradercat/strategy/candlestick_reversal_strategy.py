from typing import List, Optional, Dict, Any, Literal

from tradercat.strategy.candle_pattern.pattern_detector_orch import PatternDetectorsOrchestrator
from tradercat.strategy.exit_planner import ExitPlanner
from tradercat.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from tradercat.strategy.trading_strategy import TradingStrategy
from tradercat.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class CandlestickReversalStrategy(TradingStrategy):
    """
    Candlestick Reversal Strategy (Trend Pullback Reversal).
    
    Core Logic:
    - Identifies reversal patterns (Hammer, Engulfing, etc.) that align with the major trend.
    - Example: In an Uptrend (EMA Fast > Slow), look for Bullish Reversal candles (buying the dip).
    """
    def __init__(
        self,
        ema_fast: int = 13,
        ema_slow: int = 34,
        atr_period: int = 14,
        rsi_period: int = 14,
        adx_period: int = 14,
        macd_params: Optional[Dict[str,int]] = None,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 2.0,
        score_threshold: float = 0.6,
        # [NEW] Dynamic Weights
        weights: Optional[Dict[str, float]] = None,
        data_provider: Any = None
    ):
        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.atr_period = int(atr_period)
        self.rsi_period = int(rsi_period)
        self.adx_period = adx_period
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        
        # [NEW] Dynamic Weights configuration
        default_weights = {
            "candle": 0.35,     # The Pattern itself
            "volume": 0.20,     # Volume Confirmation
            "trend_strength": 0.10, # ADX
            "trend_dir": 0.15,  # EMA Alignment (Trend Following)
            "momentum": 0.10,   # RSI/MACD Hook
            "confirm": 0.10     # Price Action Confirmation
        }
        self.weights = {**default_weights, **(weights or {})}
        
        self.provider = data_provider

        # 指标字段名约定
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"

    def get_name(self) -> str:
        return "CandlestickReversal"
    
    def get_lookback_window(self) -> int:
        macd_max = max(int(self.macd_params.get("fast", 0) or 0),
                        int(self.macd_params.get("slow", 0) or 0),
                        int(self.macd_params.get("signal", 0) or 0))
        base = max(self.ema_slow, self.atr_period, self.rsi_period, macd_max, 3)
        return int(base + 10)

    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.REVERSAL_CANDLE,
            FactorName.VOLUME_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.TREND_DIRECTION_CONFIRM,
            FactorName.MOMENTUM_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]
        
    # --- Helper Implementation ---

    def _check_reversal_confirmation(self, highs: List[float], lows: List[float], closes: List[float], effective_bias: str) -> bool:
        """
        Strong Price Action Confirmation.
        Instead of just checking Close > Prev Close (which is redundant for patterns like Engulfing),
        we check if the candle closed strongly (in the top/bottom third of its range).
        """
        if len(closes) < 2:
            return False
            
        h, l, c = highs[-1], lows[-1], closes[-1]
        rng = h - l
        
        # Avoid division by zero
        if rng <= 0: 
            return False
            
        if effective_bias == "long":
            # 1. Close higher than previous close (Basic momentum)
            # 2. Close in top 35% of the range (Strong bull finish, no long upper wick)
            is_strong_close = (c - l) / rng >= 0.65
            is_green = c > closes[-2]
            return is_strong_close and is_green
            
        elif effective_bias == "short":
            # 1. Close lower than previous close
            # 2. Close in bottom 35% of the range (Strong bear finish, no long lower wick)
            is_strong_close = (h - c) / rng >= 0.65
            is_red = c < closes[-2]
            return is_strong_close and is_red
            
        return False

    # ---------- 主决策逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        # logger.info(f"🔍 Generating Reversal signal for {symbol}...") # Reduced log noise
        
        if not candles or len(candles) < max(self.ema_slow, self.atr_period, 3):
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold",
                                date=None, reason="insufficient data", confidence=0.0)

        # 提取 OHLCV
        opens = [float(getattr(c, "open")) for c in candles]
        highs = [float(getattr(c, "high")) for c in candles]
        lows = [float(getattr(c, "low")) for c in candles]
        closes = [float(getattr(c, "close")) for c in candles]
        vols = [getattr(c, "volume", None) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]
        close = closes[-1]

        # 指标获取
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params)
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        rsi_val_history = [getattr(r, self.rsi_field, None) for r in rsi_series]
        macd_hist_val_history = [getattr(m, self.macd_hist_field, None) for m in macd_series] if macd_series else []
        
        # 安全获取 EMA
        current_ema_fast_val = getattr(ema_fast_series[-1], self.ema_fast_field, None) if ema_fast_series else None
        current_ema_slow_val = getattr(ema_slow_series[-1], self.ema_slow_field, None) if ema_slow_series else None
        current_atr_val = atr_val_history[-1] if atr_val_history else 0.0
        current_adx_val = adx_val_history[-1] if adx_val_history else 0.0
        current_rsi_val = rsi_val_history[-1] if rsi_val_history else 50.0

        # ---------- 趋势判断 (Major Trend) ----------
        trend_long = (current_ema_fast_val > current_ema_slow_val) if (current_ema_fast_val and current_ema_slow_val) else False
        trend_short = (current_ema_fast_val < current_ema_slow_val) if (current_ema_fast_val and current_ema_slow_val) else False

        # ---------- 烛形检测 ----------
        idx = len(candles) - 1
        orchestrator = PatternDetectorsOrchestrator()

        # 顺势交易：只在上升趋势找看涨反转（Ex: Hammer），下降趋势找看跌反转（Ex: Shooting Star）
        res_bull = orchestrator.detect_bullish(opens, highs, lows, closes, vols, idx, atr=current_atr_val, trend_ok=trend_long)
        res_bear = orchestrator.detect_bearish(opens, highs, lows, closes, vols, idx, atr=current_atr_val, trend_ok=trend_short)

        found_bull = bool(res_bull and res_bull.is_pattern)
        found_bear = bool(res_bear and res_bear.is_pattern)

        # 冲突解决
        chosen_res = None
        if found_bull and trend_long:
            chosen_res = res_bull
        elif found_bear and trend_short:
            chosen_res = res_bear
        elif found_bull and not found_bear: # Fallback if no trend constraint enforced strictly
            chosen_res = res_bull
        elif found_bear and not found_bull:
            chosen_res = res_bear

        pattern = chosen_res.name if chosen_res else None
        raw_bias = chosen_res.bias if chosen_res else None

        # 确定有效方向
        effective_bias = raw_bias
        if effective_bias in (None, "neutral"):
            # Try to infer if bias is missing from pattern result
            if chosen_res == res_bull: effective_bias = "long"
            elif chosen_res == res_bear: effective_bias = "short"

        # ---------- 辅助确认 ----------
        trend_strength = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=adx_val_history,
            price_history=closes,
            window=100,
            mode='trend', # We want TRENDING markets to buy dips in
            trend_quantiles=[0.6, 0.4]
        )

        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

        # 动量确认
        mom_ok = False
        if chosen_res and chosen_res.is_pattern and effective_bias:
            mom_ok = self._momentum_confirm(
                rsi_val_history=rsi_val_history,
                macd_hist_val_history=macd_hist_val_history,
                prefer=effective_bias
            )

        # 价格行为确认 (Strong Close?)
        reversal_confirmed = False
        if effective_bias:
            reversal_confirmed = self._check_reversal_confirmation(
                highs, lows, closes, effective_bias
            )

        # ---------- 评分系统 ----------
        found_any = bool(chosen_res and chosen_res.is_pattern)

        trend_direction_ok = (
            (effective_bias == "long" and trend_long) or
            (effective_bias == "short" and trend_short)
        )

        factors = [
            # 1. The Pattern
            Factor(
                FactorName.REVERSAL_CANDLE, 
                f"Pattern: {pattern}", 
                self.weights["candle"], 
                found_any
            ),
            # 2. Volume
            Factor(
                FactorName.VOLUME_CONFIRM, 
                "Volume Surge", 
                self.weights["volume"], 
                vol_ok
            ),
            # 3. Market State (ADX)
            Factor(
                FactorName.TREND_STRENGTH, 
                "Healthy Trend (ADX)", 
                self.weights["trend_strength"], 
                bool(trend_strength.signal)
            ),
            # 4. Alignment
            Factor(
                FactorName.TREND_DIRECTION_CONFIRM, 
                "With Major Trend (EMA)", 
                self.weights["trend_dir"], 
                trend_direction_ok
            ),
            # 5. Momentum Hook
            Factor(
                FactorName.MOMENTUM_CONFIRM, 
                "Momentum Hook", 
                self.weights["momentum"], 
                mom_ok
            ),
            # 6. Price Confirmation
            Factor(
                FactorName.CONFLUENCE_BONUS, 
                "Price Confirmation", 
                self.weights["confirm"], 
                reversal_confirmed
            )
        ]

        engine = ScoringEngine(
            base_threshold=self.score_threshold,
            required_factors=self.support_scoring_factors(),
            # Strict: Must have a pattern
            determined_factors=[FactorName.REVERSAL_CANDLE],
            is_volatility_ok=bool(trend_strength.volatility.get('signal', True))
        )

        side_action = effective_bias if found_any else "neutral"
        result: ScoringResult = engine.compute_score(factors, side=side_action)

        details = {
            "pattern": pattern,
            "ema_fast": current_ema_fast_val,
            "ema_slow": current_ema_slow_val,
            "atr": current_atr_val,
            "adx": current_adx_val,
            "vol_zscore": round(volume_z, 3) if volume_z is not None else None,
            "trend_direction_ok": trend_direction_ok,
            "momentum_ok": mom_ok,
            "reversal_confirmed": reversal_confirmed,
            "score": round(result.score, 3),
        }
            
        if result.signal != 'hold':
            planner = ExitPlanner(highs=highs, lows=lows, atr=current_atr_val, close_price=close)
            
            # [Optimization] Dynamic Stop Loss for Reversals
            plan = planner.make_exit_plan(trading_signal=result.signal)
            
            # Adjust stop loss based on ADX (Weaker trend = tight stop; Strong trend = looser stop)
            # If ADX is low, trend is weak -> Tight Stop
            sl_mult = 1.0 if current_adx_val < 25 else 1.5
            
            if result.signal == 'long':
                plan['stop_loss'] = close - (sl_mult * current_atr_val)
            elif result.signal == 'short':
                plan['stop_loss'] = close + (sl_mult * current_atr_val)
                
            details.update({"plan": plan})

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            date=dates[-1],
            confidence=round(min(1.0, result.score), 3),
            reason=" | ".join(result.reasons),
            details=details
        )

def make_candlestick_reversal_presets() -> Dict[str, Dict[str, Any]]:
    """
    Returns a dictionary of all available presets for Candlestick Reversal Strategy.
    """
    return {
        "swing": {
            # ---------------- SWING TRADING (Optimized) ----------------
            # Strategy: "Buy the Dip" in an Uptrend / "Sell the Rally" in a Downtrend.
            
            "ema_fast": 9,
            "ema_slow": 21,
            "atr_period": 14,
            "rsi_period": 14,       
            "adx_period": 14,       
            "macd_params": {"fast": 12, "slow": 26, "signal": 9},
            "vol_zscore_window": 20,
            "vol_zscore_threshold": 1.5,
            "score_threshold": 0.65,
            
            # [NEW] Tuned Weights
            "weights": {
                "candle": 0.35,
                "trend_dir": 0.20,     # Must follow trend
                "volume": 0.15,
                "momentum": 0.15,
                "trend_strength": 0.10,
                "confirm": 0.05
            }
        },

        "position": {
            # ---------------- POSITION TRADING ----------------
            "ema_fast": 50,
            "ema_slow": 200,
            "atr_period": 14,
            "rsi_period": 14,
            "adx_period": 14,
            "macd_params": {"fast": 12, "slow": 26, "signal": 9},
            "vol_zscore_window": 50,
            "vol_zscore_threshold": 2.0, 
            "score_threshold": 0.75,
            
            # [NEW] Tuned Weights for Position
            "weights": {
                "candle": 0.30,
                "trend_dir": 0.30,     # Trend is everything in position trading
                "volume": 0.10,
                "momentum": 0.10,
                "trend_strength": 0.15,
                "confirm": 0.05
            }
        }
    }