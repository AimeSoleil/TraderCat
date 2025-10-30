from datetime import datetime
from trade_bot.strategy.signal_model import SignalModel

class TradeTracker:
    def __init__(self, symbol, initial_cash=100000):
        self.symbol = symbol
        self.cash = initial_cash
        self.position = 0
        self.entry_price = 0
        self.trades = []
        self.portfolio_values = []

    def execute(self, signal_mode: SignalModel, price: float, index: int):
        action = signal_mode.signal.lower()

        if action == "buy" or action == "sell":
            print(f"*********** [{signal_mode.date}] Executing signal: {action} at price {price} for symbol {self.symbol}:")
            print(f"*********** Reason: {signal_mode.reason}, Confidence: {signal_mode.confidence}, Details: {signal_mode.details}\n")

        if action == "buy":
            trade_position = self.cash // price
            if trade_position == 0:
                # Mark a buy action but with zero shares due to insufficient cash
                self.trades.append({
                    "date": signal_mode.date.strftime("%Y-%m-%d"),
                    "symbol": self.symbol,
                    "type": "buy",
                    "price": price,
                    "index": index,
                    "shares": 0, # which means no shares bought
                    "note": "No cash",
                    "cash_after": self.cash
                })
            else:
                self.entry_price = price
                self.position += trade_position
                self.cash -= trade_position * price
                self.trades.append({
                    "date": signal_mode.date.strftime("%Y-%m-%d"),
                    "symbol": self.symbol,
                    "type": "buy",
                    "price": price,
                    "index": index,
                    "shares": self.position,
                    "cash_after": self.cash
                })

        elif action == "sell":
            if self.position == 0:
                self.trades.append({
                    "date": signal_mode.date.strftime("%Y-%m-%d"),
                    "symbol": self.symbol,
                    "type": "sell",
                    "price": price,
                    "index": index,
                    "shares": 0, # which means no position
                    "entry_price": self.entry_price,
                    "profit": 0,
                    "note": "No pos",
                    "cash_after": self.cash
                })
            else:
                self.cash += self.position * price
                profit = (price - self.entry_price) * self.position
                self.trades.append({
                    "date": signal_mode.date.strftime("%Y-%m-%d"),
                    "symbol": self.symbol,
                    "type": "sell",
                    "price": price,
                    "index": index,
                    "shares": self.position,
                    "entry_price": self.entry_price,
                    "profit": profit,
                    "cash_after": self.cash
                })
                self.position = 0

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
                "Symbol": trade.get("symbol", "N/A"),
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
