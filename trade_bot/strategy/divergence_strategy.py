from typing import List, Optional, Dict, Any, Tuple
import statistics

from trade_bot.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from trade_bot.strategy.trading_strategy import ExitPlanner, TradingStrategy, EPS
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class DivergenceStrategy(TradingStrategy):
    """
    Divergence 策略（Regular + Hidden）
    - 目标：在日线识别常规背离（regular divergence）与隐藏背离（hidden divergence），
        用于捕捉反转（regular）与趋势延续（hidden）。
    - 指标：默认 RSI（可选 MACD histogram）为主；可选 ADX/ATR 过滤。
    - 逻辑要点：
        * Regular Bearish: 价格做 HH，而指标未创新高（或下降） -> 顶背离 -> 做空/平多
        * Regular Bullish: 价格做 LL，而指标未创新低 -> 底背离 -> 做多/平空
        * Hidden Bullish: 价格做 higher-low，但指标做 lower-low -> 趋势延续多头
        * Hidden Bearish: 价格做 lower-high，但指标做 higher-high -> 趋势延续空头
    - 输出 SignalModel 包含 reason、confidence、建议止损/目标（基于最近 swing + ATR）
    - 以日线为主；通过 presets 可切换短/中/长周期敏感度
    """

    def __init__(
        self,
        swing_window: int = 5,  # N-bar fractal window
        lookback_swings: int = 60,
        rsi_period: int = 14,
        macd_params: Optional[Dict[str, int]] = None,
        atr_period: int = 14,
        min_atr_price_ratio: float = 0.002,
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
        self.min_atr_price_ratio = float(min_atr_price_ratio)
        self.adx_period = int(adx_period) if adx_period else None
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # 指标字段命名（对应 provider 返回的属性）
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
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

    # Supported scoring factors
    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.DIVERGENCE,
            FactorName.TREND_STRENGTH,
            FactorName.VOLUME_CONFIRM,
            FactorName.VOLUME_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]
    
    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        输入:
            candles: 日线序列（old..new），每条需含 high/low/open/close/volume/date
        输出:
            SignalModel(signal ∈ {'buy','sell','hold'}, confidence, reason, details)
        """
        if (
            not candles
            or not self.provider
            or len(candles) < self.get_lookback_window()
        ):
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date if candles else None,
                confidence=0.0,
                reason="数据不足",
            )

        # indicators via provider
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params)
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        highs = [float(getattr(c, "high", 0)) for c in candles]
        lows = [float(getattr(c, "low", 0)) for c in candles]
        closes = [float(getattr(c, "close", 0)) for c in candles]
        vols = [float(getattr(c, "volume", 0)) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]
        close = closes[-1]
        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        rsi_val_history = [getattr(r, self.rsi_field, None) for r in rsi_series]
        macd_hist_val_history = [getattr(m, self.macd_hist_field, None) for m in macd_series] if macd_series else []
        current_atr_val = atr_val_history[-1]

        # 成交量 z-score 确认
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(
            vols, recent_window, self.vol_zscore_threshold
        )

        # find fractals (use lookback window slice to reduce noise)
        use_highs = highs[-(self.lookback_swings + self.swing_window * 2 + 5) :]
        use_lows = lows[-(self.lookback_swings + self.swing_window * 2 + 5) :]
        high_pts, low_pts = self._find_fractal_swings(use_highs, use_lows, self.swing_window)
        # rebase indices to full candles
        base = len(highs) - len(use_highs)
        high_pts = [(i + base, v) for (i, v) in high_pts]
        low_pts = [(i + base, v) for (i, v) in low_pts]

        # helper to get last two relevant swings (most recent two)
        def last_two(points: List[Tuple[int, float]]):
            if len(points) < 2:
                return None
            return points[-2], points[-1]


        details: Dict[str, Any] = {
            "close": close,
            "atr": atr_val_history[-1],
            "vol_z": volume_z
        }
        result: ScoringResult = None
        # ---- check bearish / bullish on regular & hidden using highs and lows ----
        found = False
        h2 = last_two(high_pts)
        if h2:
            (i1, p1), (i2, p2) = h2
            if i2 > i1 and p2 > p1 + EPS:
                # price made higher high -> possible regular bearish if indicator did not make HH
                # locate indicator values at approx indices (map into rsi_hist slice)
                r1, r2 = self._get_indicator_values_at_indices(
                    rsi_val_history, [i1, i2], len(candles)
                )
                macd1, macd2 = (None, None)
                if macd_hist_val_history:
                    macd1, macd2 = self._get_indicator_values_at_indices(
                        macd_hist_val_history, [i1, i2], len(candles)
                    )

                indicator_failed_to_confirm = False
                if r1 is not None and r2 is not None:
                    indicator_failed_to_confirm = r2 <= r1 + EPS
                elif macd1 is not None and macd2 is not None:
                    indicator_failed_to_confirm = macd2 <= macd1 + EPS
                else:
                    indicator_failed_to_confirm = False

                # Mark divergence found = True
                if indicator_failed_to_confirm:
                    found = True
                
                # momentum confirm: prefer RSI falling or macd hist negative
                mom_ok = self._MOMENTUM_CONFIRM(
                    rsi_val_history=rsi_val_history, 
                    macd_hist_val_history=macd_hist_val_history, 
                    prefer="bear"
                )

                # 趋势强度
                trend_strength = self._check_trend_and_volatility(
                    atr_val_history=atr_val_history,
                    adx_val_history=adx_val_history,
                    close=close,
                    window=100,
                    atr_base_threshold=self.min_atr_price_ratio,
                    atr_quantile=0.8,
                    adx_quantile=0.8,
                    mode='reversal'
                )

                details.update(
                    {
                        "type": "regular_bear",
                        "swing1": (dates[i1], p1),
                        "swing2": (dates[i2], p2),
                        "indicator_r1": r1,
                        "indicator_r2": r2,
                    }
                )

                # ---------- 评分系统 ----------
                factors = [
                    Factor(FactorName.DIVERGENCE, "Bearish背离触发", 0.4, indicator_failed_to_confirm),
                    Factor(FactorName.TREND_STRENGTH, "趋势强度和波动率确认", 0.2, trend_strength.signal),
                    Factor(FactorName.MOMENTUM_CONFIRM, "动量确认方向确认", 0.2, mom_ok),
                    Factor(FactorName.VOLUME_CONFIRM, "成交量放大确认", 0.15, vol_ok),
                    Factor(FactorName.CONFLUENCE_BONUS, "三重共振加分", 0.05, mom_ok and trend_strength.signal)
                ]

                # Compute score using ScoringEngine
                engine = ScoringEngine(
                    base_threshold=0.7, 
                    required_factors=self.support_scoring_factors(),
                    determined_factors=[
                        FactorName.DIVERGENCE
                    ]
                )
                result = engine.compute_score(factors, side="short")

                # 计算入场止损与 trailing stop
                if result.signal != 'hold':
                    planner = ExitPlanner(
                        highs=highs,
                        lows=lows,
                        atr=current_atr_val,
                        close_price=close
                    )
                    plan = planner.make_exit_plan('long' if result.signal == 'buy' else 'short')
                    details.update({"plan": plan})
        # Regular bullish / hidden bullish (use last two lows)
        l2 = last_two(low_pts)
        if not found and l2:
            (j1, q1), (j2, q2) = l2
            if j2 > j1 and q2 < q1 - EPS:
                # price made lower low -> possible regular bullish if indicator did not make LL
                r1 = r2 = None
                if rsi_val_history:
                    rel_base = len(candles) - len(rsi_val_history)
                    try:
                        r1 = (
                            rsi_val_history[j1 - rel_base]
                            if 0 <= j1 - rel_base < len(rsi_val_history)
                            else None
                        )
                        r2 = (
                            rsi_val_history[j2 - rel_base]
                            if 0 <= j2 - rel_base < len(rsi_val_history)
                            else None
                        )
                    except Exception:
                        r1 = r2 = None
                macd1 = macd2 = None
                if macd_hist_val_history:
                    rel_base = len(candles) - len(macd_hist_val_history)
                    try:
                        macd1 = (
                            macd_hist_val_history[j1 - rel_base]
                            if 0 <= j1 - rel_base < len(macd_hist_val_history)
                            else None
                        )
                        macd2 = (
                            macd_hist_val_history[j2 - rel_base]
                            if 0 <= j2 - rel_base < len(macd_hist_val_history)
                            else None
                        )
                    except Exception:
                        macd1 = macd2 = None

                indicator_failed = False
                if r1 is not None and r2 is not None:
                    indicator_failed = r2 >= r1 - EPS
                elif macd1 is not None and macd2 is not None:
                    indicator_failed = macd2 >= macd1 - EPS
                else:
                    indicator_failed = False
                
                # Mark divergence found = True
                if indicator_failed:
                    found = True
                
                # momentum confirm: prefer RSI falling or macd hist negative
                mom_ok = self._MOMENTUM_CONFIRM(
                    rsi_val_history=rsi_val_history, 
                    macd_hist_val_history=macd_hist_val_history, 
                    prefer="bull"
                )

                # 趋势强度
                trend_strength = self._check_trend_and_volatility(
                    atr_val_history=atr_val_history,
                    adx_val_history=adx_val_history,
                    close=close,
                    window=100,
                    atr_base_threshold=self.min_atr_price_ratio,
                    atr_quantile=0.8,
                    adx_quantile=0.8,
                    mode='reversal'
                )

                details.update(
                    {
                        "type": "regular_bull",
                        "swing1": (dates[j1], q1),
                        "swing2": (dates[j2], q2),
                        "indicator_r1": r1,
                        "indicator_r2": r2,
                    }
                )
                
                # ---------- 评分系统 ----------
                result: ScoringResult = None
                factors = [
                    Factor(FactorName.DIVERGENCE, "Bullish背离触发", 0.4, indicator_failed),
                    Factor(FactorName.TREND_STRENGTH, "趋势强度和波动率确认", 0.2, trend_strength.signal),
                    Factor(FactorName.MOMENTUM_CONFIRM, "动量确认方向确认", 0.2, mom_ok),
                    Factor(FactorName.VOLUME_CONFIRM, "成交量放大确认", 0.15, vol_ok),
                    Factor(FactorName.CONFLUENCE_BONUS, "三重共振加分", 0.05, mom_ok and trend_strength.signal)
                ]

                # Compute score using ScoringEngine
                engine = ScoringEngine(
                    base_threshold=0.7, 
                    required_factors=self.support_scoring_factors(),
                    determined_factors=[
                        FactorName.DIVERGENCE
                    ]
                )
                result = engine.compute_score(factors, side="long")

                # 计算入场止损与 trailing stop
                if result.signal != 'hold':
                    planner = ExitPlanner(
                        highs=highs,
                        lows=lows,
                        atr=current_atr_val,
                        close_price=close
                    )
                    plan = planner.make_exit_plan('long' if result.signal == 'buy' else 'short')
                    details.update({"plan": plan})
        # Hidden divergences: detect trend continuation signals
        if not found:
            # Hidden bullish: price makes higher-low (HL) while indicator makes lower-low
            if len(low_pts) >= 2:
                (a_idx, a_val), (b_idx, b_val) = low_pts[-2], low_pts[-1]
                if b_idx > a_idx and b_val > a_val + EPS:
                    # price HL -> check indicator made lower-low
                    r1, r2 = self._get_indicator_values_at_indices(
                        rsi_val_history, [a_idx, b_idx], len(candles)
                    )
                    macd1, macd2 = (None, None)
                    if macd_hist_val_history:
                        macd1, macd2 = self._get_indicator_values_at_indices(
                            macd_hist_val_history, [a_idx, b_idx], len(candles)
                        )
                    indicator_lower = False
                    if r1 is not None and r2 is not None:
                        indicator_lower = r2 < r1 - EPS
                    elif macd1 is not None and macd2 is not None:
                        indicator_lower = macd2 < macd1 - EPS
                    
                    # Mark divergence found = True
                    if indicator_lower:
                        found = True
                    
                    # momentum confirm: prefer RSI falling or macd hist negative
                    mom_ok = self._MOMENTUM_CONFIRM(
                        rsi_val_history=rsi_val_history, 
                        macd_hist_val_history=macd_hist_val_history, 
                        prefer="bear"
                    )
                    # 趋势强度
                    trend_strength = self._check_trend_and_volatility(
                        atr_val_history=atr_val_history,
                        adx_val_history=adx_val_history,
                        close=close,
                        window=100,
                        atr_base_threshold=self.min_atr_price_ratio,
                        atr_quantile=0.8,
                        adx_quantile=0.8,
                        mode='trend'
                    )

                    details.update(
                        {
                            "type": "hidden_bull",
                            "swing_prev": (dates[a_idx], a_val),
                            "swing_latest": (dates[b_idx], b_val),
                        }
                    )

                    # ---------- 评分系统 ----------
                    result: ScoringResult = None
                    factors = [
                        Factor(FactorName.DIVERGENCE, "隐藏Bullish背离触发", 0.3, indicator_lower),
                        Factor(FactorName.TREND_STRENGTH, "趋势强度和波动率确认", 0.25, trend_strength.signal),
                        Factor(FactorName.MOMENTUM_CONFIRM, "动量确认方向确认", 0.2, mom_ok),
                        Factor(FactorName.VOLUME_CONFIRM, "成交量放大确认", 0.15, vol_ok),
                        Factor(FactorName.CONFLUENCE_BONUS, "三重共振加分", 0.1, mom_ok and trend_strength.signal)
                    ]

                    # Compute score using ScoringEngine
                    engine = ScoringEngine(
                        base_threshold=0.7, 
                        required_factors=self.support_scoring_factors(),
                        determined_factors=[
                            FactorName.DIVERGENCE
                        ]
                    )
                    result = engine.compute_score(factors, side="long")

                    # 计算入场止损与 trailing stop
                    if result.signal != 'hold':
                        planner = ExitPlanner(
                            highs=highs,
                            lows=lows,
                            atr=current_atr_val,
                            close_price=close
                        )
                        plan = planner.make_exit_plan('long' if result.signal == 'buy' else 'short')
                        details.update({"plan": plan})
            # Hidden bearish
            if not found and len(high_pts) >= 2:
                (a_idx, a_val), (b_idx, b_val) = high_pts[-2], high_pts[-1]
                if b_idx > a_idx and b_val < a_val - EPS:
                    r1, r2 = self._get_indicator_values_at_indices(
                        rsi_val_history, [a_idx, b_idx], len(candles)
                    )
                    macd1, macd2 = (None, None)
                    if macd_hist_val_history:
                        macd1, macd2 = self._get_indicator_values_at_indices(
                            macd_hist_val_history, [a_idx, b_idx], len(candles)
                        )
                    indicator_higher = False
                    if r1 is not None and r2 is not None:
                        indicator_higher = r2 > r1 + EPS
                    elif macd1 is not None and macd2 is not None:
                        indicator_higher = macd2 > macd1 + EPS
                    
                    # Mark divergence found = True
                    if indicator_higher:
                        found = True

                    # momentum confirm: prefer RSI falling or macd hist negative
                    mom_ok = self._MOMENTUM_CONFIRM(
                        rsi_val_history=rsi_val_history, 
                        macd_hist_val_history=macd_hist_val_history, 
                        prefer="bear"
                    )
                    # 趋势强度
                    trend_strength = self._check_trend_and_volatility(
                        atr_val_history=atr_val_history,
                        adx_val_history=adx_val_history,
                        close=close,
                        window=100,
                        atr_base_threshold=self.min_atr_price_ratio,
                        atr_quantile=0.8,
                        adx_quantile=0.8,
                        mode='trend'
                    )

                    details.update(
                        {
                            "type": "hidden_bear",
                            "swing_prev": (dates[a_idx], a_val),
                            "swing_latest": (dates[b_idx], b_val),
                        }
                    )

                    # ---------- 评分系统 ----------
                    result: ScoringResult = None
                    factors = [
                        Factor(FactorName.DIVERGENCE, "隐藏Bearish背离触发", 0.3, indicator_higher),
                        Factor(FactorName.TREND_STRENGTH, "趋势强度和波动率确认", 0.25, trend_strength.signal),
                        Factor(FactorName.MOMENTUM_CONFIRM, "动量确认方向确认", 0.2, mom_ok),
                        Factor(FactorName.VOLUME_CONFIRM, "成交量放大确认", 0.15, vol_ok),
                        Factor(FactorName.CONFLUENCE_BONUS, "三重共振加分", 0.1, mom_ok and trend_strength.signal)
                    ]

                    # Compute score using ScoringEngine
                    engine = ScoringEngine(
                        base_threshold=0.7, 
                        required_factors=self.support_scoring_factors(),
                        determined_factors=[
                            FactorName.DIVERGENCE
                        ]
                    )
                    result = engine.compute_score(factors, side="short")

                    # 计算入场止损与 trailing stop
                    if result.signal != 'hold':
                        planner = ExitPlanner(
                            highs=highs,
                            lows=lows,
                            atr=current_atr_val,
                            close_price=close
                        )
                        plan = planner.make_exit_plan('long' if result.signal == 'buy' else 'short')
                        details.update({"plan": plan})
        # usage notes & failsafe
        details.setdefault(
            "notes",
            "常规背离用于反转；隐藏背离用于趋势延续。建议结合多周期确认与新闻/流动性过滤；",
        )
        if not found:
            result = ScoringResult(
                score=0.0, threshold=self.score_threshold, signal="hold", reasons=["未检测到背离"]
            )
            
        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            date=dates[-1],
            confidence=round(result.score, 3),
            reason=" | ".join(result.reasons),
            details=details,
        )

def make_divergence_presets() -> Dict[str, Dict[str, Any]]:
    """
    Divergence 策略预设（资深 algo trader 推荐）
    说明（统一三档/四档可选）：
        - swing: 短波段（1-2 周），更灵敏的背离检测、较低成交量阈值与较短确认窗口
        - intermediate: 中波段（2-6 周），平衡参数（回测默认）
        - position/long_term: 中长线（1-3 月），更严格的过滤、更长的回溯与更高成交量阈值
    """
    swing = {
        "swing_window": 4,                  # Minimum bars to confirm a swing high/low
        "lookback_swings": 30,              # Look back for divergence detection (30 swings)
        "rsi_period": 14,                   # Standard RSI for momentum divergence
        "macd_params": {"fast": 12, "slow": 26, "signal": 9}, # Standard MACD for trend/momentum
        "atr_period": 14,                   # ATR for volatility context
        "min_atr_price_ratio": 0.002,       # Ensures volatility is meaningful (0.2%)
        "adx_period": 14,                   # ADX for trend strength filter
        "vol_zscore_window": 20,            # Match ATR/BB period for volume confirmation
        "vol_zscore_threshold": 1.0,        # Stricter volume breakout confirmation
        "score_threshold": 0.75             # Higher threshold for divergence confidence
    }

    intermediate = {
        **swing,
    }

    position = {
        **swing,
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}