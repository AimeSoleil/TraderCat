from typing import List, Optional, Dict, Any
import statistics

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

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
        adx_threshold: float = 25.0,
        atr_period: int = 14,
        entry_atr_mult: float = 1.5,
        trailing_atr_mult: float = 3.0,
        time_stop_bars: int = 63,
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
        self.adx_threshold = float(adx_threshold)
        self.atr_period = int(atr_period)
        self.entry_atr_mult = float(entry_atr_mult)
        self.trailing_atr_mult = float(trailing_atr_mult)
        self.time_stop_bars = int(time_stop_bars)
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

    # ---------- helpers ----------
    def _sma(self, vals: List[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    def _std(self, vals: List[float]) -> float:
        return statistics.pstdev(vals) if len(vals) > 0 else 0.0

    def _compute_return_L(self, closes: List[float], L: int) -> Optional[float]:
        if len(closes) <= L:
            return None
        past = closes[-L - 1]
        curr = closes[-1]
        if abs(past) < EPS:
            return None
        return curr / past - 1.0

    def _extract_latest_indicator_value(
        self, series: Optional[List[Any]], keys: List[str]
    ) -> Optional[float]:
        """
        兼容封装：从 provider 的指标序列中提取最后一条数值（兼容对象属性或 dict 字段或直接数值）。
        keys: 候选属性名列表（优先级顺序）
        """
        if not series:
            return None
        last = series[-1]
        if last is None:
            return None
        if isinstance(last, (int, float)):
            try:
                return float(last)
            except Exception:
                return None
        for k in keys:
            try:
                v = (
                    getattr(last, k, None)
                    if hasattr(last, k)
                    else (last.get(k) if isinstance(last, dict) else None)
                )
            except Exception:
                v = None
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    continue
        return None

    def _compute_ema_manual(self, series: List[float], period: int) -> Optional[float]:
        if not series or len(series) < period:
            return None
        # simple EMA calculation for last value
        k = 2.0 / (period + 1.0)
        ema = series[0]
        for v in series[1:]:
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
        price = closes[-1]

        # 1) momentum ret_L
        ret_L = self._compute_return_L(closes, self.L)

        # 2) EMA (daily) via provider or manual fallback
        # EMA via provider (使用封装提取，兼容不同命名)，fallback 到手动计算
        ema_fast_series = self.provider.get_indicator(
            "ema", candles, {"length": self.ema_fast}
        )
        ema_slow_series = self.provider.get_indicator(
            "ema", candles, {"length": self.ema_slow}
        )
        ema_fast_val = self._extract_latest_indicator_value(
            ema_fast_series, [self.ema_fast_field]
        )
        ema_slow_val = self._extract_latest_indicator_value(
            ema_slow_series, [self.ema_slow_field]
        )

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

        # 4) ADX
        adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})
        adx_val = self._extract_latest_indicator_value(adx_series, [self.adx_field])
        adx_ok = True if (adx_val is None or adx_val >= self.adx_threshold) else False

        # 5) ATR
        atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        atr_val = self._extract_latest_indicator_value(atr_series, [self.atr_field])
        vol_guard = (atr_val is not None) and (atr_val / max(abs(price), EPS) >= self.min_atr_price_ratio)

        # 6) Volume z-score
        # 成交量 z-score 确认（vol_ok）：用最近 vol_zscore_window 样本计算 z-score
        vol_ok = False
        volume_z = None
        recent_window = max(1, min(self.vol_zscore_window, len(vols)))
        recent_vols = [v for v in vols[-recent_window:] if v is not None]
        try:
            if recent_vols and len(recent_vols) >= 2 and vols[-1] is not None:
                mean_v = sum(recent_vols) / len(recent_vols)
                std_v = statistics.pstdev(recent_vols) if len(recent_vols) > 1 else 0.0
                if std_v > 0:
                    volume_z = (vols[-1] - mean_v) / std_v
                    vol_ok = volume_z >= self.vol_zscore_threshold
        except Exception:
            vol_ok = False

        details: Dict[str, Any] = {
            "price": price,
            "ret_L": round(ret_L, 6) if ret_L is not None else None,
            "ema_fast": round(ema_fast_val, 6) if ema_fast_val is not None else None,
            "ema_slow": round(ema_slow_val, 6) if ema_slow_val is not None else None,
            "ht_ema_fast": (
                round(ht_fast, 6) if ht_ema_ok and ht_fast is not None else None
            ),
            "ht_ema_slow": (
                round(ht_slow, 6) if ht_ema_ok and ht_slow is not None else None
            ),
            "adx": round(adx_val, 3) if adx_val is not None else None,
            "atr": round(atr_val, 6) if atr_val is not None else None,
            "vol_guard": vol_guard,
        }

        trend_day_up = (
            ema_fast_val is not None
            and ema_slow_val is not None
            and ema_fast_val > ema_slow_val
        )
        trend_day_down = (
            ema_fast_val is not None
            and ema_slow_val is not None
            and ema_fast_val < ema_slow_val
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
        score = 0.0
        reasons = []
        if long_cond:
            score += 0.30
            reasons.append("动量向上") # 是信号的核心触发条件
            if trend_day_up:
                score += 0.20
                reasons.append("日线EMA向上") # 当前周期趋势确认
            if ht_ema_ok and trend_ht_up:
                score += 0.15
                reasons.append("高周期EMA向上") # 多周期共振增强信号
            if adx_ok:
                score += 0.15
                reasons.append("趋势强度确认") # 趋势强度决定动量是否有效
            if vol_ok:
                score += 0.10
                reasons.append("成交量放大") # 放量动能更可信
            if vol_guard:
                score += 0.10
                reasons.append("波动率过滤通过") # 防止震荡区假信号
            # 共振加分
            if trend_day_up and trend_ht_up and adx_ok:
                score += 0.1
                reasons.append("多周期趋势+ADX共振加分")
        elif short_cond:
            score += 0.30
            reasons.append("动量向下")
            if trend_day_down:
                score += 0.20
                reasons.append("日线EMA向下")
            if ht_ema_ok and trend_ht_down:
                score += 0.15
                reasons.append("高周期EMA向下")
            if adx_ok:
                score += 0.15
                reasons.append("趋势强度确认")
            if vol_ok:
                score += 0.10
                reasons.append("成交量放大")
            if vol_guard:
                score += 0.10
                reasons.append("波动率过滤通过")
            # 共振加分
            if trend_day_down and trend_ht_down and adx_ok:
                score += 0.1
                reasons.append("多周期趋势+ADX共振加分")

        confidence = min(1.0, score)
        # decide signal based on which side has higher support (simple approach)
        if long_cond and confidence >= self.score_threshold:
            signal = "buy"
        elif short_cond and confidence >= self.score_threshold:
            signal = "sell"
        else:
            signal = "hold"
            reasons.append("No momentum trend")

        # 8) position sizing suggestion (risk per trade using ATR)
        entry_price = price
        stop_price = None
        if atr_val:
            # risk monetary per share = ATR * entry_atr_mult
            unit_risk = atr_val * self.entry_atr_mult
            if unit_risk > 0:
                # translate to stop price
                if signal == "buy":
                    stop_price = entry_price - unit_risk
                elif signal == "sell":
                    stop_price = entry_price + unit_risk

        # trailing suggestion (Chandelier style)
        trailing_stop = None
        if signal == "buy" and atr_val:
            trailing_stop = (
                max([max(highs[-self.atr_period :])]) - self.trailing_atr_mult * atr_val
            )
        elif signal == "sell" and atr_val:
            trailing_stop = (
                min([min(lows[-self.atr_period :])]) + self.trailing_atr_mult * atr_val
            )

        details.update(
            {
                "signal": signal,
                "confidence": round(confidence, 3),
                "score": round(score, 3),
                "entry_price": round(entry_price, 6),
                "suggested_stop": (
                    round(stop_price, 6) if stop_price is not None else None
                ),
                "trailing_stop": (
                    round(trailing_stop, 6) if trailing_stop is not None else None
                ),
                "time_stop_bars": self.time_stop_bars,
            }
        )

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=dates[-1],
            confidence=round(confidence, 3),
            reason=" | ".join(reasons) if reasons else "no signal conditions met",
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
        "L": 21,
        "ema_fast": 8,
        "ema_slow": 21,
        "ht_ema_fast": 8,
        "ht_ema_slow": 21,
        "adx_period": 14,
        "adx_threshold": 15.0,
        "atr_period": 14,
        "entry_atr_mult": 1.2,
        "trailing_atr_mult": 2.5,
        "time_stop_bars": 21,
        "min_atr_price_ratio": 0.0008,
        "vol_zscore_window": 10,
        "vol_zscore_threshold": 0.9,
        "score_threshold": 0.7,
    }

    intermediate = {
        "L": 63,
        "ema_fast": 13,
        "ema_slow": 34,
        "ht_ema_fast": 8,
        "ht_ema_slow": 21,
        "adx_period": 14,
        "adx_threshold": 20.0,
        "atr_period": 14,
        "entry_atr_mult": 1.5,
        "trailing_atr_mult": 3.0,
        "time_stop_bars": 63,
        "min_atr_price_ratio": 0.001,
        "vol_zscore_window": 20,
        "vol_zscore_threshold": 1.0,
        "score_threshold": 0.75,
    }

    position = {
        "L": 126,
        "ema_fast": 21,
        "ema_slow": 55,
        "ht_ema_fast": 13,
        "ht_ema_slow": 34,
        "adx_period": 14,
        "adx_threshold": 25.0,
        "atr_period": 21,
        "entry_atr_mult": 1.8,
        "trailing_atr_mult": 3.5,
        "time_stop_bars": 126,
        "min_atr_price_ratio": 0.0015,
        "vol_zscore_window": 40,
        "vol_zscore_threshold": 1.2,
        "score_threshold": 0.8,
    }

    return {"swing": swing, "intermediate": intermediate, "position": position}