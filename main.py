import asyncio
import argparse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from trade_bot.data.openbb_provider import OpenBBProvider
from trade_bot.notification.discord import DiscordNotifier
from trade_bot.strategy.divergence_strategy import DivergenceStrategy
from trade_bot.strategy.hidden_divergence_strategy import HiddenDivergenceStrategy
from trade_bot.execution.trade_execution import TradeExecutor
from trade_bot.bot import TradeBot

# Top 20 S&P 500 Companies
SP_500_SYMBOLS = ['NVDA', 'MSFT', 'AAPL', 'GOOG', 'AMZN', 'META', 'AVGO', 'TSLA', 'BRK.B', 'JPM', 'WMT', 'V', 'ORCL', 'LLY', 'NFLX', 'MA', 'XOM', 'JNJ', 'COST', 'PG']
# Top 20 Nasdaq-100 Companies
NASDAQ_100_SYMBOLS = ['NVDA', 'MSFT', 'AAPL', 'AMZN', 'GOOG', 'GOOGL', 'META', 'AVGO', 'TSLA', 'NFLX', 'COST', 'ASML', 'TMUS', 'CSCO', 'LIN', 'AMD', 'AZN', 'INTU', 'TXN', 'ISRG']
# Top 20 Dow Jones Companies
DOW_JONES_SYMBOLS = ['NVDA', 'MSFT', 'AAPL', 'AMZN', 'JPM', 'WMT', 'V', 'JNJ', 'HD', 'PG', 'UNH', 'CVX', 'KO', 'CSCO', 'IBM', 'CRM', 'GS', 'AXP', 'MCD', 'MRK']

# SYMBOLS = list(set(SP_500_SYMBOLS + NASDAQ_100_SYMBOLS + DOW_JONES_SYMBOLS))
SYMBOLS = ['NVDA', 'MSFT']
print(f"Total unique symbols to trade: {len(SYMBOLS)}")

strategies = [ DivergenceStrategy(), HiddenDivergenceStrategy() ]

provider = OpenBBProvider()
executor = TradeExecutor()
discord_notifier = DiscordNotifier()

async def run_all_bots():
    all_signals = []
    bots = [
        TradeBot(
            data_provider=provider,
            strategies=strategies,
            executor=executor,
            symbol=symbol
        )
        for symbol in SYMBOLS
    ]
    for bot in bots:
        try:
            print(f'🚀🚀🚀 Starting bot for symbol: {bot.symbol}...')
            async for signal_list in bot.run():
                all_signals.append({
                    "symbol": bot.symbol,
                    "signals": signal_list
                })
            print(f'✅ Finish bot for symbol: {bot.symbol}')
        except Exception as e:
            print(f"Error running bot for symbol {bot.symbol}: {e}")
        await asyncio.sleep(5)

    # 这里 all_signals 就是所有 bot 的信号列表
    print("✅ All signals collected:")
    print(all_signals)

    # Send a summary notification
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

async def schedule_main():
    scheduler = AsyncIOScheduler(timezone=pytz.timezone('US/Eastern'))
    scheduler.add_job(lambda: asyncio.create_task(run_all_bots()), CronTrigger(hour=16, minute=0))
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
        "--mode",
        choices=["once", "schedule"],
        default="once",
        help="Run once or schedule every day at 4pm US/Eastern"
    )
    args = parser.parse_args()

    if args.mode == "once":
        asyncio.run(run_all_bots())
    else:
        asyncio.run(schedule_main())

if __name__ == "__main__":
    main()