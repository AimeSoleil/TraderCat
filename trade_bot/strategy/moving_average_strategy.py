from typing import List, Optional, Dict, Any, Tuple
import statistics
import math

from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

class MovingAverageTrendStrategy(TradingStrategy):
    """
    Moving Average Trend Strategy - 观察长期趋势（生产就绪设计，日线为主，多周期/多周期确认）

    核心思路
    - 以多条移动平均线（短/中/长）判断趋势方向与强度，结合高阶时间框架（周线/月线）确认长期趋势。
    - 可选 EMA 或 SMA；支持 ADX 趋势强度过滤、ATR 波动性/止损参考、以及基于 ATR 的仓位建议（风险%）。
    - 输出 informative SignalModel，包含入场方向建议、置信度、止损/跟踪止损与仓位建议（仅参考）。

    使用场景与建议（简洁）
    - 目的：长期趋势观察与中长期持仓决策（周到月级持仓），也可用于趋势过滤供短线策略使用。
    - 适用：流动性良好、遵循趋势的品种；不适用重大新闻/极端高频波动时期。
    - 多时间框架：主图为日线；若可用，优先使用 provider 的周线/月线指标进行确认。
    - 风控：使用 ATR 估算初始止损（x * ATR），并用 trailing（Chandelier）管理头寸；推荐风险每笔占账户 0.25-1%。
    """

    def __init__(
        self,
        ma_periods: Optional[List[int]] = None,          # e.g. [50, 100, 200]
        ma_type: str = "ema",                            # "ema" or "sma"
        ht_timeframe: Optional[str] = "W",               # higher timeframe for confirmation ("W" or "M" or None)
        adx_period: int = 14,
        adx_threshold: float = 20.0,
        atr_period: int = 21,
        trailing_atr_mult: float = 3.0,
        entry_atr_mult: float = 1.5,
        min_atr_price_ratio: float = 0.0012,
        risk_per_trade: float = 0.003,                   # fraction of equity
        allow_shorts: bool = False,
        rebalance_cadence: str = "weekly",               # 'daily' or 'weekly'
        score_threshold: float = 0.6,
        data_provider: Any = None
    ):
        self.ma_periods = ma_periods or [50, 100, 200]
        self.ma_type = ma_type.lower()
        self.ht_timeframe = ht_timeframe
        self.adx_period = int(adx_period)
        self.adx_threshold = float(adx_threshold)
        self.atr_period = int(atr_period)
        self.trailing_atr_mult = float(trailing_atr_mult)
        self.entry_atr_mult = float(entry_atr_mult)
        self.min_atr_price_ratio = float(min_atr_price_ratio)
        self.risk_per_trade = float(risk_per_trade)
        self.allow_shorts = bool(allow_shorts)
        self.rebalance_cadence = rebalance_cadence
        self.score_threshold = float(score_threshold)
        self.provider = data_provider

    def get_name(self) -> str:
        return "MovingAverageTrend"

    def get_lookback_window(self) -> int:
        return max(max(self.ma_periods), self.atr_period, self.adx_period) + 10

    # ---------- helpers ----------
    def _sma(self, series: List[float], period: int) -> Optional[float]:
        if len(series) < period:
            return None
        return sum(series[-period:]) / period

    def _ema_manual(self, series: List[float], period: int) -> Optional[float]:
        if len(series) < period:
            return None
        k = 2.0 / (period + 1.0)
        # seed with SMA
        seed = sum(series[-period:]) / period
        ema = seed
        for v in series[-period+1:]:
            ema = v * k + ema * (1 - k)
        return ema

    def _compute_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int) -> Optional[float]:
        if len(closes) < period + 1:
            return None
        trs = []
        for i in range(-period, 0):
            h = highs[i]; l = lows[i]; pc = closes[i-1]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return sum(trs) / len(trs) if trs else None

    # ---------- main ----------
    def generate_signal(self, symbol: str, candles: List[Any]) -> SignalModel:
        """
        输入:
          - candles: 日线序列（old..new），每条需含 high/low/open/close/volume/date
        输出:
          - SignalModel(signal ∈ {'buy','sell','hold'}, confidence, reason, details)
        """
        if not candles or not self.provider or len(candles) < self.get_lookback_window():
            return SignalModel(symbol=symbol, strategy=self.get_name(), signal="hold", date=candles[-1].date if candles else None, reason="数据不足", confidence=0.0)

        closes = [float(getattr(c, "close", getattr(c, "Close", 0))) for c in candles]
        highs = [float(getattr(c, "high", getattr(c, "High", 0))) for c in candles]
        lows = [float(getattr(c, "low", getattr(c, "Low", 0))) for c in candles]
        volumes = [float(getattr(c, "volume", getattr(c, "Volume", 0))) for c in candles]
        dates = [getattr(c, "date", None) for c in candles]
        price = closes[-1]

        # 获取/计算 MAs（最新值）
        ma_vals: Dict[int, Optional[float]] = {}
        for p in self.ma_periods:
            val = None
            try:
                series = self.provider.get_indicator(self.ma_type, candles, {"length": p})
                # provider 返回常见字段尝试提取
                last = series[-1]
                if isinstance(last, (int,float)):
                    val = float(last)
                else:
                    val = getattr(last, f"{self.ma_type.upper()}_{p}", None) or getattr(last, "ma", None) or getattr(last, "value", None)
                    if val is not None:
                        val = float(val)
            except Exception:
                val = None
            if val is None:
                val = self._ema_manual(closes, p) if self.ma_type == "ema" else self._sma(closes, p)
            ma_vals[p] = val

        # 计算各均线斜率（最近 period 内的相对斜率）
        slopes: Dict[int, Optional[float]] = {}
        for p in self.ma_periods:
            if len(closes) >= p + 1:
                recent_ma = self._ema_manual(closes[:-1], p) if self.ma_type == "ema" else self._sma(closes[:-1], p)
                curr_ma = ma_vals[p]
                if curr_ma is not None and recent_ma is not None and abs(recent_ma) > EPS:
                    slopes[p] = (curr_ma - recent_ma) / recent_ma
                else:
                    slopes[p] = None
            else:
                slopes[p] = None

        # higher timeframe confirmation (weekly/month) - 优先使用 provider，如不可用，快速聚合5日为周线近似
        ht_ma_vals = {}
        ht_ok = False
        if self.ht_timeframe:
            try:
                for p in self.ma_periods:
                    series = self.provider.get_indicator(self.ma_type, candles, {"length": p, "timeframe": self.ht_timeframe})
                    last = series[-1]
                    val = None
                    if isinstance(last, (int,float)):
                        val = float(last)
                    else:
                        val = getattr(last, f"{self.ma_type.upper()}_{p}", None) or getattr(last, "ma", None) or getattr(last, "value", None)
                    ht_ma_vals[p] = float(val) if val is not None else None
                ht_ok = True
            except Exception:
                # fallback: aggregate 5-day buckets to approximate weekly
                try:
                    buckets = []
                    buf = []
                    for i,c in enumerate(candles):
                        buf.append(c)
                        if (i+1) % 5 == 0 or i == len(candles)-1:
                            buckets.append(buf)
                            buf = []
                    closes_week = [float(getattr(b[-1],"close",0)) for b in buckets]
                    for p in self.ma_periods:
                        ht_ma_vals[p] = self._ema_manual(closes_week, max(1, int(p/5))) if self.ma_type == "ema" else self._sma(closes_week, max(1,int(p/5)))
                    ht_ok = True
                except Exception:
                    ht_ok = False

        # ADX & ATR
        adx_val = None
        try:
            adx_series = self.provider.get_indicator("adx", candles, {"length": self.adx_period})
            last = adx_series[-1]
            adx_val = float(getattr(last, f"ADX_{self.adx_period}", None) or getattr(last, "ADX", None) or last)
        except Exception:
            adx_val = None

        try:
            atr_series = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
            last = atr_series[-1]
            atr_val = float(getattr(last, f"ATR_{self.atr_period}", None) or getattr(last, "atr", None) or last)
        except Exception:
            atr_val = self._compute_atr(highs, lows, closes, self.atr_period)

        vol_guard = (atr_val is not None) and (atr_val / max(abs(price), EPS) >= self.min_atr_price_ratio)

        # 趋势判定与评分
        # 定义：若短期 MA > 中期 MA > 长期 MA 且斜率均为正，则多头；反之为空头
        sorted_periods = sorted(self.ma_periods)
        ma_order_vals = [ma_vals[p] for p in sorted_periods]
        ma_slopes = [slopes[p] for p in sorted_periods]

        long_trend = all(v is not None for v in ma_order_vals) and all(ma_order_vals[i] > ma_order_vals[i+1] for i in range(len(ma_order_vals)-1))
        short_trend = all(v is not None for v in ma_order_vals) and all(ma_order_vals[i] < ma_order_vals[i+1] for i in range(len(ma_order_vals)-1))
        slope_consistent_long = all(s is not None and s > 0 for s in ma_slopes)
        slope_consistent_short = all(s is not None and s < 0 for s in ma_slopes)

        ht_confirms_long = False
        ht_confirms_short = False
        if ht_ok:
            ht_vals = [ht_ma_vals.get(p) for p in sorted_periods]
            if all(v is not None for v in ht_vals):
                ht_confirms_long = all(ht_vals[i] > ht_vals[i+1] for i in range(len(ht_vals)-1))
                ht_confirms_short = all(ht_vals[i] < ht_vals[i+1] for i in range(len(ht_vals)-1))

        # ADX filter
        adx_ok = True if (adx_val is None or adx_val >= self.adx_threshold) else False

        # score aggregation
        score = 0.0
        reasons: List[str] = []
        if long_trend:
            score += 0.4
            reasons.append("MA alignment long")
        if slope_consistent_long:
            score += 0.2
            reasons.append("MA slopes positive")
        if ht_ok and ht_confirms_long:
            score += 0.2
            reasons.append("HTF confirms long")
        if vol_guard:
            score += 0.1
            reasons.append("volatility guard OK")
        if adx_ok:
            score += 0.1
            reasons.append("adx OK")

        if short_trend:
            score += 0.4
            reasons.append("MA alignment short")
        if slope_consistent_short:
            score += 0.2
            reasons.append("MA slopes negative")
        if ht_ok and ht_confirms_short:
            score += 0.2
            reasons.append("HTF confirms short")

        confidence = min(1.0, score)

        # signal decision
        signal = "hold"
        if long_trend and slope_consistent_long and confidence >= self.score_threshold and adx_ok and vol_guard:
            signal = "buy"
        elif short_trend and slope_consistent_short and self.allow_shorts and confidence >= self.score_threshold and adx_ok and vol_guard:
            signal = "sell"
        else:
            signal = "hold"

        # position sizing suggestion (基于 ATR 风险)
        pos_size_mult = None
        suggested_stop = None
        if atr_val and atr_val > EPS and self.risk_per_trade > 0:
            unit_risk = atr_val * self.entry_atr_mult
            if unit_risk > 0:
                # 返回按资本比例的建议倍数（需与账户资金结合计算）
                pos_size_mult = (self.risk_per_trade) / (unit_risk / max(abs(price), EPS))
                if signal == "buy":
                    suggested_stop = price - unit_risk
                elif signal == "sell":
                    suggested_stop = price + unit_risk

        # trailing suggestion (Chandelier using longest MA period high/low and ATR)
        trailing_stop = None
        if signal == "buy" and atr_val:
            look_len = max(self.ma_periods)
            highest = max(highs[-look_len:]) if len(highs) >= look_len else max(highs)
            trailing_stop = highest - self.trailing_atr_mult * atr_val
        elif signal == "sell" and atr_val:
            look_len = max(self.ma_periods)
            lowest = min(lows[-look_len:]) if len(lows) >= look_len else min(lows)
            trailing_stop = lowest + self.trailing_atr_mult * atr_val

        details = {
            "price": price,
            "ma_vals": {p: (round(ma_vals[p],6) if ma_vals[p] is not None else None) for p in ma_vals},
            "ma_slopes": {p: (round(slopes[p],6) if slopes[p] is not None else None) for p in slopes},
            "ht_ma_vals": {p: (round(ht_ma_vals.get(p),6) if ht_ma_vals.get(p) is not None else None) for p in ht_ma_vals},
            "adx": round(adx_val,3) if adx_val is not None else None,
            "atr": round(atr_val,6) if atr_val is not None else None,
            "vol_guard": vol_guard,
            "score": round(score,3),
            "pos_size_mult_of_capital": round(pos_size_mult,6) if pos_size_mult is not None else None,
            "suggested_stop": round(suggested_stop,6) if suggested_stop is not None else None,
            "trailing_stop": round(trailing_stop,6) if trailing_stop is not None else None,
            "rebalance": self.rebalance_cadence,
            "notes": "pos_size_mult_of_capital 表示建议仓位为该值 * 可用资金（需按手续费/滑点/资金做最终换算）"
        }

        reason = " | ".join(reasons) if reasons else "no clear long/short alignment"

        return SignalModel(
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            date=dates[-1],
            confidence=round(confidence,3),
            reason=reason,
            details=details
        )


