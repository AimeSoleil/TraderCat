import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime, timedelta, date  # [FIX] Added 'date' import
from tabulate import tabulate
from tqdm import tqdm  # [Add this import]

from trade_bot.backtest.performance_report import PerformanceReport
from trade_bot.backtest.trader_tracker import TradeTracker
from trade_bot.strategy.signal_model import SignalModel
from trade_bot.logger.logger import get_logger

logger = get_logger(__name__)

# --- Visualization Functions (Kept mostly same, added date handling robustness) ---

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
    # Ensure we don't plot NaN gaps if data is missing
    df.dropna(subset=['Close'], inplace=True)

    candle_dates = df.index.to_list()
    buy_markers = [np.nan] * len(candle_dates)
    sell_markers = [np.nan] * len(candle_dates)

    # Map trades to the chart
    # Note: Trade index might refer to the original fetched list, 
    # so we map by Date if possible, or fallback to index alignment
    for trade in trades:
        t_date = pd.to_datetime(trade.get('date'))
        price = trade.get('price')
        
        if t_date in df.index:
            loc_idx = df.index.get_loc(t_date)
            # Handle duplicate dates if any (rare in daily)
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
        plt.close() # Close plot to free memory
    else:
        mpf.plot(df, **plot_kwargs)

def plot_equity_curve(trackers, preset_name=None, save=False, filename=None):
    if not trackers:
        return

    # Align equity curves (they might have different lengths if data varies)
    # We take the shortest length to be safe for simple addition
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

def print_dashboard(results, preset_name=None):
    table = []
    for symbol, report in results.items():
        table.append([
            preset_name or "N/A",
            symbol,
            f"${report['final_value']:,.2f}",
            f"${report['net_profit']:,.2f}",
            report["num_trades"],
            f"{report['win_rate']}%",
            f"${report['avg_win']:.2f}",
            f"${report['avg_loss']:.2f}",
            f"{report['max_drawdown']}%"
        ])
    headers = ["Preset", "Symbol", "Final Value", "Net Profit", "Trades", "Win Rate", "Avg Win", "Avg Loss", "Max DD"]
    logger.info("\n📊 Strategy Performance Dashboard")
    logger.info(f"\n{tabulate(table, headers=headers, tablefmt='pretty')}")

def print_trade_hist(trades, preset_name=None):
    if not trades:
        return
    table = []
    # Limit print to last 20 trades to avoid spamming logs
    display_trades = trades[-20:] 
    
    for trade in display_trades:
        row = [
            trade.get("index"),
            preset_name or "N/A",
            trade.get("date", "N/A"),
            trade.get("symbol", "N/A"),
            trade.get("type").upper(),
            f"{trade.get('price', 0):.2f}",
            f"{trade.get('shares', 0):.4f}",
            f"{trade.get('profit', 0):.2f}" if "profit" in trade else "-",
            f"{trade.get('cash_after', 0):.2f}",
        ]
        table.append(row)
    
    headers = ["Idx", "Preset", "Date", "Sym", "Type", "Price", "Shares", "Profit", "Cash"]
    logger.info(f"\n📈 Trade History (Last {len(display_trades)})")
    logger.info(f"\n{tabulate(table, headers=headers, tablefmt='simple')}")

# --- Core Engine Classes ---

class BacktestEngine:
    """
    Runs the strategy on a single symbol's candle data.
    """
    def __init__(self, strategy, candles, symbol, start_date: datetime, initial_cash=100000):
        self.strategy = strategy
        self.candles = candles
        self.symbol = symbol
        self.start_date = start_date # The official start date for TRADING (datetime object)
        self.tracker = TradeTracker(symbol, initial_cash)

    def run(self):
        # We iterate through ALL fetched candles (including warm-up buffer)
        # But we only execute trades if the candle date is >= start_date
        
        lookback_window = self.strategy.get_lookback_window()
        
        for i in range(lookback_window, len(self.candles)):
            # Slice data for the strategy
            candle_slice = self.candles[:i+1]
            current_candle = candle_slice[-1]
            
            # Ensure date comparison works (Normalize everything to datetime)
            current_date = current_candle.date
            
            if isinstance(current_date, str):
                current_date = datetime.strptime(current_date, "%Y-%m-%d")
            elif isinstance(current_date, pd.Timestamp):
                current_date = current_date.to_pydatetime()
            elif isinstance(current_date, date) and not isinstance(current_date, datetime):
                # [FIX] Convert pure 'date' to 'datetime' (midnight) to allow comparison
                current_date = datetime.combine(current_date, datetime.min.time())

            # 1. Generate Signal
            signal_model: SignalModel = self.strategy.generate_signal(self.symbol, candle_slice)
            
            # 2. Execute Trade (Only if within the official backtest period)
            # Now both sides are guaranteed to be datetime objects
            if current_date >= self.start_date:
                price = current_candle.close
                
                # Log only significant signals or trades to reduce noise
                if signal_model.signal in ["buy", "sell"]:
                    logger.debug(f"{current_date.date()} {self.symbol}: {signal_model.signal} @ {price}")
                
                self.tracker.execute(signal_model, price, i)
                self.tracker.record_portfolio(price)

        self.tracker.get_trade_table()
        return PerformanceReport(self.tracker).generate()

