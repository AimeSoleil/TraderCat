import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf
from tabulate import tabulate

from trade_bot.backtest.performance_report import PerformanceReport
from trade_bot.backtest.trader_tracker import TradeTracker
from trade_bot.strategy.signal_model import SignalModel

def plot_trade_chart(candles, trades, symbol, preset_name=None, save=False, filename=None):
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
    df.dropna(inplace=True)

    candle_dates = df.index.to_list()
    buy_markers = [np.nan] * len(candle_dates)
    sell_markers = [np.nan] * len(candle_dates)

    for trade in trades:
        idx = trade.get('index')
        if isinstance(idx, int) and 0 <= idx < len(candle_dates):
            price = trade.get('price')
            if price is not None:
                if trade['type'] == 'buy':
                    buy_markers[idx] = price
                elif trade['type'] == 'sell':
                    sell_markers[idx] = price

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
    }

    if apds:
        plot_kwargs["addplot"] = apds

    if save and filename:
        plot_kwargs["savefig"] = filename

    mpf.plot(df, **plot_kwargs)

def plot_equity_curve(trackers, preset_name=None, save=False, filename=None):
    min_len = min(len(t.portfolio_values) for t in trackers.values())
    combined = np.zeros(min_len)
    for t in trackers.values():
        combined += np.array(t.portfolio_values[:min_len])

    plt.figure(figsize=(12, 5))
    plt.plot(combined, label="Portfolio Equity", color="blue", linewidth=2)
    plt.title("Combined Portfolio Equity Curve")
    plt.xlabel("Time (Days)")
    plt.ylabel(f"{preset_name} - Portfolio Value")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()

    if save and filename:
        plt.savefig(filename)
        plt.close()
    else:
        plt.show()


def print_dashboard(results, preset_name=None):
    table = []
    for symbol, report in results.items():
        table.append([
            preset_name or "N/A",
            symbol,
            round(report["final_value"], 2),
            round(report["net_profit"], 2),
            report["num_trades"],
            report["win_rate"],
            report["avg_win"],
            report["avg_loss"],
            report["max_drawdown"]
        ])
    headers = ["Preset", "Symbol", "Final Value", "Net Profit", "Trades", "Win Rate", "Avg Win", "Avg Loss", "Max Drawdown"]
    print("\n📊 Strategy Performance Dashboard")
    print(tabulate(table, headers=headers, tablefmt="pretty"))

def print_trade_hist(trades, preset_name=None):
    if not trades:
        print("No trades executed.")
        return
    table = []
    for trade in trades:
        row = [
            trade.get("index"),
            preset_name or "N/A",
            trade.get("date", "N/A"),
            trade.get("symbol", "N/A"),
            trade.get("type").upper(),
            round(trade.get("price", 0), 2),
            trade.get("shares", 0),
            round(trade.get("entry_price", 0), 2) if "entry_price" in trade else "",
            round(trade.get("profit", 0), 2) if "profit" in trade else "",
            round(trade.get("cash_after", 0), 2),
            trade.get("note", "")
        ]
        table.append(row)
    headers = ["Index", "Preset", "Date", "Symbol", "Type", "Price", "Shares", "Entry Price", "Profit", "Cash After", "Note"]
    print("\n📈 Trade History")
    print(tabulate(table, headers=headers, tablefmt="pretty"))

class BacktestEngine:
    def __init__(self, strategy, candles, symbol, initial_cash=100000):
        self.strategy = strategy
        self.candles = candles
        self.symbol = symbol
        self.tracker = TradeTracker(symbol, initial_cash)

    def run(self):
        for i in range(self.strategy.get_lookback_window() + 1, len(self.candles)):
            candle_slice = self.candles[:i+1]
            signal_model: SignalModel = self.strategy.generate_signal(self.symbol, candle_slice)
            date = candle_slice[-1].date
            price = candle_slice[-1].close
            print(f"{date} symbol: {self.symbol}, signal: {signal_model}")
            self.tracker.execute(signal_model, price, i)
            self.tracker.record_portfolio(price)

        self.tracker.get_trade_table()
        return PerformanceReport(self.tracker).generate()

class MultiSymbolBacktestEngine:
    def __init__(self, strategy, preset_name, symbols, provider, interval="1d", lookback_days=365, initial_cash=100000):
        self.strategy = strategy
        self.preset_name = preset_name
        self.symbols = symbols
        self.provider = provider
        self.interval = interval
        self.lookback_days = lookback_days
        self.initial_cash = initial_cash
        self.results = {}
        self.trackers = {}
        self.candle_data = {}

    def run(self):
        lookback = max(self.strategy.get_lookback_window(), self.lookback_days) + 100
        for symbol in self.symbols:
            candles = self.provider.get_price_data(symbol, interval=self.interval, lookback=lookback)
            if not candles or len(candles) < self.strategy.get_lookback_window():
                print(f"⚠️ Skipping {symbol}: insufficient data.")
                continue
            self.candle_data[symbol] = candles
            engine = BacktestEngine(self.strategy, candles, symbol, initial_cash=self.initial_cash)
            report = engine.run()
            self.results[symbol] = report
            self.trackers[symbol] = engine.tracker

        return self.results

    def visualize(self, save=False, output_dir="charts", file_prefix=None):
        print_dashboard(self.results, self.preset_name)

        if save:
            os.makedirs(output_dir, exist_ok=True)
        plot_equity_curve(self.trackers, self.preset_name, save, f"{output_dir}/{file_prefix}_equity_curve.png")
        for symbol in self.symbols:
            if symbol in self.candle_data and symbol in self.trackers:
                print_trade_hist(self.trackers[symbol].trades, self.preset_name)
                plot_trade_chart(
                    self.candle_data[symbol], 
                    self.trackers[symbol].trades,
                    symbol,
                    self.preset_name,
                    save,
                    f"{output_dir}/{file_prefix}_trade_chart.png"
                )

class BacktestRunner:
    """
    A unified runner for executing multi-symbol strategy backtests,
    printing performance dashboards, and visualizing trade results.
    """

    def __init__(self, strategy, preset_name, symbols, provider, interval="1d", lookback_days=365, initial_cash=100000):
        self.strategy = strategy
        self.preset_name = preset_name
        self.symbols = symbols
        self.provider = provider
        self.interval = interval
        self.lookback_days = lookback_days
        self.initial_cash = initial_cash
        self.engine = None

    def run(self):
        self.engine = MultiSymbolBacktestEngine(
            strategy=self.strategy,
            preset_name=self.preset_name,
            symbols=self.symbols,
            provider=self.provider,
            interval=self.interval,
            lookback_days=self.lookback_days,
            initial_cash=self.initial_cash
        )
        results = self.engine.run()
        return results

    def visualize(self, save=False, output_dir="charts", file_prefix=None):
        if not self.engine:
            print("⚠️ Backtest not yet run. Call run() first.")
            return
        self.engine.visualize(save, output_dir, file_prefix)
