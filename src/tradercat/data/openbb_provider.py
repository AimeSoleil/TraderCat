from datetime import date
import os
import traceback
from openbb import obb
from tradercat.data.market_data_provider import MarketDataProvider
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

# Set your Tiingo API key: https://docs.openbb.co/odp/python/settings/user_settings/api_keys
data_provider = "yfinance" # default to yahoo
if os.environ.get("TIINGO_API_KEY"):
    obb.user.credentials.tiingo_token = os.environ.get("TIINGO_API_KEY")
    data_provider = "tiingo"

class OpenBBProvider(MarketDataProvider):
    def get_price_data(self, symbol: str, interval: str, lookback: int):
        df = obb.equity.price.historical(symbol=symbol, interval=interval, period=f"{lookback}d", provider=data_provider)
        return df.results # list[EquityPrice]

    def get_price_data_by_range(self, symbol: str, start_date: str, end_date: str, interval: str='1d'):
        df = obb.equity.price.historical(symbol=symbol, start_date=start_date, end_date=end_date, interval=interval)
        return df.results # list[EquityPrice]

    # For indicators, please refer to https://docs.openbb.co/platform/reference/technical
    def get_indicator(self, indicator: str, data: list, params: dict):
        func = getattr(obb.technical, indicator)
        try:
            return func(data = data, **params).results
        except Exception as e:
            logger.info(f"Error fetching indicator {indicator} with params {params}: {traceback.format_exc()}")
            return None

    # https://docs.openbb.co/platform/reference/derivatives/options/chains
    def get_option_chains(self, symbol, end_of_day: date):
        df = obb.derivatives.options.chains(symbol=symbol, date=end_of_day)
        return df.results.implied_volatility