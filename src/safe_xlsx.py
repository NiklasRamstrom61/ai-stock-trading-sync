"""Minimal XLSX editor with a fail-closed Market_Data and Run_Log sync path."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET

from .market_data import ValidatedMarketData

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", MAIN)
ET.register_namespace("r", REL)


class WorkbookSafetyError(RuntimeError):
    pass


def q(name: str) -> str:
    return f"{{{MAIN}}}{name}"


def col(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _sheet_path(files: dict[str, bytes], name: str) -> str:
    book = ET.fromstring(files["xl/workbook.xml"])
    rels = ET.fromstring(files["xl/_rels/workbook.xml.rels"])
    targets = {r.attrib["Id"]: r.attrib["Target"] for r in rels.findall(f"{{{PKG}}}Relationship")}
    for sheet in book.find(q("sheets")):
        if sheet.attrib.get("name") == name:
            target = targets[sheet.attrib[f"{{{REL}}}id"]].lstrip("/")
            return target if target.startswith("xl/") else "xl/" + target
    raise WorkbookSafetyError(f"Missing sheet: {name}")


def _inline(ref: str, value, template: ET.Element | None) -> ET.Element:
    attrs = {"r": ref}
    if template is not None and "s" in template.attrib:
        attrs["s"] = template.attrib["s"]
    if isinstance(value, (int, float)):
        cell = ET.Element(q("c"), attrs)
        ET.SubElement(cell, q("v")).text = str(value)
        return cell
    cell = ET.Element(q("c"), {**attrs, "t": "inlineStr"})
    inner = ET.SubElement(cell, q("is"))
    ET.SubElement(inner, q("t")).text = str(value)
    return cell


def _shared_strings(files: dict[str, bytes]) -> list[str]:
    raw = files.get("xl/sharedStrings.xml")
    if raw is None:
        return []
    root = ET.fromstring(raw)
    return ["".join(node.itertext()) for node in root.findall(q("si"))]


def _cell_text(cell: ET.Element | None, shared: list[str]) -> str:
    if cell is None:
        return ""
    inline = cell.find(f".//{q('t')}")
    if inline is not None and inline.text is not None:
        return inline.text
    value = cell.find(q("v"))
    if value is None or value.text is None:
        return ""
    if cell.attrib.get("t") == "s":
        try:
            return shared[int(value.text)]
        except (IndexError, ValueError):
            raise WorkbookSafetyError("Invalid shared string reference")
    return value.text


def _row_values(row: ET.Element, shared: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for cell in row.findall(q("c")):
        reference = cell.attrib.get("r", "")
        letter = "".join(ch for ch in reference if ch.isalpha())
        values[letter] = _cell_text(cell, shared)
    return values


def _excel_serial(value: datetime) -> float:
    return (value - datetime(1899, 12, 30, tzinfo=timezone.utc)).total_seconds() / 86400


def _iso_date(value: str) -> str:
    if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        return value[:10]
    try:
        converted = datetime(1899, 12, 30, tzinfo=timezone.utc)
        return (converted + timedelta(days=float(value))).date().isoformat()
    except (ValueError, OverflowError):
        return value


def _append_values(
    data: ET.Element,
    values: list[object],
    row_number: int,
    template_row: ET.Element,
) -> None:
    template = {
        cell.attrib["r"]: cell
        for cell in template_row.findall(q("c"))
        if "r" in cell.attrib
    }
    new_row = ET.Element(q("row"), {"r": str(row_number)})
    for index, value in enumerate(values, 1):
        letter = col(index)
        new_row.append(_inline(f"{letter}{row_number}", value, template.get(f"{letter}{row_number - 1}")))
    data.append(new_row)


def _update_table_range(sheet: ET.Element, end_column: str, row_number: int) -> None:
    for tag in ("dimension", "autoFilter"):
        node = sheet.find(q(tag))
        if node is not None:
            node.set("ref", f"A1:{end_column}{row_number}")


def _serialize_with_integrity(
    files: dict[str, bytes],
    changed: dict[str, ET.Element],
) -> bytes:
    originals = dict(files)
    for path, sheet in changed.items():
        files[path] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as destination:
        for name, content in files.items():
            destination.writestr(name, content)
    result = output.getvalue()
    with ZipFile(BytesIO(result), "r") as check:
        for name, content in originals.items():
            if name not in changed and sha256(check.read(name)).digest() != sha256(content).digest():
                raise WorkbookSafetyError(f"Unexpected change outside permitted sheets: {name}")
    return result


def append_run_log_only(book: bytes, run_id: str, version: str) -> bytes:
    """Append exactly one log row and reject any mutation outside Run_Log."""
    with ZipFile(BytesIO(book), "r") as source:
        files = {info.filename: source.read(info.filename) for info in source.infolist()}
    target = _sheet_path(files, "Run_Log")
    sheet = ET.fromstring(files[target])
    data = sheet.find(q("sheetData"))
    rows = data.findall(q("row"))
    shared = _shared_strings(files)
    for row in rows[1:]:
        if _row_values(row, shared).get("A") == run_id:
            raise WorkbookSafetyError("Duplicate Run ID")
    row_number = max(int(row.attrib["r"]) for row in rows) + 1
    now = datetime.now(timezone.utc).replace(microsecond=0)
    serial = _excel_serial(now)
    values = [
        run_id, serial, serial, "SE/US", "NO ACTION", "CONTROLLED AZURE WRITE TEST",
        0, 0, version,
        "Exactly one Run_Log row added; no data, signals, orders, holdings or transactions changed.",
    ]
    _append_values(data, values, row_number, rows[-1])
    _update_table_range(sheet, "J", row_number)
    return _serialize_with_integrity(files, {target: sheet})


def append_market_data_and_run_log(
    book: bytes,
    validated: ValidatedMarketData,
    run_id: str,
    version: str,
) -> bytes:
    """Append six validated market rows and one audit row; mutate nothing else."""
    with ZipFile(BytesIO(book), "r") as source:
        files = {info.filename: source.read(info.filename) for info in source.infolist()}
    market_path = _sheet_path(files, "Market_Data")
    log_path = _sheet_path(files, "Run_Log")
    market_sheet = ET.fromstring(files[market_path])
    log_sheet = ET.fromstring(files[log_path])
    market_data = market_sheet.find(q("sheetData"))
    log_data = log_sheet.find(q("sheetData"))
    market_rows = market_data.findall(q("row"))
    log_rows = log_data.findall(q("row"))
    if len(validated.records) != 6:
        raise WorkbookSafetyError("Expected exactly six validated market records")
    shared = _shared_strings(files)

    requested_tickers = {record.workbook_ticker for record in validated.records}
    for row in market_rows[1:]:
        values = _row_values(row, shared)
        if values.get("A") in requested_tickers and _iso_date(values.get("C", "")) == validated.session_date:
            raise WorkbookSafetyError("Duplicate Market_Data session")
    for row in log_rows[1:]:
        if _row_values(row, shared).get("A") == run_id:
            raise WorkbookSafetyError("Duplicate Run ID")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    now_serial = _excel_serial(now)
    session_serial = _excel_serial(datetime.fromisoformat(validated.session_date).replace(tzinfo=timezone.utc))
    next_market_row = max(int(row.attrib["r"]) for row in market_rows) + 1
    for record in validated.records:
        fx = 1 if record.currency == "SEK" else validated.usdsek
        note = (
            "Complete daily OHLC from EODHD."
            if record.currency == "SEK"
            else "Complete daily OHLC from EODHD. USD/SEK from Sveriges Riksbank SWEA."
        )
        values = [
            record.workbook_ticker, record.market, session_serial, record.open, record.high,
            record.low, record.close, record.volume, record.currency, fx,
            f"https://eodhd.com/api/eod/{record.source_ticker}", now_serial, 1, note,
        ]
        _append_values(market_data, values, next_market_row, market_rows[-1])
        next_market_row += 1

    next_log_row = max(int(row.attrib["r"]) for row in log_rows) + 1
    log_values = [
        run_id, now_serial, now_serial, "SE/US", "DATA INGESTED", "VALIDATED EODHD DAILY OHLC",
        0, 0, version,
        "6 complete daily-OHLC rows added. No signals, orders, holdings or transactions changed.",
    ]
    _append_values(log_data, log_values, next_log_row, log_rows[-1])
    _update_table_range(market_sheet, "N", next_market_row - 1)
    _update_table_range(log_sheet, "J", next_log_row)
    return _serialize_with_integrity(files, {market_path: market_sheet, log_path: log_sheet})
