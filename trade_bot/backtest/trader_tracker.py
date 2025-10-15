from trade_bot.strategy.signal_model import SignalModel

class TradeTracker:
    def __init__(self, symbol, initial_cash=100000):
        self.symbol = symbol
        self.cash = initial_cash
        self.position = 0
        self.entry_price = None
        self.trades = []
        self.portfolio_values = []

    def execute(self, signal_mode: SignalModel, price: float, index: int):
        action = signal_mode.signal.lower()

        if action == "buy" and self.position == 0:
            self.position = self.cash // price
            self.entry_price = price
            self.cash -= self.position * price
            self.trades.append({
                "date": signal_mode.date,
                "type": "buy",
                "price": price,
                "index": index,
                "shares": self.position,
                "cash_after": self.cash
            })

        elif action == "sell" and self.position > 0:
            self.cash += self.position * price
            profit = (price - self.entry_price) * self.position
            self.trades.append({
                "date": signal_mode.date,
                "type": "sell",
                "price": price,
                "index": index,
                "shares": self.position,
                "entry_price": self.entry_price,
                "profit": profit,
                "cash_after": self.cash
            })
            self.position = 0
            self.entry_price = None

    def record_portfolio(self, price):
        value = self.cash + (self.position * price if self.position > 0 else 0)
        self.portfolio_values.append(value)

    def get_trade_table(self):
        """
        Returns a list of trade records suitable for tabular display.
        Each record includes: index, type, price, shares, profit (if applicable), cash_after.
        """
        table = []
        for trade in self.trades:
            row = {
                "Index": trade.get("index"),
                "Date": trade.get("date", "N/A"),
                "Type": trade.get("type").upper(),
                "Price": round(trade.get("price", 0), 2),
                "Shares": trade.get("shares", 0),
                "Entry Price": round(trade.get("entry_price", 0), 2) if "entry_price" in trade else "",
                "Profit": round(trade.get("profit", 0), 2) if "profit" in trade else "",
                "Cash After": round(trade.get("cash_after", 0), 2) if "cash_after" in trade else trade.get("cash", ""),
                "Note": trade.get("note", "")
            }
            table.append(row)
        return table
