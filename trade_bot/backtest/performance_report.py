from trade_bot.backtest.trader_tracker import TradeTracker

class PerformanceReport:
    def __init__(self, tracker: TradeTracker, initial_cash=100000):
        self.tracker = tracker
        self.initial_cash = initial_cash

    def generate(self):
        trades = self.tracker.trades
        # Filter only completed sell trades with shares > 0
        profits = [t["profit"] or 0 for t in trades if t["type"] == "sell" and t["shares"] > 0]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]

        return {
            "init_value": self.initial_cash,
            "final_value": self.tracker.portfolio_values[-1],
            "net_profit": self.tracker.portfolio_values[-1] - self.initial_cash,
            "num_trades": len(trades),
            "win_rate": round(len(wins) / len(profits), 2) if profits else 0,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "max_drawdown": self._max_drawdown(),
            "trade_hist": trades
        }

    def _max_drawdown(self):
        peak = self.initial_cash
        max_dd = 0
        for value in self.tracker.portfolio_values:
            if value > peak:
                peak = value
            dd = peak - value
            if dd > max_dd:
                max_dd = dd
        return round(max_dd, 2)