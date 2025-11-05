from typing import List, Optional, Dict, Any, Tuple
import math
import statistics
from datetime import datetime

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
    - risk_per_trade: 每笔目标风险占账户比例 (e.g. 0.003 = 0.3%)
    - rebalance_cadence: 'daily' / 'weekly' 建议
    """

    def __init__(
        self,
        L: int = 63,  # momentum lookback (e.g. 63 trading days ~ quarter)
        ema_fast: int = 13,
        ema_slow: int = 34,
        ht_ema_fast: int = 8,   # higher timeframe EMA fast (aggregated weekly)
        ht_ema_slow: int = 21,  # higher timeframe EMA slow
        adx_period: int = 14,
        adx_threshold: float = 20.0,
        atr_period: int = 14,
        entry_atr_mult: float = 1.5,
        trailing_atr_mult: float = 3.0,
        time_stop_bars: int = 63,
        risk_per_trade: float = 0.003,
        min_atr_price_ratio: float = 0.001,
        allow_shorts: bool = False,
        rebalance_cadence: str = "daily",
        score_threshold: float = 0.6,
        data_provider: Any = None
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
        self.risk_per_trade = float(risk_per_trade)
        self.min_atr_price_ratio = float(min_atr_price_ratio)
        self.allow_shorts = bool(allow_shorts)
        self.rebalance_cadence = rebalance_cadence
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

    def get_name(self) -> str:
        return "MomentumTrend"

    def get_lookback_window(self) -> int:
        # 需要的最小历史窗口
        return max(self.L, self.ema_slow, self.ht_ema_slow * 5, self.atr_period, self.adx_period) + 10

    # ---------- helpers ----------
    def _sma(self, vals: List[float]) -> float:
        return sum(vals) / len(vals) if vals else 0.0

    def _std(self, vals: List[float]) -> float:
        return statistics.pstdev(vals) if len(vals) > 0 else 0.0

    def _compute_return_L(self, closes: List[float], L: int) -> Optional[float]:
        if len(closes) <= L:
            return None
        past = closes[-L-1]
        curr = closes[-1]
        if abs(past) < EPS:
            return None
        return curr / past - 1.0

    def _compute_ema_manual(self, series: List[float], period: int) -> Optional[float]:
        if not series or len(series) < period:
            return None
        # simple EMA calculation for last value
        k = 2.0 / (period + 1.0)
        ema = series[0]
        for v in series[1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _aggregate_higher_timeframe(self, candles: List[Any], days: int = 5) -> List[Dict[str, Any]]:
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
                highs = max(float(getattr(x, "high", getattr(x, "High", 0))) for x in buf)
                lows = min(float(getattr(x, "low", getattr(x, "Low", 0))) for x in buf)
                vols = sum(float(getattr(x, "volume", getattr(x, "Volume", 0))) for x in buf)
                agg.append({"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols, "date": getattr(buf[-1], "date", None)})
                buf = []
        return agg

    def _compute_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int) -> Optional[float]:
        if len(closes) < period + 1:
            return None
        trs = []
        for i in range(-period, 0):
            h = highs[i]; l = lows[i]; pc = closes[i-1]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return sum(trs) / len(trs) if trs else None

    # ---------- 主逻辑 ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        输入:
          - candles: 日线数组（old..new），每条需包含 high/low/open/close/volume/date
        输出:
          - SignalModel: signal ∈ {'buy','sell','hold'}, confidence, reason, details（包含 entry stop trailing sizing 建议）
        """
        if not candles or not self.provider or len(candles) < self.get_lookback_window():
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=candles[-1].date if candles else None, confidence=0.0, reason="数据不足", details={})

        closes = [float(getattr(c, "close", getattr(c, "Close", 0))) for c in candles]
        highs = [float(getattr(c, "high", getattr(c, "High", 0))) for c in candles]
        lows = [float(getattr(c, "low", getattr(c, "Low", 0))) for c in candles]
        volumes = [float(getattr(c, "volume", getattr(c, "Volume", 0))) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]
        idx = len(candles) - 1
        price = closes[-1]

        # 1) momentum ret_L
        ret_L = self._compute_return_L(closes, self.L)

        # 2) EMA (daily) via provider or manual fallback
        try:
            ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
            ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ema_slow})
            ema_fast_val = float(getattr(ema_fast_series[-1], f"EMA_{self.ema_fast}", None) or getattr(ema_fast_series[-1], "ema", None) or ema_fast_series[-1])
            ema_slow_val = float(getattr(ema_slow_series[-1], f"EMA_{self.ema_slow}", None) or getattr(ema_slow_series[-1], "ema", None) or ema_slow_series[-1])
        except Exception:
            ema_fast_val = self._compute_ema_manual(closes[-(self.ema_fast*5):], self.ema_fast)
            ema_slow_val = self._compute_ema_manual(closes[-(self.ema_slow*5):], self.ema_slow)

        # 3) higher timeframe EMA confirmation (try provider then fallback to aggregation)
        ht_ema_ok = False
        try:
            # provider may offer higher timeframe indicators
            ht_ema_fast_series = self.provider.get_indicator("ema", candles, {"length": self.ht_ema_fast, "timeframe": "W"})
            ht_ema_slow_series = self.provider.get_indicator("ema", candles, {"length": self.ht_ema_slow, "timeframe": "W"})
            ht_fast = float(getattr(ht_ema_fast_series[-1], f"EMA_{self.ht_ema_fast}", None) or getattr(ht_ema_fast_series[-1], "ema", None) or ht_ema_fast_series[-1])
            ht_slow = float(getattr(ht_ema_slow_series[-1], f"EMA_{self.ht_ema_slow}", None) or getattr(ht_ema_slow_series[-1], "ema", None) or ht_ema_slow_series[-1])
            ht_ema_ok = True if (ht_fast is not None and ht_slow is not None) else False
        except Exception:
            # fallback: aggregate 5-day bars to approximate weekly
            agg = self._aggregate_higher_timeframe(candles, days=5)
            agg_closes = [x["close"] for x in agg]
            ht_fast = self._compute_ema_manual(agg_closes[-(self.ht_ema_fast*3):], self.ht_ema_fast) if len(agg_closes) >= self.ht_ema_fast else None
            ht_slow = self._compute_ema_manual(agg_closes[-(self.ht_ema_slow*3):], self.ht_ema_slow) if len(agg_closes) >= self.ht_ema_slow else None
            ht_ema_ok = True if (ht_fast is not None and ht_slow is not None) else False

        # 4) ADX
        try:
            adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})
            adx_val = float(getattr(adx_series[-1], f"ADX_{self.adx_period}", None) or getattr(adx_series[-1], "ADX", None) or adx_series[-1])
        except Exception:
            adx_val = None

        # 5) ATR
        try:
            atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
            atr_val = float(getattr(atr_series[-1], f"ATR_{self.atr_period}", None) or getattr(atr_series[-1], "atr", None) or atr_series[-1])
        except Exception:
            atr_val = self._compute_atr(highs, lows, closes, self.atr_period)

        vol_guard = (atr_val is not None) and (atr_val / max(abs(price), EPS) >= self.min_atr_price_ratio)

        # 6) signals & scoring
        score = 0.0
        reasons: List[str] = []
        details: Dict[str, Any] = {
            "price": price,
            "ret_L": round(ret_L, 6) if ret_L is not None else None,
            "ema_fast": round(ema_fast_val, 6) if ema_fast_val is not None else None,
            "ema_slow": round(ema_slow_val, 6) if ema_slow_val is not None else None,
            "ht_ema_fast": round(ht_fast, 6) if ht_ema_ok and ht_fast is not None else None,
            "ht_ema_slow": round(ht_slow, 6) if ht_ema_ok and ht_slow is not None else None,
            "adx": round(adx_val, 3) if adx_val is not None else None,
            "atr": round(atr_val, 6) if atr_val is not None else None,
            "vol_guard": vol_guard,
            "allow_shorts": self.allow_shorts,
            "rebalance": self.rebalance_cadence
        }

        trend_day_up = ema_fast_val is not None and ema_slow_val is not None and ema_fast_val > ema_slow_val
        trend_day_down = ema_fast_val is not None and ema_slow_val is not None and ema_fast_val < ema_slow_val
        trend_ht_up = ht_ema_ok and ht_fast is not None and ht_slow is not None and ht_fast > ht_slow
        trend_ht_down = ht_ema_ok and ht_fast is not None and ht_slow is not None and ht_fast < ht_slow

        # momentum rule: long if ret_L > 0 and same direction EMAs; short if ret_L < 0 and allow_shorts and EMA alignment
        long_cond = (ret_L is not None and ret_L > 0) and trend_day_up and (not ht_ema_ok or trend_ht_up)
        short_cond = (ret_L is not None and ret_L < 0) and self.allow_shorts and trend_day_down and (not ht_ema_ok or trend_ht_down)

        # ADX filter
        adx_ok = True if (adx_val is None or adx_val >= self.adx_threshold) else False

        if long_cond:
            score += 0.5  # 基础动量权重
            reasons.append("momentum positive")
        if trend_day_up:
            score += 0.2
            reasons.append("daily EMA up")
        if ht_ema_ok and trend_ht_up:
            score += 0.15
            reasons.append("higher-timeframe EMA up")
        if vol_guard:
            score += 0.05
            reasons.append("volatility guard OK")
        if adx_ok:
            score += 0.05
            reasons.append("adx OK")

        if short_cond:
            score += 0.5
            reasons.append("momentum negative")
        if trend_day_down:
            score += 0.2
            reasons.append("daily EMA down")
        if ht_ema_ok and trend_ht_down:
            score += 0.15
            reasons.append("higher-timeframe EMA down")
        # ADX and vol guard apply similarly for shorts
        if score <= 0.0:
            signal = "hold"
            confidence = 0.0
        else:
            confidence = min(1.0, score)
            # decide signal based on which side has higher support (simple approach)
            if long_cond and confidence >= self.score_threshold and adx_ok and vol_guard:
                signal = "buy"
            elif short_cond and confidence >= self.score_threshold and adx_ok and vol_guard:
                signal = "sell"
            else:
                signal = "hold"

        # 7) position sizing suggestion (risk per trade using ATR)
        pos_size = None
        entry_price = price
        stop_price = None
        if atr_val and self.risk_per_trade and self.risk_per_trade > 0:
            # risk monetary per share = ATR * entry_atr_mult
            unit_risk = atr_val * self.entry_atr_mult
            if unit_risk > 0:
                # assume account value unknown -> provide fraction-of-price sizing guidance
                # shares = (risk_percent * capital) / (unit_risk) ; without capital, provide suggested risk-dist ratio
                # here we compute suggested position dollars per unit price to risk ratio:
                pos_size = (self.risk_per_trade * 1.0) / (unit_risk / max(abs(price), EPS))  # dimensionless multiplier of capital
                # translate to stop price
                if signal == "buy":
                    stop_price = entry_price - unit_risk
                elif signal == "sell":
                    stop_price = entry_price + unit_risk

        # trailing suggestion (Chandelier style)
        trailing_stop = None
        if signal == "buy" and atr_val:
            trailing_stop = max([max(highs[-self.atr_period:])]) - self.trailing_atr_mult * atr_val
        elif signal == "sell" and atr_val:
            trailing_stop = min([min(lows[-self.atr_period:])]) + self.trailing_atr_mult * atr_val

        details.update({
            "signal": signal,
            "confidence": round(confidence, 3),
            "score": round(score, 3),
            "entry_price": round(entry_price, 6),
            "suggested_stop": round(stop_price, 6) if stop_price is not None else None,
            "trailing_stop": round(trailing_stop, 6) if trailing_stop is not None else None,
            "position_size_mult_of_capital": round(pos_size, 6) if pos_size is not None else None,
            "time_stop_bars": self.time_stop_bars,
            "notes": "position_size_mult_of_capital 表示建议仓位为该值 * 可用资金 (仅参考, 需结合资本和手续费计算)"
        })

        reason = " | ".join(reasons) if reasons else "no signal conditions met"

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=dates[-1],
            confidence=round(confidence if isinstance(confidence, float) else 0.0, 3),
            reason=reason,
            details=details
        )


