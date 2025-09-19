import asyncio
import logging
import subprocess
import azure.functions as func
from azure.functions import TimerRequest
import datetime

from trade_bot.execution.trade_execution import TradeExecutor
from trade_bot.main import run_all_bots
from trade_bot.notification.discord import DiscordNotifier

app = func.FunctionApp()

@app.function_name(name="TradeBotTrigger")
@app.schedule(schedule="0 40 8 * * *", arg_name="mytimer", run_on_startup=False, use_monitor=True)
def run_trade_bot(mytimer: TimerRequest) -> None:
    """
        Azure Function to trigger the trade bot daily at 8:30 PM UTC.
        Azure Functions use UTC time by default. So:
        0 30 20 * * * = 8:30 PM UTC, which is 4:30 PM US Eastern Time during Daylight Saving Time.
    """
    logging.info(f"Function triggered at: {datetime.datetime.now(datetime.UTC).isoformat()} UTC")

    symbols = ["AAPL", "MSFT", "GOOG"]
    discord_notifier = DiscordNotifier()
    executor = TradeExecutor()  # Example symbols, replace with your logic to load symbols
    asyncio.run(run_all_bots(symbols, executor, discord_notifier))