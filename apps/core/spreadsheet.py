"""
Real Excel files (.xlsx): reading uploaded workbooks and writing downloads.

Downloads are proper workbooks — a bold frozen header, filters, sensible column widths, money and dates
as real numbers and dates — so they open in Excel, LibreOffice and Google Sheets without the
"Save as CSV" dance. Text is always written as text, so a guest called "=HYPERLINK(...)" can't become a formula.
"""

import io
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse
from django.utils import timezone

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def is_xlsx(raw: bytes) -> bool:
    return raw[:4] == b"PK\x03\x04"


def _cell_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, datetime):
        return v.strftime("%d.%m.%Y") if (v.hour, v.minute, v.second) == (0, 0, 0) else v.strftime("%d.%m.%Y %H:%M")
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    if isinstance(v, float):
        # 2.5 → "2.5", 3.0 → "3", and no 0.30000000000000004
        d = Decimal(repr(v)).normalize()
        return f"{d:f}"
    if isinstance(v, int):
        return str(v)
    return str(v).strip()


def read_rows(raw: bytes, limit: int = 6000) -> list[list[str]]:
    """The first sheet of a workbook as rows of text. Raises ValueError if it can't be read."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as e:  # zipfile.BadZipFile, KeyError, InvalidFileException…
        raise ValueError(str(e)) from e
    try:
        ws = wb.worksheets[0]
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append([_cell_text(v) for v in row])
            if len(rows) > limit:
                break
        return rows
    finally:
        wb.close()


class Sheet:
    def __init__(self, title: str, header: list, rows=(), *, money: tuple = (), widths: dict | None = None):
        self.title = str(title)[:31] or "Sheet"
        self.header = [str(h) for h in header]
        self.rows = rows
        self.money = set(money)  # column indexes shown as 1,234.50
        self.widths = widths or {}


def _write_sheet(ws, sheet: Sheet):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    bold = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="2F4858")
    ws.title = "".join(ch for ch in sheet.title if ch not in "[]:*?/\\") or "Sheet"
    ws.append(sheet.header)
    for cell in ws[1]:
        cell.font = bold
        cell.fill = fill
        cell.alignment = Alignment(vertical="center")
    widths = [len(h) for h in sheet.header]
    n = 1
    for row in sheet.rows:
        n += 1
        for col, v in enumerate(row, start=1):
            if isinstance(v, datetime):
                v = timezone.localtime(v).replace(tzinfo=None) if timezone.is_aware(v) else v
            elif v is None:
                v = ""
            elif not isinstance(v, (int, float, Decimal, date, bool, str)):
                v = str(v)
            cell = ws.cell(row=n, column=col, value=v)
            if isinstance(v, str):
                cell.data_type = "s"  # never a formula
            elif isinstance(v, Decimal):
                cell.number_format = "#,##0.00" if (col - 1) in sheet.money else "General"
            elif isinstance(v, datetime):
                cell.number_format = "DD.MM.YYYY HH:MM"
            elif isinstance(v, date):
                cell.number_format = "DD.MM.YYYY"
            if (col - 1) in sheet.money and isinstance(v, (int, float)):
                cell.number_format = "#,##0.00"
            text = len(_cell_text(v))
            if col - 1 < len(widths):
                widths[col - 1] = max(widths[col - 1], min(text, 60))
            else:
                widths.append(min(text, 60))
    for i, w in enumerate(widths):
        ws.column_dimensions[get_column_letter(i + 1)].width = sheet.widths.get(i, max(8, w + 2))
    ws.freeze_panes = "A2"
    if sheet.header:
        ws.auto_filter.ref = f"A1:{get_column_letter(max(len(sheet.header), 1))}{max(n, 1)}"


def workbook_bytes(*sheets: Sheet) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    first = True
    for sheet in sheets:
        ws = wb.active if first else wb.create_sheet()
        first = False
        _write_sheet(ws, sheet)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def response(filename: str, *sheets: Sheet) -> HttpResponse:
    if not filename.endswith(".xlsx"):
        filename += ".xlsx"
    resp = HttpResponse(workbook_bytes(*sheets), content_type=XLSX_TYPE)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
