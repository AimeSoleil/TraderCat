from typing import Any, Dict, List, Literal, Optional

class ExitPlanner:
    def __init__(
            self,
            highs: List[float],
            lows: List[float],
            atr: float,
            atr_period: Optional[int] = 14,
            close_price: Optional[float ]= None,
            atr_mult: float = 3.0,
            atr_tp_mult: float = 2.0,        # Default ATR-based TP multiplier
            fib_stop_ratio: float = 0.236,   # Default for stop-loss
            fib_tp_ratio: float = 0.618,     # Default for take-profit
    ):
        """
        Initialize ExitPlanner with ATR multiplier, Fibonacci ratios, and ATR-based TP multiplier.
        """
        self.highs = highs
        self.lows = lows
        self.atr = atr
        self.atr_period = atr_period
        self.close_price = close_price
        self.atr_mult = atr_mult
        self.fib_stop_ratio = fib_stop_ratio
        self.fib_tp_ratio = fib_tp_ratio
        self.atr_tp_mult = atr_tp_mult

    def make_exit_plan(self, trading_signal: Literal['buy', 'sell']) -> Dict[str, Any]:
        """
        Create exit plan combining Chandelier Exit, Fibonacci stop, and take-profit levels.
        """
        plan = {
            "atr": self.atr,
            "atr_period": self.atr_period,
            "atr_mult": self.atr_mult,
            "fib_stop_ratio": self.fib_stop_ratio,
            "fib_tp_ratio": self.fib_tp_ratio,
            "atr_tp_mult": self.atr_tp_mult,
        }
        signal = trading_signal

        if self.atr is None or not self.highs or not self.lows:
            return plan

        # Slice highs and lows based on lookback
        lookback = self.atr_period
        highs_slice = self.highs[-lookback:] if len(self.highs) >= lookback else self.highs
        lows_slice = self.lows[-lookback:] if len(self.lows) >= lookback else self.lows

        highest_high = max(highs_slice)
        lowest_low = min(lows_slice)

        # --- Stop Loss Calculation ---
        if self.fib_stop_ratio is not None and self.close_price is not None:
            if signal == "buy":
                stop_fib_level = lowest_low + (highest_high - lowest_low) * self.fib_stop_ratio
            else:
                stop_fib_level = highest_high - (highest_high - lowest_low) * self.fib_stop_ratio
            plan["fib_stop_loss_at"] = stop_fib_level

        # Chandelier stop
        if signal == "buy":
            chandelier_stop = highest_high - self.atr_mult * self.atr
        else:
            chandelier_stop = lowest_low + self.atr_mult * self.atr
        plan["chandelier_stop_loss_at"] = chandelier_stop

        # --- Take Profit Calculation ---
        tp_levels = {}

        # ATR-based TP
        if self.atr_tp_mult is not None and self.close_price is not None:
            if signal == "buy":
                tp_levels["atr_tp"] = self.close_price + self.atr_tp_mult * self.atr
            else:
                tp_levels["atr_tp"] = self.close_price - self.atr_tp_mult * self.atr

        # Fibonacci-based TP
        if self.fib_tp_ratio is not None and self.close_price is not None:
            if signal == "buy":
                tp_levels["fib_tp"] = lowest_low + (highest_high - lowest_low) * self.fib_tp_ratio
            else:
                tp_levels["fib_tp"] = highest_high - (highest_high - lowest_low) * self.fib_tp_ratio

        if tp_levels:
            plan["take_profit_levels"] = tp_levels

        return plan