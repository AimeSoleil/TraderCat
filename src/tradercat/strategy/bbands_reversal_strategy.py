from typing import List, Literal, Optional, Dict, Any

from tradercat.strategy.candle_pattern.pattern_detector import PatternResult
from tradercat.strategy.candle_pattern.pattern_detector_orch import PatternDetectorsOrchestrator
from tradercat.strategy.exit_planner import ExitPlanner
from tradercat.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from tradercat.strategy.trading_strategy import TradingStrategy
from tradercat.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class BBandsReversalStrategy(TradingStrategy):
    """
    基于布林带的反转策略
    核心思想：
        - 当价格接近上/下轨并出现拒绝性蜡烛（长影线、吞没、反转实体）时，作为反转候选
        - 用 ATR 过滤低波动、用 ADX 避免强趋势中做逆向交易
        - [优化] 动态权重配置
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        # [Optimization] Replaced fixed touch_pct with ATR multiplier
        touch_atr_multiplier: float = 0.5,  # Dynamic threshold: 0.5 * ATR
        rsi_period: int = 14,
        atr_period: int = 14,
        adx_period: int = 14,
        adx_threshold: float = 30.0,
        max_time_bars: int = 3,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        macd_params: Optional[Dict[str, int]] = None,
        score_threshold: float = 0.6,
        # [NEW] Dynamic Weights
        weights: Optional[Dict[str, float]] = None,
        data_provider=None,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.touch_atr_multiplier = float(touch_atr_multiplier)
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.adx_threshold = float(adx_threshold)
        self.max_time_bars = int(max_time_bars)
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.score_threshold = float(score_threshold)
        
        # [NEW] Dynamic Weights configuration
        default_weights = {
            "candle": 0.35,     # Pattern is the primary trigger
            "trend": 0.25,      # ADX filter is crucial for mean reversion
            "volume": 0.20,     # Volume confirms rejection
            "momentum": 0.10,   # RSI/MACD hook
            "bonus": 0.10       # Mid-line cross etc
        }
        self.weights = {**default_weights, **(weights or {})}
        
        self.provider = data_provider

        # 字段名（兼容 provider 产出）
        self.bb_bw_field = f"close_BBB_{self.bb_period}_{self.bb_std}"
        self.bb_up_field = f"close_BBU_{self.bb_period}_{self.bb_std}"
        self.bb_low_field = f"close_BBL_{self.bb_period}_{self.bb_std}"
        self.bb_mid_field = f"close_BBM_{self.bb_period}_{self.bb_std}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"

    def get_name(self) -> str:
        return "BBandsReversal"

    def get_lookback_window(self) -> int:
        return (
            max(
                self.adx_period,
                self.bb_period,
                self.rsi_period,
                self.atr_period,
                self.max_time_bars,
                (self.macd_params["slow"] or 0),
            )
            + 5
        )
    
    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.BB_REVERSAL_CANDLE,
            FactorName.TREND_STRENGTH,
            FactorName.VOLUME_CONFIRM,
            FactorName.MOMENTUM_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

    # --- Helper Methods ---

    def _resolve_bias(
        self,
        rejection_res_bias: str | None,
        candidate_buy: bool,
        candidate_sell: bool,
        near_lower: bool,
        near_upper: bool,
    ) -> str:
        # Primary: pattern bias agrees with candidate side
        if rejection_res_bias == "long" and candidate_buy:
            return "long"
        if rejection_res_bias == "short" and candidate_sell:
            return "short"

        # Secondary: neutral or mismatched bias — tilt by proximity and mid-line cross
        if near_lower and candidate_buy:
            return "long"
        if near_upper and candidate_sell:
            return "short"

        # No clear signal
        return "neutral"

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        # Check basic data sufficiency (using base class helper logic usually, but manual check here)
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=None, reason="Low Data", confidence=0.0)

        # 获取指标
        bb_series = self.provider.get_indicator("bbands", candles, {"length": self.bb_period, "std": self.bb_std})
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params)
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        opens = [float(c.open) for c in candles]
        vols = [float(c.volume) for c in candles]
        dates = [c.date for c in candles]
        
        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        current_atr_val = atr_val_history[-1] if atr_val_history else 0.0
        
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        current_adx_val = adx_val_history[-1] if adx_val_history else 0.0
        
        rsi_val_history = [getattr(r, self.rsi_field, None) for r in rsi_series]
        macd_hist_val_history = [getattr(m, self.macd_hist_field, None) for m in macd_series] if macd_series else []
        
        idx = len(candles) - 1
        close = closes[-1]
        prev_close = closes[-2] if len(closes) >= 2 else close

        # 读取当前带位
        try:
            bb_last = bb_series[-1]
            u_curr = float(getattr(bb_last, self.bb_up_field, 0))
            l_curr = float(getattr(bb_last, self.bb_low_field, 0))
            m_curr = float(getattr(bb_last, self.bb_mid_field, 0))
        except Exception:
            # Fatal error for this strat
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=dates[-1], reason="Indicator Error", confidence=0.0)

        # 判断趋势强度和市场波动 (Reversal Mode: We prefer Low Trend Strength aka Chop/Range)
        # Use 'reversal' mode so low ADX is scored positively
        trend_config = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=adx_val_history,
            price_history=closes,
            window=100,
            mode='reversal', 
            trend_quantiles=[0.6, 0.4]
        )

        # 成交量 z-score 确认
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

        # --- Adaptive Bandwidth ---
        touch_threshold = current_atr_val * self.touch_atr_multiplier

        near_upper = (close >= u_curr - touch_threshold)
        near_lower = (close <= l_curr + touch_threshold)
        # Mid proximity logic can be tricky, simplified here:
        near_mid = (abs(close - m_curr) <= touch_threshold) 

        # 检测拒绝蜡烛
        orchestrator = PatternDetectorsOrchestrator()
        rejection_found: bool = False
        reject_idx: int | None = None
        rejection_res: PatternResult = PatternResult(False, None, None, None)
        start = max(0, idx - self.max_time_bars + 1)
        
        if near_lower or near_upper:
            for i in range(start, idx + 1):
                # Ensure we have data for this index
                if i >= len(atr_val_history): continue
                
                atr_i = atr_val_history[i]

                if near_lower:
                    res = orchestrator.detect_bullish(opens, highs, lows, closes, i, atr=atr_i)
                else:
                    res = orchestrator.detect_bearish(opens, highs, lows, closes, i, atr=atr_i)

                if res.is_pattern:
                    rejection_found = True
                    rejection_res = res
                    reject_idx = i
                    break

        # Candidates triggers
        candidate_buy = (near_lower or near_mid) and rejection_found
        candidate_sell = (near_upper or near_mid) and rejection_found
        
        # 中轨穿越反转逻辑
        middle_line_reversal = False
        if m_curr:
            if candidate_buy: # Crossed UP over mid line?
                middle_line_reversal = (prev_close < m_curr and close > m_curr)
            elif candidate_sell:# Crossed DOWN under mid line?
                middle_line_reversal = (prev_close > m_curr and close < m_curr)

        # Side resolution
        side_bias = self._resolve_bias(
            rejection_res_bias=rejection_res.bias,
            candidate_buy=candidate_buy,
            candidate_sell=candidate_sell,
            near_lower=near_lower,
            near_upper=near_upper
        )

        # 动量确认 (Using Base Class Helper logic)
        momentum_ok: bool = self._momentum_confirm(
            rsi_val_history=rsi_val_history,
            macd_hist_val_history=macd_hist_val_history,
            prefer=side_bias
        )

        details: Dict[str, Any] = {
            "close": close,
            "upper": u_curr,
            "lower": l_curr,
            "atr": round(current_atr_val, 6),
            "adx": round(current_adx_val, 3),
            "rejection_pattern": rejection_res.name,
            "vol_zscore": round(volume_z, 3) if volume_z is not None else 0,
            "trend_ok": trend_config.signal, # Should refer to signal
            "momentum_ok": momentum_ok,
        }

        # --- SCORING ENGINE ---
        factors = [
            # Factor 1: The Candle Pattern (Must exist)
            Factor(
                FactorName.BB_REVERSAL_CANDLE, 
                f"Rejection: {rejection_res.name}", 
                self.weights["candle"], 
                candidate_buy or candidate_sell
            ),
            # Factor 2: Market State (Low ADX / Range)
            Factor(
                FactorName.TREND_STRENGTH, 
                "Ranging Market (Low ADX)", 
                self.weights["trend"], 
                trend_config.signal
            ),
            # Factor 3: Volume
            Factor(
                FactorName.VOLUME_CONFIRM, 
                "Volume Rejection", 
                self.weights["volume"], 
                vol_ok
            ),
            # Factor 4: Momentum
            Factor(
                FactorName.MOMENTUM_CONFIRM, 
                "Momentum Hook (RSI)", 
                self.weights["momentum"], 
                momentum_ok
            ),
            # Factor 5: Confluence
            Factor(
                FactorName.CONFLUENCE_BONUS, 
                "Mid-Line Cross / Confluence", 
                self.weights["bonus"], 
                middle_line_reversal
            )
        ]

        engine = ScoringEngine(
            base_threshold=self.score_threshold, 
            # We enforce that a pattern MUST exist for a reversal trade
            determined_factors=[FactorName.BB_REVERSAL_CANDLE],
            is_volatility_ok=True # We used trend_config.signal via Factor 2 already
        )
        
        result = engine.compute_score(factors, side=side_bias)

        # 计算入场止损与 trailing stop
        if result and result.signal != 'hold':
            planner = ExitPlanner(
                highs=highs,
                lows=lows,
                atr=current_atr_val,
                close_price=close
            )
            plan = planner.make_exit_plan(trading_signal=result.signal)
            
            # [Optimization] Mean Reversion Target (Mid Band)
            if m_curr:
                plan['take_profit_ref'] = m_curr
                plan['take_profit_type'] = 'mean_reversion_mid'
            
            details["plan"] = plan

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            date=dates[-1],
            # Cap confidence at 1.0
            confidence=round(min(1.0, result.score), 3),
            reason=" | ".join(result.reasons),
            details=details,
        )

def make_bbands_reversal_presets() -> Dict[str, Dict[str, Any]]:
    return {
        "swing": {
            # ---------------- SWING TRADING (Optimized) ----------------
            "bb_period": 20,
            "bb_std": 2.0,
            "touch_atr_multiplier": 0.5,    
            "adx_period": 14,
            "adx_threshold": 30.0,      
            "max_time_bars": 3,
            "vol_zscore_window": 20,
            "vol_zscore_threshold": 1.5,
            "rsi_period": 14,
            "atr_period": 14,
            "macd_params": {"fast": 12, "slow": 26, "signal": 9},
            "score_threshold": 0.60,
            
            # [NEW] Tuned Weights
            "weights": {
                "candle": 0.35,    # Pattern is king for reversal
                "trend": 0.25,     # Must be ranging
                "volume": 0.20,
                "momentum": 0.10,
                "bonus": 0.10
            }
        },

        "position": {
            # ---------------- POSITION TRADING (Strong Levels) ----------------
            "bb_period": 50,
            "bb_std": 2.5,
            "touch_atr_multiplier": 1.0, # looser touch tolerance on weekly charts
            "adx_period": 14,
            "adx_threshold": 25.0,
            "max_time_bars": 5,
            "vol_zscore_window": 50,
            "vol_zscore_threshold": 1.5,
            "rsi_period": 14,
            "atr_period": 14,
            "macd_params": {"fast": 12, "slow": 26, "signal": 9},
            "score_threshold": 0.70,
            
            # [NEW] Tuned Weights
            "weights": {
                "candle": 0.30,
                "trend": 0.30,     # Market structure matters more
                "volume": 0.15,
                "momentum": 0.15,
                "bonus": 0.10
            }
        }
    }
