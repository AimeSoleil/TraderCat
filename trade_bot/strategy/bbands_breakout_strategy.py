from typing import List, Optional, Dict, Any, Tuple

from trade_bot.strategy.exit_planner import ExitPlanner
from trade_bot.strategy.signal_scorer import Factor, FactorName, ScoringEngine, ScoringResult
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

class BollingerBreakoutStrategy(TradingStrategy):

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        trailing_bw_window: int = 60,
        bw_percentile_threshold: float = 20.0,
        ema_fast: int = 8,
        ema_slow: int = 21,
        atr_period: int = 14,
        adx_period: int = 14,
        rsi_period: Optional[int] = 14,
        prior_swing_bars: int = 5,
        vol_zscore_window: int = 20,
        vol_zscore_threshold: float = 2.0,
        score_threshold: float = 0.6,
        # --- [Optimization] New Params ---
        min_atr_percent: float = 0.5,       # Dead Stock Filter: ATR must be > 0.5% of price
        breakout_margin_atr: float = 0.2,   # Breakout Margin: Close > BBU + 0.2 * ATR
        # ---------------------------------
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
        self.vol_zscore_window = int(vol_zscore_window)
        self.vol_zscore_threshold = float(vol_zscore_threshold)
        self.score_threshold = score_threshold
        
        # [Optimization] Store new params
        self.min_atr_percent = min_atr_percent
        self.breakout_margin_atr = breakout_margin_atr
        
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
        curr_bw = None
        u_curr = l_curr = m_curr = None
        if not bb_series:
            return None, [], None, None, None
        try:
            curr_bw = getattr(bb_series[-1], self.bb_bw_field, None)
            u_curr = getattr(bb_series[-1], self.bb_up_field, None)
            l_curr = getattr(bb_series[-1], self.bb_low_field, None)
            m_curr = getattr(bb_series[-1], self.bb_mid_field, None)
        except Exception:
            u_curr = l_curr = m_curr = None
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

        # --- [Optimization 1] Dead Stock Filter (最小波动率检查) ---
        # 如果 ATR 占比过小，说明该资产波动率不足以覆盖交易成本
        atr_pct = (current_atr_val / close) * 100.0
        if atr_pct < self.min_atr_percent:
            return SignalModel(
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                date=dates[-1],
                reason=f"波动率过低 (ATR%={atr_pct:.2f} < {self.min_atr_percent}%)",
                confidence=0.0,
            )
        # -------------------------------------------------------
        
        # Squeeze判断
        bw_pct = self._percentile_rank(bw_list, curr_bw)
        in_squeeze = bw_pct <= self.bw_percentile_threshold

        # 趋势过滤
        ema_f = self._extract_latest_indicator_value(ema_fast_series, [self.ema_fast_field])
        ema_s = self._extract_latest_indicator_value(ema_slow_series, [self.ema_slow_field])
        trend_long = ema_f > ema_s
        trend_short = ema_f < ema_s

        trend_strength = self._check_trend_and_volatility(
            atr_val_history=atr_val_history,
            adx_val_history=adx_val_history,
            price_history=closes,
            window=100,
            mode='trend',
            trend_quantiles=[0.6, 0.4]
        )
        
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok = self._check_volume_zscore(
            vols, recent_window, self.vol_zscore_threshold
        )

        # --- [Optimization 2] Breakout Margin (假突破过滤) ---
        # 要求收盘价必须显著突破上轨/下轨，而不仅仅是 > bbu
        margin = current_atr_val * self.breakout_margin_atr
        
        long_break = (close >= bbu + margin) 
        short_break = (close <= bbl - margin)
        # ---------------------------------------------------

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
            "in_squeeze": in_squeeze,
            "atr_pct": round(atr_pct, 2)
        }

        # 评分 & 生成 signal
        result: ScoringResult = None
        factors = [
            Factor(FactorName.BREAKOUT_TRIGGER, f"布林带{'long' if long_break else 'short'}显著突破", 0.30, long_break or short_break),
            Factor(FactorName.SQUEEZE_CONFIRM, "布林带Squeeze确认", 0.25, in_squeeze),
            Factor(FactorName.TREND_STRENGTH, "趋势强度和波动率确认", 0.20, trend_strength.signal),
            Factor(FactorName.VOLUME_CONFIRM, "成交量放大", 0.15, vol_ok),
            Factor(FactorName.EMA_ALIGNMENT, "趋势方向一致", 0.05, (long_break and trend_long) or (short_break and trend_short)),
            Factor(FactorName.CONFLUENCE_BONUS, "趋势方向强度波动率一致", 0.05, trend_strength.signal and ((long_break and trend_long) or (short_break and trend_short))),
        ]
        engine = ScoringEngine(
            base_threshold=self.score_threshold, 
            required_factors=self.support_scoring_factors(),
            determined_factors=[
                FactorName.BREAKOUT_TRIGGER
            ],
            is_volatility_ok=trend_strength.volatility['signal']
        )
        side = "long" if long_break else "short" if short_break else "neutral"
        result = engine.compute_score(factors, side=side)

        # 计算入场止损与 trailing stop
        if result and result.signal != "hold":
            planner = ExitPlanner(
                highs=highs,
                lows=lows,
                atr=current_atr_val,
                close_price=close
            )
            plan = planner.make_exit_plan(trading_signal=result.signal)
            
            # --- [Optimization 3] Mean Reversion Stop (中轨止损) ---
            # 建议使用布林带中轨作为移动止损参考
            if bbm:
                plan['trailing_stop_ref'] = bbm
                plan['stop_loss_type'] = 'mean_reversion_band'
            # -----------------------------------------------------
            
            details.update({"plan": plan})

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=result.signal,
            date=dates[-1],
            confidence=round(min(1.0, result.score), 3),
            reason=" | ".join(result.reasons),
            details=details,
        )

