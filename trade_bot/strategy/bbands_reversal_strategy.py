from typing import List, Optional, Dict, Any

from trade_bot.strategy.candle_pattern.pattern_detector import PatternResult
from trade_bot.strategy.candle_pattern.pattern_detector_orch import PatternDetectorsOrchestrator
from trade_bot.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from trade_bot.strategy.trading_strategy import ExitPlanner, TradingStrategy, EPS
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class BBandsReversalStrategy(TradingStrategy):
    """
    基于布林带的反转策略
    核心思想：
        - 当价格接近上/下轨并出现拒绝性蜡烛（长影线、吞没、反转实体）时，作为反转候选
        - 用 ATR 过滤低波动、用 ADX 避免强趋势中做逆向交易，用成交量 z-score 与动量作为确认
        - 可配置的确认窗口（max_time_bars），以及 presets（swing/intermediate/position）
    输出：
        SignalModel(signal in {'buy','sell','hold'}, confidence, reason(中文), details)
    """

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        touch_pct: float = 0.03,  # 价格与带位的相对容差（3%以内视为“接触”）
        rsi_period: int = 14,
        atr_period: int = 14,
        adx_period: int = 14,
        adx_threshold: float = 30.0,  # ADX 超过视为强趋势，避免逆势反转
        max_time_bars: int = 3,  # 延续/确认窗口
        atr_base_factor: float = 1,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        macd_params: Optional[Dict[str, int]] = {"fast": 12, "slow": 26, "signal": 9},
        score_threshold: float = 0.6,
        data_provider=None,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.touch_pct = float(touch_pct)
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.adx_threshold = float(adx_threshold)
        self.max_time_bars = int(max_time_bars)
        self.atr_base_factor = float(atr_base_factor)
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
        self.atr_field = f"ATRr_{self.atr_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.adx_field = f"ADX_{self.adx_period}"

    def get_name(self) -> str:
        return "BBandsReversal"

    def get_lookback_window(self) -> int:
        return (
            max(
                self.bb_period,
                self.rsi_period,
                self.atr_period,
                self.max_time_bars,
                (self.macd_params["slow"] or 0),
            )
            + 5
        )
    
    # Supported scoring factors
    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.BB_REVERSAL_CANDLE,
            FactorName.TREND_STRENGTH,
            FactorName.VOLUME_CONFIRM,
            FactorName.MOMENTUM_CONFIRM
        ]

    def _resolve_bias(
        rejection_res_bias: str | None,
        candidate_buy: bool,
        candidate_sell: bool,
        near_lower: bool,
        near_upper: bool,
        middle_line_reversal: bool
    ) -> str:
        # Primary: pattern bias agrees with candidate side
        if rejection_res_bias == "bull" and candidate_buy:
            return "bull"
        if rejection_res_bias == "bear" and candidate_sell:
            return "bear"

        # Secondary: neutral or mismatched bias — tilt by proximity and mid-line cross
        if near_lower and candidate_buy:
            # If we also have a middle-line reversal in the bullish sense, reinforce bull
            return "bull" if middle_line_reversal or (rejection_res_bias in (None, "neutral")) else "bull"
        if near_upper and candidate_sell:
            return "bear" if middle_line_reversal or (rejection_res_bias in (None, "neutral")) else "bear"

        # Fallback: use band proximity if no candidate agreement
        if near_lower:
            return "bull"
        if near_upper:
            return "bear"

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
        current_atr_val = atr_val_history[-1]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        current_adx_val = adx_val_history[-1]
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
            adx_val_history=atr_val_history,
            price_history=closes,
            window=100,
            atr_base_factor=self.atr_base_factor,
            atr_quantile=0.8,
            adx_quantile=0.8,
            mode='reversal'
        )

        # 成交量 z-score 确认（vol_ok
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

        # 检查是否接近上轨/下轨/中轨（相对容差
        near_upper = (u_curr is not None) and (
            close > u_curr or abs(close - u_curr) / (u_curr if abs(u_curr) > EPS else 1.0) <= self.touch_pct
        )
        near_lower = (l_curr is not None) and (
            close < l_curr or abs(close - l_curr) / (l_curr if abs(l_curr) > EPS else 1.0) <= self.touch_pct
        )
        near_mid = (m_curr is not None) and (
            abs(close - m_curr) / (m_curr if abs(m_curr) > EPS else 1.0) <= self.touch_pct
        )

        # 检测拒绝蜡烛（以最近 self.max_time_bars 根内的任意一根作为确认）
        orchestrator = PatternDetectorsOrchestrator()
        rejection_found: bool = False
        reject_idx: int | None = None
        rejection_res: PatternResult = PatternResult(False, None, None, None)
        start = max(0, idx - self.max_time_bars + 1)
        side = "neutral"
        if near_lower or near_upper:
            for i in range(start, idx + 1):
                atr_i = atr_val_history[i] if atr_val_history is not None else None

                if near_lower:
                    # Bullish reversal candidates (e.g., Tweezer Bottom, Morning Star, etc.)
                    rejection_res = orchestrator.detect_bullish(
                        opens, highs, lows, closes, i,
                        atr=atr_i,
                        # extra_overrides can pass pattern-specific knobs if desired
                        # extra_overrides={"low_similarity_tolerance": 0.0015}
                    )
                else:
                    # Bearish reversal candidates (e.g., Tweezer Top, Evening Star, etc.)
                    rejection_res = orchestrator.detect_bearish(
                        opens, highs, lows, closes, i,
                        atr=atr_i,
                        # extra_overrides={"high_similarity_tolerance": 0.0015}
                    )

                if rejection_res.is_pattern:
                    rejection_found = True
                    reject_idx = i
                    break
        
        # 只有在带位接近并出现拒绝蜡烛的情况下考虑反转
        candidate_buy = (near_lower or near_mid) and rejection_found
        candidate_sell = (near_upper or near_mid) and rejection_found
        middle_line_reversal = (candidate_buy and prev_close > m_curr and close < m_curr) or (candidate_sell and prev_close < m_curr and close > m_curr)
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
            "candle_pattern": rejection_res.name,
            "candle_pattern_bias": rejection_res.bias,
            "pattern_metrics": rejection_res.metrics,   # full metrics for downstream analysis
            "vol_zscore": round(volume_z, 3) if volume_z is not None else None,
            "trend_volatility_ok": trend_strength.signal,
            "trend_info": trend_strength.trend,
            "volatility_info": trend_strength.volatility,
            "near_upper": near_upper,
            "near_lower": near_lower,
            "rejection_found": rejection_found,
            "rejection_idx": reject_idx,
            "momentum_ok": momentum_ok,
            "resolved_side": side,                     # final direction used for trading decision
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
            plan = planner.make_exit_plan('long' if result.signal == 'buy' else 'short')
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
    Bollinger Band reversal strategy presets based on algo trading best practices:
    - swing: Short-term (1–2 weeks), tighter band touch, quick confirmation.
    - intermediate: Medium-term (2–6 weeks), balanced thresholds.
    - position: Long-term (1–3 months), looser band touch, stricter confirmation.
    """

    # ---------------- SWING ----------------
    swing = {
        "bb_period": 20,                # Standard BB period for volatility context.
        "bb_std": 2.0,                  # Classic BB width (2 std dev).
        "touch_pct": 0.02,              # Price within 2% of band → tighter for short-term reversals.
        "rsi_period": 14,               # RSI standard for momentum reversal.
        "atr_period": 14,               # ATR for volatility filter.
        "adx_period": 14,               # ADX for trend strength.
        "max_time_bars": 3,             # Quick reversal confirmation (within 3 bars).
        "atr_base_factor": 0.5,         # ATR base factor for volatility.
        "vol_zscore_window": 20,        # Volume z-score window matches BB period.
        "vol_zscore_threshold": 1.5,    # Moderate volume spike confirmation.
        "macd_params": {"fast": 12, "slow": 26, "signal": 9}, # Standard MACD.
        "score_threshold": 0.6          # Slightly higher threshold for reversal confidence.
    }

    # ---------------- INTERMEDIATE ----------------
    intermediate = {
        "bb_period": 20,
        "bb_std": 2.0,
        "touch_pct": 0.03,              # Looser band touch for medium-term reversals.
        "rsi_period": 14,
        "atr_period": 14,
        "adx_period": 14,
        "max_time_bars": 5,             # Allow more bars for confirmation.
        "atr_base_factor": 1,           # ATR base factor for volatility.
        "vol_zscore_window": 30,        # Longer volume window for stability.
        "vol_zscore_threshold": 2.0,    # Stricter volume confirmation.
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "score_threshold": 0.7          # Balanced confidence threshold.
    }

    # ---------------- POSITION ----------------
    position = {
        "bb_period": 20,
        "bb_std": 2.0,
        "touch_pct": 0.05,              # Loosest band touch for long-term reversals.
        "rsi_period": 14,
        "atr_period": 14,
        "adx_period": 14,
        "max_time_bars": 7,             # More bars allowed for confirmation.
        "atr_base_factor": 2,           # ATR base factor for volatility.
        "vol_zscore_window": 40,        # Long volume window for position trades.
        "vol_zscore_threshold": 2.5,    # Very strict volume confirmation.
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "score_threshold": 0.8          # High confidence threshold for position entries.
    }

    return {
        "swing": swing,
        "intermediate": intermediate,
        "position": position
    }
