import asyncio
import argparse
import traceback
import pandas as pd
from datetime import datetime
import yaml
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from trade_bot.logger.logger import get_logger
from trade_bot.notification.discord import DiscordNotifier
from trade_bot.execution.trade_execution import TradeExecutor
from trade_bot.bot import TradeBot

logger = get_logger(__name__)

DEFAULT_SYMBOLS_STR = os.environ.get("ENV_SYMBOLS")  # e.g. "AAPL,MSFT,GOOG"
logger.info(f"Default symbols from ENV_SYMBOLS: {DEFAULT_SYMBOLS_STR}")

def parse_symbols(symbols_str):
    return [s.strip().upper() for s in symbols_str.split(",") if s.strip()]


def load_symbols_from_file(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    if ext in [".yaml", ".yml"]:
        with open(filepath, "r") as f:
            data = yaml.safe_load(f)
            return [s.strip().upper() for s in data.get("symbols", [])]
    else:
        with open(filepath, "r") as f:
            return [line.strip().upper() for line in f if line.strip()]


async def run_all_bots(symbols, executor, discord_notifier, max_concurrency: int = 5, start_stagger_sec: int = 2):
    """
    Run all bots concurrently with a semaphore limiting max_concurrency.
    Each bot.run() is consumed as an async generator; collected signals are appended to all_signals.

    Parameters
    ----------
    symbols : list[str]
        List of symbols to run bots for.
    executor : TradeExecutor
        Executor instance to perform trades (passed to TradeBot).
    discord_notifier : DiscordNotifier
        Notifier to send summary messages.
    max_concurrency : int, default=5
        Maximum number of bots to run concurrently.
    start_stagger_sec : int, default=2
        Seconds to wait after starting each task to stagger initialization.
        For example, to control the rate of API calls to openbb or other data providers 
        in case of data provider's API throttling.
    """
    start_time = datetime.now()

    all_signals = []
    bots = [
        TradeBot(symbol=symbol, executor=executor)
        for symbol in symbols
    ]

    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(max_concurrency)

    async def consume_bot(bot: TradeBot, index: int):
        await semaphore.acquire()
        try:
            logger.info(f'🚀 Start bot[{index}] for symbol: {bot.symbol}...')
            try:
                async for signal_list in bot.run():
                    # signal_list expected to be an iterable/list of SignalModel
                    async with lock:
                        all_signals.append({
                            "symbol": bot.symbol,
                            "signals": signal_list
                        })
            except Exception:
                logger.info(f"Error running bot[{index}] for symbol {bot.symbol}: {traceback.format_exc()}")
            finally:
                logger.info(f'✅ Finish bot[{index}] for symbol: {bot.symbol}')
        finally:
            semaphore.release()

    # Launch tasks with stagger to avoid thundering init
    tasks = []
    for index, bot in enumerate(bots):
        logger.info(f"Scheduling bot[{index}] for symbol: {bot.symbol}...")
        tasks.append(asyncio.create_task(consume_bot(bot, index)))
        await asyncio.sleep(start_stagger_sec)

    # Wait for all tasks to complete
    await asyncio.gather(*tasks)

    logger.info(f"✅ All signals collected from {len(bots)} symbols")

    if not all_signals:
        logger.info("No signals generated. Skipping notification.")
        # log total time and return
        end_time = datetime.now()
        duration = end_time - start_time
        total_seconds = int(duration.total_seconds())
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        logger.info(f"🕒 Total execution time: {minutes} minutes and {seconds} seconds")
        return

    # Convert to CSV
    rows = []
    for entry in all_signals:
        for signal in entry["signals"]:
            # ensure `date` attribute exists on signal (v2 strategies expected to set date=current_close_date)
            rows.append({
                "Close_Date": getattr(signal, "date", None),
                "Symbol": getattr(signal, "symbol", entry["symbol"]),
                "Strategy": getattr(signal, "strategy", None),
                "Signal": getattr(signal, "signal", None),
                "Confidence": getattr(signal, "confidence", None),
                "Reason": getattr(signal, "reason", None),
                "Details": getattr(signal, "details", None)
            })
    df = pd.DataFrame(rows)
    csv_filename = f"trade_signals_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    df.to_csv(csv_filename, index=False, encoding='utf-8-sig')
    logger.info(f"📄 Signals CSV created: {csv_filename}")

    # Send summary notification to Discord
    today_str = datetime.today().strftime("%Y-%m-%d")
    title_message = f"** :money_with_wings: Daily [{today_str}] Trade Signals Summary: **\n"
    summary_message = ""
    for entry in all_signals:
        symbol = entry["symbol"]
        signals = entry["signals"]
        sell_buy_signals = [s for s in signals if getattr(s, "signal", None) in ("buy", "sell")]
        for s in sell_buy_signals:
            summary_message += f"* Symbol: {symbol}, Strategy: {getattr(s, 'strategy', '')}, Signal: {getattr(s, 'signal', '')}, Confidence: {getattr(s, 'confidence', '')}, Reason: {getattr(s, 'reason', '')} *\n"

    if not summary_message:
        summary_message = "No buy/sell signals generated. "

    logger.info(f"Summary Message:\n{title_message + summary_message}")
    logger.info("🔔 Sending summary notification to Discord...")
    try:
        await discord_notifier.send(title_message + summary_message)
    except Exception as e:
        logger.info(f"Error sending summary notification to Discord: {e}")

    # Log execution time
    end_time = datetime.now()
    duration = end_time - start_time
    total_seconds = int(duration.total_seconds())
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    logger.info(f"🕒 Total execution time: {minutes} minutes and {seconds} seconds")


async def schedule_main(symbols, executor, discord_notifier, schedule_hour=16, schedule_minute=0, max_concurrency=5, start_stagger_sec=5):
    scheduler = AsyncIOScheduler(timezone=pytz.timezone('US/Eastern'))
    scheduler.add_job(
        lambda: asyncio.create_task(run_all_bots(symbols, executor, discord_notifier, max_concurrency=max_concurrency, start_stagger_sec=start_stagger_sec)),
        CronTrigger(hour=schedule_hour, minute=schedule_minute)
    )
    logger.info(f"Scheduler started. Bots will run every day at {schedule_hour:02d}:{schedule_minute:02d} US/Eastern.")
    scheduler.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        pass


def main(args=None):
    parser = argparse.ArgumentParser(description="TraderCat Bot Runner")
    parser.add_argument(
        "-m", "--mode",
        choices=["once", "schedule"],
        default="once",
        help="Run once or schedule every day at a specified time (default: 4pm US/Eastern)"
    )
    parser.add_argument(
        "-s", "--symbols",
        type=str,
        default=None,
        help="Comma separated list of symbols to trade, e.g. 'AAPL,MSFT,GOOG'"
    )
    parser.add_argument(
        "-f", "--symbols-file",
        type=str,
        default=None,
        help="Path to a file (txt or yaml) containing symbols"
    )
    parser.add_argument(
        "-H", "--schedule-hour",
        type=int,
        default=16,
        help="Hour (0-23) for scheduled run in US/Eastern timezone (default: 16)"
    )
    parser.add_argument(
        "-M", "--schedule-minute",
        type=int,
        default=0,
        help="Minute (0-59) for scheduled run in US/Eastern timezone (default: 0)"
    )
    parser.add_argument(
        "-c", "--concurrency",
        type=int,
        default=5,
        help="Maximum number of bots to run concurrently (default: 5)"
    )
    parser.add_argument(
        "-S", "--stagger",
        type=int,
        default=5,
        help="Seconds to wait between launching bot tasks to stagger initialization (default: 5)"
    )

    if args is None:
        args = parser.parse_args()
    else:
        args = parser.parse_args(args)

    # choose symbols source
    if args.symbols:
        logger.info(f"Symbols provided via command line: {args.symbols}")
        symbols = parse_symbols(args.symbols)
    elif args.symbols_file:
        logger.info(f"Loading symbols from file: {args.symbols_file}")
        symbols = load_symbols_from_file(args.symbols_file)
    else:
        logger.info("Loading symbols from default environment variable [DEFAULT_SYMBOLS_STR].")
        symbols = DEFAULT_SYMBOLS_STR and parse_symbols(DEFAULT_SYMBOLS_STR) or []

    symbols = list(dict.fromkeys(symbols))  # remove duplication while preserving order
    if not symbols:
        logger.info("No symbols provided. Exiting.")
        return
    logger.info(f"Total unique symbols to trade: {len(symbols)}")

    discord_notifier = DiscordNotifier()
    executor = TradeExecutor()

    if args.mode == "once":
        asyncio.run(run_all_bots(symbols, executor, discord_notifier, max_concurrency=args.concurrency, start_stagger_sec=args.stagger))
    else:
        asyncio.run(schedule_main(
            symbols, executor, discord_notifier,
            schedule_hour=args.schedule_hour,
            schedule_minute=args.schedule_minute,
            max_concurrency=args.concurrency,
            start_stagger_sec=args.stagger
        ))


if __name__ == "__main__":
    main()