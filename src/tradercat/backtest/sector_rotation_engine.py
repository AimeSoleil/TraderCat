import sys
import os
from datetime import datetime, timedelta
import traceback
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from typing import List, Dict, Any

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from tradercat.logger.logger import get_logger
from tradercat.strategy.sector_rotation_strategy import SectorRotationStrategy, make_sector_rotation_presets
from tradercat.data.openbb_provider import OpenBBProvider
from tradercat.data.market_data_provider import MarketDataProvider

logger = get_logger(__name__)

# --- 1. Backtest Data Provider Wrapper ---

class BacktestOpenBBProvider(MarketDataProvider):
    """
    Wraps OpenBBProvider to serve historical data slices for backtesting.
    Pre-fetches all data once to avoid API rate limits during the loop.
    """
    def __init__(self, symbols: List[str], start_date: str, end_date: str):
        self.real_provider = OpenBBProvider() # Initialize your real provider
        self.data_cache = {}
        self.current_date = None
        
        logger.info(f"Pre-fetching data for {len(symbols)} symbols from {start_date} to {end_date}...")
        
        # Pre-fetch all data to memory
        for sym in symbols:
            try:
                # Fetch with a buffer for indicators (e.g. 6 months before start_date)
                # This ensures we have enough data for SMA200 at the very beginning of the backtest
                fetch_start = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=180)).strftime("%Y-%m-%d")
                
                # Use the new method to get precise range
                candles = self.real_provider.get_price_data_by_range(
                    symbol=sym, 
                    start_date=fetch_start, 
                    end_date=end_date, 
                    interval="1d"
                )
                logger.info(f"Fetched {len(candles)} candles for {sym}")
                
                # Convert to DataFrame for easy slicing
                data = []
                for c in candles:
                    # Ensure date is datetime object
                    # OpenBB results usually have 'date' as datetime.date or datetime.datetime
                    d = c.date if isinstance(c.date, (datetime, pd.Timestamp)) else datetime.strptime(str(c.date), "%Y-%m-%d")
                    data.append({
                        "date": d,
                        "open": float(c.open),
                        "high": float(c.high),
                        "low": float(c.low),
                        "close": float(c.close),
                        "volume": float(c.volume)
                    })
                
                df = pd.DataFrame(data)
                if not df.empty:
                    df.set_index("date", inplace=True)
                    df.sort_index(inplace=True)
                    self.data_cache[sym] = df
                    
            except Exception as e:
                logger.error(f"Failed to fetch data for {sym}: {traceback.format_exc()}")

    def set_current_date(self, date):
        self.current_date = date

    def get_price_data(self, symbol: str, interval: str, lookback: int) -> List[Any]:
        if symbol not in self.data_cache:
            return []
        
        df = self.data_cache[symbol]
        # Slice: Get data up to current_date
        mask = df.index <= self.current_date
        sliced = df.loc[mask].tail(lookback)
        
        # Convert back to object list (mimicking what Strategy expects)
        candles = []
        for date, row in sliced.iterrows():
            # Create a simple object structure
            c = type('Candle', (), {})()
            c.date = date
            c.open = row['open']
            c.high = row['high']
            c.low = row['low']
            c.close = row['close']
            c.volume = row['volume']
            candles.append(c)
            
        return candles

    def get_indicator(self, name: str, candles: List[Any], params: Dict[str, Any]) -> List[Any]:
        """
        Delegate indicator calculation to the real provider or calculate locally.
        Since we are in a backtest loop, calling API for indicators is slow/impossible.
        We calculate locally using pandas.
        """
        if not candles:
            return []
        
        df = pd.DataFrame([vars(c) for c in candles])
        length = params.get('length', 14)
        result_objects = []
        
        if name == 'rsi':
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
            rs = gain / loss
            rsi_vals = 100 - (100 / (1 + rs))
            
            field_name = f"close_RSI_{length}"
            for val in rsi_vals:
                obj = type('Obj', (), {})()
                setattr(obj, field_name, val)
                result_objects.append(obj)

        elif name == 'atr':
            high_low = df['high'] - df['low']
            high_close = np.abs(df['high'] - df['close'].shift())
            low_close = np.abs(df['low'] - df['close'].shift())
            ranges = pd.concat([high_low, high_close, low_close], axis=1)
            true_range = np.max(ranges, axis=1)
            atr_vals = true_range.rolling(window=length).mean()

            field_name = f"ATRr_{length}"
            for val in atr_vals:
                obj = type('Obj', (), {})()
                setattr(obj, field_name, val)
                result_objects.append(obj)
                
        return result_objects

    def get_option_chains(self, symbol: str, end_of_day: datetime):
        return self.real_provider.get_option_chains(symbol, end_of_day)

# --- 2. Backtest Engine ---

