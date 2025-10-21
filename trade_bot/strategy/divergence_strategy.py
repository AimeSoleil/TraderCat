"""
MidTermDivergenceStrategy

- 以中期（日线，lookback ~ 30-90 日）背离为核心信号（以 RSI / MACD histogram）。
- 自动识别 recent swing low/high（基于 window min/max 排除最新正在形成的 bar）。
- 支持 Regular Divergence（反转信号）和 Hidden Divergence（延续信号）。
- 用 ATR 进行止损/仓位规模计算；用 volume z-score 作可选确认。
- 将各项确认项通过 SignalScorer 加权合成并与 confirmation_threshold 比较。
- 提供 presets 。
"""

from typing import List, Optional, Dict, Any, Tuple
import math

from regex import F

from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel

DEFAULT_WEIGHTS = {
    "divergence": 0.45,  # 主信号（RSI/MACD divergence）
    "atr": 0.20,  # ATR 用于过滤低波动
    "trend_filter": 0.15,  # 长期均线方向（SMA50/SMA200）
    "momentum": 0.10,  # MACD cross 或 RSI 动量
    "volume": 0.10,  # 成交量 z-score 确认（可选）
}

EPS = 1e-6

class DivergenceStrategy(TradingStrategy):
    """
    Mid-term divergence strategy focused on daily timeframe.

    Constructor params (key ones):
        - data_provider: provider implementing get_indicator(name, candles, params)
        - lookback_days: window to search swings (default 40)
        - min_swing_pct: minimum swing range as fraction to avoid micro-swings
        - rsi_period: RSI period for divergence detection
        - atr_period: ATR period for volatility and position sizing
        - volume_window: window for volume z-score (set 0 to disable volume)
        - volume_z_th: volume z-score threshold for "volume confirmation"
        - ema_fast, ema_slow: for trend filter (e.g., 20, 60)
        - confirmation_threshold: scorer threshold (0-1)
        - weights: override DEFAULT_WEIGHTS (will be normalized)
    """

    def __init__(
        self,
        data_provider,
        lookback_days: int = 40,
        min_swing_pct: float = 0.02,
        rsi_period: int = 14,
        atr_period: int = 14,
        volume_window: int = 30,
        volume_z_th: float = 1.0,
        ema_fast: int = 20,
        ema_slow: int = 60,
        confirmation_threshold: float = 0.58,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.provider = data_provider
        self.lookback_days = int(max(10, lookback_days))
        self.min_swing_pct = float(min_swing_pct)
        self.rsi_period = int(rsi_period)
        self.atr_period = int(atr_period)
        self.volume_window = int(max(0, volume_window))
        self.volume_z_th = float(volume_z_th)
        self.ema_fast = int(ema_fast)
        self.ema_slow = int(ema_slow)
        self.confirmation_threshold = float(confirmation_threshold)

        merged = DEFAULT_WEIGHTS.copy()
        if weights:
            merged.update(weights)
        self.weights = self._normalize_weights(merged)

    def get_name(self) -> str:
        return "Divergence (regular & hidden)"

    def get_lookback_window(self) -> int:
        return max(120, self.lookback_days + self.atr_period + self.volume_window + 10)

    # -------------------------
    # Helpers
    # -------------------------
    def _normalize_weights(self, w: Dict[str, float]) -> Dict[str, float]:
        total = sum(float(v) for v in w.values()) or 1.0
        return {k: float(v) / total for k, v in w.items()}

    def _safe_get(self, series, idx: int, attr: str, default=None):
        """Single-attribute safe getter (no multi candidates)."""
        try:
            node = series[idx]
        except Exception:
            return default
        return getattr(node, attr, default)

    def _volume_zscore(self, recent_volumes: List[float], latest: float) -> float:
        if not recent_volumes:
            return 0.0
        n = len(recent_volumes)
        mean = sum(recent_volumes) / n
        var = sum((v - mean) ** 2 for v in recent_volumes) / n
        std = math.sqrt(var)
        if std < 1e-9:
            med = sorted(recent_volumes)[n // 2]
            mad = sum(abs(v - med) for v in recent_volumes) / n
            robust_std = max(mad * 1.4826, 1e-9)
            return (latest - med) / robust_std
        return (latest - mean) / std

    def _build_atr_list(self, atr_series, lookback: int) -> List[float]:
        if not atr_series:
            return []
        take = min(len(atr_series), lookback)
        vals = []
        for i in range(1, take + 1):
            v = self._safe_get(atr_series, -i, f"ATRr_{self.atr_period}", None)
            if v is None:
                v = self._safe_get(atr_series, -i, "value", None)
            vals.append(float(v or 0.0))
        return vals

    # -------------------------
    # Swing detection
    # -------------------------
    def _find_swing(self, candles: list) -> Optional[Tuple[int, float, int, float]]:
        """
        Find a simple recent swing low and swing high within lookback_days.
        Returns (idx_low, low_price, idx_high, high_price) where indices are absolute indices in candles list.
        Uses completed bars only (exclude last forming bar).
        """
        n = len(candles)
        if n < self.lookback_days + 2:
            return None
        window = candles[-(self.lookback_days + 1) : -1]  # exclude latest forming bar
        lows = [self._safe_get(window, i, "low", None) for i in range(len(window))]
        highs = [self._safe_get(window, i, "high", None) for i in range(len(window))]
        lows = [(i, v) for i, v in enumerate(lows) if v is not None]
        highs = [(i, v) for i, v in enumerate(highs) if v is not None]
        if not lows or not highs:
            return None
        lo_idx_rel, lo_price = min(lows, key=lambda x: x[1])
        hi_idx_rel, hi_price = max(highs, key=lambda x: x[1])
        # translate to absolute indices in candles
        start_idx = n - (self.lookback_days + 1)
        lo_idx = start_idx + lo_idx_rel
        hi_idx = start_idx + hi_idx_rel
        # require meaningful swing range
        if hi_price <= lo_price:
            return None
        if (hi_price - lo_price) / max(abs(lo_price), 1.0) < self.min_swing_pct:
            return None
        return (lo_idx, float(lo_price), hi_idx, float(hi_price))

    # -------------------------
    # Divergence detection
    # -------------------------
    def _detect_divergence(
        self, candles: list, indicator_series, indicator_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Detect regular or hidden divergence using price swing extremes and indicator extremes.
        Returns dict with keys: type ('regular'|'hidden'), direction ('bullish'|'bearish'), score_info...
        Approach:
            - Get two swing points: older (A) and newer (B) for lows or highs.
            - For bullish regular: price_low_B < price_low_A and indicator_low_B > indicator_low_A.
            - For bullish hidden: price_low_B > price_low_A and indicator_low_B < indicator_low_A (for continuation).
            - Symmetric for bearish.
        """
        swing = self._find_swing(candles)
        if swing is None:
            return None
        lo_idx, lo_price, hi_idx, hi_price = swing

        # Identify which pair to use based on recent price direction: if latest price closer to high -> check highs; else lows
        latest_close = self._safe_get(candles, -1, "close", None)
        if latest_close is None:
            return None

        # pull indicator values aligned to candle indices for A (older) and B (newer)
        # choose A earlier than B in time; we take A = earlier extreme, B = later extreme
        if lo_idx < hi_idx:
            # low occurred before high -> two pivots are low->high; determine which pair to compare:
            # We'll test both low-pair and high-pair possibilities.
            pass

        # We'll search for two recent lows and two recent highs within swing window
        # Build indicator value series (use safe_get candidates)
        # indicator_series is expected to be provider.get_indicator(...) result; we'll try 'value' or named fields
        # Collect local minima/maxima indexes within the same swing window (simple approach: min and max)
        start_idx = len(candles) - (self.lookback_days + 1)
        window_idxs = list(
            range(start_idx, len(candles) - 1)
        )  # exclude last forming bar

        # helper to get indicator value at absolute candle index
        def ind_at(abs_idx):
            return self._safe_get(indicator_series, abs_idx, indicator_name, None)

        # find two most recent lows and highs by price in the window for comparison
        prices = [
            self._safe_get(candles, idx, "close", None)
            for idx in window_idxs
        ]
        price_pairs = [
            (window_idxs[i], prices[i])
            for i in range(len(prices))
            if prices[i] is not None
        ]
        if len(price_pairs) < 4:
            return None

        # find two local lows: take two smallest closes with older-first ordering
        sorted_by_idx = sorted(price_pairs, key=lambda x: x[0])
        sorted_by_price_asc = sorted(sorted_by_idx, key=lambda x: x[1])
        # pick earliest small and later small as A and B (ensure A earlier than B)
        lows = sorted(
            sorted_by_price_asc[:6], key=lambda x: x[0]
        )  # pick up to 6 smallest then keep order
        if len(lows) < 2:
            lows = []
        highs = sorted(sorted_by_idx, key=lambda x: x[1], reverse=True)
        highs = sorted(highs[:6], key=lambda x: x[0])
        if len(highs) < 2:
            highs = []

        def compare_pair(pairA, pairB, kind: str):
            """
            pairA/B: (abs_idx, price)
            kind: 'low' or 'high'
            Returns divergence dict or None
            """
            idxA, pA = pairA
            idxB, pB = pairB
            # indicator at times (map abs_idx to relative index into indicator_series)
            valA = ind_at(idxA)
            valB = ind_at(idxB)
            if valA is None or valB is None:
                return None
            # For lows:
            if kind == "low":
                # Regular bullish divergence: price_B < price_A and ind_B > ind_A
                if pB < pA - EPS and valB > valA + EPS:
                    return {
                        "type": "regular",
                        "direction": "bullish",
                        "priceA": pA,
                        "priceB": pB,
                        "indA": valA,
                        "indB": valB,
                        "idxA": idxA,
                        "idxB": idxB,
                    }
                # Hidden bullish divergence (continuation): price_B > price_A and ind_B < ind_A
                if pB > pA + EPS and valB < valA - EPS:
                    return {
                        "type": "hidden",
                        "direction": "bullish",
                        "priceA": pA,
                        "priceB": pB,
                        "indA": valA,
                        "indB": valB,
                        "idxA": idxA,
                        "idxB": idxB,
                    }
            else:
                # highs: Regular bearish: price_B > price_A and ind_B < ind_A
                if pB > pA + EPS and valB < valA - EPS:
                    return {
                        "type": "regular",
                        "direction": "bearish",
                        "priceA": pA,
                        "priceB": pB,
                        "indA": valA,
                        "indB": valB,
                        "idxA": idxA,
                        "idxB": idxB,
                    }
                # Hidden bearish: price_B < price_A and ind_B > ind_A
                if pB < pA - EPS and valB > valA + EPS:
                    return {
                        "type": "hidden",
                        "direction": "bearish",
                        "priceA": pA,
                        "priceB": pB,
                        "indA": valA,
                        "indB": valB,
                        "idxA": idxA,
                        "idxB": idxB,
                    }
            return None

        # try low pairs first
        divergence = None
        if len(lows) >= 2:
            # use the earliest two in time ordering
            for i in range(len(lows) - 1):
                a = lows[i]
                b = lows[i + 1]
                div = compare_pair(a, b, "low")
                if div:
                    divergence = div
                    break
        if divergence is None and len(highs) >= 2:
            for i in range(len(highs) - 1):
                a = highs[i]
                b = highs[i + 1]
                div = compare_pair(a, b, "high")
                if div:
                    divergence = div
                    break

        return divergence

    # -------------------------
    # Signal generation
    # -------------------------
    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        """
        Main signal pipeline:
            - Check data sufficiency.
            - Get indicators (RSI primary; MACD optional).
            - Detect divergence (RSI first, then MACD if RSI absent).
            - Apply trend filter using SMA50/SMA200 (soft/weighted).
            - Compose confirmations into SignalScorer and evaluate.
        """
        current_date = candles[-1].date if candles else None

        if not self.provider or len(candles) < self.get_lookback_window() + 1:
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="Insufficient data",
                details={},
            )

        # fetch indicators
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        ema_fast = self.provider.get_indicator(
            "ema", candles, {"length": self.ema_fast}
        )
        ema_slow = self.provider.get_indicator(
            "ema", candles, {"length": self.ema_slow}
        )

        try:
            macd = self.provider.get_indicator(
                "macd", candles, {"fast": 12, "slow": 26, "signal": 9}
            )
        except Exception:
            macd = None

        # optional volume
        vol_series = None
        if self.volume_window > 0:
            # volume is read from candles directly
            vol_series = [
                self._safe_get(candles, i, "volume", None) for i in range(len(candles))
            ]
        # basic checks
        if not all([rsi, atr]) or len(rsi) < 3 or len(atr) < 3:
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="Indicators missing",
                details={},
            )

        # detect divergence using RSI first
        if (len(candles) != len(rsi or len(candles) != len(macd))):
            raise ValueError("Indicator series length mismatch with candles")
        divergence = self._detect_divergence(candles, rsi, f"close_RSI_{self.rsi_period}")
        used_indicator = "rsi"
        if divergence is None and macd:
            divergence = self._detect_divergence(candles, macd, "close_MACD_12_26_9")
            used_indicator = "macd"

        if divergence is None:
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="No divergence detected",
                details={},
            )

        # basic price info and ATR
        completed_idx = -1
        completed_close = self._safe_get(candles, completed_idx, "close", None)
        cur_atr = self._safe_get(
            atr, completed_idx, f"ATRr_{self.atr_period}", None
        ) or self._safe_get(atr, completed_idx, "value", None)
        atr_hist = self._build_atr_list(atr, lookback=self.atr_period * 4)
        atr_percentile = 0.0
        if atr_hist:
            atr_percentile = sorted(atr_hist)[
                int(len(atr_hist) * 0.3)
            ]  # simple 30th pct approx
        atr_ok = cur_atr is not None and cur_atr > (atr_percentile + EPS)

        # trend filter using EMA fast/slow (completed)
        ema_fast = self._safe_get(
            ema_fast, -2, f"close_EMA_{self.ema_fast}", None
        ) or self._safe_get(ema_fast, -2, "value", None)
        ema_slow = self._safe_get(
            ema_slow, -2, f"close_EMA_{self.ema_slow}", None
        ) or self._safe_get(ema_slow, -2, "value", None)
        trend_is_up = ema_fast is not None and ema_slow is not None and ema_fast > ema_slow
        trend_is_down = ema_fast is not None and ema_slow is not None and ema_fast < ema_slow

        # volume confirmation if enabled
        vol_z = 0.0
        vol_confirm = False
        if self.volume_window > 0 and vol_series:
            recent_vols = vol_series[-(self.volume_window + 1) : -1]
            vol_z = self._volume_zscore(
                [v for v in recent_vols if v is not None],
                self._safe_get(candles, -1, "volume", 0.0) or 0.0,
            )
            vol_confirm = vol_z > self.volume_z_th

        # Build scorer
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)
        # divergence primary
        scorer.add(
            True,
            f"Divergence {divergence.get('type')} on {used_indicator}",
            weight=self.weights.get("divergence", 0.0),
        )
        # ATR filter weight
        scorer.add(atr_ok, "ATR volatility pass", weight=self.weights.get("atr", 0.0))
        # trend filter weight: favor trades aligned with trend for hidden divergence (continuation),
        # for regular divergence prefer opposite of trend (reversal)
        dirn = divergence.get("direction")
        div_type = divergence.get("type")
        if div_type == "hidden":
            # hidden -> continuation: require trend same as divergence direction
            if dirn == "bullish":
                scorer.add(
                    trend_is_up,
                    "Trend up (hidden continuation)",
                    weight=self.weights.get("trend_filter", 0.0),
                )
            else:
                scorer.add(
                    trend_is_down,
                    "Trend down (hidden continuation)",
                    weight=self.weights.get("trend_filter", 0.0),
                )
        else:
            # regular divergence -> reversal: require trend opposite or neutral
            if dirn == "bullish":
                scorer.add(
                    not trend_is_up,
                    "Trend not up (regular reversal)",
                    weight=self.weights.get("trend_filter", 0.0),
                )
            else:
                scorer.add(
                    not trend_is_down,
                    "Trend not down (regular reversal)",
                    weight=self.weights.get("trend_filter", 0.0),
                )

        # momentum confirmation (MACD cross or RSI direction)
        if used_indicator == "macd" and macd:
            # check if macd histogram turned positive/negative recently
            mh_prev = self._safe_get(macd, -3, "close_MACDh_12_26_9", None)
            mh_now = self._safe_get(macd, -2, "close_MACDh_12_26_9", None)
            if mh_prev is not None and mh_now is not None:
                if dirn == "bullish":
                    scorer.add(
                        mh_now > mh_prev,
                        "MACD histogram rising",
                        weight=self.weights.get("momentum", 0.0),
                    )
                else:
                    scorer.add(
                        mh_now < mh_prev,
                        "MACD histogram falling",
                        weight=self.weights.get("momentum", 0.0),
                    )
        else:
            # use RSI slope
            r_prev = self._safe_get(
                rsi, -3, f"close_RSI_{self.rsi_period}", None
            )
            r_now = self._safe_get(
                rsi, -2, f"close_RSI_{self.rsi_period}", None
            )
            if r_prev is not None and r_now is not None:
                if dirn == "bullish":
                    scorer.add(
                        r_now > r_prev,
                        "RSI rising",
                        weight=self.weights.get("momentum", 0.0),
                    )
                else:
                    scorer.add(
                        r_now < r_prev,
                        "RSI falling",
                        weight=self.weights.get("momentum", 0.0),
                    )

        # volume weight
        if self.volume_window > 0:
            scorer.add(
                vol_confirm, "Volume confirm", weight=self.weights.get("volume", 0.0)
            )
        else:
            # if volume disabled, treat as neutral (add small weight to momentum instead)
            scorer.add(True, "Volume disabled (neutral)", weight=0.0)

        signal, confidence, reasons = scorer.evaluate(
            direction="bullish" if dirn == "bullish" else "bearish"
        )

        # If hold, return
        if signal == "hold":
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="Scorer did not reach threshold",
                details={"divergence": divergence, "reasons": reasons},
            )

        details = {
            "divergence": divergence,
            "used_indicator": used_indicator,
            "scorer_reasons": reasons,
            "confidence": round(confidence, 3),
            "completed_close": completed_close,
            "cur_atr": cur_atr,
            "atr_percentile_est": atr_percentile,
            "atr_ok": atr_ok,
            "ema_fast": ema_fast,
            "ema_slow": ema_slow,
            "trend_is_up": trend_is_up,
            "trend_is_down": trend_is_down,
            "vol_z": round(vol_z, 3),
            "vol_confirm": vol_confirm,
        }

        return SignalModel(
            date=current_date,
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            confidence=round(confidence, 3),
            reason="; ".join(reasons),
            details=details,
        )


# -------------------------
# Presets
# -------------------------
def make_divergence_presets() -> Dict[str, Dict[str, Any]]:
    # 🟦 Mid-Term Presets (1–3 week swing setups)

    mid_balanced = {
        "lookback_days": 40,         # How far back to search for swing highs/lows
        "min_swing_pct": 0.02,       # Minimum price movement to qualify as a swing
        "rsi_period": 12,            # RSI window for momentum confirmation
        "atr_period": 12,            # ATR window for volatility sizing
        "volume_window": 25,         # Number of candles for volume Z-score calculation
        "volume_z_th": 1.2,          # Minimum volume Z-score to confirm breakout
        "ema_fast": 20,              # Fast EMA for trend direction
        "ema_slow": 50,              # Slow EMA for trend filter
        "confirmation_threshold": 0.58,  # Minimum signal strength to trigger entry
        "weights": {                 # Relative importance of each signal component
            "divergence": 0.45,      # Core signal: price vs indicator divergence
            "atr": 0.20,             # Volatility filter
            "trend_filter": 0.15,    # EMA-based trend bias
            "momentum": 0.10,        # RSI confirmation
            "volume": 0.10,          # Volume spike confirmation
        },
    }

    mid_conservative = {
        "lookback_days": 50,         # Longer swing window for stronger setups
        "min_swing_pct": 0.025,      # Require larger price moves
        "rsi_period": 14,
        "atr_period": 14,
        "volume_window": 30,
        "volume_z_th": 1.5,          # Higher volume threshold for confirmation
        "ema_fast": 30,
        "ema_slow": 100,
        "confirmation_threshold": 0.62,  # Stricter signal requirement
        "weights": {
            "divergence": 0.45,
            "atr": 0.20,
            "trend_filter": 0.15,
            "momentum": 0.10,
            "volume": 0.10,
        },
    }

    mid_aggressive = {
        "lookback_days": 25,         # Shorter swing window for faster entries
        "min_swing_pct": 0.015,      # Allow smaller price moves
        "rsi_period": 10,
        "atr_period": 10,
        "volume_window": 20,
        "volume_z_th": 1.0,          # Lower volume threshold for more signals
        "ema_fast": 10,
        "ema_slow": 30,
        "confirmation_threshold": 0.54,  # Looser signal gate
        "weights": {
            "divergence": 0.48,
            "atr": 0.18,
            "trend_filter": 0.12,
            "momentum": 0.12,
            "volume": 0.10,
        },
    }

    # 🟨 Short-Term Weekly Presets (2–5 day trades)

    short_quick = {
        "lookback_days": 12,         # Very short swing window
        "min_swing_pct": 0.012,
        "rsi_period": 5,
        "atr_period": 7,
        "volume_window": 12,
        "volume_z_th": 1.0,
        "ema_fast": 8,
        "ema_slow": 21,
        "confirmation_threshold": 0.54,
        "weights": {
            "divergence": 0.45,
            "atr": 0.20,
            "trend_filter": 0.15,
            "momentum": 0.10,
            "volume": 0.10,
        },
    }

    short_balanced = {
        "lookback_days": 15,
        "min_swing_pct": 0.015,
        "rsi_period": 6,
        "atr_period": 10,
        "volume_window": 15,
        "volume_z_th": 1.1,
        "ema_fast": 10,
        "ema_slow": 30,
        "confirmation_threshold": 0.56,
        "weights": {
            "divergence": 0.45,
            "atr": 0.20,
            "trend_filter": 0.15,
            "momentum": 0.10,
            "volume": 0.10,
        },
    }

    short_conservative = {
        "lookback_days": 18,
        "min_swing_pct": 0.018,
        "rsi_period": 7,
        "atr_period": 10,
        "volume_window": 18,
        "volume_z_th": 1.3,
        "ema_fast": 12,
        "ema_slow": 35,
        "confirmation_threshold": 0.60,
        "weights": {
            "divergence": 0.45,
            "atr": 0.20,
            "trend_filter": 0.15,
            "momentum": 0.10,
            "volume": 0.10,
        },
    }

    return {
        "mid_balanced": mid_balanced,
        "mid_conservative": mid_conservative,
        "mid_aggressive": mid_aggressive,
        "short_quick": short_quick,
        "short_balanced": short_balanced,
        "short_conservative": short_conservative,
    }



