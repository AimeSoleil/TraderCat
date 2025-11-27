from typing import List, Optional, Dict, Any, Tuple
import math
import statistics

from trade_bot.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from trade_bot.strategy.trading_strategy import ExitPlanner, TradingStrategy, EPS
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class FibonacciRetracementStrategy(TradingStrategy):
    """
    Fibonacci Retracement + Breakout 策略（生产就绪）

    概要:
        - 在一次冲击波(impulse)后，等待价格回撤至 Fib 38.2% - 61.8% 区间，
        当价格在该区间确认回撤后出现突破（突破区间高位或突破上一个摆动高点）则入场顺势；
        - 使用 EMA 快慢线作为趋势滤波；ATR 用于止损与仓位基准；支持时间止损与多种保护；
        - 以日线为主，持仓以周为单位；通过 presets 可切换为中/长期模式。

    使用建议（简短）:
        - 适用: 趋势明显的品种，流动性充足，波段持仓（数日到数周）
        - 不适用: 新闻驱动价差，低流动性或持续震荡盤
    """

    def __init__(
        self,
        lookback_swings: int = 30,
        swing_window: int = 4,
        fib_zone: Tuple[float, float] = (0.382, 0.618),
        ema_fast: int = 13,
        ema_slow: int = 34,
        atr_period: int = 14,
        rsi_period: int = 14,
        macd_params: Optional[Dict[str, int]] = None,
        adx_period: int = 14,
        min_atr_price_ratio: float = 0.0015,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.6,
        data_provider: Any = None,
    ):
        self.lookback_swings = int(lookback_swings)
        self.swing_window = max(1, int(swing_window))
        self.fib_low = float(fib_zone[0])
        self.fib_high = float(fib_zone[1])
        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.atr_period = int(atr_period)
        self.rsi_period = int(rsi_period)
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}
        self.adx_period = adx_period
        self.min_atr_price_ratio = float(min_atr_price_ratio)
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # 指标字段命名（集中在构造函数定义，方便后续修改）
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"
        self.macd_field = f"close_MACD_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_signal_field = f"close_MACDs_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"
        self.macd_hist_field = f"close_MACDh_{self.macd_params['fast']}_{self.macd_params['slow']}_{self.macd_params['signal']}"

    def get_name(self) -> str:
        return "FibonacciRetracement"

    def get_lookback_window(self) -> int:
        return (
            max(
                self.lookback_swings,
                self.ema_slow,
                self.atr_period,
                (self.macd_params["slow"] or 0),
            )
            + 10
        )

    # Supported scoring factors
    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.FIB_ZONE_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.VOLUME_CONFIRM,
            FactorName.MOMENTUM_CONFIRM,
            FactorName.TREND_DIRECTION_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

    # -------------- Helper Functions --------------
    def _select_fib_zone(
        self,
        fib_levels: Dict[float, float]=None,
        base_fib_low=0.382,
        base_fib_high=0.618,
        pullback_type="auto",
        trend_strength=None,
    ):
        """
        Select Fibonacci zone dynamically based on pullback type or trend strength.
        - fib_levels: dict of fib ratios to price levels
        - base_fib_low: fib zone high
        - base_fib_high: fib zone low
        - pullback_type: 'shallow', 'deep', or 'auto'
        - trend_strength: optional ADX or similar metric
        Returns: (zone_high, zone_low)
        """
        if not fib_levels:
            raise ValueError("Missing fib_levels")
        
        # Default zones
        if base_fib_low > 0.5 or base_fib_high < 0.5:
            raise ValueError("Invalid base fib levels")
        
        shallow_zone = (base_fib_low, 0.5)
        deep_zone = (0.5, base_fib_high)

        # Auto mode: decide based on trend strength
        if pullback_type == "auto":
            if trend_strength and trend_strength > 25:  # strong trend
                zone = shallow_zone
            else:
                zone = deep_zone
        elif pullback_type == "shallow":
            zone = shallow_zone
        elif pullback_type == "deep":
            zone = deep_zone
        else:
            raise ValueError("Invalid pullback_type")
        
        zone_high = fib_levels[zone[0]]
        zone_low = fib_levels[zone[1]]
        return zone_high, zone_low

    def _calc_fib_levels(
        self, swing_high: float, swing_low: float
    ) -> Dict[float, float]:
        diff = abs(swing_high - swing_low)
        base = swing_high
        direction = -1
        ratios = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
        return {r: base + direction * r * diff for r in ratios}

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        输入:
            - candles: 日线列表，按时间升序（旧->新），每条需包含 high/low/open/close/volume/date
        输出:
            - SignalModel: signal in {'buy','sell','hold'} + details 包含入场/止损/目标计划与诊断信息
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
                reason="insufficient data or provider",
                details={},
            )

        # extract OHLCV windows
        N = min(
            len(candles), max(self.lookback_swings, self.ema_slow, self.atr_period) + 5
        )
        base = len(candles) - N
        highs = [float(getattr(c, "high", None)) for c in candles[base:]]
        lows = [float(getattr(c, "low", None)) for c in candles[base:]]
        closes = [float(getattr(c, "close", None)) for c in candles[base:]]
        vols = [float(getattr(c, "volume", None)) for c in candles[base:]]
        dates = [getattr(c, "date", None) for c in candles[base:]]
        curr_close = closes[-1]

        # 指标 via provider（使用构造函数中定义的 period/field）
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        macd_series = self.provider.get_indicator("macd", candles, self.macd_params)
        rsi_series = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        rsi_val_history = [getattr(r, self.rsi_field, None) for r in rsi_series]
        macd_hist_val_history = [getattr(m, self.macd_hist_field, None) for m in macd_series] if macd_series else []
        ema_fast_history = [getattr(m, self.ema_fast_field, None) for m in ema_fast_series]
        ema_slow_history = [getattr(m, self.ema_slow_field, None) for m in ema_slow_series]
        current_atr_val = atr_val_history[-1]
        current_adx_val = adx_val_history[-1]
        current_ema_fast_val = ema_fast_history[-1]
        current_ema_slow_val = ema_slow_history[-1]

        # trend filter
        trend_up = (
            current_ema_fast_val is not None
            and current_ema_slow_val is not None
            and current_ema_fast_val > current_ema_slow_val
        )
        trend_down = (
            current_ema_fast_val is not None
            and current_ema_slow_val is not None
            and current_ema_fast_val < current_ema_slow_val
        )

        # swings detection on lookback window
        swings_highs, swings_lows = self._find_fractal_swings(
            highs[-(self.lookback_swings + self.swing_window * 2 + 5) :],
            lows[-(self.lookback_swings + self.swing_window * 2 + 5) :],
            self.swing_window,
        )

        # convert local indices to global (relative to full candles)
        # pick most recent impulse: last pair of opposite swing (e.g., low->high for bullish impulse)
        if not swings_highs and not swings_lows:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=dates[-1],
                confidence=0.0,
                reason="no swing points",
            )

        # default: treat impulse as high->low or low->high depending on which is more recent
        # choose swing pair to compute fib base: for long we want an impulse low->high, for short high->low
        # find last completed impulse (use the two most recent opposite swings)
        long_candidate = None
        short_candidate = None
        if len(swings_lows) >= 2:
            # possible long impulse: earlier low -> later high
            # find latest low preceding a later high
            for i in range(len(swings_lows) - 1, -1, -1):
                low_idx, low_val = swings_lows[i]
                # find next high after low
                nxt_highs = [h for h in swings_highs if h[0] > low_idx]
                if nxt_highs:
                    high_idx, high_val = nxt_highs[-1]
                    long_candidate = (low_idx, low_val, high_idx, high_val)
                    break

        if len(swings_highs) >= 2:
            # possible short impulse: earlier high -> later low
            for i in range(len(swings_highs) - 1, -1, -1):
                high_idx, high_val = swings_highs[i]
                nxt_lows = [l for l in swings_lows if l[0] > high_idx]
                if nxt_lows:
                    low_idx, low_val = nxt_lows[-1]
                    short_candidate = (high_idx, high_val, low_idx, low_val)
                    break

        # Choose the recent swing impulse if both long/short swing existing
        chosen = None
        if long_candidate and short_candidate:
            # Compare last indices
            if long_candidate[2] > short_candidate[2]:
                chosen = "long_candidate"  # Long impulse ends later
            else:
                chosen = "short_candidate"
        else:
            if long_candidate:
                chosen = "long_candidate"
            elif short_candidate:
                chosen = "short_candidate"

        # ---------- 趋势强度和波动率 -----------
        trend_strength = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=atr_val_history,
            close=curr_close,
            window=100,
            atr_base_threshold=self.min_atr_price_ratio,
            atr_quantile=0.8,
            adx_quantile=0.8,
            mode='reversal'
        )

        # ---------- 成交量 z-score 确认 -----------
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

        # evaluate long candidate
        details = {}
        result: ScoringResult = None
        if chosen:
            if chosen == "long_candidate":
                swing_low_idx, swing_low_val, swing_high_idx, swing_high_val = (
                    long_candidate
                )
            else:
                swing_high_idx, swing_high_val, swing_low_idx, swing_low_val = (
                    short_candidate
                )
            details.update(
                {
                    "pattern": chosen,
                    "swing_low_at": dates[swing_low_idx],
                    "swing_low_val": swing_low_val,
                    "swing_high_at": dates[swing_high_idx],
                    "swing_high_val": swing_high_val,
                }
            )
            # compute fib levels from swing_high (impulse top) and swing_low (impulse low)
            fib_levels = self._calc_fib_levels(swing_high_val, swing_low_val)
            zone_high, zone_low = self._select_fib_zone(
                fib_levels=fib_levels,
                base_fib_low=self.fib_low,
                base_fib_high=self.fib_high,
                pullback_type="auto",
                trend_strength=current_adx_val
            )
            details.update({"fib_zone_high": zone_high, "fib_zone_low": zone_low})
            # check price is inside fib zone (between zone_high and zone_low)
            in_zone = zone_low - EPS <= curr_close <= zone_high + EPS
            # breakout confirmation: close above zone_high (i.e., price moves back above the upper zone boundary) OR close above recent swing high
            breakout_up_confirm = (curr_close > zone_high + EPS) or (
                curr_close > swing_high_val + EPS
            )
            breakout_down_confirm = (curr_close < zone_low + EPS) or (
                curr_close < swing_low_val + EPS
            )

            # 动量确认
            mom_ok = None
            if breakout_up_confirm or in_zone:
                mom_ok = self._momentum_confirm(
                    rsi_val_history, macd_hist_val_history, prefer="bull"
                )
            elif breakout_down_confirm:
                mom_ok = self._momentum_confirm(
                    rsi_val_history, macd_hist_val_history, prefer="bear"
                )

            # 评分 & 生成 signal
            factors: List[Factor] = []
            if in_zone:
                factors.append(Factor(FactorName.FIB_ZONE_CONFIRM, "回撤区间确认(价格在Fibonacci区间内)", 0.25, in_zone))
            elif breakout_up_confirm:
                factors.append(Factor(FactorName.FIB_ZONE_CONFIRM, "向上突破区间确认(价格突破Fibonacci区间)", 0.35, breakout_up_confirm))
            elif breakout_down_confirm:
                factors.append(Factor(FactorName.FIB_ZONE_CONFIRM, "向下突破区间确认(价格突破Fibonacci区间)", 0.35, breakout_down_confirm))
            factors.append(
                Factor(FactorName.TREND_STRENGTH, "趋势强度确认", 0.15, trend_strength.signal)
            )
            factors.append(
                Factor(FactorName.VOLUME_CONFIRM, "成交量放大", 0.1, vol_ok)
            )
            factors.append(
                Factor(FactorName.MOMENTUM_CONFIRM, "动量确认", 0.15, mom_ok)
            )
            factors.append(
                Factor(FactorName.TREND_DIRECTION_CONFIRM, "趋势方向一致", 0.1, (in_zone and breakout_up_confirm and trend_up) or (breakout_down_confirm and trend_down))
            )
            factors.append(
                Factor(FactorName.CONFLUENCE_BONUS, "三重共振加分", 0.05, trend_strength.signal and mom_ok)
            )
            engine = ScoringEngine(
                base_threshold=self.score_threshold, 
                required_factors=self.support_scoring_factors(),
                determined_factors=[
                    FactorName.FIB_ZONE_CONFIRM
                ],
                is_volatility_ok=trend_strength.volatility.signal
            )
            side = "long" if (in_zone or breakout_up_confirm) else "short" if breakout_down_confirm else "hold"
            result = engine.compute_score(factors, side=side)

            # 计算入场止损与 trailing stop
            if result and result.signal != 'hold':
                planner = ExitPlanner(
                    highs=highs,
                    lows=lows,
                    atr=current_atr_val,
                    close_price=curr_close,
                )
                plan = planner.make_exit_plan('long' if result.signal == 'buy' else 'short')
                details.update({"plan": plan})
        else:
            result = ScoringResult(
                score=0.0, threshold=self.score_threshold, signal="hold", reasons=["无有效高低波摆动点检测"]
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


def make_fibonacci_presets() -> Dict[str, Dict[str, Any]]:
    """
    为 FibonacciRetracementStrategy 设计的专业预设（swing / intermediate / position）
    说明：
        - 值基于经验与风险管理最佳实践，便于快速在不同周期间切换和回测比较。
    """
    swing = {
        "lookback_swings": 20,               # Look back for swing highs/lows
        "swing_window": 5,                   # Minimum bars to confirm a swing pivot
        "fib_zone": (0.382, 0.618),          # Golden zone for retracement entries
        "ema_fast": 8,                       # Fast EMA for short-term trend
        "ema_slow": 21,                      # Slow EMA for trend confirmation
        "atr_period": 14,                    # ATR for volatility context
        "rsi_period": 14,                    # Standard RSI for momentum confirmation
        "macd_params": {"fast": 12, "slow": 26, "signal": 9}, # Standard MACD settings
        "adx_period": 14,                    # ADX for trend strength filter
        "min_atr_price_ratio": 0.002,        # Ensures volatility is meaningful (0.2%)
        "vol_zscore_window": 20,             # Match EMA/BB period for volume breakout detection
        "vol_zscore_threshold": 1.0,         # Stricter volume confirmation for breakout
        "score_threshold": 0.7              # Balanced threshold for breakout confidence
    }

    intermediate = {
        **swing
    }

    position = {
        **swing
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}