def run_sector_rotation_backtest(
    start_date: str,
    end_date: str,
    preset_name: str = "swing",
    rebalance_freq: str = "W-FRI",
    initial_capital: float = 10000.0
):
    # [FIX] Handle deprecated 'M' frequency automatically
    if rebalance_freq == 'M':
        rebalance_freq = 'ME'
        
    logger.info("--- Starting Sector Rotation Backtest (OpenBB Powered) ---")
    logger.info(f"Config: {preset_name.upper()} | Freq: {rebalance_freq} | Range: {start_date} to {end_date}")

    # 1. Load Configuration
    presets = make_sector_rotation_presets()
    if preset_name not in presets:
        raise ValueError(f"Invalid preset '{preset_name}'. Options: {list(presets.keys())}")
    
    config = presets[preset_name]
    
    # 2. Prepare Universe
    universe_map = {}
    if config['universe'] == 'sub_sector':
        from tradercat.strategy.sector_rotation_strategy import SUB_SECTOR_LIST
        universe_map = SUB_SECTOR_LIST
    else:
        from tradercat.strategy.sector_rotation_strategy import GICS_SECTOR_LIST
        universe_map = GICS_SECTOR_LIST
        
    symbols_to_download = list(universe_map.values()) + [config['benchmark_symbol'], config['safe_haven_symbol']]
    symbols_to_download = list(set(symbols_to_download))

    # 3. Initialize Backtest Provider (Pre-fetches data)
    backtest_provider = BacktestOpenBBProvider(symbols_to_download, start_date, end_date)

    # 4. Initialize Strategy
    strategy = SectorRotationStrategy(
        look_back_days=config['look_back_days'],
        num_sectors_to_select=config['num_sectors_to_select'],
        weights=config['weights'],
        universe=universe_map,
        safe_haven_symbol=config['safe_haven_symbol'],
        benchmark_symbol=config['benchmark_symbol'],
        data_provider=backtest_provider
    )

    # 5. Run Loop
    dates = pd.date_range(start=start_date, end=end_date, freq=rebalance_freq)
    portfolio_value = initial_capital
    holdings = { "CASH": initial_capital }
    history = []

    logger.info(f"Running backtest loop...")

    for current_date in dates:
        backtest_provider.set_current_date(current_date)
        
        # Calculate Portfolio Value
        current_total_value = 0
        for sym, amount in holdings.items():
            if sym == "CASH":
                current_total_value += amount
            else:
                price_data = backtest_provider.get_price_data(sym, "1d", 1)
                if price_data:
                    current_total_value += price_data[-1].close * amount
                else:
                    pass 
        
        if current_total_value == 0 and holdings.get("CASH") > 0:
            current_total_value = holdings["CASH"]

        portfolio_value = current_total_value
        
        # Generate Signal
        try:
            signal = strategy.generate_signal()
        except Exception as e:
            logger.error(f"Error on {current_date}: {e}")
            continue

        # Execute Rebalance
        new_holdings = {}
        if signal.signal == "rebalance":
            allocations = signal.details['allocations']
            selected_symbols = signal.symbol.split(',')
            
            logger.info(f"[{current_date.date()}] Rebalance: {signal.details.get('regime')} -> {selected_symbols}")
            
            for sym, weight in allocations.items():
                target_value = portfolio_value * weight
                price_data = backtest_provider.get_price_data(sym, "1d", 1)
                if price_data:
                    price = price_data[-1].close
                    shares = target_value / price
                    new_holdings[sym] = shares
                else:
                    new_holdings["CASH"] = new_holdings.get("CASH", 0) + target_value
        else:
            if signal.symbol == "CASH":
                new_holdings = {"CASH": portfolio_value}
            else:
                new_holdings = holdings

        holdings = new_holdings
        
        history.append({
            "date": current_date,
            "portfolio_value": portfolio_value,
            "holdings": str(list(holdings.keys()))
        })

    # 6. Results
    if not history:
        logger.warning("No history generated. Check data fetching.")
        return None  # [Changed] Return None on failure

    df_res = pd.DataFrame(history)
    df_res.set_index("date", inplace=True)
    
    total_return = (portfolio_value - initial_capital) / initial_capital * 100
    
    # [NEW] Calculate Max Drawdown for reporting
    running_max = df_res['portfolio_value'].cummax()
    drawdown = (df_res['portfolio_value'] - running_max) / running_max * 100
    max_dd = abs(drawdown.min())

    logger.info(f"\n--- Backtest Finished ---")
    logger.info(f"Final Value: ${portfolio_value:.2f}")
    logger.info(f"Total Return: {total_return:.2f}%")
    logger.info(f"Max Drawdown: {max_dd:.2f}%")
    
    # [MODIFIED] Plotting and Saving Logic
    plt.figure(figsize=(12, 6))
    df_res['portfolio_value'].plot(title=f"Sector Rotation ({preset_name.upper()}) Backtest")
    plt.ylabel("Portfolio Value ($)")
    plt.grid(True, alpha=0.3)
    
    # Create charts directory if it doesn't exist
    output_dir = "charts"
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate filename with timestamp to avoid overwriting
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{output_dir}/sector_rotation_{preset_name}_{timestamp}.png"
    
    plt.savefig(filename)
    logger.info(f"Chart saved to: {filename}")
    
    # Optional: Still show the plot if running interactively
    # plt.show()

    # [NEW] Return metrics dictionary
    return {
        "final_value": portfolio_value,
        "net_profit": portfolio_value - initial_capital,
        "total_return": total_return,
        "max_drawdown": max_dd
    }

if __name__ == "__main__":
    # Backtest Configuration
    # ----------------------
    # start_date:      Start date of the backtest (YYYY-MM-DD)
    # end_date:        End date of the backtest (YYYY-MM-DD)
    # preset_name:     Strategy preset to use ('swing' or 'position')
    # rebalance_freq:  Frequency of rebalancing ('W-FRI' for weekly Friday, 'ME' for month end)
    # initial_capital: Starting capital in USD
    
    run_sector_rotation_backtest(
        start_date='2020-01-01',
        end_date=datetime.now().strftime("%Y-%m-%d"),
        preset_name='swing',       # Options: 'swing', 'position'
        rebalance_freq='ME',       # [FIX] Changed 'M' to 'ME'
        initial_capital=10000.0
    )