from abc import ABC, abstractmethod

from trade_bot.strategy.signal_model import SignalModel

class TradingStrategy(ABC):
    @abstractmethod
    def generate_signal(self, symbol: str, candles: dict) -> SignalModel:
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
