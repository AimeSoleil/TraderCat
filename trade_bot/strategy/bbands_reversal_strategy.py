from typing import List, Literal, Optional, Dict, Any

from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult
from trade_bot.strategy.candle_pattern.pattern_detector_orch import PatternDetectorsOrchestrator
from trade_bot.strategy.exit_planner import ExitPlanner
from trade_bot.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class BBandsReversalStrategy(TradingStrategy):
    """
    基于布林带的反转策略
    核心思想：
        - 当价格接近上/下轨并出现拒绝性蜡烛（长影线、吞没、反转实体）时，作为反转候选
        - 用 ATR 过滤低波动、用 ADX 避免强趋势中做逆向交易，用成交量 z-score 与动量作为确认
        - [优化] 动态接触阈值 (ATR-based)
        - [优化] 中轨作为第一止盈位
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
        macd_params: Optional[Dict[str, int]] = {"fast": 12, "slow": 26, "signal": 9},
        score_threshold: float = 0.6,
        data_provider=None,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        # [Optimization] Store ATR multiplier
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
        rejection_res_bias: Literal["long", "short", "neutral"] | None,
        candidate_buy: bool,
        candidate_sell: bool,
        near_lower: bool,
        near_upper: bool,
        middle_line_reversal: bool
    ) -> Literal["long", "short", "neutral"]:
        # Primary: pattern bias agrees with candidate side
        if rejection_res_bias == "long" and candidate_buy:
            return "long"
        if rejection_res_bias == "short" and candidate_sell:
            return "short"

        # Secondary: neutral or mismatched bias — tilt by proximity and mid-line cross
        if near_lower and candidate_buy:
            # If we also have a middle-line reversal in the bullish sense, reinforce bull
            return "long" if middle_line_reversal or (rejection_res_bias in (None, "neutral")) else "long"
        if near_upper and candidate_sell:
            return "short" if middle_line_reversal or (rejection_res_bias in (None, "neutral")) else "short"

        # Fallback: use band proximity if no candidate agreement
        if near_lower:
            return "long"
        if near_upper:
            return "short"

        # No clear signal
        return "neutral"

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date if candles else None,
                reason="数据不足",
                confidence=0.0,
            )

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
            u_curr = getattr(bb_last, self.bb_up_field, None)
            l_curr = getattr(bb_last, self.bb_low_field, None)
            m_curr = getattr(bb_last, self.bb_mid_field, None)
        except Exception:
            u_curr = l_curr = m_curr = None

        # 判断趋势强度和市场波动
        trend_strength = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=adx_val_history,
            price_history=closes,
            window=100,
            mode='reversal',
            trend_quantiles=[0.6, 0.4]
        )

        # 成交量 z-score 确认（vol_ok
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

        # --- [Optimization 1] Adaptive Bandwidth (波动率自适应带宽) ---
        # 使用 ATR 计算动态接触阈值，而不是固定的百分比
        touch_threshold = current_atr_val * self.touch_atr_multiplier

        near_upper = (u_curr is not None) and (close >= u_curr - touch_threshold)
        near_lower = (l_curr is not None) and (close <= l_curr + touch_threshold)
        near_mid = (m_curr is not None) and (abs(close - m_curr) <= touch_threshold)
        # -----------------------------------------------------------

        # 检测拒绝蜡烛（以最近 self.max_time_bars 根内的任意一根作为确认）
        orchestrator = PatternDetectorsOrchestrator()
        rejection_found: bool = False
        reject_idx: int | None = None
        rejection_res: PatternResult = PatternResult(False, None, None, None)
        start = max(0, idx - self.max_time_bars + 1)
        
        if near_lower or near_upper:
            for i in range(start, idx + 1):
                atr_i = atr_val_history[i] if atr_val_history is not None else None

                if near_lower:
                    # Bullish reversal candidates (e.g., Tweezer Bottom, Morning Star, etc.)
                    res = orchestrator.detect_bullish(
                        opens, highs, lows, closes, i,
                        atr=atr_i,
                    )
                else:
                    # Bearish reversal candidates (e.g., Tweezer Top, Evening Star, etc.)
                    res = orchestrator.detect_bearish(
                        opens, highs, lows, closes, i,
                        atr=atr_i,
                    )

                if res.is_pattern:
                    rejection_found = True
                    rejection_res = res
                    reject_idx = i
                    break

        # 只有在带位接近并出现拒绝蜡烛的情况下考虑反转
        candidate_buy = (near_lower or near_mid) and rejection_found
        candidate_sell = (near_upper or near_mid) and rejection_found
        
        # 修正：中轨穿越反转逻辑
        # 看涨反转：之前在下，现在在上 (上穿)
        # 看跌反转：之前在上，现在在下 (下穿)
        middle_line_reversal = False
        if m_curr is not None:
            if candidate_buy:
                middle_line_reversal = (prev_close < m_curr and close > m_curr)
            elif candidate_sell:
                middle_line_reversal = (prev_close > m_curr and close < m_curr)

        # Side resolution
        side_bias = self._resolve_bias(
            rejection_res_bias=rejection_res.bias,
            candidate_buy=candidate_buy,
            candidate_sell=candidate_sell,
            near_lower=near_lower,
            near_upper=near_upper,
            middle_line_reversal=middle_line_reversal
        )

        # 动量确认
        momentum_ok: bool = self._momentum_confirm(
            rsi_val_history=rsi_val_history,
            macd_hist_val_history=macd_hist_val_history,
            prefer=side_bias
        )

        details: Dict[str, Any] = {
            "close": close,
            "upper": u_curr,
            "lower": l_curr,
            "mid": m_curr,
            "atr": round(current_atr_val, 6),
            "adx": round(current_adx_val, 3),
            "rejection_date": dates[reject_idx] if reject_idx is not None else None,
            "rejection_pattern": rejection_res.name,
            "rejection_pattern_bias": rejection_res.bias,
            "reject_pattern_metrics": rejection_res.metrics,   # full metrics for downstream analysis
            "vol_zscore": round(volume_z, 3) if volume_z is not None else None,
            "trend_volatility_ok": trend_strength.signal,
            "trend_info": trend_strength.trend,
            "volatility_info": trend_strength.volatility,
            "near_upper": near_upper,
            "near_lower": near_lower,
            "momentum_ok": momentum_ok,
            "resolved_side": side_bias,                     # final direction used for trading decision
        }

        # 评分 & 生成 signal
        result: ScoringResult = None
        factors = [
            Factor(FactorName.BB_REVERSAL_CANDLE, f"检测到布林带拒绝蜡烛({rejection_res.name})", 0.35, candidate_buy or candidate_sell),
            Factor(FactorName.TREND_STRENGTH, "趋势强度和波动率确认", 0.25, trend_strength.signal),
            Factor(FactorName.VOLUME_CONFIRM, "成交量放大确认", 0.2, vol_ok),
            Factor(FactorName.MOMENTUM_CONFIRM, "动量确认方向确认", 0.1, momentum_ok),
            Factor(FactorName.CONFLUENCE_BONUS, "中轨穿越反转", 0.1, middle_line_reversal)
        ]

        # Compute score using ScoringEngine
        engine = ScoringEngine(
            base_threshold=self.score_threshold, 
            required_factors=self.support_scoring_factors(),
            determined_factors=[
                FactorName.BB_REVERSAL_CANDLE
            ],
            is_volatility_ok=trend_strength.volatility['signal']
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
            
            # --- [Optimization 2] Mean Reversion Target (中轨止盈) ---
            # 布林带反转的第一目标位通常是中轨
            if m_curr:
                plan['take_profit_ref'] = m_curr
                plan['take_profit_type'] = 'mean_reversion_mid'
            # -------------------------------------------------------
            
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

def make_bbands_reversal_presets() -> Dict[str, Dict[str, Any]]:
    """
    Bollinger Band reversal strategy presets (Optimized).
    """
    # ---------------- SWING ----------------
    swing = {
        "bb_period": 20,
        "bb_std": 2.0,
        # [Opt] Dynamic touch: 0.5 ATR is generous for swings
        "touch_atr_multiplier": 0.5,    
        "rsi_period": 9,
        "atr_period": 14,
        "adx_period": 14,
        "adx_threshold": 35.0,
        "max_time_bars": 3,
        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.2,
        "macd_params": {"fast": 8, "slow": 17, "signal": 9},
        "score_threshold": 0.55
    }

    # ---------------- INTERMEDIATE ----------------
    intermediate = {
        "bb_period": 20,
        "bb_std": 2.0,
        # [Opt] Stricter touch: 0.3 ATR
        "touch_atr_multiplier": 0.3,    
        "rsi_period": 14,
        "atr_period": 14,
        "adx_period": 14,
        "adx_threshold": 30.0,
        "max_time_bars": 5,
        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.5,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "score_threshold": 0.65
    }

    # ---------------- POSITION ----------------
    position = {
        "bb_period": 20,
        "bb_std": 2.2,
        # [Opt] Very strict touch: 0.1 ATR (Must almost hit the band)
        "touch_atr_multiplier": 0.1,    
        "rsi_period": 21,
        "atr_period": 21,
        "adx_period": 14,
        "adx_threshold": 25.0,
        "max_time_bars": 8,
        "vol_zscore_window": 40,
        "vol_zscore_threshold": 1.8,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "score_threshold": 0.75
    }

    return {
        "swing": swing,
        "intermediate": intermediate,
        "position": position
    }