def make_momentum_trend_presets() -> Dict[str, Dict[str, Any]]:
    """
    presets:
      - swing: 更短期、更灵敏（1-2周持仓）
      - intermediate: 中等（2-6周）
      - position: 长期趋势（数月）
    """
    swing = {
        "L": 21,
        "ema_fast": 8,
        "ema_slow": 21,
        "ht_ema_fast": 5,
        "ht_ema_slow": 13,
        "adx_period": 14,
        "adx_threshold": 18,
        "atr_period": 10,
        "entry_atr_mult": 1.2,
        "trailing_atr_mult": 3.0,
        "time_stop_bars": 14,
        "risk_per_trade": 0.002,
        "min_atr_price_ratio": 0.0008,
        "allow_shorts": False,
        "rebalance_cadence": "daily",
        "score_threshold": 0.55
    }
    intermediate = {
        "L": 63,
        "ema_fast": 13,
        "ema_slow": 34,
        "ht_ema_fast": 8,
        "ht_ema_slow": 21,
        "adx_period": 14,
        "adx_threshold": 20,
        "atr_period": 14,
        "entry_atr_mult": 1.5,
        "trailing_atr_mult": 3.0,
        "time_stop_bars": 63,
        "risk_per_trade": 0.003,
        "min_atr_price_ratio": 0.0012,
        "allow_shorts": False,
        "rebalance_cadence": "weekly",
        "score_threshold": 0.6
    }
    position = {
        "L": 126,
        "ema_fast": 21,
        "ema_slow": 55,
        "ht_ema_fast": 13,
        "ht_ema_slow": 34,
        "adx_period": 21,
        "adx_threshold": 22,
        "atr_period": 21,
        "entry_atr_mult": 2.0,
        "trailing_atr_mult": 3.5,
        "time_stop_bars": 126,
        "risk_per_trade": 0.004,
        "min_atr_price_ratio": 0.0015,
        "allow_shorts": True,
        "rebalance_cadence": "weekly",
        "score_threshold": 0.65
    }
    return {"swing": swing, "intermediate": intermediate, "position": position}
