from typing import List, Optional, Dict, Any, Tuple

from trade_bot.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from trade_bot.strategy.trading_strategy import ExitPlanner, TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class BollingerBreakoutStrategy(TradingStrategy):

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        trailing_bw_window: int = 60,
        bw_percentile_threshold: float = 30.0,  # percentile threshold (e.g. 30)
        ema_fast: int = 8,
        ema_slow: int = 21,
        atr_period: int = 14,
        adx_period: int = 14,
        rsi_period: Optional[int] = 14,
        prior_swing_bars: int = 3,
        min_atr_price_ratio: float = 0.02,  # volatility guard: ATR / price
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 2.0,
        score_threshold: float = 0.7,
        data_provider=None,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.trailing_bw_window = trailing_bw_window
        self.bw_percentile_threshold = bw_percentile_threshold
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.atr_period = atr_period
        self.adx_period = adx_period
        self.rsi_period = rsi_period
        self.prior_swing_bars = prior_swing_bars
        self.min_atr_price_ratio = min_atr_price_ratio
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = score_threshold
        self.provider = data_provider

        # 指标字段命名（对应 provider 返回的属性）
        self.bb_bw_field = f"close_BBB_{self.bb_period}_{self.bb_std}"
        self.bb_up_field = f"close_BBU_{self.bb_period}_{self.bb_std}"
        self.bb_low_field = f"close_BBL_{self.bb_period}_{self.bb_std}"
        self.bb_mid_field = f"close_BBM_{self.bb_period}_{self.bb_std}"
        self.ema_fast_field = f"close_EMA_{self.ema_fast}"
        self.ema_slow_field = f"close_EMA_{self.ema_slow}"
        self.atr_field = f"ATRr_{self.atr_period}"
        self.adx_field = f"ADX_{self.adx_period}"
        self.rsi_field = f"close_RSI_{self.rsi_period}"

    def get_name(self) -> str:
        return "BollingerBreakout"

    def get_lookback_window(self) -> int:
        # 需要的最少历史条数：用于计算 trailing_bw_window、chandelier、ATR、EMA 等
        return (
            max(
                self.trailing_bw_window,
                self.adx_period,
                self.atr_period,
                self.ema_slow,
                self.prior_swing_bars,
            )
            + 5
        )
    
    # Supported scoring factors
    def support_scoring_factors(self) -> List[FactorName]:
        return  [
            FactorName.BREAKOUT_TRIGGER,
            FactorName.SQUEEZE_CONFIRM,
            FactorName.TREND_STRENGTH,
            FactorName.VOLUME_CONFIRM,
            FactorName.EMA_ALIGNMENT,
            FactorName.CONFLUENCE_BONUS
        ]

    # --------- Helper Functions ---------
    def _read_provider_bandwidth(self, bb_series: Any, idx: int) -> Tuple[
        Optional[float], List[float], Optional[float], Optional[float], Optional[float]
    ]:
        """
        统一读取 provider 提供的 bandwidth 字段及上/中/下带（若可用）。
        返回: (curr_bw, bw_list, u_curr, l_curr, m_curr)
        """
        curr_bw = None
        u_curr = l_curr = m_curr = None
        if not bb_series:
            return None, [], None, None, None
        # 尝试读取 upper/mid/lower（用于止损/显示）
        try:
            curr_bw = getattr(bb_series[-1], self.bb_bw_field, None)
            u_curr = getattr(bb_series[-1], self.bb_up_field, None)
            l_curr = getattr(bb_series[-1], self.bb_low_field, None)
            m_curr = getattr(bb_series[-1], self.bb_mid_field, None)
        except Exception:
            u_curr = l_curr = m_curr = None
        # 构建历史 bandwidth 列表：仅从 provider 的 bandwidth 字段收集
        bw_list: List[float] = []
        start = max(0, idx - self.trailing_bw_window + 1)
        for i in range(start, idx + 1):
            try:
                bbi = bb_series[i] if bb_series and i < len(bb_series) else None
                if bbi is None:
                    continue
                v = getattr(bbi, self.bb_bw_field, None)
                if v is not None:
                    bw_list.append(float(v))
            except Exception:
                continue
        return curr_bw, bw_list, u_curr, l_curr, m_curr

    # --- 主逻辑 ---
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        Input:
            symbol: 标的
            candles: 日线序列，按时间升序排列（old ... recent），每个元素需包含 high/low/open/close/volume/date
        Output:
            SignalModel with fields: signal in {'buy','sell','hold'}, confidence, reason, details
        """
        # 基本数据校验
        if not candles or len(candles) < self.get_lookback_window():
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=candles[-1].date if candles else None,
                reason="数据不足",
                confidence=0.0,
            )

        # 获取指标（依赖 provider）
        bb_series = self.provider.get_indicator(
            "bbands", candles, {"length": self.bb_period, "std": self.bb_std}
        )
        ema_fast_series = self.provider.get_indicator(
            "ema", candles, {"length": self.ema_fast}
        )
        ema_slow_series = self.provider.get_indicator(
            "ema", candles, {"length": self.ema_slow}
        )
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})

        # 提取 recent 值（以 provider 返回的属性命名为近似格式）
        closes = [float(c.close) for c in candles]
        highs = [float(c.high) for c in candles]
        lows = [float(c.low) for c in candles]
        vols = [float(c.volume) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]
        atr_val_history = [getattr(a, self.atr_field, None) for a in atr_series]
        current_atr_val = atr_val_history[-1]
        adx_val_history = [getattr(a, self.adx_field, None) for a in adx_series]
        current_adx_val = adx_val_history[-1]
        idx = len(candles) - 1
        close = closes[-1]
        curr_bw, bw_list, bbu, bbl, bbm = self._read_provider_bandwidth(bb_series, idx)
        if curr_bw is None or not bw_list:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=dates[-1],
                reason=f"缺少 BB bandwidth",
                confidence=0.0,
            )
        
        # Squeeze判断
        # 值越小表示相对于历史越窄（更“收缩”）
        # 用 ≤ threshold 表示“在历史最窄的 X% 范围内视为 squeeze”
        bw_pct = self._percentile_rank(bw_list, curr_bw)
        in_squeeze = bw_pct <= self.bw_percentile_threshold

        # 趋势过滤（EMA），使用封装的提取函数（兼容 provider 命名）
        ema_f = self._extract_latest_indicator_value(ema_fast_series, [self.ema_fast_field])
        ema_s = self._extract_latest_indicator_value(ema_slow_series, [self.ema_slow_field])
        trend_long = ema_f > ema_s
        trend_short = ema_f < ema_s

        # 判断趋势强度和市场波动
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
        # 成交量 z-score 确认
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok = self._check_volume_zscore(
            vols, recent_window, self.vol_zscore_threshold
        )

        # prior swing high/low over prior_swing_bars (exclude current)
        prior_range_high = (
            max(highs[max(0, idx - self.prior_swing_bars) : idx])
            if idx - self.prior_swing_bars >= 0
            else max(highs[:-1])
        )
        prior_range_low = (
            min(lows[max(0, idx - self.prior_swing_bars) : idx])
            if idx - self.prior_swing_bars >= 0
            else min(lows[:-1])
        )
        long_break = (close > bbu) and (close > prior_range_high)
        short_break = (close < bbl) and (close < prior_range_low)

        details: Dict[str, Any] = {
            "close": close,
            "bbu": bbu,
            "bbl": bbl,
            "bbm": bbm,
            "bw_pct": round(bw_pct, 2),
            "ema_fast": round(ema_f, 4),
            "ema_slow": round(ema_s, 4),
            "atr": round(current_atr_val, 6),
            "adx": round(current_adx_val, 6),
            "prior_high": prior_range_high,
            "prior_low": prior_range_low,
            "in_squeeze": in_squeeze,
        }

        # 评分 & 生成 signal
        result: ScoringResult = None
        factors = [
            Factor(FactorName.BREAKOUT_TRIGGER, "布林带突破", 0.30, long_break or short_break),
            Factor(FactorName.SQUEEZE_CONFIRM, "布林带Squeeze确认", 0.25, in_squeeze),
            Factor(FactorName.TREND_STRENGTH, "趋势强度和波动率确认", 0.20, trend_strength.signal),
            Factor(FactorName.VOLUME_CONFIRM, "成交量放大", 0.15, vol_ok),
            Factor(FactorName.EMA_ALIGNMENT, "趋势方向一致", 0.05, (long_break and trend_long) or (short_break and trend_short)),
            Factor(FactorName.CONFLUENCE_BONUS, "趋势方向强度波动率一致", 0.05, trend_strength.signal and ((long_break and trend_long) or (short_break and trend_short))),
        ]
        engine = ScoringEngine(
            base_threshold=0.7, 
            required_factors=self.support_scoring_factors(),
            determined_factors=[
                FactorName.BREAKOUT_TRIGGER
            ]
        )
        side = "long" if long_break else "short" if short_break else "hold"
        result = engine.compute_score(factors, side=side)

        # 计算入场止损与 trailing stop
        if result and result.signal != "hold":
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
            confidence=round(min(1.0, result.signal.score), 3),
            reason=" | ".join(result.reasons),
            details=details,
        )


def make_bbands_breakout_presets() -> Dict[str, Dict[str, Any]]:
    """
    预设：便于在不同持仓周期间快速切换（基于资深 algo trader 的经验调优）
    - swing: 短波段（1-2周），更灵敏的入场、更短的历史窗口、更低的成交量 z-score 阈值
    - intermediate: 中波段（2-6周），平衡的参数（回测默认）
    - position: 中长线（1-3月），更保守、更严格的趋势/成交量/波动性门槛
    """
    swing = {
        "bb_period": 20,                # Standard Bollinger Band period (20 bars)
        "bb_std": 2.0,                  # Classic BB width (2 standard deviations)
        "trailing_bw_window": 60,       # Longer window for squeeze detection (3× BB period)
        "bw_percentile_threshold": 20.0,# 20th percentile = strict squeeze condition
        "ema_fast": 8,                  # Fast EMA for short-term trend
        "ema_slow": 21,                 # Slow EMA for trend confirmation
        "atr_period": 14,               # ATR period for volatility context
        "adx_period": 14,               # ADX standard period for trend strength
        "rsi_period": 14,               # RSI standard period for momentum
        "prior_swing_bars": 3,          # Minimum bars to confirm swing pivot
        "min_atr_price_ratio": 0.002,   # Ensures volatility is meaningful (0.2%)
        "vol_zscore_window": 20,        # Match BB period for volume z-score
        "vol_zscore_threshold": 1.0,    # Slightly stricter volume breakout confirmation
        "score_threshold": 0.7          # Composite score threshold for signal validation
    }

    intermediate = {
        **swing,
    }

    position = {
        **swing,
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}
