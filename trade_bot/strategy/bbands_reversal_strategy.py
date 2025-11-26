import logging
from typing import List, Optional, Dict, Any, Tuple
import statistics

from trade_bot.strategy.candle_pattern import CandlePatterns
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
        min_atr_price_ratio: float = 0.002,
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
        self.min_atr_price_ratio = float(min_atr_price_ratio)
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
            FactorName.MOMENTUM_CONFIRM,
            FactorName.CONFLUENCE_BONUS
        ]

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
            close=close,
            window=100,
            atr_base_threshold=self.min_atr_price_ratio,
            atr_quantile=0.8,
            adx_quantile=0.8,
            mode='reversal'
        )

        # 成交量 z-score 确认（vol_ok
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        vol_ok, volume_z = self._check_volume_zscore(vols, recent_window, self.vol_zscore_threshold)

        # 检查是否接近上轨/下轨（相对容差
        near_upper = (u_curr is not None) and (
            close > u_curr or abs(close - u_curr) / (u_curr if abs(u_curr) > EPS else 1.0) <= self.touch_pct
        )
        near_lower = (l_curr is not None) and (
            close < l_curr or abs(close - l_curr) / (l_curr if abs(l_curr) > EPS else 1.0) <= self.touch_pct
        )

        # 检测拒绝蜡烛（以最近 self.max_time_bars 根内的任意一根作为确认）
        rejection_found = False
        rejection_type, pattern_type, reject_idx = None, None, None
        start = max(0, idx - self.max_time_bars + 1)
        for i in range(start, idx + 1):
            if near_lower:
                rejection_found, rejection_type, pattern_type = CandlePatterns.detect_bullish_pattern(opens, highs, lows, closes, i)
                reject_idx = i
                break
            # 看空候选（接近上轨）
            if near_upper:
                rejection_found, rejection_type, pattern_type = CandlePatterns.detect_bearish_pattern(opens, highs, lows, closes, i)
                reject_idx = i
                break

        # 动量确认（若启用）
        momentum_ok = False
        if near_upper or near_upper:
            self._MOMENTUM_CONFIRM(rsi_val_history=rsi_val_history, macd_hist_val_history=macd_hist_val_history, prefer=pattern_type)

        details: Dict[str, Any] = {
            "close": close,
            "upper": u_curr,
            "lower": l_curr,
            "mid": m_curr,
            "atr": round(current_atr_val, 6),
            "adx": round(current_adx_val, 3),
            "vol_zscore": round(volume_z, 3) if volume_z is not None else None,
            "trend_volatility_ok": trend_strength.signal,
            "trend_info": trend_strength.trend,
            "volatility_info": trend_strength.volatility,
            "near_upper": near_upper,
            "near_lower": near_lower,
            "rejection_found": rejection_found,
            "rejection_type": rejection_type,
            "reject_idx": reject_idx,
        }

        # 只有在带位接近并出现拒绝蜡烛的情况下考虑反转
        candidate_buy = near_lower and rejection_found
        candidate_sell = near_upper and rejection_found
        middle_line_reversal = (candidate_buy and prev_close > m_curr and close < m_curr) or (candidate_sell and prev_close < m_curr and close > m_curr)

        # 评分 & 生成 signal
        result: ScoringResult = None
        factors = [
            Factor(FactorName.BB_REVERSAL_CANDLE, f"检测到布林带带拒绝蜡烛({rejection_type})", 0.35, candidate_buy or candidate_sell),
            Factor(FactorName.TREND_STRENGTH, "趋势强度和波动率确认", 0.25, trend_strength.signal),
            Factor(FactorName.VOLUME_CONFIRM, "成交量放大确认", 0.2, vol_ok),
            Factor(FactorName.MOMENTUM_CONFIRM, "动量确认方向确认", 0.1, momentum_ok),
            Factor(FactorName.CONFLUENCE_BONUS, "中轨穿越反转", 0.1, middle_line_reversal)
        ]

        # Compute score using ScoringEngine
        engine = ScoringEngine(
            base_threshold=0.7, 
            required_factors=self.support_scoring_factors(),
            determined_factors=[
                FactorName.BB_REVERSAL_CANDLE
            ]
        )
        side = "long" if candidate_buy else "short" if candidate_sell else "hold"
        result = engine.compute_score(factors, side=side)

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
    依据实战与最佳实践的预设（swing/intermediate/position）
    """
    swing = {
        "bb_period": 20,                # Standard BB period for swing trading
        "bb_std": 2.0,                  # Classic BB width (2 standard deviations)
        "touch_pct": 0.05,              # Price must be within 5% of band to count as a touch
        "rsi_period": 14,               # RSI standard period for reversal confirmation
        "atr_period": 14,               # ATR for volatility context
        "adx_period": 14,               # ADX standard period for trend strength
        "max_time_bars": 3,             # Signal must trigger within 3 bars after band touch
        "min_atr_price_ratio": 0.002,   # Ensures volatility is meaningful (0.2%)
        "vol_zscore_window": 20,        # Match BB period for volume breakout detection
        "vol_zscore_threshold": 1.0,    # Slightly stricter volume confirmation
        "macd_params": {"fast": 12, "slow": 26, "signal": 9}, # Standard MACD settings
        "score_threshold": 0.7          # Slightly higher threshold for reversal confidence
    }

    intermediate = {
        **swing,
    }

    position = {
        **swing,
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}
