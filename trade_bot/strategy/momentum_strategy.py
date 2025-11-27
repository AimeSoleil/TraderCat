from typing import List, Optional, Dict, Any
import statistics

from trade_bot.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from trade_bot.strategy.trading_strategy import ExitPlanner, TradingStrategy, EPS
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class MomentumTrendStrategy(TradingStrategy):
    """
    Momentum Trend 策略 - Time-Series Momentum + EMA + ADX + 多周期确认（生产就绪设计）

    核心思路
    - 基于日线识别短期趋势（短期动量 ret_L）并用 EMA 快/慢 作为趋势过滤（短期 + higher timeframe 确认）
    - 使用 ADX 作为趋势强度过滤，ATR 用于止损与头寸尺寸（vol targeting）
    - 支持多周期确认（可从 provider 请求 higher timeframe 或使用简单聚合）
    - 包含初始止损（x * ATR）、Chandelier trailing、时间止损、以及仓位建议（基于风险%与ATR）

    主要参数（可通过 presets 切换）
    - L: 动量窗口（ret_L）
    - ema_fast / ema_slow: EMA 周期（用于日线）
    - ht_ema_fast / ht_ema_slow: higher-timeframe EMA 周期（用于周线或月线确认）
    - adx_period / adx_threshold: ADX 判断
    - atr_period / atr_mults: ATR 相关参数
    """

    def __init__(
        self,
        L: int = 63,  # momentum lookback (e.g. 63 trading days ~ quarter)
        ema_fast: int = 13,
        ema_slow: int = 34,
        ht_ema_fast: int = 8,  # higher timeframe EMA fast (aggregated weekly)
        ht_ema_slow: int = 21,  # higher timeframe EMA slow
        adx_period: int = 14,
        atr_period: int = 14,
        min_atr_price_ratio: float = 0.001,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 1.0,
        score_threshold: float = 0.6,
        data_provider: Any = None,
    ):
        self.L = int(L)
        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.ht_ema_fast = int(ht_ema_fast)
        self.ht_ema_slow = int(ht_ema_slow)
        self.adx_period = int(adx_period)
        self.atr_period = int(atr_period)
        self.min_atr_price_ratio = float(min_atr_price_ratio)
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

        # 指标字段命名与参数（集中声明，便于 provider 字段名对齐）
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.ht_ema_fast_field = f"close_EMA_{self.ht_ema_fast}"
        self.ht_ema_slow_field = f"close_EMA_{self.ht_ema_slow}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.atr_field = f"ATRr_{self.atr_period}"

    def get_name(self) -> str:
        return "MomentumTrend"

    def get_lookback_window(self) -> int:
        # 需要的最小历史窗口
        return (
            max(
                self.L,
                self.ema_slow,
                self.ht_ema_slow * 5,
                self.atr_period,
                self.adx_period,
            )
            + 10
        )

    # Supported scoring factors
    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.MOMENTUM_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.DAILY_TREND_CONFIRM,
            FactorName.HIGHER_TIMEFRAME_TREND_CONFIRM,
            FactorName.VOLUME_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

    # ---------- helpers ----------
    def _compute_ema_manual(self, ema_series: List[float], period: int) -> Optional[float]:
        if not ema_series or len(ema_series) < period:
            return None
        # simple EMA calculation for last value
        k = 2.0 / (period + 1.0)
        ema = ema_series[0]
        for v in ema_series[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _aggregate_higher_timeframe(
        self, candles: List[Any], days: int = 5
    ) -> List[Dict[str, Any]]:
        """
        简单的 higher-timeframe 聚合：按固定 days 聚合为一条 OHLC（用于周线近似）。
        返回按时间升序的聚合条目列表，字段: open, high, low, close, volume, date
        注：若 provider 提供更准确的周线/月线接口，可优先使用 provider.get_higher_timeframe
        """
        if days <= 1 or len(candles) < days:
            return []
        agg = []
        buf = []
        for i, c in enumerate(candles):
            buf.append(c)
            if (i + 1) % days == 0 or i == len(candles) - 1:
                opens = float(getattr(buf[0], "open", getattr(buf[0], "Open", 0)))
                closes = float(getattr(buf[-1], "close", getattr(buf[-1], "Close", 0)))
                highs = max(
                    float(getattr(x, "high", getattr(x, "High", 0))) for x in buf
                )
                lows = min(float(getattr(x, "low", getattr(x, "Low", 0))) for x in buf)
                vols = sum(
                    float(getattr(x, "volume", getattr(x, "Volume", 0))) for x in buf
                )
                agg.append(
                    {
                        "open": opens,
                        "high": highs,
                        "low": lows,
                        "close": closes,
                        "volume": vols,
                        "date": getattr(buf[-1], "date", None),
                    }
                )
                buf = []
        return agg

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        输入:
            - candles: 日线数组（old..new），每条需包含 high/low/open/close/volume/date
        输出:
            - SignalModel: signal ∈ {'buy','sell','hold'}, confidence, reason, details（包含 entry stop trailing sizing 建议）
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
                details={},
            )

        closes = [float(getattr(c, "close")) for c in candles]
        highs = [float(getattr(c, "high")) for c in candles]
        lows = [float(getattr(c, "low")) for c in candles]
        vols = [float(getattr(c, "volume")) for c in candles]
        dates = [getattr(c, "date") for c in candles]
        curr_close = closes[-1]

        # 1) momentum ret_L
        ret_L = self._compute_return_L(closes, self.L)

        # 2) EMA (daily) via provider or manual fallback
        # EMA via provider (使用封装提取，兼容不同命名)，fallback 到手动计算
        ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        ema_fast_history = [getattr(m, self.ema_fast_field, None) for m in ema_fast_series]
        ema_slow_history = [getattr(m, self.ema_slow_field, None) for m in ema_slow_series]
        current_atr_val = atr_val_history[-1]
        current_adx_val = adx_val_history[-1]
        current_ema_fast_val = ema_fast_history[-1]
        current_ema_slow_val = ema_slow_history[-1]

        # 3) higher timeframe EMA confirmation
        # higher timeframe EMA via aggregation, use extractor for last values when available
        agg = self._aggregate_higher_timeframe(candles, days=5)
        agg_closes = [x["close"] for x in agg]
        ht_fast = (
            self._compute_ema_manual(
                agg_closes[-(self.ht_ema_fast * 3) :], self.ht_ema_fast
            )
            if len(agg_closes) >= self.ht_ema_fast
            else None
        )
        ht_slow = (
            self._compute_ema_manual(
                agg_closes[-(self.ht_ema_slow * 3) :], self.ht_ema_slow
            )
            if len(agg_closes) >= self.ht_ema_slow
            else None
        )
        ht_ema_ok = True if (ht_fast is not None and ht_slow is not None) else False

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

        details: Dict[str, Any] = {
            "price": curr_close,
            "ret_L": round(ret_L, 6) if ret_L is not None else None,
            "ema_fast": round(current_ema_fast_val, 6) if current_ema_fast_val is not None else None,
            "ema_slow": round(current_ema_slow_val, 6) if current_ema_slow_val is not None else None,
            "ht_ema_fast": (
                round(ht_fast, 6) if ht_ema_ok and ht_fast is not None else None
            ),
            "ht_ema_slow": (
                round(ht_slow, 6) if ht_ema_ok and ht_slow is not None else None
            ),
            "adx": round(current_adx_val, 3) if current_adx_val is not None else None,
            "atr": round(current_atr_val, 6) if current_atr_val is not None else None,
            "trend_strength": trend_strength.reason,
        }

        trend_day_up = (
            current_ema_fast_val is not None
            and current_ema_slow_val is not None
            and current_ema_fast_val > current_ema_slow_val
        )
        trend_day_down = (
            current_ema_fast_val is not None
            and current_ema_slow_val is not None
            and current_ema_fast_val < current_ema_slow_val
        )
        trend_ht_up = (
            ht_ema_ok
            and ht_fast is not None
            and ht_slow is not None
            and ht_fast > ht_slow
        )
        trend_ht_down = (
            ht_ema_ok
            and ht_fast is not None
            and ht_slow is not None
            and ht_fast < ht_slow
        )

        # momentum rule: long if ret_L > 0 and same direction EMAs; short if ret_L < 0 and EMA alignment
        # classic momentum measure:
        #   - If return_L > 0, price has risen over the last L periods → bullish momentum.
        #   - If return_L < 0, price has fallen → bearish momentum.
        long_cond = (
            (ret_L is not None and ret_L > 0)
            and trend_day_up
            and (not ht_ema_ok or trend_ht_up)
        )
        short_cond = (
            (ret_L is not None and ret_L < 0)
            and trend_day_down
            and (not ht_ema_ok or trend_ht_down)
        )

        # 7) signals & scoring - 重点强调 动量 + 多周期趋势 + ADX 共振，适度降低辅助因子权重
        result: ScoringResult = None
        factors = [
            Factor(FactorName.MOMENTUM_CONFIRM, "动量确认", 0.3, long_cond or short_cond),
            Factor(FactorName.TREND_STRENGTH, "趋势强度确认", 0.25, trend_strength.signal),
            Factor(FactorName.DAILY_TREND_CONFIRM, "日线EMA确认", 0.2, trend_strength.signal),
            Factor(FactorName.HIGHER_TIMEFRAME_TREND_CONFIRM, "高周期EMA确认", 0.15, trend_strength.signal),
            Factor(FactorName.VOLUME_CONFIRM, "成交量放大确认", 0.05, vol_ok),
            Factor(FactorName.CONFLUENCE_BONUS, "多周期趋势+ADX共振加分", 0.05, (trend_day_up and trend_ht_up and trend_strength.trend) or (trend_day_down and trend_ht_down and trend_strength.trend))
        ]

        # Compute score using ScoringEngine
        engine = ScoringEngine(
            base_threshold=self.score_threshold, 
            required_factors=self.support_scoring_factors(),
            determined_factors=[
                FactorName.MOMENTUM_CONFIRM
            ],
            is_volatility_ok=trend_strength.volatility['signal']
        )
        side = "long" if long_cond else "short" if short_cond else "hold"
        result = engine.compute_score(factors, side=side)

        # 8) 计算入场止损与 trailing stop
        if result and result.signal != 'hold':
            planner = ExitPlanner(
                highs=highs,
                lows=lows,
                atr=current_atr_val,
                close_price=curr_close
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

def make_momentum_presets() -> Dict[str, Dict[str, Any]]:
    """
    MomentumTrend 策略预设（资深 algo trader 推荐）
    - swing：短波段（更快响应），较低门槛与较小止损
    - intermediate：中波段（平衡），回测默认
    - position：中长线（更严格确认），更高门槛与更大止损
    """
    swing = {
        "L": 21,                           # Lookback for momentum score (often matches slow EMA)
        "ema_fast": 8,                     # Fast EMA for short-term trend
        "ema_slow": 21,                    # Slow EMA for trend confirmation
        "ht_ema_fast": 8,                  # Hilbert Transform EMA fast (same as EMA fast)
        "ht_ema_slow": 21,                 # Hilbert Transform EMA slow (same as EMA slow)
        "adx_period": 14,                  # ADX standard period for trend strength
        "atr_period": 14,                  # ATR for volatility context
        "min_atr_price_ratio": 0.002,      # Ensures volatility is meaningful (0.2%)
        "vol_zscore_window": 20,           # Match EMA period for volume breakout detection
        "vol_zscore_threshold": 1.0,       # Stricter volume confirmation for trend continuation
        "score_threshold": 0.7             # Balanced threshold for momentum confidence
    }


    intermediate = {
        **swing,
    }

    position = {
        **swing,
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}