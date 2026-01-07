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
        return int(base + 5)

    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.REVERSAL_CANDLE,
            FactorName.VOLUME_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.TREND_DIRECTION_CONFIRM,
            FactorName.MOMENTUM_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

    # [New] Helper for Confirmation Candle
    def _check_reversal_confirmation(
        self, 
        closes: List[float], 
        effective_bias: str,
    ) -> bool:
        """确认反转有效性：价格是否朝着预期方向移动"""
        if len(closes) < 3:
            return False
        
        # 简单的确认：最新收盘价优于前一根
        if effective_bias == "long":
            return closes[-1] > closes[-2]
        elif effective_bias == "short":
            return closes[-1] < closes[-2]
        
        return False

    # ---------- 主决策逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        logger.info(f"🔍 Generating Candlestick Reversal signal for {symbol} at {candles[-1].date if candles else 'N/A'}...")
        
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

        # 策略：在上升趋势中寻找看涨反转（回调买入），在下降趋势中寻找看跌反转（反弹做空）
        # 注意：这里 trend_ok 传入的是主趋势方向，用于过滤逆势信号
        res_bull = orchestrator.detect_bullish(opens, highs, lows, closes, idx, atr=current_atr_val, trend_ok=trend_long)
        res_bear = orchestrator.detect_bearish(opens, highs, lows, closes, idx, atr=current_atr_val, trend_ok=trend_short)

        found_bull = bool(res_bull and res_bull.is_pattern)
        found_bear = bool(res_bear and res_bear.is_pattern)

        # 冲突解决：优先选择顺应主趋势的信号
        chosen_res = None
        if found_bull and found_bear:
            if trend_long: chosen_res = res_bull # Uptrend -> Buy Dip
            elif trend_short: chosen_res = res_bear # Downtrend -> Sell Rally
            else: 
                # 无明确趋势时，保持中立
                chosen_res = None 
        elif found_bull:
            chosen_res = res_bull
        elif found_bear:
            chosen_res = res_bear

        pattern = chosen_res.name if chosen_res else None
        raw_bias = chosen_res.bias if chosen_res else None

        # 确定有效方向 (long/short)
        effective_bias = raw_bias
        if raw_bias in (None, "neutral"):
            if found_bull: effective_bias = "long"
            elif found_bear: effective_bias = "short"

        # ---------- 辅助确认 ----------
        trend_strength = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=adx_val_history,
            price_history=closes,
            window=100,
            mode='reversal',
            trend_quantiles=[0.6, 0.4]
        )

        # 根据 preset 动态调整：swing 用 10-15 根，position 用 30-50 根
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

        # [Optimization] Use parent class momentum check
        mom_ok = False
        if chosen_res and chosen_res.is_pattern and effective_bias:
            mom_ok = self._momentum_confirm(
                rsi_val_history=rsi_val_history,
                macd_hist_val_history=macd_hist_val_history,
                prefer=effective_bias
            )

        # [Optimization] Reversal Confirmation (Price Action)
        reversal_confirmed = False
        if effective_bias:
            reversal_confirmed = self._check_reversal_confirmation(
                closes, effective_bias
            )

        # ---------- 评分系统 ----------
        found_any = bool(chosen_res and chosen_res.is_pattern)

        trend_direction_ok = (
            (effective_bias == "long" and trend_long) or
            (effective_bias == "short" and trend_short)
        )

        factors = [
            Factor(FactorName.REVERSAL_CANDLE, f"检测到烛形({pattern})", 0.35, found_any),
            Factor(FactorName.VOLUME_CONFIRM, "成交量放大", 0.20, vol_ok),
            Factor(FactorName.TREND_STRENGTH, "趋势强度(ADX)", 0.10, bool(trend_strength.signal)),
            Factor(FactorName.TREND_DIRECTION_CONFIRM, "顺大势(EMA)", 0.15, trend_direction_ok),
            Factor(FactorName.MOMENTUM_CONFIRM, "动量确认(RSI/MACD)", 0.10, mom_ok),
            Factor(FactorName.CONFLUENCE_BONUS, "反转确认(Price Action)", 0.10, reversal_confirmed)
        ]

        engine = ScoringEngine(
            base_threshold=self.score_threshold,
            required_factors=self.support_scoring_factors(),
            determined_factors=[FactorName.REVERSAL_CANDLE],
            is_volatility_ok=bool(trend_strength.volatility.get('signal', True))
        )

        side_action = "neutral"
        if found_any:
            side_action = effective_bias # "long" or "short"

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
            
            # Adjust stop loss based on ADX (Weaker trend = tighter stop)
            sl_mult = 1.0 if current_adx_val < 20 else 1.5
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
            confidence=round(result.score, 3),
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
            
            # --- Trend Filter ---
            # Use 9/21 EMA. This is the standard "Swing Trader's Zone".
            # We only look for Bullish patterns when EMA 9 > EMA 21.
            "ema_fast": 9,
            "ema_slow": 21,

            # --- Volatility & Momentum ---
            "atr_period": 14,
            "rsi_period": 14,       # Standard RSI. Look for oversold dips (RSI < 40) in uptrends.
            "adx_period": 14,       # ADX helps filter out ranging markets.

            # --- MACD (Momentum Confirmation) ---
            "macd_params": {"fast": 12, "slow": 26, "signal": 9},

            # --- Volume Confirmation ---
            # Reversal candles (e.g., Hammer) need volume validation.
            # 1.5 std devs above mean ensures institutions are stepping in.
            "vol_zscore_window": 20,
            "vol_zscore_threshold": 1.5,

            # --- Scoring ---
            # Set to 0.65 to filter out weak patterns.
            # We want Confluence: Trend + Pattern + Volume + Momentum.
            "score_threshold": 0.65,
        },

        "position": {
            # ---------------- POSITION TRADING ----------------
            # Weekly/Monthly reversals
            "ema_fast": 50,
            "ema_slow": 200,
            "atr_period": 14,
            "rsi_period": 14,
            "adx_period": 14,
            "macd_params": {"fast": 12, "slow": 26, "signal": 9},
            "vol_zscore_window": 50,
            "vol_zscore_threshold": 2.0, # High conviction accumulation
            "score_threshold": 0.75
        },

        "scalp": {
            # ---------------- SCALPING ----------------
            # 1m/5m timeframe reversals
            "ema_fast": 5,
            "ema_slow": 13,
            "atr_period": 10,
            "rsi_period": 7,
            "adx_period": 7,
            "macd_params": {"fast": 6, "slow": 13, "signal": 4},
            "vol_zscore_window": 10,
            "vol_zscore_threshold": 2.5, # Volume spike essential for scalp reversals
            "score_threshold": 0.60
        }
    }