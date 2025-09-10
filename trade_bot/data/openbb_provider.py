from openbb import obb
from trade_bot.data.market_data_provider import MarketDataProvider

# Set your Tiingo API key
# obb.user.credentials.tiingo_token = "89b5edcdaafcfe5c36ecf4b637b90b6312cb0a5d"

class OpenBBProvider(MarketDataProvider):
    def get_price_data(self, symbol: str, interval: str, lookback: int):
        #df = obb.equity.price.historical(symbol=symbol, interval=interval, period=f"{lookback}d", provider="tiingo")
        df = obb.equity.price.historical(symbol=symbol, interval=interval, period=f"{lookback}d")
        return df.results # list[EquityPrice]

    # For indicators, please refer to https://docs.openbb.co/platform/reference/technical
    def get_indicator(self, indicator: str, data: list, params: dict):
        func = getattr(obb.technical, indicator)
        return func(data = data, **params).results