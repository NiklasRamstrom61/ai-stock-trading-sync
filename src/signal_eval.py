"""Read-only, deterministic paper-trading signal evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

from .market_data import INSTRUMENTS, MarketDataPreflightError

_NEW_YORK = ZoneInfo("America/New_York")
_EOD_READY_TIME = time(16, 30)


@dataclass(frozen=True)
class SignalCandidate:
    ticker: str
    decision: str
    close: float
    sma20: float
    return_5d: float
    volume_ratio: float
    reason: str


def _complete_rows(payload: object, ticker: str) -> list[dict]:
    if not isinstance(payload, list):
        raise MarketDataPreflightError(f"{ticker}: invalid EODHD response")
    rows = [
        row for row in payload
        if isinstance(row, dict)
        and isinstance(row.get("date"), str)
        and all(row.get(field) is not None for field in ("open", "high", "low", "close", "volume"))
    ]
    if len(rows) < 21:
        raise MarketDataPreflightError(f"{ticker}: fewer than 21 complete daily sessions")
    return sorted(rows, key=lambda row: str(row["date"]))


def _validate_completed_session(session_date: str) -> None:
    """Accept today's data only after a conservative New York EOD grace period."""
    try:
        observed = date.fromisoformat(session_date)
    except ValueError as error:
        raise MarketDataPreflightError("invalid latest session date") from error

    now_ny = datetime.now(_NEW_YORK)
    if observed > now_ny.date():
        raise MarketDataPreflightError("latest market session is dated in the future")
    if observed == now_ny.date() and now_ny.time() < _EOD_READY_TIME:
        raise MarketDataPreflightError(
            "USA session is not yet eligible as completed daily data; retry after 16:30 New York time"
        )


def evaluate_signals_read_only(env: dict[str, str]) -> str:
    """Evaluate transparent candidates only; does not read or mutate the workbook."""
    token = env.get("EODHD_API_KEY")
    if not token:
        raise MarketDataPreflightError("EODHD API key is not configured")

    start = (date.today() - timedelta(days=45)).isoformat()
    candidates: list[SignalCandidate] = []
    session_dates: set[str] = set()
    for source_ticker, workbook_ticker, _market, _currency in INSTRUMENTS:
        response = requests.get(
            f"https://eodhd.com/api/eod/{source_ticker}",
            params={"api_token": token, "fmt": "json", "from": start},
            timeout=45,
        )
        if not response.ok:
            raise MarketDataPreflightError(f"{source_ticker}: EODHD HTTP {response.status_code}")
        rows = _complete_rows(response.json(), source_ticker)
        latest = rows[-1]
        session_dates.add(str(latest["date"]))
        closes = [float(row["close"]) for row in rows[-21:]]
        volumes = [float(row["volume"]) for row in rows[-21:]]
        sma20 = sum(closes[-20:]) / 20
        return_5d = closes[-1] / closes[-6] - 1
        volume_ratio = volumes[-1] / (sum(volumes[-21:-1]) / 20)
        if closes[-1] > sma20 and return_5d >= 0.02 and volume_ratio >= 0.80:
            decision = "BUY CANDIDATE"
            reason = "Close above 20-session average; 5-session momentum at least 2%; volume support."
        else:
            decision = "WATCH"
            reason = "Entry criteria not all met."
        candidates.append(
            SignalCandidate(
                ticker=workbook_ticker,
                decision=decision,
                close=closes[-1],
                sma20=sma20,
                return_5d=return_5d,
                volume_ratio=volume_ratio,
                reason=reason,
            )
        )

    if len(session_dates) != 1:
        detail = ", ".join(sorted(session_dates))
        raise MarketDataPreflightError(f"mixed latest session dates: {detail}")
    session_date = session_dates.pop()
    _validate_completed_session(session_date)

    report = "; ".join(
        f"{candidate.ticker}: {candidate.decision}, close {candidate.close:g}, "
        f"SMA20 {candidate.sma20:g}, 5d {candidate.return_5d:.1%}, "
        f"volume {candidate.volume_ratio:.2f}x"
        for candidate in candidates
    )
    count = sum(candidate.decision == "BUY CANDIDATE" for candidate in candidates)
    return (
        f"DATA REDO — read-only signal evaluation for {session_date}: {count} buy candidates. "
        f"{report}. No signals, orders, holdings, transactions, Excel or OneDrive were changed."
    )
