from typing import List, Optional, Dict, Any

from trade_bot.strategy.signal_scorer import SignalScorer
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel


DEFAULT_WEIGHTS = {
    "structure": 0.55,
    "rsi": 0.14,
    "atr": 0.14,
    "volume": 0.08,
    "macd": 0.03,
    "vwap": 0.03,
    "obv": 0.03,
}

EPS = 1e-6 # 浮点数据误差


class MAStrategy(TradingStrategy):
    """
    EMA/SMA strategy (robust, Bollinger removed), specialied for weekly options trade.

    Key features:
    - Weight normalization at init and consistent use of weights for VWAP/OBV when available.
    - No lookahead: crossovers and confirmations use completed-bar values only.
    - Robust volume z-score with std guard and MAD fallback.
    - ATR history built from available bars with empty handling.
    - Float comparison tolerance via EPS.
    - MACD parameters configurable via macd_params dict (defaults: fast=12, slow=26, signal=9).

    Constructor params and defaults tuned for weekly options; override as needed.
    """

    def __init__(
        self,
        data_provider,
        ema_fast: int = 8,
        sma_slow: int = 21,
        rsi_period: int = 7,
        atr_period: int = 14,
        volume_window: int = 30,
        volume_zscore_threshold: float = 1.8,
        atr_expansion_ratio: float = 1.15,
        confirmation_threshold: float = 0.58,
        weights: Optional[Dict[str, float]] = None,
        macd_params: Optional[Dict[str, int]] = None,
    ):
        self.provider = data_provider

        # Core indicator parameters
        self.ema_fast = int(ema_fast)
        self.sma_slow = int(sma_slow)
        self.rsi_period = int(rsi_period)
        self.atr_period = int(atr_period)

        # Volume & ATR normalization
        self.volume_window = int(max(5, volume_window))
        self.volume_zscore_threshold = float(volume_zscore_threshold)
        self.atr_expansion_ratio = float(atr_expansion_ratio)

        # Scoring threshold
        self.confirmation_threshold = float(confirmation_threshold)

        # MACD params
        self.macd_params = macd_params or {"fast": 12, "slow": 26, "signal": 9}

        # Normalize and store weights (merge user weights with defaults)
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
        Safe getter that reads a single attribute name from series[idx].
        This function intentionally accepts a single attribute name only.
        """
        try:
            node = series[idx]
        except Exception:
            return default
        return getattr(node, attr, default)

    def _volume_zscore(self, recent_volumes: List[float], latest_volume: float) -> float:
        if not recent_volumes:
            return 0.0
        n = len(recent_volumes)
        mean = sum(recent_volumes) / n
        var = sum((v - mean) ** 2 for v in recent_volumes) / n
        std = var ** 0.5
        if std < 1e-9:
            # fallback to MAD-based robust estimate
            med = sorted(recent_volumes)[n // 2]
            mad = sum(abs(v - med) for v in recent_volumes) / n
            robust_std = max(mad * 1.4826, 1e-9)
            z = (latest_volume - med) / robust_std
            return z
        return (latest_volume - mean) / std

    def _build_atr_hist(self, atr_series, lookback_bars: int):
        # Take up to lookback_bars available completed ATR values
        available = len(atr_series) if atr_series else 0
        take = min(available, lookback_bars)
        hist = []
        for i in range(1, take + 1):  # 1..take => -1 .. -take (completed bars)
            val = self._safe_get(atr_series, -i, f'ATRr_{self.atr_period}', 0.0)
            hist.append(val or 0.0)
        return hist

    # -------------------------
    # Public API
    # -------------------------
    def get_name(self) -> str:
        return "MA (EMA/SMA)"

    def get_lookback_window(self) -> int:
        core = max(self.sma_slow, self.atr_period)
        return max(120, core + self.volume_window + 10)

    # -------------------------
    # Main signal generation
    # -------------------------
    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f"Strategy[{self.get_name()}] generating signal for {symbol}...")

        current_date = candles[-1].date if candles else None

        # 1) Data sufficiency
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

        # Fetch indicators (provider-dependent field names handled via _safe_get/_safe_get)
        ema = self.provider.get_indicator("ema", candles, {"length": self.ema_fast})
        sma = self.provider.get_indicator("sma", candles, {"length": self.sma_slow})
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

        # Basic availability checks
        if not all([ema, sma, rsi, atr]) or len(ema) < 3 or len(sma) < 3:
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="Indicator data unavailable or insufficient length",
                details={},
            )

        # Use completed-bar values only (no values from the still-forming latest bar)
        # completed bar indices: -2 (most recent completed), -3 (prior completed)
        completed_idx = -2
        prior_idx = -3

        cur = candles[-1]
        # For price comparisons prefer the last completed close to avoid intrabar lookahead
        completed_close = self._safe_get(candles, completed_idx, "close", None)
        latest_close = self._safe_get(candles, -1, "close", None)
        volume = self._safe_get(candles, -1, "volume", None)

        # Resolve EMA/SMA from provider fields using multi-candidate helper that calls _safe_get per candidate
        prev_ema = self._safe_get(ema, completed_idx, f'close_EMA_{self.ema_fast}', None)
        curr_ema = self._safe_get(ema, prior_idx, f'close_EMA_{self.ema_fast}', None)
        prev_sma = self._safe_get(sma, completed_idx, f'close_SMA_{self.sma_slow}', None)
        curr_sma = self._safe_get(sma, prior_idx, f'close_SMA_{self.sma_slow}', None)

        # If provider uses the opposite ordering, attempt fallback (ensure not None)
        if None in (prev_ema, curr_ema, prev_sma, curr_sma):
            prev_ema = prev_ema or self._safe_get(ema, -1, f'close_EMA_{self.ema_fast}', None)
            curr_ema = curr_ema or self._safe_get(ema, -2, f'close_EMA_{self.ema_fast}', None)
            prev_sma = prev_sma or self._safe_get(sma, -1, f'close_SMA_{self.sma_slow}', None)
            curr_sma = curr_sma or self._safe_get(sma, -2, f'close_SMA_{self.sma_slow}', None)

        if None in (prev_ema, curr_ema, prev_sma, curr_sma):
            return SignalModel(
                date=current_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal="hold",
                confidence=0.0,
                reason="MA fields missing after fallback attempts",
                details={},
            )

        # Cross detection using two completed bars (prior_idx vs completed_idx)
        ema_cross_up = (curr_ema <= curr_sma + EPS) and (prev_ema > prev_sma + EPS)
        ema_cross_down = (curr_ema >= curr_sma - EPS) and (prev_ema < prev_sma - EPS)

        # ATR expansion: build history from completed bars
        atr_hist = self._build_atr_hist(atr, lookback_bars=self.atr_period * 2)
        cur_atr = self._safe_get(atr, -2, f'ATRr_{self.atr_period}', None)
        atr_mean = (sum(atr_hist) / len(atr_hist)) if atr_hist else 0.0
        atr_expanding = (cur_atr is not None and atr_mean > 0 and cur_atr > self.atr_expansion_ratio * atr_mean)

        # RSI context (use most recent completed RSI)
        curr_rsi = self._safe_get(rsi, -2, f'close_RSI_{self.rsi_period}', None)
        rsi_bull = curr_rsi is not None and curr_rsi > 50 + EPS
        rsi_bear = curr_rsi is not None and curr_rsi < 50 - EPS

        # Volume spike: compute using recent completed volumes (exclude latest incomplete if desired)
        vol_window = max(5, self.volume_window)
        # recent_vols: use completed bars volumes (exclude current forming bar)
        completed_volumes = [self._safe_get(candles, -i, "volume", 0.0) for i in range(2, vol_window + 2)]
        completed_volumes = [v for v in completed_volumes if v is not None]
        vol_z = self._volume_zscore(completed_volumes, volume or 0.0)
        vol_spike = vol_z > self.volume_zscore_threshold

        # MACD confirmations (light) using configured macd_params
        macd_confirm_up = macd_confirm_down = False
        if macd and len(macd) >= 3:
            macd_name_val = f'close_MACD_{self.macd_params["fast"]}_{self.macd_params["slow"]}_{self.macd_params["signal"]}'
            macd_name_sig = f'close_MACDs_{self.macd_params["fast"]}_{self.macd_params["slow"]}_{self.macd_params["signal"]}'
            mv_prev = self._safe_get(macd, completed_idx, macd_name_val, None)
            ms_prev = self._safe_get(macd, completed_idx, macd_name_sig, None)
            mv_prior = self._safe_get(macd, prior_idx, macd_name_val, None)
            ms_prior = self._safe_get(macd, prior_idx, macd_name_sig, None)
            if None not in (mv_prior, ms_prior, mv_prev, ms_prev):
                macd_confirm_up = (mv_prior <= ms_prior + EPS) and (mv_prev > ms_prev + EPS)
                macd_confirm_down = (mv_prior >= ms_prior - EPS) and (mv_prev < ms_prev - EPS)

        # VWAP and OBV resolution (use completed-bar VWAP/OBV if provider returns per-bar populated)
        vwap_price = None
        if vwap:
            vwap_price = self._safe_get(vwap, -2, 'VWAP_D', None)

        obv_trend_up = obv_trend_down = None
        if obv and len(obv) >= 3:
            obv_curr = self._safe_get(obv, -2, 'OBV', None)
            obv_prev = self._safe_get(obv, -3, 'OBV', None)
            if obv_curr is not None and obv_prev is not None:
                obv_trend_up = obv_curr > obv_prev + EPS
                obv_trend_down = obv_curr < obv_prev - EPS

        # Scoring setup
        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)

        # Evaluate bullish scenario
        if ema_cross_up:
            scorer.add(True, "Structure: EMA crossed above SMA", weight=self.weights.get("structure", 0.0))
            scorer.add(rsi_bull, "RSI > 50", weight=self.weights.get("rsi", 0.0))
            scorer.add(atr_expanding, "ATR expanding", weight=self.weights.get("atr", 0.0))
            scorer.add(vol_spike, "Volume spike (z-score)", weight=self.weights.get("volume", 0.0))
            scorer.add(macd_confirm_up, "MACD confirms", weight=self.weights.get("macd", 0.0))

            # VWAP/OBV as weighted confirmations if available
            if vwap_price is not None:
                scorer.add((completed_close or 0.0) >= vwap_price - EPS, "Price >= VWAP", weight=self.weights.get("vwap", 0.0))
            if obv_trend_up is not None:
                scorer.add(obv_trend_up, "OBV trending up", weight=self.weights.get("obv", 0.0))

            signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Evaluate bearish scenario
        elif ema_cross_down:
            scorer.add(True, "Structure: EMA crossed below SMA", weight=self.weights.get("structure", 0.0))
            scorer.add(rsi_bear, "RSI < 50", weight=self.weights.get("rsi", 0.0))
            scorer.add(atr_expanding, "ATR expanding", weight=self.weights.get("atr", 0.0))
            scorer.add(vol_spike, "Volume spike (z-score)", weight=self.weights.get("volume", 0.0))
            scorer.add(macd_confirm_down, "MACD confirms", weight=self.weights.get("macd", 0.0))

            if vwap_price is not None:
                scorer.add((completed_close or 0.0) <= vwap_price + EPS, "Price <= VWAP", weight=self.weights.get("vwap", 0.0))
            if obv_trend_down is not None:
                scorer.add(obv_trend_down, "OBV trending down", weight=self.weights.get("obv", 0.0))

            signal, confidence, reasons = scorer.evaluate(direction="bearish")

        else:
            signal, confidence, reasons = "hold", 0.0, ["No strong MA crossover"]

        # Details for observability
        details: Dict[str, Any] = {
            "prev_ema": prev_ema, "curr_ema": curr_ema,
            "prev_sma": prev_sma, "curr_sma": curr_sma,
            "completed_close": completed_close, "latest_close": latest_close,
            "curr_rsi": curr_rsi,
            "atr_current": cur_atr, "atr_mean": atr_mean, "atr_expanding": atr_expanding,
            "volume": volume, "vol_zscore": round(vol_z, 2), "vol_window": vol_window, "vol_spike": vol_spike,
            "macd_up": macd_confirm_up, "macd_down": macd_confirm_down,
            "vwap": vwap_price, "obv_trend_up": obv_trend_up, "obv_trend_down": obv_trend_down,
            "confidence": round(confidence, 3),
        }

        return SignalModel(
            date=current_date,
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            confidence=round(confidence, 3),
            reason="; ".join(reasons),
            details=details
        )


# -------------------------
# Preset factory
# -------------------------
def make_ma_presets() -> Dict[str, Dict[str, Any]]:
    mid_balanced = {
        "ema_fast": 20,
        "sma_slow": 50,
        "rsi_period": 14,
        "atr_period": 14,
        "volume_window": 30,
        "volume_zscore_threshold": 1.5,
        "atr_expansion_ratio": 1.2,
        "confirmation_threshold": 0.58,
        "weights": {
            "ma_cross": 0.50,
            "atr": 0.18,
            "rsi": 0.12,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    mid_conservative = {
        "ema_fast": 30,
        "sma_slow": 100,
        "rsi_period": 14,
        "atr_period": 14,
        "volume_window": 40,
        "volume_zscore_threshold": 1.8,
        "atr_expansion_ratio": 1.2,
        "confirmation_threshold": 0.62,
        "weights": {
            "ma_cross": 0.55,
            "atr": 0.20,
            "rsi": 0.10,
            "volume": 0.08,
            "vwap": 0.03,
            "obv": 0.02,
            "macd": 0.02,
        },
    }

    mid_aggressive = {
        "ema_fast": 10,
        "sma_slow": 30,
        "rsi_period": 10,
        "atr_period": 10,
        "volume_window": 25,
        "volume_zscore_threshold": 1.2,
        "atr_expansion_ratio": 1.2,
        "confirmation_threshold": 0.54,
        "weights": {
            "ma_cross": 0.48,
            "atr": 0.20,
            "rsi": 0.12,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    short_quick = {
        "ema_fast": 5,
        "sma_slow": 15,
        "rsi_period": 7,
        "atr_period": 7,
        "volume_window": 15,
        "volume_zscore_threshold": 1.0,
        "atr_expansion_ratio": 1.2,
        "confirmation_threshold": 0.52,
        "weights": {
            "ma_cross": 0.50,
            "atr": 0.20,
            "rsi": 0.10,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    short_balanced = {
        "ema_fast": 8,
        "sma_slow": 20,
        "rsi_period": 10,
        "atr_period": 10,
        "volume_window": 20,
        "volume_zscore_threshold": 1.2,
        "atr_expansion_ratio": 1.2,
        "confirmation_threshold": 0.56,
        "weights": {
            "ma_cross": 0.52,
            "atr": 0.18,
            "rsi": 0.10,
            "volume": 0.10,
            "vwap": 0.05,
            "obv": 0.03,
            "macd": 0.02,
        },
    }

    short_conservative = {
        "ema_fast": 10,
        "sma_slow": 30,
        "rsi_period": 12,
        "atr_period": 10,
        "volume_window": 25,
        "volume_zscore_threshold": 1.4,
        "atr_expansion_ratio": 1.2,
        "confirmation_threshold": 0.60,
        "weights": {
            "ma_cross": 0.55,
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
