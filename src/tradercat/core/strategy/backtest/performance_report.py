import numpy as np
import pandas as pd
from typing import Dict, Any
from tradercat.core.strategy.backtest.trader_tracker import TradeTracker

class PerformanceReport:
    """
    Generates professional-grade performance metrics for a backtest.
    """
    def __init__(self, tracker: TradeTracker):
        self.tracker = tracker
        # Use the initial cash from the tracker's history (first point)
        self.initial_cash = tracker.portfolio_values[0] if tracker.portfolio_values else 100000

    def generate(self) -> Dict[str, Any]:
        trades = self.tracker.trades
        equity_curve = pd.Series(self.tracker.portfolio_values)
        
        if equity_curve.empty:
            return self._empty_report()

        final_value = equity_curve.iloc[-1]
        net_profit = final_value - self.initial_cash
        total_return_pct = (net_profit / self.initial_cash) * 100

        # 1. Trade Analysis
        # Filter completed trades (sells)
        completed_trades = [t for t in trades if t["type"] == "sell"]
        profits = [t.get("profit", 0) for t in completed_trades]
        
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        
        num_trades = len(completed_trades)
        num_wins = len(wins)
        num_losses = len(losses)
        
        win_rate = (num_wins / num_trades * 100) if num_trades > 0 else 0
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        
        # Profit Factor (Gross Win / Gross Loss)
        total_won = sum(wins)
        total_lost = abs(sum(losses))
        profit_factor = (total_won / total_lost) if total_lost > 0 else float('inf')

        # 2. Risk Metrics
        max_dd_pct = self._calculate_max_drawdown_pct(equity_curve)
        sharpe_ratio = self._calculate_sharpe_ratio(equity_curve)
        sortino_ratio = self._calculate_sortino_ratio(equity_curve)

        return {
            # --- General ---
            "init_value": self.initial_cash,
            "final_value": round(final_value, 2),
            "net_profit": round(net_profit, 2),
            "return_pct": round(total_return_pct, 2),
            
            # --- Trade Stats ---
            "num_trades": num_trades,
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            
            # --- Risk Stats ---
            "max_drawdown": round(max_dd_pct, 2), # Now in Percentage
            "sharpe_ratio": round(sharpe_ratio, 2),
            "sortino_ratio": round(sortino_ratio, 2),
            
            # --- Raw Data ---
            "trade_hist": trades
        }

    def _calculate_max_drawdown_pct(self, equity_curve: pd.Series) -> float:
        """Calculates the Maximum Drawdown in Percentage."""
        # Calculate running peak
        running_max = equity_curve.cummax()
        # Calculate drawdown percentage relative to peak
        drawdown = (equity_curve - running_max) / running_max * 100
        # Min because drawdowns are negative numbers
        max_dd = drawdown.min()
        return abs(max_dd) # Return as positive number (e.g., 15.5%)

    def _calculate_sharpe_ratio(self, equity_curve: pd.Series, risk_free_rate: float = 0.02) -> float:
        """Calculates Annualized Sharpe Ratio."""
        returns = equity_curve.pct_change().dropna()
        if returns.empty or returns.std() == 0:
            return 0.0
        
        # Assume 252 trading days
        # Excess returns = Strategy Return - Risk Free (daily approx)
        excess_returns = returns - (risk_free_rate / 252)
        sharpe = np.sqrt(252) * (excess_returns.mean() / returns.std())
        return sharpe

    def _calculate_sortino_ratio(self, equity_curve: pd.Series, target_return: float = 0) -> float:
        """Calculates Annualized Sortino Ratio (Downside Risk only)."""
        returns = equity_curve.pct_change().dropna()
        if returns.empty:
            return 0.0
        
        downside_returns = returns[returns < target_return]
        if downside_returns.empty or downside_returns.std() == 0:
            return 0.0 # No downside risk
            
        sortino = np.sqrt(252) * (returns.mean() / downside_returns.std())
        return sortino

    def _empty_report(self):
        return {
            "init_value": self.initial_cash,
            "final_value": self.initial_cash,
            "net_profit": 0,
            "return_pct": 0,
            "num_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "max_drawdown": 0,
            "sharpe_ratio": 0,
            "trade_hist": []
        }