from datetime import date
from openbb import obb
from trade_bot import logger
from trade_bot.data.market_data_provider import MarketDataProvider
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

# Set your Tiingo API key
# obb.user.credentials.tiingo_token = "your_tiingo_api_token"

class OpenBBProvider(MarketDataProvider):
    def get_price_data(self, symbol: str, interval: str, lookback: int):
        #df = obb.equity.price.historical(symbol=symbol, interval=interval, period=f"{lookback}d", provider="tiingo")
        df = obb.equity.price.historical(symbol=symbol, interval=interval, period=f"{lookback}d")
        return df.results # list[EquityPrice]

    # For indicators, please refer to https://docs.openbb.co/platform/reference/technical
    def get_indicator(self, indicator: str, data: list, params: dict):
        func = getattr(obb.technical, indicator)
        try:
            return func(data = data, **params).results
        except Exception as e:
            logger.info(f"Error fetching indicator {indicator} with params {params}: {e}")
            return None

    # https://docs.openbb.co/platform/reference/derivatives/options/chains
    def get_option_chains(self, symbol, end_of_day: date):
        df = obb.derivatives.options.chains(symbol=symbol, date=end_of_day)
        return df.results.implied_volatility