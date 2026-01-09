import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf
from tabulate import tabulate
from tradercat.logger.logger import get_logger

logger = get_logger(__name__)

class BacktestVisualizer:
    """
    Handles all charting, plotting, and console reporting for backtests.
    """
    
    @staticmethod
    def print_dashboard(results, preset_name=None):
        table = []
        for symbol, report in results.items():
            table.append([
                preset_name or "N/A",
                symbol,
                f"${report['final_value']:,.2f}",
                f"${report['net_profit']:,.2f}",
                f"{report['return_pct']:.2f}%",  # [NEW] Added Return
                report["num_trades"],
                f"{report['win_rate']:.2f}%",    # Added % unit
                f"${report['avg_win']:,.2f}",
                f"${report['avg_loss']:,.2f}",
                f"{report['max_drawdown']:.2f}%" # Added % unit
            ])

        headers = ["Preset", "Symbol", "Final Value", "Net Profit", "Return", "Trades", "Win Rate", "Avg Win", "Avg Loss", "Max DD"]
        logger.info("\n📊 Strategy Performance Dashboard")
        logger.info(f"\n{tabulate(table, headers=headers, tablefmt='pretty')}")

    @staticmethod
    def print_trade_history(trades, preset_name=None):
        if not trades:
            return
        
        # Limit print to last 20 trades
        display_trades = trades[-20:] 
        table = []
        
        for trade in display_trades:
            row = [
                trade.get("index"),
                preset_name or "N/A",
                trade.get("date", "N/A"),
                trade.get("symbol", "N/A"),
                trade.get("type").upper(),
                f"${trade.get('price', 0):,.2f}",
                f"{trade.get('shares', 0):,.4f}",
                f"${trade.get('profit', 0):,.2f}" if "profit" in trade else "-", # Added $
                f"${trade.get('cash_after', 0):,.2f}", # Added $
            ]
            table.append(row)
        
        headers = ["Idx", "Preset", "Date", "Sym", "Type", "Price", "Shares", "Profit", "Cash"]
        logger.info(f"\n📈 Trade History (Last {len(display_trades)})")
        logger.info(f"\n{tabulate(table, headers=headers, tablefmt='pretty')}")

    @staticmethod
    def plot_equity_curve(trackers, preset_name=None, save=False, filename=None):
        if not trackers:
            return

        # Align equity curves
        min_len = min(len(t.portfolio_values) for t in trackers.values())
        if min_len == 0:
            return

        combined = np.zeros(min_len)
        for t in trackers.values():
            combined += np.array(t.portfolio_values[:min_len])

        plt.figure(figsize=(12, 5))
        plt.plot(combined, label="Portfolio Equity", color="blue", linewidth=2)
        plt.title(f"Combined Portfolio Equity Curve ({preset_name})")
        plt.xlabel("Time (Days)")
        plt.ylabel("Portfolio Value ($)")
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()

        if save and filename:
            plt.savefig(filename)
            plt.close()
        else:
            plt.show()

    @staticmethod
    def plot_trade_chart(candles, trades, symbol, preset_name=None, save=False, filename=None):
        if not candles:
            return

        df = pd.DataFrame([{
            'Date': candle.date,
            'Open': candle.open,
            'High': candle.high,
            'Low': candle.low,
            'Close': candle.close,
            'Volume': candle.volume
        } for candle in candles])

        df['Date'] = pd.to_datetime(df['Date'])
        df.set_index('Date', inplace=True)
        df.dropna(subset=['Close'], inplace=True)

        candle_dates = df.index.to_list()
        buy_markers = [np.nan] * len(candle_dates)
        sell_markers = [np.nan] * len(candle_dates)

        for trade in trades:
            t_date = pd.to_datetime(trade.get('date'))
            price = trade.get('price')
            
            if t_date in df.index:
                loc_idx = df.index.get_loc(t_date)
                if isinstance(loc_idx, slice) or isinstance(loc_idx, np.ndarray):
                    loc_idx = loc_idx.start if isinstance(loc_idx, slice) else loc_idx[0]
                
                if trade['type'] == 'buy':
                    buy_markers[loc_idx] = price
                elif trade['type'] == 'sell':
                    sell_markers[loc_idx] = price

        apds = []
        if np.isfinite(buy_markers).any():
            buy_series = pd.Series(buy_markers, index=candle_dates)
            apds.append(mpf.make_addplot(buy_series, type='scatter', marker='^', color='green', markersize=100))
        if np.isfinite(sell_markers).any():
            sell_series = pd.Series(sell_markers, index=candle_dates)
            apds.append(mpf.make_addplot(sell_series, type='scatter', marker='v', color='red', markersize=100))

        plot_kwargs = {
            "type": "candle",
            "style": "yahoo",
            "title": f"{preset_name} - {symbol} Trade Chart",
            "volume": True,
            "figsize": (12, 6),
            "warn_too_much_data": 2000 
        }

        if apds:
            plot_kwargs["addplot"] = apds

        if save and filename:
            plot_kwargs["savefig"] = filename
            plt.close()
        else:
            mpf.plot(df, **plot_kwargs)
