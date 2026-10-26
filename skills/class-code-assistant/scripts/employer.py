"""Load one employer file (a folder of Markdown and CSV records) into plain data.

CSV records are recognised by their columns, not their file names, so a renamed
export still loads. Files this Skill cannot use are listed so the report can say so.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Columns that identify each kind of record.
RECORD_KINDS = {
    "payroll_register": {"employee_id", "name", "position", "wages_paid"},
    "timesheets": {"date", "employee_id", "work_type", "hours"},
    "route_log": {"date", "route_id", "driver_id", "ride_along_id"},
    "site_signins": {"date", "employee_id", "site"},
    "weekly_payroll": {"week_start", "week_end", "employee_id", "gross_pay"},
    "subcontractor_payments": {"date", "subcontractor", "work", "amount_paid"},
    "certificates": {"subcontractor", "coverage_from", "coverage_to"},
}


class EmployerFileError(ValueError):
    pass


@dataclass
class ReportedLine:
    code: str
    employees: int
    payroll: Decimal


@dataclass
class OwnerStatement:
    name: str
    excluded: bool
    sentence: str


@dataclass
class Employer:
    slug: str
    folder: Path
    name: str
    application_id: str
    reported: list[ReportedLine]
    employer_note: str
    period_start: dt.date
    period_end: dt.date
    description: str
    field_notes: str
    owners: list[OwnerStatement]
    records: dict[str, list[dict]] = field(default_factory=dict)
    record_files: dict[str, str] = field(default_factory=dict)
    unused_files: dict[str, str] = field(default_factory=dict)

    def in_period(self, day: dt.date) -> bool:
        return self.period_start <= day <= self.period_end


def money(value: str, where: str) -> Decimal:
    try:
        amount = Decimal(value.replace(",", "").strip())
    except InvalidOperation as exc:
        raise EmployerFileError(f"{where}: {value!r} is not an amount") from exc
    return amount.quantize(Decimal("0.01"))


def parse_date(value: str, where: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise EmployerFileError(f"{where}: {value!r} is not a YYYY-MM-DD date") from exc


def _read(folder: Path, name: str) -> str:
    path = folder / name
    if not path.exists():
        raise EmployerFileError(f"{folder.name}: required file {name} is missing")
    return path.read_text(encoding="utf-8")


def _parse_application(text: str, folder: Path) -> tuple[str, str, list[ReportedLine], str]:
    title = re.search(r"^#\s*(.+?):", text, re.M)
    app = re.search(r"Application\s+(APP-[A-Z0-9-]+)", text)
    lines = [
        ReportedLine(m.group(1), int(m.group(2)), money(m.group(3), f"{folder.name}/application.md"))
        for m in re.finditer(r"^\|\s*([A-Z]-\d{3})\s*\|\s*(\d+)\s*\|\s*([\d.,]+)\s*\|", text, re.M)
    ]
    note = re.search(r"Employer's note:\s*\"(.+?)\"", text, re.S)
    if not title or not lines:
        raise EmployerFileError(f"{folder.name}/application.md: employer name or reported split not found")
    note_text = " ".join(note.group(1).split()) if note else ""
    return title.group(1).strip(), app.group(1) if app else "unknown", lines, note_text


def _parse_period(text: str, folder: Path) -> tuple[dt.date, dt.date]:
    m = re.search(r"Audit period\s+([A-Z][a-z]+ \d{1,2}, \d{4})\s+to\s+([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if not m:
        raise EmployerFileError(f"{folder.name}/business-description.md: audit period not found")
    fmt = "%B %d, %Y"
    return dt.datetime.strptime(m.group(1), fmt).date(), dt.datetime.strptime(m.group(2), fmt).date()


OWNER_RE = re.compile(
    r"(?:owner|partner|officer),\s+(?P<name>[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+)+),\s+(?:who\s+)?"
    r"has\s+(?P<neg>not\s+)?filed an election of exclusion"
)


def _parse_owners(text: str) -> list[OwnerStatement]:
    flat = " ".join(text.split())
    owners = []
    for sentence in re.split(r"(?<=\.)\s+", flat):
        for m in OWNER_RE.finditer(sentence):
            owners.append(OwnerStatement(m.group("name"), excluded=not m.group("neg"), sentence=sentence))
    return owners


def _classify_csv(path: Path) -> tuple[str | None, list[dict]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in reader]
        cols = {c.strip() for c in (reader.fieldnames or [])}
    for kind, needed in RECORD_KINDS.items():
        if needed <= cols:
            return kind, rows
    return None, rows


def load_employer(folder: Path) -> Employer:
    if not folder.is_dir():
        raise EmployerFileError(f"employer folder {folder} does not exist")
    name, app_id, reported, note = _parse_application(_read(folder, "application.md"), folder)
    description = _read(folder, "business-description.md")
    start, end = _parse_period(description, folder)
    notes_path = folder / "field-notes.md"
    emp = Employer(
        slug=folder.name,
        folder=folder,
        name=name,
        application_id=app_id,
        reported=reported,
        employer_note=note,
        period_start=start,
        period_end=end,
        description=description,
        field_notes=notes_path.read_text(encoding="utf-8") if notes_path.exists() else "",
        owners=_parse_owners(description),
    )
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() != ".csv":
            if path.name not in ("application.md", "business-description.md", "field-notes.md"):
                emp.unused_files[path.name] = "not a CSV record this Skill reads"
            continue
        kind, rows = _classify_csv(path)
        if kind is None:
            emp.unused_files[path.name] = "not a payroll, time, subcontractor or certificate record"
            continue
        if kind in emp.records:
            raise EmployerFileError(f"{folder.name}: two files look like {kind}: {emp.record_files[kind]}, {path.name}")
        emp.records[kind] = rows
        emp.record_files[kind] = path.name
    if "payroll_register" not in emp.records:
        raise EmployerFileError(f"{folder.name}: no payroll register (employee_id,name,position,wages_paid) found")
    return emp
