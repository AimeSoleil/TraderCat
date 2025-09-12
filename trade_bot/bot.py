from trade_bot.strategy.signal_model import SignalModel

class TradeBot:
    def __init__(self, data_provider, strategies, executor, symbol):
        self.data_provider = data_provider
        self.strategies = strategies  # List of strategy instances
        self.executor = executor
        self.symbol = symbol

    async def run(self):
        print(f'Running bot for symbol: {self.symbol} with strategies: {[s.get_name() for s in self.strategies]}')
        data = self.data_provider.get_price_data(self.symbol, interval="1d", lookback=30)
        print(f"Fetched {len(data)} data points for {self.symbol}: {data[-1] if data else 'No data'}")

        signals = [strategy.generate_signal(self.symbol, data) for strategy in self.strategies]
        final_signal_list = self.aggregate_signals(signals)

        self.executor.execute_trade(final_signal_list, self.symbol)

        yield final_signal_list
        
        # today_str = date.today().strftime("%Y-%m-%d")
        # new_data = [signal.model_dump() for signal in final_signal_list]
        # print(f'Signal for symbol: {self.symbol}', json.dumps(new_data, indent=4))
        # for row in new_data:
        #     if isinstance(row["details"], dict):
        #         row["details"] = " ".join([f"{k}:{v}\n" for k, v in row["details"].items()])

        # markdown_table_message = tabulate(new_data, headers="keys", tablefmt="mixed_grid", maxcolwidths=30)
        # message = f""":bangbang: :bell: ** [{today_str}] `{self.symbol}` Trade signals** :rocket: :rocket: :rocket:\n```{markdown_table_message}``` \n"""
        # await self.send_notification(message)

    def aggregate_signals(self, signals: list[SignalModel]) -> list[SignalModel]:
        # Reserve logic for future improvements
        return signals