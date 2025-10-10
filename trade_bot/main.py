import asyncio
import argparse
import pandas as pd
from datetime import datetime
import yaml
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from trade_bot.notification.discord import DiscordNotifier
from trade_bot.execution.trade_execution import TradeExecutor
from trade_bot.bot import TradeBot

DEFAULT_SYMBOLS_STR = os.environ.get("ENV_SYMBOLS") # e.g. "AAPL,MSFT,GOOG"
print(f"Default symbols from ENV_SYMBOLS: {DEFAULT_SYMBOLS_STR}")

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

async def run_all_bots(symbols, executor, discord_notifier):
    start_time = datetime.now()  # ⏱️ Start timer

    all_signals = []
    bots = [
        TradeBot(symbol=symbol, executor=executor)  # strategies will be initialized inside the bot
        for symbol in symbols
    ]

    for index, bot in enumerate(bots):
        try:
            print(f'🚀 Start bot[{index}] for symbol: {bot.symbol}...')
            async for signal_list in bot.run():
                all_signals.append({
                    "symbol": bot.symbol,
                    "signals": signal_list
                })
            print(f'✅ Finish bot[{index}] for symbol: {bot.symbol}')
        except Exception as e:
            print(f"Error running bot[{index}] for symbol {bot.symbol}: {e}")
        await asyncio.sleep(5)


    print(f"✅ All signals collected from {len(bots)} symbols")

    if not all_signals:
        print("No signals generated. Skipping notification.")
        return
    
    # 🔄 Convert to CSV
    rows = []
    for entry in all_signals:
        for signal in entry["signals"]:
            rows.append({
                "Close_Date": signal.date,
                "Symbol": signal.symbol,
                "Strategy": signal.strategy,
                "Signal": signal.signal,
                "Confidence": signal.confidence,
                "Reason": signal.reason,
                "Details": signal.details
            })
    df = pd.DataFrame(rows)
    csv_filename = f"trade_signals_{datetime.now().strftime('%Y%m%d%H%M%S')}.csv"
    df.to_csv(csv_filename, index=False)
    print(f"📄 Signals CSV created: {csv_filename}")
    
    # 🔔 Send summary notification to Discord
    today_str = datetime.today().strftime("%Y-%m-%d")
    title_message = f"** :money_with_wings: Daily [{today_str}] Trade Signals Summary: **\n"
    summary_message = ""
    for entry in all_signals:
        symbol = entry["symbol"]
        signals = entry["signals"]
        sell_buy_signals = [ signal for signal in signals if signal.signal == "buy" or signal.signal == "sell" ]
        for signal in sell_buy_signals:
            summary_message += f"* *Symbol: {symbol}, Strategy: {signal.strategy}, Signal: {signal.signal}, Confidence: {signal.confidence} Reason: {signal.reason}*\n"
    
    if not summary_message:
        summary_message = "No buy/sell signals generated. "

    print(f"Summary Message:\n{title_message + summary_message}")
    print("🔔 Sending summary notification to Discord...")
    try:
        await discord_notifier.send(title_message + summary_message)
    except Exception as e:
        print(f"Error sending summary notification to Discord: {e}")
    
    # ⏱️ Log execution time
    end_time = datetime.now()  # ⏱️ End timer
    duration = end_time - start_time
    total_seconds = int(duration.total_seconds())
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    print(f"🕒 Total execution time: {minutes} minutes and {seconds} seconds")

async def schedule_main(symbols, executor, discord_notifier, schedule_hour=16, schedule_minute=0):
    scheduler = AsyncIOScheduler(timezone=pytz.timezone('US/Eastern'))
    scheduler.add_job(
        lambda: asyncio.create_task(run_all_bots(symbols, executor, discord_notifier)),
        CronTrigger(hour=schedule_hour, minute=schedule_minute)
    )
    print(f"Scheduler started. Bots will run every day at {schedule_hour:02d}:{schedule_minute:02d} US/Eastern.")
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

    if args is None:
        args = parser.parse_args()
    else:
        args = parser.parse_args(args)
    
    # 选择symbols来源
    if args.symbols:
        print(f"Symbols provided via command line: {args.symbols}")
        symbols = parse_symbols(args.symbols)
    elif args.symbols_file:
        print(f"Loading symbols from file: {args.symbols_file}")
        symbols = load_symbols_from_file(args.symbols_file)
    else:
        print("Loading symbols from default environment variable [DEFAULT_SYMBOLS_STR].")
        symbols = DEFAULT_SYMBOLS_STR and parse_symbols(DEFAULT_SYMBOLS_STR) or []

    symbols = list(dict.fromkeys(symbols)) # remove duplication
    if not symbols:
        print("No symbols provided. Exiting.")
        return
    print(f"Total unique symbols to trade: {len(symbols)}")

    discord_notifier = DiscordNotifier()
    executor = TradeExecutor()

    if args.mode == "once":
        asyncio.run(run_all_bots(symbols, executor, discord_notifier))
    else:
        asyncio.run(schedule_main(
            symbols, executor, discord_notifier,
            schedule_hour=args.schedule_hour,
            schedule_minute=args.schedule_minute
        ))

if __name__ == "__main__":
    main()