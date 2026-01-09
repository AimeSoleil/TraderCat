import os
import pandas as pd
from datetime import datetime, timedelta, date
from typing import Dict, List, Any

from tradercat.backtest.performance_report import PerformanceReport
from tradercat.backtest.trader_tracker import TradeTracker
from tradercat.backtest.visualizer import BacktestVisualizer
from tradercat.strategy.signal_model import SignalModel
from tradercat.logger.logger import get_logger
from tradercat.utils.spinner import LoadingSpinner

logger = get_logger(__name__)

class SingleSymbolEngine:
    """
    Core Engine: Runs the strategy on a SINGLE symbol's data.
    """
    def __init__(self, strategy, candles, symbol, start_date: datetime, initial_cash=100000):
        self.strategy = strategy
        self.candles = candles
        self.symbol = symbol
        self.start_date = start_date
        self.tracker = TradeTracker(symbol, initial_cash)

    def run(self) -> Dict[str, Any]:
        lookback_window = self.strategy.get_lookback_window()
        
        # Main Loop
        for i in range(lookback_window, len(self.candles)):
            candle_slice = self.candles[:i+1]
            current_candle = candle_slice[-1]
            current_date = self._normalize_date(current_candle.date)

            # 1. Generate Signal
            signal_model: SignalModel = self.strategy.generate_signal(self.symbol, candle_slice)
            
            # 2. Execute Trade (Only within valid date range)
            if current_date >= self.start_date:
                price = current_candle.close
                self.tracker.execute(signal_model, price, i)
                self.tracker.record_portfolio(price)

        # self.tracker.get_trade_table()
        return PerformanceReport(self.tracker).generate()

    def _normalize_date(self, date_val) -> datetime:
        """Helper to ensure date is always a datetime object."""
        if isinstance(date_val, str):
            return datetime.strptime(date_val, "%Y-%m-%d")
        elif isinstance(date_val, pd.Timestamp):
            return date_val.to_pydatetime()
        elif isinstance(date_val, date) and not isinstance(date_val, datetime):
            return datetime.combine(date_val, datetime.min.time())
        return date_val

class BacktestRunner:
    """
    Orchestrator: Manages data fetching, multiple symbols, and result aggregation.
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
        
        # State
        self.results = {}
        self.trackers = {}
        self.candle_data = {}

    def run(self):
        warmup_start = self._calculate_warmup_date()
        start_dt_obj = datetime.strptime(self.start_date, "%Y-%m-%d")

        logger.info(f"🚀 Starting Backtest: {self.preset_name} ({len(self.symbols)} symbols)")
        
        for symbol in self.symbols:
            spinner = LoadingSpinner(message=f"Processing {symbol}")
            spinner.start()
            
            try:
                candles = self._fetch_data(symbol, warmup_start)
                
                if not self._validate_data(candles, symbol):
                    spinner.stop()
                    continue

                self.candle_data[symbol] = candles
                
                # Run Single Engine
                engine = SingleSymbolEngine(
                    strategy=self.strategy, 
                    candles=candles, 
                    symbol=symbol, 
                    start_date=start_dt_obj,
                    initial_cash=self.initial_cash
                )
                
                self.results[symbol] = engine.run()
                self.trackers[symbol] = engine.tracker
            
            except Exception as e:
                spinner.stop()
                logger.error(f"❌ Error processing {symbol}: {e}")
            finally:
                spinner.stop()

        return self.results

    def visualize(self, save=False, output_dir="charts", file_prefix=None):
        """Delegates visualization to the Visualizer class."""
        if not self.results:
            logger.warning("⚠️ No results to visualize.")
            return

        if save:
            os.makedirs(output_dir, exist_ok=True)

        # 1. Dashboard
        BacktestVisualizer.print_dashboard(self.results, self.preset_name)
        
        # 2. Equity Curve
        BacktestVisualizer.plot_equity_curve(
            self.trackers, 
            self.preset_name, 
            save, 
            f"{output_dir}/{file_prefix}_equity_curve.png" if file_prefix else None
        )
        
        # 3. Individual Charts
        for symbol in self.symbols:
            if symbol in self.candle_data and symbol in self.trackers:
                tracker = self.trackers[symbol]
                if tracker.trades:
                    BacktestVisualizer.print_trade_history(tracker.trades, self.preset_name)
                    BacktestVisualizer.plot_trade_chart(
                        self.candle_data[symbol], 
                        tracker.trades,
                        symbol,
                        self.preset_name,
                        save,
                        f"{output_dir}/{file_prefix}_{symbol}_chart.png" if file_prefix else None
                    )

    def _calculate_warmup_date(self) -> str:
        required_lookback = self.strategy.get_lookback_window()
        buffer_days = int(required_lookback * 1.6) + 10
        start_dt = datetime.strptime(self.start_date, "%Y-%m-%d")
        return (start_dt - timedelta(days=buffer_days)).strftime("%Y-%m-%d")

    def _fetch_data(self, symbol, start_date):
        try:
            return self.provider.get_price_data_by_range(
                symbol=symbol, 
                start_date=start_date, 
                end_date=self.end_date, 
                interval=self.interval
            )
        except AttributeError:
            return self.provider.get_price_data(symbol, self.interval, 1000)

    def _validate_data(self, candles, symbol):
        if not candles or len(candles) < self.strategy.get_lookback_window():
            logger.warning(f"⚠️ Skipping {symbol}: insufficient data.")
            return False
        return True
