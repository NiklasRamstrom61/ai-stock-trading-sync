"""Validated daily market-data retrieval shared by read-only and sync paths."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests

INSTRUMENTS = (
    ("INVE-B.ST", "INVE.B", "SE", "SEK"),
    ("ATCO-A.ST", "ATCO.A", "SE", "SEK"),
    ("SAND.ST", "SAND", "SE", "SEK"),
    ("ABB.ST", "ABB", "SE", "SEK"),
    ("MSFT.US", "MSFT", "US", "USD"),
    ("NVDA.US", "NVDA", "US", "USD"),
)


class MarketDataPreflightError(RuntimeError):
    """A user-visible, secret-free failure for the data preflight."""


@dataclass(frozen=True)
class MarketRecord:
    source_ticker: str
    workbook_ticker: str
    market: str
    currency: str
    session_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class ValidatedMarketData:
    session_date: str
    usdsek: float
    records: tuple[MarketRecord, ...]


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


def load_validated_market_data(env: dict[str, str]) -> ValidatedMarketData:
    """Fetch six complete EOD records and the matching dated USD/SEK rate."""
    token = env.get("EODHD_API_KEY")
    if not token:
        raise MarketDataPreflightError("EODHD API key is not configured")

    start = (date.today() - timedelta(days=10)).isoformat()
    records: list[MarketRecord] = []
    for source_ticker, workbook_ticker, market, currency in INSTRUMENTS:
        response = requests.get(
            f"https://eodhd.com/api/eod/{source_ticker}",
            params={"api_token": token, "fmt": "json", "from": start},
            timeout=45,
        )
        if not response.ok:
            raise MarketDataPreflightError(f"{source_ticker}: EODHD HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, list):
            raise MarketDataPreflightError(f"{source_ticker}: invalid EODHD response")
        row = _latest_complete(payload, source_ticker)
        records.append(
            MarketRecord(
                source_ticker=source_ticker,
                workbook_ticker=workbook_ticker,
                market=market,
                currency=currency,
                session_date=str(row["date"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )

    session_dates = {record.session_date for record in records}
    if len(session_dates) != 1:
        details = ", ".join(f"{record.source_ticker}={record.session_date}" for record in records)
        raise MarketDataPreflightError(f"mixed session dates: {details}")
    session_date = session_dates.pop()
    if session_date >= date.today().isoformat():
        raise MarketDataPreflightError("USA session is not yet eligible as completed daily data")

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

    return ValidatedMarketData(
        session_date=session_date,
        usdsek=matching_fx[0],
        records=tuple(records),
    )


def read_only_data_preflight(env: dict[str, str]) -> str:
    validated = load_validated_market_data(env)
    overview = "; ".join(
        f"{record.source_ticker} {record.close:g} ({record.volume:g})"
        for record in validated.records
    )
    return (
        f"DATA REDO — read-only validation passed for {validated.session_date}; "
        f"6 complete EODHD records and matching USD/SEK ({validated.usdsek:g}) from Riksbanken. "
        f"Snapshot: {overview}. Excel and OneDrive were not changed."
    )
