from typing import Optional, Tuple, Dict, Any
import datetime
from openbb import obb
from trade_bot.strategy.trading_strategy import TradingStrategy
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.strategy.signal_scorer import SignalScorer

# Incomplete - Intraday option trading strategy
class IntradayOptionStrategy(TradingStrategy):
    def __init__(
        self,
        data_provider,
        exec_interval="5m",
        htf_interval="15m",
        exec_lookback=150,
        htf_lookback=150,
        rsi_fast=7,
        rsi_slow=14,
        macd_fast=(8, 21, 5),
        macd_slow=(12, 26, 9),
        atr_period=5,
        ema_fast=9,
        ema_slow=21,
        volume_multiplier=1.3,
        confirmation_threshold=0.65
    ):
        self.provider = data_provider
        self.exec_interval = exec_interval
        self.htf_interval = htf_interval
        self.exec_lookback = exec_lookback
        self.htf_lookback = htf_lookback
        self.rsi_fast = rsi_fast
        self.rsi_slow = rsi_slow
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.atr_period = atr_period
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.volume_multiplier = volume_multiplier
        self.confirmation_threshold = confirmation_threshold

    def get_name(self) -> str:
        return "QQQIntradayOption"

    def get_lookback_window(self) -> int:
        return max(self.exec_lookback, self.htf_lookback)

    # ---------------------------
    # Option chain fetch via OpenBB
    # ---------------------------
    def _fetch_option_context(self, symbol: str) -> Dict[str, Any]:
        try:
            chain = self.provide.get_option_chains(symbol, datetime.date.today())
            iv_hist = obb.equity.options.iv(symbol)

            # Compute IV rank
            current_iv = iv_hist["iv"].iloc[-1]
            iv_rank = 100 * (current_iv - iv_hist["iv"].min()) / (iv_hist["iv"].max() - iv_hist["iv"].min())

            today = datetime.date.today()
            same_day_available = any(exp.date() == today for exp in chain.expirations)

            return {
                "iv_rank": iv_rank,
                "same_day_available": same_day_available,
                "expirations": chain.expirations,
                "calls": chain.calls,
                "puts": chain.puts
            }
        except Exception as e:
            print(f"Option chain fetch failed: {e}")
            return {
                "iv_rank": None,
                "same_day_available": False,
                "expirations": [],
                "calls": None,
                "puts": None
            }

    # ---------------------------
    # Option plan (no sizing)
    # ---------------------------
    def _build_option_plan(self, direction: str, cur, strong_trend: bool,
                           iv_rank: Optional[float] = None,
                           same_day_available: bool = True,
                           event_today: bool = False) -> Dict[str, Any]:
        strike_choice = "OTM (Δ ~0.40)" if strong_trend else "ATM (Δ ~0.50)"
        dt = getattr(cur, "time", None)
        hour = getattr(dt, "hour", 10) if dt else 10
        dte_choice = 0 if same_day_available and hour < 14 else 1
        if iv_rank is None or iv_rank < 40:
            structure = "single debit option"
        else:
            structure = "vertical spread (bull call / bear put)"
        size_factor = 0.5 if event_today else 1.0
        return {
            "type": "call" if direction == "bullish" else "put",
            "strike": strike_choice,
            "dte": dte_choice,
            "structure": structure,
            "risk": "30% premium stop or VWAP/OR invalidation",
            "target": "Scale 50% at +40–50%, trail via 5m EMA9",
            "size_factor": size_factor,
            "iv_rank": iv_rank
        }

    # ---------------------------
    # Main signal
    # ---------------------------
    def generate_signal(self, symbol: str) -> SignalModel:
        print(f"[{self.get_name()}] Generating signal for {symbol}")

        # Fetch option context
        option_ctx = self._fetch_option_context(symbol)

        # Fetch execution candles
        exec_data = self.provider.get_candles(symbol, interval=self.exec_interval, lookback=self.exec_lookback)
        if not exec_data or len(exec_data) < 50:
            return SignalModel(symbol, self.get_name(), "hold", "Insufficient candles", {}, 0.0)

        cur = exec_data[-1]
        avg_vol = sum(c.volume for c in exec_data[-20:]) / 20

        # Example: simple bullish/bearish bias
        avg_price = sum(c.close for c in exec_data[-20:]) / 20
        bullish = cur.close > avg_price and cur.volume > avg_vol * self.volume_multiplier
        bearish = cur.close < avg_price and cur.volume > avg_vol * self.volume_multiplier

        scorer = SignalScorer(threshold_percent=self.confirmation_threshold)
        opt_action = None
        signal, confidence, reasons = "hold", 0.0, ["No setup"]

        if bullish:
            scorer.add(True, "Price > 20-bar avg and volume spike")
            signal, confidence, reasons = scorer.evaluate(direction="bullish")
            opt_action = self._build_option_plan("bullish", cur,
                                                 strong_trend=True,
                                                 iv_rank=option_ctx["iv_rank"],
                                                 same_day_available=option_ctx["same_day_available"])
        elif bearish:
            scorer.add(True, "Price < 20-bar avg and volume spike")
            signal, confidence, reasons = scorer.evaluate(direction="bearish")
            opt_action = self._build_option_plan("bearish", cur,
                                                 strong_trend=True,
                                                 iv_rank=option_ctx["iv_rank"],
                                                 same_day_available=option_ctx["same_day_available"])

        details = {
            "price": cur.close,
            "volume": cur.volume,
            "avg_volume": avg_vol,
            "option_plan": opt_action,
            "confidence": confidence
        }

        return SignalModel(symbol, self.get_name(), signal, "; ".join(reasons), details, confidence)
