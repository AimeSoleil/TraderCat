from datetime import datetime
import pandas as pd
from tradercat.logger import get_logger
from tradercat.core.strategy.signal_model import SignalModel

logger = get_logger(__name__)

class TradeTracker:
    def __init__(self, symbol, initial_cash=100000, commission_rate=0.001):
        self.symbol = symbol
        self.cash = initial_cash
        self.position = 0
        self.avg_entry_price = 0.0 # Track average cost basis
        self.trades = []
        self.portfolio_values = []
        self.commission_rate = commission_rate # e.g., 0.1% per trade

    def execute(self, signal_model: SignalModel, price: float, index: int):
        action = signal_model.signal.lower()

        # Handle date formatting safely
        date_str = signal_model.date
        if isinstance(date_str, (datetime, pd.Timestamp)):
            date_str = date_str.strftime("%Y-%m-%d")

        logger.info(f"[{date_str}]: Get signal for {self.symbol} at price {price}: {signal_model}\n")

        # --- BUY LOGIC ---
        if action == "buy":
            # Position Sizing: Currently defaults to 95% of cash to leave room for fees/slippage
            # In future, pass 'size' in SignalModel
            invest_amount = self.cash * 0.95 
            shares_to_buy = int(invest_amount // price)

            if shares_to_buy > 0:
                cost = shares_to_buy * price
                commission = cost * self.commission_rate
                total_cost = cost + commission

                if self.cash >= total_cost:
                    # Update Average Entry Price
                    current_value = self.position * self.avg_entry_price
                    new_value = shares_to_buy * price
                    self.avg_entry_price = (current_value + new_value) / (self.position + shares_to_buy)

                    self.cash -= total_cost
                    self.position += shares_to_buy
                    
                    self._log_trade(date_str, "buy", price, shares_to_buy, index, commission=commission)
                else:
                    self._log_trade(date_str, "buy", price, 0, index, note="Insufficient Cash")
            else:
                self._log_trade(date_str, "buy", price, 0, index, note="Low Cash")

        # --- SELL LOGIC ---
        elif action == "sell":
            if self.position > 0:
                # Default to selling ALL shares
                shares_to_sell = self.position
                
                proceeds = shares_to_sell * price
                commission = proceeds * self.commission_rate
                net_proceeds = proceeds - commission
                
                # Calculate Profit based on Average Entry Price
                gross_profit = (price - self.avg_entry_price) * shares_to_sell
                net_profit = gross_profit - commission # Subtract exit commission

                self.cash += net_proceeds
                self.position -= shares_to_sell # Should be 0 if selling all
                
                if self.position == 0:
                    self.avg_entry_price = 0 # Reset if flat

                self._log_trade(
                    date_str, "sell", price, shares_to_sell, index, 
                    profit=net_profit, 
                    entry_price=self.avg_entry_price,
                    commission=commission
                )
            else:
                self._log_trade(date_str, "sell", price, 0, index, note="No Position")

    def _log_trade(self, date, type_, price, shares, index, profit=0, entry_price=0, commission=0, note=""):
        """Helper to append trade record."""
        self.trades.append({
            "date": date,
            "symbol": self.symbol,
            "type": type_,
            "price": price,
            "index": index,
            "shares": shares,
            "entry_price": entry_price,
            "profit": profit,
            "commission": commission,
            "cash_after": self.cash,
            "note": note
        })
        
        if shares > 0:
            logger.info(f"[{date}] {type_.upper()} {self.symbol}: {shares} @ {price:.2f} | Cash: {self.cash:.2f}")

    def record_portfolio(self, price):
        # Mark-to-Market Value
        market_value = self.position * price
        total_equity = self.cash + market_value
        self.portfolio_values.append(total_equity)
