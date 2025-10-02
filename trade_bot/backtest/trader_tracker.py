class TradeTracker:
    def __init__(self, initial_cash=100000):
        self.cash = initial_cash
        self.position = 0
        self.entry_price = None
        self.trades = []
        self.portfolio_values = []

    def execute(self, symbol, signal, price, index):
        if signal == "buy" and self.position == 0:
            self.position = self.cash // price
            self.entry_price = price
            self.cash -= self.position * price
            self.trades.append({"type": "buy", "price": price, "index": index})
            print(f'Backtest: Buy {symbol} at price {price}, position at {self.position}, cash at {self.cash}')

        elif signal == "sell" and self.position > 0:
            self.cash += self.position * price
            profit = (price - self.entry_price) * self.position
            self.trades.append({
                "type": "sell",
                "price": price,
                "index": index,
                "profit": profit
            })
            self.position = 0
            self.entry_price = None
            print(f'Sell {symbol} at price {price}, position at {self.position}, cash at {self.cash}')

    def record_portfolio(self, price):
        value = self.cash + (self.position * price if self.position > 0 else 0)
        self.portfolio_values.append(value)