import asyncio
import argparse
import yaml
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from trade_bot.notification.discord import DiscordNotifier
from trade_bot.execution.trade_execution import TradeExecutor
from trade_bot.bot import TradeBot

DEFAULT_SYMBOLS = []

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
    all_signals = []
    bots = [
        TradeBot(symbol=symbol, executor=executor)  # strategies will be initialized inside the bot
        for symbol in symbols
    ]
    for bot in bots:
        try:
            print(f'🚀 Starting bot for symbol: {bot.symbol}...')
            async for signal_list in bot.run():
                all_signals.append({
                    "symbol": bot.symbol,
                    "signals": signal_list
                })
            print(f'✅ Finish bot for symbol: {bot.symbol}')
        except Exception as e:
            print(f"Error running bot for symbol {bot.symbol}: {e}")
        await asyncio.sleep(5)

    print("✅ All signals collected:")
    print(all_signals)

    if not all_signals:
        print("No signals generated. Skipping notification.")
        return
    
    summary_message = "Daily Trade Signals Summary:\n"
    for entry in all_signals:
        symbol = entry["symbol"]
        signals = entry["signals"]
        for signal in signals:
            summary_message += f"Symbol: {symbol}, Strategy: {signal.strategy}, Signal: {signal.signal}, Reason: {signal.reason}\n"
    print(f"Summary Message:\n{summary_message}")
    print("🔔🔔🔔 Sending summary notification to Discord...")
    try:
        await discord_notifier.send(summary_message)
    except Exception as e:
        print(f"Error sending summary notification to Discord: {e}")

async def schedule_main(symbols, executor, discord_notifier):
    scheduler = AsyncIOScheduler(timezone=pytz.timezone('US/Eastern'))
    scheduler.add_job(
        lambda: asyncio.create_task(run_all_bots(symbols, executor, discord_notifier)),
        CronTrigger(hour=16, minute=0)
    )
    scheduler.start()
    print("Scheduler started. Bots will run every day at 4pm US/Eastern.")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        pass

def main():
    parser = argparse.ArgumentParser(description="TraderCat Bot Runner")
    parser.add_argument(
        "-m", "--mode",
        choices=["once", "schedule"],
        default="once",
        help="Run once or schedule every day at 4pm US/Eastern"
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
    args = parser.parse_args()

    # 选择symbols来源
    if args.symbols:
        symbols = parse_symbols(args.symbols)
    elif args.symbols_file:
        symbols = load_symbols_from_file(args.symbols_file)
    else:
        symbols = DEFAULT_SYMBOLS

    symbols = list(set(symbols)) # remove duplication
    if not symbols:
        print("No symbols provided. Exiting.")
        return
    print(f"Total unique symbols to trade: {len(symbols)}")

    discord_notifier = DiscordNotifier()
    executor = TradeExecutor()

    if args.mode == "once":
        asyncio.run(run_all_bots(symbols, executor, discord_notifier))
    else:
        asyncio.run(schedule_main(symbols, executor, discord_notifier))

if __name__ == "__main__":
    main()