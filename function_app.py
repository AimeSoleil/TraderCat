import logging
import subprocess
import azure.functions as func
from azure.functions import TimerRequest
import datetime

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

    try:
        result = subprocess.run(
            ["python", "trade_bot/main.py", "-f", "sample_symbols.yml", "-m", "once"],
            check=True,
            capture_output=True,
            text=True
        )
        logging.info(f"Trade bot output:\n{result.stdout}")
        if result.stderr:
            logging.warning(f"Trade bot error output:\n{result.stderr}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Trade bot failed with return code {e.returncode}")
        logging.error(f"Error output:\n{e.stderr}")
