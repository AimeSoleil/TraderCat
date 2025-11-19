from abc import ABC, abstractmethod
from typing import Dict

from trade_bot.strategy.signal_model import SignalModel

EPS = 1e-9

class TradingStrategy(ABC):

    @abstractmethod
    def generate_signal(self, symbol: str = None, candles: dict = None) -> SignalModel:
        """
        Returns a dict: { "strategy": name, "signal": 'buy'|'sell'|'hold', "details": {...} }
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """
        Returns strategy name
        """
        pass

    @abstractmethod
    def get_lookback_window(self) -> int:
        """
        Returns minimum length of candle window
        """
        pass
