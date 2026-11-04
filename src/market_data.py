"""Read-only validation of daily EOD prices and matching USD/SEK."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import requests

INSTRUMENTS = (
    ("INVE-B.ST", "SEK"),
    ("ATCO-A.ST", "SEK"),
    ("SAND.ST", "SEK"),
    ("ABB.ST", "SEK"),
    ("MSFT.US", "USD"),
    ("NVDA.US", "USD"),
)


class MarketDataPreflightError(RuntimeError):
    """A user-visible, secret-free failure for the read-only data preflight."""


def _latest_complete(rows: list[dict[str, Any]], instrument: str) -> dict[str, Any]:
    valid = [
        row for row in rows
        if isinstance(row, dict)
        and isinstance(row.get("date"), str)
        and all(row.get(field) is not None for field in ("open", "high", "low", "close", "volume"))
    ]
    if not valid:
        raise MarketDataPreflightError(f"{instrument}: no complete daily OHLC record")
    return max(valid, key=lambda row: row["date"])


def _extract_observations(value: Any) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    if isinstance(value, dict):
        day = value.get("date") or value.get("period") or value.get("timePeriod")
        rate = value.get("value") or value.get("obsValue")
        if isinstance(day, str) and isinstance(rate, (int, float)):
            found.append((day[:10], float(rate)))
        for child in value.values():
            found.extend(_extract_observations(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_extract_observations(child))
    return found


def read_only_data_preflight(env: dict[str, str]) -> str:
    token = env.get("EODHD_API_KEY")
    if not token:
        raise MarketDataPreflightError("EODHD API key is not configured")

    start = (date.today() - timedelta(days=10)).isoformat()
    records: list[tuple[str, str, float, float]] = []
    for instrument, currency in INSTRUMENTS:
        response = requests.get(
            f"https://eodhd.com/api/eod/{instrument}",
            params={"api_token": token, "fmt": "json", "from": start},
            timeout=45,
        )
        if not response.ok:
            raise MarketDataPreflightError(f"{instrument}: EODHD HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, list):
            raise MarketDataPreflightError(f"{instrument}: invalid EODHD response")
        row = _latest_complete(payload, instrument)
        records.append((instrument, str(row["date"]), float(row["close"]), float(row["volume"])))

    session_dates = {item[1] for item in records}
    if len(session_dates) != 1:
        details = ", ".join(f"{instrument}={day}" for instrument, day, _, _ in records)
        raise MarketDataPreflightError(f"mixed session dates: {details}")
    session_date = session_dates.pop()

    fx_response = requests.get(
        f"https://api.riksbank.se/swea/v1/Observations/SEKUSDPMI/{session_date}/{session_date}",
        timeout=45,
    )
    if not fx_response.ok:
        raise MarketDataPreflightError(f"USD/SEK: Riksbank HTTP {fx_response.status_code}")
    observations = _extract_observations(fx_response.json())
    matching_fx = [rate for day, rate in observations if day == session_date]
    if len(matching_fx) != 1:
        raise MarketDataPreflightError("USD/SEK: matching dated Riksbank observation not found")

    overview = "; ".join(
        f"{instrument} {close:g} ({volume:g})" for instrument, _, close, volume in records
    )
    return (
        f"DATA REDO — read-only validation passed for {session_date}; "
        f"6 complete EODHD records and matching USD/SEK ({matching_fx[0]:g}) from Riksbanken. "
        f"Snapshot: {overview}. Excel and OneDrive were not changed."
    )