def make_bbands_breakout_presets() -> Dict[str, Dict[str, Any]]:
    """
    Bollinger Band breakout strategy presets based on algo trading best practices:
    - swing: Short-term (1–2 weeks), aggressive entry, tighter thresholds.
    - intermediate: Medium-term (2–6 weeks), balanced parameters.
    - position: Long-term (1–3 months), conservative, stricter filters.
    """

    # ---------------- SWING TRADING ----------------
    swing = {
        "bb_period": 20,
        "bb_std": 2.0,
        "trailing_bw_window": 60,
        "bw_percentile_threshold": 30.0,
        "ema_fast": 8,
        "ema_slow": 21,
        "atr_period": 14,
        "adx_period": 14,
        "rsi_period": 14,
        "prior_swing_bars": 5,
        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.5,
        "score_threshold": 0.6,
        # [New]
        "min_atr_percent": 0.5,      # Allow slightly lower vol for swings
        "breakout_margin_atr": 0.1   # Faster entry
    }

    # ---------------- INTERMEDIATE TERM ----------------
    intermediate = {
        "bb_period": 20,
        "bb_std": 2.0,
        "trailing_bw_window": 80,
        "bw_percentile_threshold": 25.0,
        "ema_fast": 13,
        "ema_slow": 34,
        "atr_period": 14,
        "adx_period": 14,
        "rsi_period": 14,
        "prior_swing_bars": 5,
        "vol_zscore_window": 30,
        "vol_zscore_threshold": 2.5,
        "score_threshold": 0.7,
        # [New]
        "min_atr_percent": 0.8,      # Standard filter
        "breakout_margin_atr": 0.2   # Standard confirmation
    }

    # ---------------- POSITION TRADING ----------------
    position = {
        "bb_period": 20,
        "bb_std": 2.0,
        "trailing_bw_window": 100,
        "bw_percentile_threshold": 30.0,
        "ema_fast": 21,
        "ema_slow": 55,
        "atr_period": 14,
        "adx_period": 14,
        "rsi_period": 14,
        "prior_swing_bars": 7,
        "vol_zscore_window": 40,
        "vol_zscore_threshold": 3.0,
        "score_threshold": 0.8,
        # [New]
        "min_atr_percent": 1.0,      # 高波动率过滤
        "breakout_margin_atr": 0.3   # 更严格的突破确认
    }

    return {
        "swing": swing,
        "intermediate": intermediate,
        "position": position
    }