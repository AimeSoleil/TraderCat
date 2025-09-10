from abc import ABC, abstractmethod

class MarketDataProvider(ABC):
    @abstractmethod
    def get_price_data(self, symbol: str, interval: str, lookback: int):
        pass

    @abstractmethod
    def get_indicator(self, symbol: str, indicator: str, params: dict):
        pass
