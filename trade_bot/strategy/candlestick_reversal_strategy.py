from typing import List, Optional, Dict, Any

from trade_bot.strategy.candle_pattern.pattern_detector_orch import PatternDetectorsOrchestrator
from trade_bot.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from trade_bot.strategy.trading_strategy import ExitPlanner, TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class CandlestickReversalStrategy(TradingStrategy):
    """
    基于蜡烛图的反转策略（中文注释）
    要点：
        - 检测常见反转烛形：锤子/倒锤子、吞没、十字/十字星、刺透/乌云（此处实现为常见子集）
        - 使用 EMA 作为趋势过滤，ATR 作为止损尺度，RSI/MACD/成交量作为确认项
        - 返回 SignalModel，details 包含 entry/stop/target 与评分细节
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

        # 指标字段名约定（provider 兼容）
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
        """
        返回此策略需要的最小回溯 candle 数（用于判断是否有足够数据）。
        计算逻辑（经验规则）：
            - 至少包括慢速 EMA、ATR、RSI 与 MACD 的周期长度中的最大者
            - 再加少量安全边际
        这样在回测/实盘中能保证 provider 指标序列包含所需历史数据。
        """
        # 安全读取各指标周期（若未设置则使用合理默认）
        macd_max = max(int(self.macd_params.get("fast", 0) or 0),
                        int(self.macd_params.get("slow", 0) or 0),
                        int(self.macd_params.get("signal", 0) or 0))
        # 基础窗口取上述最大者
        base = max(self.ema_slow, self.atr_period, self.rsi_period, macd_max, 3)
        # 最后加上小的安全边际
        lookback = base + 3
        return int(lookback)

    # Supported scoring factors
    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.REVERSAL_CANDLE,
            FactorName.VOLUME_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.TREND_DIRECTION_CONFIRM,
            FactorName.MOMENTUM_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

    # ---------- 主决策逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        # ---------- 数据校验 ----------
        if not candles or len(candles) < max(self.ema_slow, self.atr_period, 3):
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold",
                                date=None, reason="insufficient data", confidence=0.0)

        # 提取 OHLCV 与日期
        opens = [float(getattr(c, "open")) for c in candles]
        highs = [float(getattr(c, "high")) for c in candles]
        lows = [float(getattr(c, "low")) for c in candles]
        closes = [float(getattr(c, "close")) for c in candles]
        vols = [getattr(c, "volume", None) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]
        close = closes[-1]
        # ---------- 指标获取 ----------
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast}) if self.provider else None
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow}) if self.provider else None
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period}) if self.provider else None
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period}) if self.provider else None
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params) if (self.provider and self.macd_params) else None
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period}) if self.provider else None

        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        rsi_val_history = [getattr(r, self.rsi_field, None) for r in rsi_series]
        macd_hist_val_history = [getattr(m, self.macd_hist_field, None) for m in macd_series] if macd_series else []
        ema_fast_history = [getattr(m, self.ema_fast_field, None) for m in ema_fast_series]
        ema_slow_history = [getattr(m, self.ema_slow_field, None) for m in ema_slow_series]
        current_atr_val = atr_val_history[-1]
        current_adx_val = adx_val_history[-1]
        current_rsi_val = rsi_val_history[-1]
        current_ema_fast_val = ema_fast_history[-1]
        current_ema_slow_val = ema_slow_history[-1]

        # ---------- 趋势判断 ----------
        trend_long = (
            current_ema_fast_val is not None
            and current_ema_slow_val is not None
            and current_ema_fast_val > current_ema_slow_val
        )
        trend_short = (
            current_ema_fast_val is not None
            and current_ema_slow_val is not None
            and current_ema_fast_val < current_ema_slow_val
        )

        # ---------- 烛形检测 (使用 PatternOrchestratorSingleton) ----------
        idx = len(candles) - 1

        # Singleton orchestrator (import once at module level ideally)
        orchestrator = PatternDetectorsOrchestrator()

        # Detect both directions and then resolve
        res_bull = orchestrator.detect_bullish(
            opens, highs, lows, closes, idx,
            atr=current_atr_val,
            # trend gating hint for detectors that care (e.g., Tweezer Bottom after downtrend)
            trend_ok=trend_short  # bullish reversal more credible if prior downtrend
        )
        res_bear = orchestrator.detect_bearish(
            opens, highs, lows, closes, idx,
            atr=current_atr_val,
            # trend gating hint (e.g., Tweezer Top after uptrend)
            trend_ok=trend_long   # bearish reversal more credible if prior uptrend
        )

        found_bull = bool(res_bull and res_bull.is_pattern)
        found_bear = bool(res_bear and res_bear.is_pattern)

        # Choose a canonical result:
        # Priority: if both found, prefer alignment with current trend direction;
        # otherwise prefer non-neutral bias; fallback to whichever exists.
        chosen_res = None
        if found_bull and found_bear:
            if trend_long and not trend_short:
                chosen_res = res_bear   # bearish reversal against uptrend (tops) is typically more actionable
            elif trend_short and not trend_long:
                chosen_res = res_bull   # bullish reversal against downtrend (bottoms)
            else:
                # No clear trend; prefer non-neutral bias or pick bullish by default
                chosen_res = res_bear if (res_bear.bias in ("short",) and res_bull.bias == "neutral") else (
                    res_bull if res_bull.bias in ("long",) else res_bull
                )
        elif found_bull:
            chosen_res = res_bull
        elif found_bear:
            chosen_res = res_bear

        pattern = chosen_res.name if chosen_res else None
        raw_bias = chosen_res.bias if chosen_res else None  # "long" | "short" | "neutral" | None

        # Neutral tilt: if bias is neutral, tilt with the EMA trend
        effective_bias = raw_bias
        if raw_bias in (None, "neutral"):
            if trend_long and not trend_short:
                effective_bias = "long"
            elif trend_short and not trend_long:
                effective_bias = "short"
            else:
                # Fallback: prefer bull if res_bull exists; else bear if res_bear exists; else neutral
                effective_bias = "long" if found_bull else ("short" if found_bear else "neutral")

        # ---------- 趋势强度和波动率 -----------
        trend_strength = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=adx_val_history,      # <-- 修正：传入 ADX 历史
            price_history=closes,
            window=100,
            mode='reversal',
            trend_quantiles=[0.6, 0.4]
        )

        # ---------- 成交量 z-score 确认 -----------
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

        # ---------- 动量确认 ----------
        mom_ok = False
        if chosen_res and chosen_res.is_pattern:
            mom_ok = bool(self._momentum_confirm(
                rsi_val_history=rsi_val_history,
                macd_hist_val_history=macd_hist_val_history,
                prefer=effective_bias
            ))

        # ---------- 评分系统 ----------
        # 判定是否识别到拒绝蜡烛
        found_any = bool(chosen_res and chosen_res.is_pattern)

        # 趋势方向一致（信号与当前趋势方向一致）
        trend_direction_ok = (
            (effective_bias == "bull" and trend_long) or
            (effective_bias == "bear" and trend_short)
        )

        factors = [
            Factor(FactorName.REVERSAL_CANDLE, f"检测到拒绝蜡烛({pattern})", 0.35, found_any),
            Factor(FactorName.VOLUME_CONFIRM, "成交量放大确认", 0.20, vol_ok),
            Factor(FactorName.TREND_STRENGTH, "趋势强度和波动率确认", 0.15, bool(trend_strength.signal)),
            Factor(FactorName.TREND_DIRECTION_CONFIRM, "趋势方向一致", 0.15, trend_direction_ok),
            Factor(FactorName.MOMENTUM_CONFIRM, "动量确认方向确认", 0.10, mom_ok),
            Factor(
                FactorName.CONFLUENCE_BONUS,
                "三重共振加分",
                0.05,
                mom_ok and bool(trend_strength.signal) and trend_direction_ok
            )
        ]

        engine = ScoringEngine(
            base_threshold=self.score_threshold,
            required_factors=self.support_scoring_factors(),
            determined_factors=[FactorName.REVERSAL_CANDLE],
            is_volatility_ok=bool(trend_strength.volatility.get('signal', True))
        )

        # 交易侧：根据有效偏向与识别结果确定
        side_action = (
            "long"  if (found_any and effective_bias == "long") else
            "short" if (found_any and effective_bias == "short") else
            "hold"
        )

        result: ScoringResult = engine.compute_score(factors, side=side_action)

        details = {
            "pattern": pattern,
            "pattern_bias_raw": raw_bias,
            "pattern_bias_effective": effective_bias,
            "pattern_metrics": chosen_res.metrics if chosen_res else None,
            "ema_fast": current_ema_fast_val,
            "ema_slow": current_ema_slow_val,
            "atr": current_atr_val,
            "rsi": current_rsi_val,
            "adx": current_adx_val,
            "vol_zscore": round(volume_z, 3) if volume_z is not None else None,
            "trend_signal": bool(trend_strength.signal),
            "trend_info": trend_strength.trend,
            "volatility_info": trend_strength.volatility,
            "trend_direction_ok": trend_direction_ok,
            "momentum_ok": mom_ok,
            "score": round(result.score, 3),
            "side": side_action,
        }
            
        # 计算入场止损与 trailing stop
        if result.signal != 'hold':
            planner = ExitPlanner(
                highs=highs,
                lows=lows,
                atr=current_atr_val,
                close_price=close
            )
            plan = planner.make_exit_plan(trading_signal=result.signal)
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
    Candlestick reversal strategy presets based on algo trading best practices:
    - swing: Short-term (1–2 weeks), aggressive entry, tighter trend filters.
    - intermediate: Medium-term (2–6 weeks), balanced thresholds.
    - position: Long-term (1–3 months), conservative, stricter trend and volume filters.
    """

    # ---------------- SWING ----------------
    swing = {
        "ema_fast": 8,                     # Fast EMA for short-term trend alignment.
        "ema_slow": 21,                    # Slow EMA for trend confirmation.
        "atr_period": 14,                  # ATR for volatility context.
        "rsi_period": 14,                  # RSI for momentum reversal confirmation.
        "adx_period": 14,                  # ADX for trend strength.
        "macd_params": {"fast": 12, "slow": 26, "signal": 9}, # Standard MACD settings.
        "vol_zscore_window": 20,           # Volume z-score window matches EMA period.
        "vol_zscore_threshold": 1.5,       # Moderate volume spike confirmation for swing trades.
        "score_threshold": 0.6,            # Slightly lenient threshold for short-term reversals.
    }

    # ---------------- INTERMEDIATE ----------------
    intermediate = {
        "ema_fast": 13,                    # Slightly slower EMA for medium-term trend.
        "ema_slow": 34,                    # Slower EMA for confirmation.
        "atr_period": 14,
        "rsi_period": 14,
        "adx_period": 14,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "vol_zscore_window": 30,           # Longer volume window for stability.
        "vol_zscore_threshold": 2.0,       # Stricter volume confirmation.
        "score_threshold": 0.7,            # Balanced confidence threshold.
    }

    # ---------------- POSITION ----------------
    position = {
        "ema_fast": 21,                    # Slow EMA for position trend.
        "ema_slow": 55,                    # Very slow EMA for strong trend confirmation.
        "atr_period": 14,
        "rsi_period": 14,
        "adx_period": 14,
        "macd_params": {"fast": 12, "slow": 26, "signal": 9},
        "vol_zscore_window": 40,           # Long volume window for position trades.
        "vol_zscore_threshold": 2.5,       # Very strict volume confirmation.
        "score_threshold": 0.8,            # High confidence threshold for position entries.
    }

    return {
        "swing": swing,
        "intermediate": intermediate,
        "position": position
    }