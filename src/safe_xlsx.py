"""Minimal XLSX editor: only Run_Log XML may be changed in the write test."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree as ET

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


def append_run_log_only(book: bytes, run_id: str, version: str) -> bytes:
    """Append exactly one log row and reject any mutation outside Run_Log."""
    with ZipFile(BytesIO(book), "r") as source:
        files = {info.filename: source.read(info.filename) for info in source.infolist()}
    target = _sheet_path(files, "Run_Log")
    sheet = ET.fromstring(files[target])
    data = sheet.find(q("sheetData"))
    rows = data.findall(q("row"))
    for row in rows[1:]:
        first = row.find(q("c"))
        text = first.find(f".//{q('t')}") if first is not None else None
        if text is not None and text.text == run_id:
            raise WorkbookSafetyError("Duplicate Run ID")
    row_number = max(int(row.attrib["r"]) for row in rows) + 1
    now = datetime.now(timezone.utc).replace(microsecond=0)
    serial = (now - datetime(1899, 12, 30, tzinfo=timezone.utc)).total_seconds() / 86400
    values = [run_id, serial, serial, "SE/US", "NO ACTION", "CONTROLLED AZURE WRITE TEST", 0, 0, version, "Exactly one Run_Log row added; no data, signals, orders, holdings or transactions changed."]
    template = {cell.attrib["r"]: cell for cell in rows[-1].findall(q("c"))}
    new_row = ET.Element(q("row"), {"r": str(row_number)})
    for index, value in enumerate(values, 1):
        letter = col(index)
        new_row.append(_inline(f"{letter}{row_number}", value, template.get(f"{letter}{row_number - 1}")))
    data.append(new_row)
    for tag in ("dimension", "autoFilter"):
        node = sheet.find(q(tag))
        if node is not None:
            node.set("ref", f"A1:J{row_number}")
    files[target] = ET.tostring(sheet, encoding="utf-8", xml_declaration=True)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=6) as destination:
        for name, content in files.items():
            destination.writestr(name, content)
    result = output.getvalue()
    with ZipFile(BytesIO(result), "r") as check:
        for name, content in files.items():
            if name != target and sha256(check.read(name)).digest() != sha256(content).digest():
                raise WorkbookSafetyError(f"Unexpected change outside Run_Log: {name}")
    return result
