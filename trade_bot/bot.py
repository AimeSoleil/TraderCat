import asyncio
from datetime import date
from tabulate import tabulate

from trade_bot.strategy.signal_model import SignalModel

class TradeBot:
    def __init__(self, data_provider, strategies, executor, notifiers, symbol):
        self.data_provider = data_provider
        self.strategies = strategies  # List of strategy instances
        self.executor = executor
        self.notifiers = notifiers
        self.symbol = symbol

    async def run(self):
        print(f'Running bot for symbol: {self.symbol} with strategies: {[s.get_name() for s in self.strategies]}')
        data = self.data_provider.get_price_data(self.symbol, interval="1d", lookback=30)

        signals = [strategy.generate_signal(data) for strategy in self.strategies]
        final_signal_list = self.aggregate_signals(signals)

        # Will implement actual trade execution logic in the future
        self.executor.execute_trade(final_signal_list, self.symbol)

        today_str = date.today().strftime("%Y-%m-%d")

        # 不要修改 item.details 的类型，直接序列化
        new_data = [signal.model_dump() for signal in final_signal_list]
        # 如果想让 details 字段在表格中更美观，可以在渲染时格式化
        for row in new_data:
            if isinstance(row["details"], dict):
                row["details"] = " ".join([f"{k}->{v}" for k, v in row["details"].items()])

        markdown_table_message = tabulate(new_data, headers="keys", tablefmt="mixed_grid", maxcolwidths=30)
        message = f""":bangbang: :bell: ** [{today_str}] `{self.symbol}` Trade signals** :rocket: :rocket: :rocket:\n```{markdown_table_message}``` \n"""
        print(message)
        await asyncio.gather(*(notifier.send(message) for notifier in self.notifiers))

    def aggregate_signals(self, signals: list[SignalModel]) -> list[SignalModel]:
        # Reserve logic for future improvements
        return signals