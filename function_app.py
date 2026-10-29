"""Azure Functions entry point. Default mode cannot alter the workbook."""
import logging
import os

import azure.functions as func

from src.runner import execute

app = func.FunctionApp()


@app.function_name(name="market_data_sync")
@app.schedule(schedule="%TIMER_SCHEDULE%", arg_name="timer", use_monitor=True)
def market_data_sync(timer: func.TimerRequest) -> None:
    if timer.past_due:
        logging.warning("Timer is past due; safety checks still apply.")
    logging.info("%s", execute(os.environ))
