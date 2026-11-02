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


@app.function_name(name="manual_preflight")
@app.route(route="manual-preflight", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def manual_preflight(_: func.HttpRequest) -> func.HttpResponse:
    """Run a write-blocked check on demand; this endpoint always forces preflight."""
    safe_env = dict(os.environ)
    safe_env["RUN_MODE"] = "preflight"
    try:
        result = execute(safe_env)
    except Exception:
        logging.exception("Manual preflight failed")
        return func.HttpResponse(
            "ÅTGÄRD KRÄVS — preflight failed. Inspect Azure logs for details.",
            status_code=500,
        )
    return func.HttpResponse(result, status_code=200, mimetype="text/plain")
