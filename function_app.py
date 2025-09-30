import logging
import subprocess
import azure.functions as func
from azure.functions import TimerRequest
import datetime

from trade_bot.main import main

# An reserved entry point for Azure Function;
# Comment those code as I temporarily give up Azure Function deployment 
# after trying several times successful deployment but can't find the function in azure portal. 
# You can uncomment and use it if you want to deploy to Azure Function.
# Make sure you have the `azure-functions` package in your environment.

# app = func.FunctionApp()

# @app.function_name(name="TradeBotTrigger")
# @app.schedule(schedule="0 30 8 * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
# def run_trade_bot(timer: TimerRequest) -> None:
#     """
#         Azure Function to trigger the trade bot daily at 8:30 PM UTC.
#         Azure Functions use UTC time by default. So:
#         0 30 20 * * * = 8:30 PM UTC, which is 4:30 PM US Eastern Time during Daylight Saving Time.
#     """
#     logging.info(f"Function triggered at: {datetime.datetime.now(datetime.UTC).isoformat()} UTC")

#     try:
#         main(["--mode", "once"])
#     except subprocess.CalledProcessError as e:
#         logging.error(f"Trade bot failed with return code {e.returncode}")
#         logging.error(f"Error output:\n{e.stderr}")