def make_moving_average_trend_presets() -> Dict[str, Dict[str, Any]]:
    """
    Presets:
      - swing/intermediate/position 用于快速切换周期偏好
      - swing: 相对短一点的长期观测（适合 2-6 周）
      - intermediate: 1-3 月
      - position: 多月到数季度
    """
    swing = {
        "ma_periods": [21, 50, 100],
        "ma_type": "ema",
        "ht_timeframe": "W",
        "adx_period": 14,
        "adx_threshold": 18,
        "atr_period": 14,
        "trailing_atr_mult": 3.0,
        "entry_atr_mult": 1.2,
        "min_atr_price_ratio": 0.0008,
        "risk_per_trade": 0.002,
        "allow_shorts": False,
        "rebalance_cadence": "weekly",
        "score_threshold": 0.55
    }
    intermediate = {
        "ma_periods": [50, 100, 200],
        "ma_type": "ema",
        "ht_timeframe": "W",
        "adx_period": 14,
        "adx_threshold": 20,
        "atr_period": 21,
        "trailing_atr_mult": 3.0,
        "entry_atr_mult": 1.5,
        "min_atr_price_ratio": 0.0012,
        "risk_per_trade": 0.003,
        "allow_shorts": False,
        "rebalance_cadence": "weekly",
        "score_threshold": 0.6
    }
    position = {
        "ma_periods": [100, 200, 400],
        "ma_type": "sma",
        "ht_timeframe": "M",
        "adx_period": 21,
        "adx_threshold": 22,
        "atr_period": 21,
        "trailing_atr_mult": 3.5,
        "entry_atr_mult": 2.0,
        "min_atr_price_ratio": 0.0015,
        "risk_per_trade": 0.004,
        "allow_shorts": True,
        "rebalance_cadence": "weekly",
        "score_threshold": 0.65
    }
    return {"swing": swing, "intermediate": intermediate, "position": position}