class MultiSymbolBacktestEngine:
    """
    Orchestrates backtests across multiple symbols.
    Handles data fetching with warm-up buffers.
    """
    def __init__(self, strategy, preset_name, symbols, provider, start_date, end_date, interval="1d", initial_cash=100000):
        self.strategy = strategy
        self.preset_name = preset_name
        self.symbols = symbols
        self.provider = provider
        self.start_date = start_date
        self.end_date = end_date
        self.interval = interval
        self.initial_cash = initial_cash
        
        self.results = {}
        self.trackers = {}
        self.candle_data = {}

    def _get_warmup_start_date(self) -> str:
        """Calculates a start date that includes enough buffer for indicators."""
        # Get strategy requirement (e.g., 200 for SMA200)
        required_lookback = self.strategy.get_lookback_window()
        # Add a safety margin (e.g., weekends/holidays) -> 1.5x days
        buffer_days = int(required_lookback * 1.6) + 10
        
        start_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
        warmup_dt = start_dt - timedelta(days=buffer_days)
        return warmup_dt.strftime("%Y-%m-%d")

    def run(self):
        warmup_start = self._get_warmup_start_date()        
        start_dt_obj = datetime.strptime(self.start_date, "%Y-%m-%d")

        # [FIX] Wrap the loop with tqdm for a real progress bar
        # desc: Description text
        # unit: Unit name (e.g., "sym" for symbol)
        for symbol in tqdm(self.symbols, desc=f"Backtesting ({self.preset_name})", unit="sym"):
            
            # Use the new range-based fetching
            try:
                logger.info(f"Fetching data for {symbol} from {warmup_start} to {self.end_date}...")
                candles = self.provider.get_price_data_by_range(
                    symbol=symbol, 
                    start_date=warmup_start, 
                    end_date=self.end_date, 
                    interval=self.interval
                )
                logger.info(f"Fetched {len(candles)} candles for {symbol}.")
            except AttributeError:
                # Fallback if provider doesn't have range method yet
                logger.warning("Provider missing 'get_price_data_by_range', using default lookback.")
                candles = self.provider.get_price_data(symbol, self.interval, 1000)

            if not candles or len(candles) < self.strategy.get_lookback_window():
                # Use tqdm.write instead of logger to avoid breaking the progress bar layout
                tqdm.write(f"⚠️ Skipping {symbol}: insufficient data.")
                continue
            
            self.candle_data[symbol] = candles
            
            # Initialize Single Engine
            engine = BacktestEngine(
                strategy=self.strategy, 
                candles=candles, 
                symbol=symbol, 
                start_date=start_dt_obj,
                initial_cash=self.initial_cash
            )
            
            report = engine.run()
            self.results[symbol] = report
            self.trackers[symbol] = engine.tracker

        return self.results

    def visualize(self, save=False, output_dir="charts", file_prefix=None):
        print_dashboard(self.results, self.preset_name)

        if save:
            os.makedirs(output_dir, exist_ok=True)
        
        # Plot Equity Curve
        plot_equity_curve(self.trackers, self.preset_name, save, f"{output_dir}/{file_prefix}_equity_curve.png")
        
        # Plot Individual Trades
        for symbol in self.symbols:
            if symbol in self.candle_data and symbol in self.trackers:
                # Only print history if there were trades
                if self.trackers[symbol].trades:
                    print_trade_hist(self.trackers[symbol].trades, self.preset_name)
                    plot_trade_chart(
                        self.candle_data[symbol], 
                        self.trackers[symbol].trades,
                        symbol,
                        self.preset_name,
                        save,
                        f"{output_dir}/{file_prefix}_{symbol}_chart.png"
                    )

class BacktestRunner:
    """
    Wrapper for compatibility with main.py
    """
    def __init__(self, strategy, preset_name, symbols, provider, start_date, end_date, interval="1d", initial_cash=100000):
        self.strategy = strategy
        self.preset_name = preset_name
        self.symbols = symbols
        self.provider = provider
        self.start_date = start_date
        self.end_date = end_date
        self.interval = interval
        self.initial_cash = initial_cash
        self.engine = None

    def run(self):
        self.engine = MultiSymbolBacktestEngine(
            strategy=self.strategy,
            preset_name=self.preset_name,
            symbols=self.symbols,
            provider=self.provider,
            start_date=self.start_date,
            end_date=self.end_date,
            interval=self.interval,
            initial_cash=self.initial_cash
        )
        results = self.engine.run()
        return results

    def visualize(self, save=False, output_dir="charts", file_prefix=None):
        if not self.engine:
            logger.info("⚠️ Backtest not yet run. Call run() first.")
            return
        self.engine.visualize(save, output_dir, file_prefix)
