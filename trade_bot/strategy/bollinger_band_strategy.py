from datetime import datetime
from typing import List, Optional, Dict, Any
import math

from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel


DEFAULT_WEIGHTS = {
    "bb": 0.50,  # Bollinger band breakout / position strength (primary)
    "atr": 0.14,  # volatility filter / expansion
    "rsi": 0.10,  # momentum / avoid extremes
    "volume": 0.10,  # volume z-score confirmation
    "vwap": 0.04,  # price vs VWAP soft confirmation
    "obv": 0.04,  # OBV trend confirmation
    "macd": 0.08,  # optional momentum confirmation
}

EPS = 1e-6

class BollingerBandStrategy(TradingStrategy):
    """
    Bollinger-band centric weekly-option strategy — robust, completed-bar based.
    Key features:
        - BB primary signal
        - Completed-bar based decisions (no lookahead).
        - Single-attribute _safe_get for provider-agnostic access.
        - Volume z-score with MAD fallback.
        - ATR percentile filtering to avoid low-volatility false breakouts.
        - VWAP/OBV soft confirmations when available.
        - Normalized weights and presets factory included.
    """

    def __init__(
        self,
        data_provider,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 7,
        atr_period: int = 14,
        volume_window: int = 30,
        volume_zscore_threshold: float = 1.8,
        atr_percentile_filter: float = 0.4,
        confirmation_threshold: float = 0.58,
        weights: Optional[Dict[str, float]] = None,
        macd_params: Optional[Dict[str, int]] = None,
        atr_percentile_window: int = 60,
    ):
        self.provider = data_provider

        # BB params
        self.bb_period = int(bb_period)
        self.bb_std = float(bb_std)

        # Other indicator params
        self.rsi_period = int(rsi_period)
        self.atr_period = int(atr_period)
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}

        # Volume / ATR filters
        self.volume_window = int(max(5, volume_window))
        self.volume_zscore_threshold = float(volume_zscore_threshold)
        self.atr_percentile_filter = float(atr_percentile_filter)
        self.atr_percentile_window = int(max(20, atr_percentile_window))

        # Scoring threshold
        self.confirmation_threshold = float(confirmation_threshold)

        # Normalize weights
        merged = DEFAULT_WEIGHTS.copy()
        if weights:
            merged.update(weights)
        self.weights = self._normalize_weights(merged)

    # -------------------------
    # Helpers
    # -------------------------
    def _normalize_weights(self, w: Dict[str, float]) -> Dict[str, float]:
        total = sum(float(v) for v in w.values()) or 1.0
        return {k: float(v) / total for k, v in w.items()}

    def _safe_get(self, series, idx: int, attr: str, default=None):
        """
        Single-attribute safe getter (returns getattr(series[idx], attr, default)).
        """
        try:
            node = series[idx]
        except Exception:
            return default
        return getattr(node, attr, default)

    def _volume_zscore(
        self, recent_volumes: List[float], latest_volume: float
    ) -> float:
        if not recent_volumes:
            return 0.0
        n = len(recent_volumes)
        mean = sum(recent_volumes) / n
        var = sum((v - mean) ** 2 for v in recent_volumes) / n
        std = math.sqrt(var)
        if std < 1e-9:
            # MAD fallback
            sorted_vals = sorted(recent_volumes)
            med = sorted_vals[n // 2]
            mad = sum(abs(v - med) for v in recent_volumes) / n
            robust_std = max(mad * 1.4826, 1e-9)
            return (latest_volume - med) / robust_std
        return (latest_volume - mean) / std

    def _build_atr_list(self, atr_series, lookback_bars: int) -> List[float]:
        available = len(atr_series) if atr_series else 0
        take = min(available, lookback_bars)
        hist = []
        for i in range(1, take + 1):  # completed bars: -1 .. -take
            val = self._safe_get(atr_series, -i, f"ATRr_{self.atr_period}", None)
            if val is None:
                val = self._safe_get(atr_series, -i, "value", 0.0)
            hist.append(val or 0.0)
        return hist

    def _percentile(self, data: List[float], q: float) -> float:
        if not data:
            return 0.0
        s = sorted(data)
        idx = (len(s) - 1) * q
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return s[lo]
        frac = idx - lo
        return s[lo] * (1 - frac) + s[hi] * frac

    # -------------------------
    # Public API
    # -------------------------
    def get_name(self) -> str:
        return "BB Weekly (Bollinger primary)"

    def get_lookback_window(self) -> int:
        core = max(
            self.bb_period,
            self.atr_period,
            self.rsi_period,
            self.volume_window,
            self.atr_percentile_window,
        )
        return max(120, core + 20)

    # -------------------------
    # Main signal generation
    # -------------------------
    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        current_date = candles[-1].date if candles else None

        # Data sufficiency
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

        # Fetch indicators
        bb = self.provider.get_indicator(
            "bbands", candles, {"length": self.bb_period, "std": self.bb_std}
        )
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})
        try:
            macd = self.provider.get_indicator("macd", candles, self.macd_params)
        except Exception:
            macd = None
        try:
            vwap = self.provider.get_indicator("vwap", candles, {})
        except Exception:
            vwap = None
        try:
            obv = self.provider.get_indicator("obv", candles, {})
        except Exception:
            obv = None

        # Basic availability
        if not all([bb, rsi, atr]) or len(bb) < 3 or len(rsi) < 3 or len(atr) < 3:
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="Indicator data unavailable",
                details={},
            )

        # Completed-bar indices
        completed_idx = -2
        prior_idx = -3

        # Price and volume
        completed_close = self._safe_get(candles, completed_idx, "close", None)
        latest_close = self._safe_get(candles, -1, "close", None)
        latest_volume = self._safe_get(candles, -1, "volume", 0.0)

        # BB values (common names via multi-get)
        bbu = self._safe_get(
            bb,
            completed_idx,
            f"close_BBU_{self.bb_period}_{self.bb_std}",
            None,
        )
        bbm = self._safe_get(
            bb,
            completed_idx,
            f"close_BBM_{self.bb_period}_{self.bb_std}",
            None,
        )
        bbl = self._safe_get(
            bb,
            completed_idx,
            f"close_BBL_{self.bb_period}_{self.bb_std}",
            None,
        )

        if None in (bbu, bbm, bbl):
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="BB fields missing",
                details={},
            )

        # RSI (completed)
        curr_rsi = self._safe_get(
            rsi,
            completed_idx,
            f"close_RSI_{self.rsi_period}",
            None,
        )

        # ATR list and current
        atr_hist = self._build_atr_list(atr, lookback_bars=self.atr_percentile_window)
        cur_atr = self._safe_get(atr, completed_idx, f"ATRr_{self.atr_period}", None)
        if cur_atr is None:
            cur_atr = self._safe_get(atr, completed_idx, "value", None)

        # ATR percentile filter
        atr_percentile_value = (
            self._percentile(atr_hist, self.atr_percentile_filter) if atr_hist else 0.0
        )
        atr_vol_ok = (
            cur_atr is not None and atr_hist and cur_atr > atr_percentile_value + EPS
        )

        # Volume spike (completed vols exclude current forming bar)
        completed_vols = [
            self._safe_get(candles, -i, "volume", 0.0)
            for i in range(2, self.volume_window + 2)
        ]
        completed_vols = [v for v in completed_vols if v is not None]
        vol_z = self._volume_zscore(completed_vols, latest_volume or 0.0)
        vol_spike = vol_z > self.volume_zscore_threshold

        # MACD confirmation (optional)
        macd_confirm_up = macd_confirm_down = False
        if macd and len(macd) >= 3:
            name_val = f'close_MACD_{self.macd_params["fast"]}_{self.macd_params["slow"]}_{self.macd_params["signal"]}'
            name_sig = f'close_MACDs_{self.macd_params["fast"]}_{self.macd_params["slow"]}_{self.macd_params["signal"]}'
            mv_prev = self._safe_get(
                macd, completed_idx, name_val, None
            )
            ms_prev = self._safe_get(
                macd, completed_idx, name_sig, None
            )
            mv_prior = self._safe_get(
                macd, prior_idx, name_val, None
            )
            ms_prior = self._safe_get(
                macd, prior_idx, name_sig, None
            )
            if None not in (mv_prior, ms_prior, mv_prev, ms_prev):
                macd_confirm_up = (mv_prior <= ms_prior + EPS) and (
                    mv_prev > ms_prev + EPS
                )
                macd_confirm_down = (mv_prior >= ms_prior - EPS) and (
                    mv_prev < ms_prev - EPS
                )

        # VWAP / OBV soft confirmations
        vwap_price = None
        if vwap:
            vwap_price = self._safe_get(
                vwap, completed_idx, "VWAP_D", None
            )

        obv_trend_up = obv_trend_down = None
        if obv and len(obv) >= 3:
            obv_curr = self._safe_get(obv, completed_idx, "OBV", None)
            obv_prev = self._safe_get(obv, prior_idx, "OBV", None)
            if obv_curr is not None and obv_prev is not None:
                obv_trend_up = obv_curr > obv_prev + EPS
                obv_trend_down = obv_curr < obv_prev - EPS

        # Bollinger breakout checks (completed bar)
        eps = max(EPS, 1e-6)
        bb_break_up = (
            completed_close is not None
            and bbu is not None
            and completed_close > bbu + eps
        )
        bb_break_down = (
            completed_close is not None
            and bbl is not None
            and completed_close < bbl - eps
        )

        # BB distance pct
        bb_dist_pct = None
        if completed_close is not None and bbm:
            try:
                bb_dist_pct = (completed_close - bbm) / (abs(bbm) + EPS)
            except Exception:
                bb_dist_pct = None

        # Scoring
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)

        # Bullish breakout
        if bb_break_up:
            scorer.add(True, "BB breakout up", weight=self.weights.get("bb", 0.0))
            scorer.add(
                atr_vol_ok, "ATR above percentile", weight=self.weights.get("atr", 0.0)
            )
            scorer.add(
                curr_rsi is not None and curr_rsi > 50 + EPS,
                "RSI > 50",
                weight=self.weights.get("rsi", 0.0),
            )
            scorer.add(
                vol_spike, "Volume spike", weight=self.weights.get("volume", 0.0)
            )
            scorer.add(
                macd_confirm_up, "MACD confirms", weight=self.weights.get("macd", 0.0)
            )
            if vwap_price is not None:
                scorer.add(
                    (completed_close or 0.0) >= vwap_price - EPS,
                    "Price >= VWAP",
                    weight=self.weights.get("vwap", 0.0),
                )
            if obv_trend_up is not None:
                scorer.add(
                    obv_trend_up, "OBV trending up", weight=self.weights.get("obv", 0.0)
                )
            signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Bearish breakout
        elif bb_break_down:
            scorer.add(True, "BB breakout down", weight=self.weights.get("bb", 0.0))
            scorer.add(
                atr_vol_ok, "ATR above percentile", weight=self.weights.get("atr", 0.0)
            )
            scorer.add(
                curr_rsi is not None and curr_rsi < 50 - EPS,
                "RSI < 50",
                weight=self.weights.get("rsi", 0.0),
            )
            scorer.add(
                vol_spike, "Volume spike", weight=self.weights.get("volume", 0.0)
            )
            scorer.add(
                macd_confirm_down, "MACD confirms", weight=self.weights.get("macd", 0.0)
            )
            if vwap_price is not None:
                scorer.add(
                    (completed_close or 0.0) <= vwap_price + EPS,
                    "Price <= VWAP",
                    weight=self.weights.get("vwap", 0.0),
                )
            if obv_trend_down is not None:
                scorer.add(
                    obv_trend_down,
                    "OBV trending down",
                    weight=self.weights.get("obv", 0.0),
                )
            signal, confidence, reasons = scorer.evaluate(direction="bearish")

        # Mean-reversion extreme handling
        else:
            extreme_long = (
                completed_close is not None
                and bbu is not None
                and completed_close > bbu + abs(bbu) * 0.01
            ) and (vol_z > 2.0 or (curr_rsi is not None and curr_rsi > 80))
            extreme_short = (
                completed_close is not None
                and bbl is not None
                and completed_close < bbl - abs(bbl) * 0.01
            ) and (vol_z > 2.0 or (curr_rsi is not None and curr_rsi < 20))

            if extreme_long:
                scorer.add(
                    True, "BB extreme above upper", weight=self.weights.get("bb", 0.0)
                )
                scorer.add(
                    not atr_vol_ok,
                    "ATR extreme check (prefer volatile)",
                    weight=self.weights.get("atr", 0.0),
                )
                scorer.add(
                    curr_rsi is not None and curr_rsi > 50,
                    "RSI extreme",
                    weight=self.weights.get("rsi", 0.0),
                )
                scorer.add(
                    vol_spike, "Volume extreme", weight=self.weights.get("volume", 0.0)
                )
                signal, confidence, reasons = scorer.evaluate(direction="bearish")
            elif extreme_short:
                scorer.add(
                    True, "BB extreme below lower", weight=self.weights.get("bb", 0.0)
                )
                scorer.add(
                    not atr_vol_ok,
                    "ATR extreme check (prefer volatile)",
                    weight=self.weights.get("atr", 0.0),
                )
                scorer.add(
                    curr_rsi is not None and curr_rsi < 50,
                    "RSI extreme",
                    weight=self.weights.get("rsi", 0.0),
                )
                scorer.add(
                    vol_spike, "Volume extreme", weight=self.weights.get("volume", 0.0)
                )
                signal, confidence, reasons = scorer.evaluate(direction="bullish")
            else:
                signal, confidence, reasons = (
                    "hold",
                    0.0,
                    ["No BB breakout or clear extreme"],
                )

        # Details
        details: Dict[str, Any] = {
            "completed_close": completed_close,
            "latest_close": latest_close,
            "bbu": bbu,
            "bbm": bbm,
            "bbl": bbl,
            "bb_dist_pct": round(bb_dist_pct, 6) if bb_dist_pct is not None else None,
            "curr_rsi": curr_rsi,
            "atr_current": cur_atr,
            "atr_percentile_value": (
                round(atr_percentile_value, 6) if atr_hist else None
            ),
            "atr_vol_ok": atr_vol_ok,
            "volume": latest_volume,
            "vol_zscore": round(vol_z, 3),
            "vol_spike": vol_spike,
            "macd_up": macd_confirm_up,
            "macd_down": macd_confirm_down,
            "vwap": vwap_price,
            "obv_trend_up": obv_trend_up,
            "obv_trend_down": obv_trend_down,
            "confidence": round(confidence, 3),
            "reasons": reasons,
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
def make_bb_presets() -> Dict[str, Dict[str, Any]]:
    mid_balanced = {
        "bb_period": 20,
        "bb_std": 2.0,
        "rsi_period": 14,
        "atr_period": 14,
        "volume_window": 30,
        "volume_zscore_threshold": 1.5,
        "atr_percentile_filter": 0.4,
        "atr_percentile_window": 60,
        "confirmation_threshold": 0.58,
        "weights": {
            "bb": 0.50,
            "atr": 0.18,
            "rsi": 0.12,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    mid_conservative = {
        "bb_period": 20,
        "bb_std": 2.2,
        "rsi_period": 14,
        "atr_period": 14,
        "volume_window": 40,
        "volume_zscore_threshold": 1.8,
        "atr_percentile_filter": 0.5,
        "atr_percentile_window": 80,
        "confirmation_threshold": 0.62,
        "weights": {
            "bb": 0.55,
            "atr": 0.20,
            "rsi": 0.10,
            "volume": 0.08,
            "vwap": 0.03,
            "obv": 0.02,
            "macd": 0.02,
        },
    }

    mid_aggressive = {
        "bb_period": 14,
        "bb_std": 1.9,
        "rsi_period": 10,
        "atr_period": 10,
        "volume_window": 25,
        "volume_zscore_threshold": 1.2,
        "atr_percentile_filter": 0.35,
        "atr_percentile_window": 50,
        "confirmation_threshold": 0.54,
        "weights": {
            "bb": 0.48,
            "atr": 0.20,
            "rsi": 0.12,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    short_quick = {
        "bb_period": 10,
        "bb_std": 1.8,
        "rsi_period": 7,
        "atr_period": 7,
        "volume_window": 15,
        "volume_zscore_threshold": 1.0,
        "atr_percentile_filter": 0.3,
        "atr_percentile_window": 40,
        "confirmation_threshold": 0.52,
        "weights": {
            "bb": 0.50,
            "atr": 0.20,
            "rsi": 0.10,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    short_balanced = {
        "bb_period": 12,
        "bb_std": 2.0,
        "rsi_period": 10,
        "atr_period": 10,
        "volume_window": 20,
        "volume_zscore_threshold": 1.2,
        "atr_percentile_filter": 0.35,
        "atr_percentile_window": 50,
        "confirmation_threshold": 0.56,
        "weights": {
            "bb": 0.52,
            "atr": 0.18,
            "rsi": 0.10,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    short_conservative = {
        "bb_period": 14,
        "bb_std": 2.2,
        "rsi_period": 12,
        "atr_period": 10,
        "volume_window": 25,
        "volume_zscore_threshold": 1.4,
        "atr_percentile_filter": 0.4,
        "atr_percentile_window": 60,
        "confirmation_threshold": 0.60,
        "weights": {
            "bb": 0.55,
            "atr": 0.18,
            "rsi": 0.10,
            "volume": 0.08,
            "vwap": 0.05,
            "obv": 0.02,
            "macd": 0.02,
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
