from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.strategy.signal_scorer import SignalScorer

# BollingerBandStrategy implements a weighted Bollinger Bands trading strategy
# If the strategy feels too sensitive, raise structure from 0.40 to 0.50 and reduce momentum_mag to 0.03.
# If you want momentum-first behavior, increase rsi to 0.20 and momentum_mag to 0.08, keep structure at 0.35.
# If you enable MACD/ADX from your provider, wire their conditions into macd_cross_up/down and adx_strong, and their weights will contribute automatically.
class BollingerBandStrategy(TradingStrategy):
    def __init__(
        self,
        data_provider,
        bb_period=10,
        bb_std=2.0,
        rsi_period=7,
        volume_window=5,
        volume_spike_ratio=1.2,
        bw_median_window=20,
        atr_period=14,
        confirmation_threshold=0.55,
        weights=None,
    ):
        self.provider = data_provider
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.volume_window = volume_window
        self.volume_spike_ratio = volume_spike_ratio
        self.bw_median_window = bw_median_window
        self.atr_period = atr_period
        self.confirmation_threshold = confirmation_threshold

        # Strategy-defined default weights (can be overridden via constructor)
        self.weights = weights or {
            "structure": 0.40,  # band breach / re-entry trigger
            "macd": 0.20,  # MACD crossover / histogram (optional)
            "rsi": 0.15,  # RSI extreme / momentum filter
            "volume": 0.12,  # volume spike catalyst
            "adx": 0.08,  # ADX trend strength (optional)
            "momentum_mag": 0.05,  # %b magnitude / band distance partial credit
        }

    def get_name(self) -> str:
        return "Bollinger Bands"

    def get_lookback_window(self) -> int:
        return max(
            50,
            self.bb_period
            + self.bw_median_window
            + self.volume_window
            + self.atr_period,
        )

    def generate_signal(self, symbol: str, candles: list) -> SignalModel:
        print(f"Strategy[{self.get_name()}] generating signal for {symbol}...")
        signal, confidence, details = "hold", 0.0, {}
        current_close_date = candles[-1].date if candles else None

        if not self.provider or len(candles) < self.get_lookback_window():
            return SignalModel(
                date=current_close_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal=signal,
                confidence=confidence,
                reason="Insufficient data",
                details=details,
            )

        # Indicators
        bb = self.provider.get_indicator(
            "bbands", candles, {"length": self.bb_period, "std": self.bb_std}
        )
        rsi = self.provider.get_indicator("rsi", candles, {"length": self.rsi_period})
        atr = self.provider.get_indicator("atr", candles, {"length": self.atr_period})

        if not all([bb, rsi, atr]):
            return SignalModel(
                date=current_close_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal=signal,
                confidence=confidence,
                reason="Indicator data unavailable",
                details=details,
            )

        cur = candles[-1]
        prev = candles[-2]
        close = cur.close
        volume = cur.volume

        bb_last = bb[-1]
        ma = getattr(bb_last, f"close_BBM_{self.bb_period}_{self.bb_std}", None)
        bbu = getattr(bb_last, f"close_BBU_{self.bb_period}_{self.bb_std}", None)
        bbl = getattr(bb_last, f"close_BBL_{self.bb_period}_{self.bb_std}", None)
        if not all([ma, bbu, bbl]):
            return SignalModel(
                date=current_close_date,
                symbol=symbol,
                strategy=self.get_name(),
                signal=signal,
                confidence=confidence,
                reason="BB fields missing",
                details=details,
            )

        # Derived: %b and Bandwidth
        band_width = bbu - bbl
        pct_b = (close - bbl) / band_width if band_width > 0 else 0.5
        bw = band_width / ma if ma else 0

        # Median BW (squeeze/expansion reference)
        recent_bb = bb[-self.bw_median_window :]
        recent_bw = []
        for x in recent_bb:
            up = getattr(x, f"close_BBU_{self.bb_period}_{self.bb_std}", 0)
            lo = getattr(x, f"close_BBL_{self.bb_period}_{self.bb_std}", 0)
            m = getattr(x, f"close_BBM_{self.bb_period}_{self.bb_std}", 0)
            recent_bw.append((up - lo) / m if m else 0)
        bw_median = sorted(recent_bw)[len(recent_bw) // 2] if recent_bw else 0

        # RSI and ATR
        cur_rsi = getattr(rsi[-1], f"close_RSI_{self.rsi_period}", None)
        cur_atr = getattr(atr[-1], f"ATRr_{self.atr_period}", None)
        atr_series = [
            getattr(x, f"ATRr_{self.atr_period}", 0)
            for x in atr[-self.bw_median_window :]
        ]
        atr_median = sorted(atr_series)[len(atr_series) // 2] if atr_series else 0

        # Volume spike
        vols = [c.volume for c in candles[-self.volume_window - 1 :]]
        avg_vol = (
            (sum(vols[:-1]) / self.volume_window) if self.volume_window > 0 else volume
        )
        vol_spike = volume > avg_vol * self.volume_spike_ratio

        # Optional placeholders (uncomment if provider supports)
        # macd = self.provider.get_indicator("macd", candles, {"fast": 12, "slow": 26, "signal": 9})
        # adx = self.provider.get_indicator("adx", candles, {"length": 14})
        macd_cross_up = False
        macd_cross_down = False
        adx_strong = False

        # Regimes
        breakout_up = (
            (close > bbu)
            and (bw > bw_median)
            and (cur_rsi is not None and cur_rsi > 55)
            and (cur_atr > atr_median)
        )
        breakout_dn = (
            (close < bbl)
            and (bw > bw_median)
            and (cur_rsi is not None and cur_rsi < 45)
            and (cur_atr > atr_median)
        )
        reversion_up = (
            (pct_b < 0)
            and (cur_rsi is not None and cur_rsi < 30)
            and (prev.close < bbl)
            and (close >= bbl)
            and (bw <= bw_median)
        )
        reversion_dn = (
            (pct_b > 1)
            and (cur_rsi is not None and cur_rsi > 70)
            and (prev.close > bbu)
            and (close <= bbu)
            and (bw <= bw_median)
        )

        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)

        # Breakout scoring (bullish)
        if close > bbu:
            scorer.add(
                True, "Breakout: Close > upper band", weight=self.weights["structure"]
            )
            scorer.add(
                bw > bw_median,
                "Bandwidth expansion",
                weight=self.weights["momentum_mag"],
            )
            scorer.add(
                cur_rsi is not None and cur_rsi > 55,
                "RSI momentum > 55",
                weight=self.weights["rsi"],
            )
            scorer.add(
                cur_atr > atr_median,
                "ATR above median",
                weight=self.weights["momentum_mag"],
            )
            scorer.add(
                vol_spike, "Volume spike catalyst", weight=self.weights["volume"]
            )
            # Optional extras
            scorer.add(
                macd_cross_up, "MACD bullish crossover", weight=self.weights["macd"]
            )
            scorer.add(adx_strong, "ADX strong trend", weight=self.weights["adx"])
            signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Breakout scoring (bearish)
        elif close < bbl:
            scorer.add(
                True, "Breakdown: Close < lower band", weight=self.weights["structure"]
            )
            scorer.add(
                bw > bw_median,
                "Bandwidth expansion",
                weight=self.weights["momentum_mag"],
            )
            scorer.add(
                cur_rsi is not None and cur_rsi < 45,
                "RSI momentum < 45",
                weight=self.weights["rsi"],
            )
            scorer.add(
                cur_atr > atr_median,
                "ATR above median",
                weight=self.weights["momentum_mag"],
            )
            scorer.add(
                vol_spike, "Volume spike catalyst", weight=self.weights["volume"]
            )
            # Optional extras
            scorer.add(
                macd_cross_down, "MACD bearish crossover", weight=self.weights["macd"]
            )
            scorer.add(adx_strong, "ADX strong trend", weight=self.weights["adx"])
            signal, confidence, reasons = scorer.evaluate(direction="bearish")

        # Mean reversion scoring (bullish fade)
        elif prev.close < bbl and close >= bbl:
            scorer.add(
                True,
                "Reversion up: Re-entry above lower band",
                weight=self.weights["structure"],
            )
            scorer.add(
                cur_rsi is not None and cur_rsi < 30,
                "RSI < 30",
                weight=self.weights["rsi"],
            )
            scorer.add(
                bw <= bw_median,
                "No expansion (safe to fade)",
                weight=self.weights["momentum_mag"],
            )
            scorer.add(
                pct_b < 0, "Extreme %b (<0)", weight=self.weights["momentum_mag"]
            )
            scorer.add(
                vol_spike, "Volume spike catalyst", weight=self.weights["volume"]
            )
            signal, confidence, reasons = scorer.evaluate(direction="bullish")

        # Mean reversion scoring (bearish fade)
        elif prev.close > bbu and close <= bbu:
            scorer.add(
                True,
                "Reversion down: Re-entry below upper band",
                weight=self.weights["structure"],
            )
            scorer.add(
                cur_rsi is not None and cur_rsi > 70,
                "RSI > 70",
                weight=self.weights["rsi"],
            )
            scorer.add(
                bw <= bw_median,
                "No expansion (safe to fade)",
                weight=self.weights["momentum_mag"],
            )
            scorer.add(
                pct_b > 1, "Extreme %b (>1)", weight=self.weights["momentum_mag"]
            )
            scorer.add(
                vol_spike, "Volume spike catalyst", weight=self.weights["volume"]
            )
            signal, confidence, reasons = scorer.evaluate(direction="bearish")

        else:
            signal, confidence, reasons = "hold", 0.0, ["No strong signal"]

        details = {
            "close": close,
            "ma": ma,
            "bb_upper": bbu,
            "bb_lower": bbl,
            "pct_b": pct_b,
            "bw": bw,
            "bw_median": bw_median,
            "rsi": cur_rsi,
            "atr": cur_atr,
            "atr_median": atr_median,
            "volume": volume,
            "avg_volume": avg_vol,
            "confidence": confidence,
        }

        return SignalModel(
            date=current_close_date,
            symbol=symbol,
            strategy=self.get_name(),
            signal=signal,
            confidence=confidence,
            reason="; ".join(reasons),
            details=details,
        )
