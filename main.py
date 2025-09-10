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

SYMBOLS = ['FFAI']  # 支持多个股票代码

strategies = [
    DivergenceStrategy(),
    HiddenDivergenceStrategy()
]

provider = OpenBBProvider()
executor = TradeExecutor()
discord_notifier = DiscordNotifier()


async def run_all_bots():
    bots = [
        TradeBot(
            data_provider=provider,
            strategies=strategies,
            executor=executor,
            notifiers=[discord_notifier],
            symbol=symbol
        )
        for symbol in SYMBOLS
    ]
    await asyncio.gather(*(bot.run() for bot in bots))


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