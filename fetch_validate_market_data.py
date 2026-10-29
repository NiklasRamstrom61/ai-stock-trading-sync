"""Fetch and validate daily EODHD OHLC plus Riksbank USD/SEK.

The script creates a validated snapshot only.  It never edits Excel, OneDrive,
signals, orders, positions, or transactions.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "market_data_config.json"
OUTPUT = ROOT / "outputs" / "market_data"
EOD_URL = "https://eodhd.com/api/eod"
FX_URL = "https://api.riksbank.se/swea/v1/Observations/Latest/sekusdPMI"


class Rejected(RuntimeError):
    """Raised when safety requirements are not satisfied."""


def get_json(url: str, params: dict[str, str] | None = None):
    query = urllib.parse.urlencode(params or {})
    request = urllib.request.Request(
        f"{url}?{query}" if query else url, headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise Rejected(f"HTTP {error.code} from {url}") from error
    except urllib.error.URLError as error:
        raise Rejected(f"Could not reach {url}: {error.reason}") from error


def number(value, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise Rejected(f"Invalid {field}") from error


def fetch_equity(item: dict, api_key: str) -> dict:
    data = get_json(
        f"{EOD_URL}/{urllib.parse.quote(item['symbol'], safe='.-')}",
        {
            "api_token": api_key,
            "fmt": "json",
            "period": "d",
            "order": "d",
            "from": (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat(),
        },
    )
    if not isinstance(data, list) or not data:
        raise Rejected(f"{item['ticker']}: no daily price returned")
    bar = data[0]
    required = ("date", "open", "high", "low", "close", "volume")
    if any(bar.get(field) in (None, "") for field in required):
        raise Rejected(f"{item['ticker']}: incomplete daily OHLC row")
    return {
        "ticker": item["ticker"], "provider_symbol": item["symbol"],
        "market": item["exchange"], "session_date": str(bar["date"]),
        "open": number(bar["open"], "open"), "high": number(bar["high"], "high"),
        "low": number(bar["low"], "low"), "close": number(bar["close"], "close"),
        "volume": number(bar["volume"], "volume"), "currency": item["currency"],
        "source": "EODHD EOD",
    }


def find_observation(value):
    if isinstance(value, dict):
        date = value.get("date") or value.get("observationDate")
        rate = value.get("value") or value.get("valueNumber")
        if date is not None and rate is not None:
            return str(date), number(rate, "USD/SEK")
        for child in value.values():
            try:
                return find_observation(child)
            except Rejected:
                pass
    if isinstance(value, list):
        for child in value:
            try:
                return find_observation(child)
            except Rejected:
                pass
    raise Rejected("Riksbank response has no dated USD/SEK observation")


def validate_session(equities: list[dict], delay_minutes: int) -> str:
    dates = {row["session_date"] for row in equities}
    if len(dates) != 1:
        raise Rejected("The six instruments do not share one session date")
    session_date = dates.pop()
    now_us = datetime.now(ZoneInfo("America/New_York"))
    if session_date == now_us.date().isoformat():
        earliest = datetime.combine(now_us.date(), time(16, 0), tzinfo=now_us.tzinfo) + timedelta(minutes=delay_minutes)
        if now_us < earliest:
            raise Rejected(f"US session may still be incomplete; eligible after {earliest:%Y-%m-%d %H:%M %Z}")
    return session_date


def main() -> int:
    api_key = os.getenv("EODHD_API_KEY")
    if not api_key:
        raise Rejected("Missing EODHD_API_KEY")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    equities = [fetch_equity(item, api_key) for item in config["equities"]]
    session_date = validate_session(equities, config["requirements"]["minimum_completed_session_delay_minutes"])
    fx_date, fx = find_observation(get_json(FX_URL))
    if fx <= 0 or fx_date != session_date:
        raise Rejected("USD/SEK date does not match the completed US session date")
    snapshot = {
        "retrieved_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "validated", "equities": equities,
        "usd_sek": {"date": fx_date, "sek_per_usd": fx, "source": "Sveriges Riksbank SWEA"},
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / f"daily_snapshot_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Rejected as error:
        print(f"REJECTED: {error}", file=sys.stderr)
        raise SystemExit(2)
