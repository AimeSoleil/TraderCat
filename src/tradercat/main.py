import asyncio
import argparse
import pandas as pd
from datetime import datetime
import yaml
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from typing import List, Dict

from tradercat.logger.logger import get_logger
from tradercat.notification.discord import DiscordNotifier
from tradercat.execution.trade_execution import TradeExecutor
from tradercat.bot import TraderBot
from tradercat.strategy.signal_model import SignalModel

logger = get_logger(__name__)

DEFAULT_SYMBOLS_STR = os.environ.get("ENV_SYMBOLS")

# --- Helper Functions ---

def load_symbols(args) -> List[str]:
    """Determines the source of symbols and loads them."""
    symbols = []
    if args.symbols:
        logger.info(f"Symbols from CLI: {args.symbols}")
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.symbols_file:
        logger.info(f"Loading symbols from file: {args.symbols_file}")
        ext = os.path.splitext(args.symbols_file)[1].lower()
        with open(args.symbols_file, "r") as f:
            if ext in [".yaml", ".yml"]:
                data = yaml.safe_load(f)
                symbols = [s.strip().upper() for s in data.get("symbols", [])]
            else:
                symbols = [line.strip().upper() for line in f if line.strip()]
    else:
        logger.info("Loading symbols from ENV_SYMBOLS.")
        if DEFAULT_SYMBOLS_STR:
            symbols = [s.strip().upper() for s in DEFAULT_SYMBOLS_STR.split(",") if s.strip()]
    
    # Remove duplicates while preserving order
    return list(dict.fromkeys(symbols))

def save_signals_to_csv(all_signals: List[Dict]):
    """Exports collected signals to a CSV file."""
    rows = []
    for entry in all_signals:
        for signal in entry["signals"]:
            rows.append({
                "Close_Date": getattr(signal, "date", datetime.now().date()),
                "Symbol": getattr(signal, "symbol", entry["symbol"]),
                "Strategy": getattr(signal, "strategy", "Unknown"),
                "Signal": getattr(signal, "signal", "Unknown"),
                "Confidence": getattr(signal, "confidence", 0),
                "Reason": getattr(signal, "reason", ""),
                "Details": getattr(signal, "details", "")
            })
    
    if not rows:
        return

    df = pd.DataFrame(rows)
    filename = f"trade_signals_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    logger.info(f"📄 Signals CSV created: {filename}")

async def send_discord_summary(discord_notifier: DiscordNotifier, all_signals: List[Dict]):
    """Formats and sends a summary to Discord."""
    today_str = datetime.today().strftime("%Y-%m-%d")
    message_lines = [f"** 💸 Daily [{today_str}] Trade Signals Summary: **"]
    
    has_signals = False
    for entry in all_signals:
        for s in entry["signals"]:
            if s.signal in ("buy", "sell"):
                has_signals = True
                line = (f"* **{entry['symbol']}**: {s.signal.upper()} | "
                        f"Strat: {s.strategy} | Conf: {s.confidence:.2f} | "
                        f"Reason: {s.reason} *")
                message_lines.append(line)

    if not has_signals:
        message_lines.append("No actionable BUY/SELL signals generated.")

    full_message = "\n".join(message_lines)
    logger.info(f"🔔 Sending Discord Notification:\n{full_message}")
    
    try:
        await discord_notifier.send(full_message)
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")

# --- Core Logic ---

async def run_trading_session(symbols: List[str], executor: TradeExecutor, discord_notifier: DiscordNotifier, 
                            max_concurrency: int = 5, stagger_sec: int = 2, run_portfolio: bool = True):
    """
    Orchestrates the entire trading session:
    1. Runs Portfolio Strategies (Global) - Optional
    2. Runs Single-Asset Strategies (Concurrent)
    3. Aggregates results -> CSV -> Discord
    """
    start_time = datetime.now()
    bot = TraderBot(executor=executor)
    all_results = []
    logger.info(f"run_portfolio: {run_portfolio}")

    # 1. Run Portfolio Strategies (Sequential, usually fast)
    if run_portfolio:
        try:
            portfolio_signals = await bot.process_portfolio()
            if portfolio_signals:
                all_results.append({"symbol": "PORTFOLIO", "signals": portfolio_signals})
        except Exception as e:
            logger.error(f"Error in portfolio strategies: {e}")
    else:
        logger.info("Skipping Portfolio Strategies.")

    # 2. Run Single-Asset Strategies (Concurrent)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def worker(symbol):
        async with semaphore:
            # Stagger start to be nice to APIs
            await asyncio.sleep(stagger_sec * (symbols.index(symbol) % max_concurrency)) 
            try:
                signals = await bot.process_symbol(symbol)
                if signals:
                    return {"symbol": symbol, "signals": signals}
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
            return None

    tasks = [worker(sym) for sym in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Filter out failures and empty results
    for res in results:
        if isinstance(res, dict):
            all_results.append(res)

    # 3. Reporting
    if all_results:
        save_signals_to_csv(all_results)
        await send_discord_summary(discord_notifier, all_results)
    else:
        logger.info("No signals generated this session.")

    duration = datetime.now() - start_time
    logger.info(f"✅ Session finished in {duration.total_seconds():.2f}s")

# --- Scheduler ---

async def start_scheduler(symbols, executor, notifier, args):
    scheduler = AsyncIOScheduler(timezone=pytz.timezone('US/Eastern'))
    
    job_fn = lambda: asyncio.create_task(
        run_trading_session(symbols, executor, notifier, args.concurrency, args.stagger, not args.skip_portfolio)
    )
    
    scheduler.add_job(job_fn, CronTrigger(hour=args.schedule_hour, minute=args.schedule_minute))
    
    logger.info(f"⏰ Scheduler started. Next run at {args.schedule_hour:02d}:{args.schedule_minute:02d} ET.")
    scheduler.start()
    
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        pass

# --- Entry Point ---

def main():
    parser = argparse.ArgumentParser(description="TraderCat Bot Runner")
    parser.add_argument("-m", "--mode", choices=["once", "schedule"], default="once", help="Run mode")
    parser.add_argument("-s", "--symbols", type=str, help="Comma separated symbols")
    parser.add_argument("-f", "--symbols-file", type=str, help="Path to symbols file")
    parser.add_argument("-H", "--schedule-hour", type=int, default=16, help="Schedule Hour (ET)")
    parser.add_argument("-M", "--schedule-minute", type=int, default=0, help="Schedule Minute (ET)")
    parser.add_argument("-c", "--concurrency", type=int, default=5, help="Max concurrent bots")
    parser.add_argument("-S", "--stagger", type=int, default=2, help="Stagger seconds")
    parser.add_argument("--skip-portfolio", action="store_true", help="Skip running portfolio strategies")

    args = parser.parse_args()
    
    symbols = load_symbols(args)
    if not symbols:
        logger.error("No symbols found. Exiting.")
        return

    logger.info(f"Loaded {len(symbols)} unique symbols.")
    
    executor = TradeExecutor()
    notifier = DiscordNotifier()

    if args.mode == "once":
        asyncio.run(run_trading_session(symbols, executor, notifier, args.concurrency, args.stagger, not args.skip_portfolio))
    else:
        asyncio.run(start_scheduler(symbols, executor, notifier, args))

if __name__ == "__main__":
    main()