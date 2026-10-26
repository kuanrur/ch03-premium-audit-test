"""Write the per-employer CSV and the employer's sections of the audit report and questions."""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal
from pathlib import Path

from allocate import ZERO, Result

CSV_HEADER = ["class_code", "payroll_allocated", "rationale_ref"]

REPORT_TITLE = """# Audit report: class codes and payroll allocation

First-pass classification by the class-code-assistant Skill. Amounts are US dollars for each employer's audit period.
The Skill classifies and allocates payroll only; it does not set rates or quote premium. Each section says whether the
employer's own split is accepted, every adjustment with its amount, and the records that decided it. Paragraph
identifiers (CG-nn) are cited from the classification guide read during the run.
"""

QUESTIONS_TITLE = """# Audit questions for the employers

Questions for the premium auditor to put to each employer before signing off. Each one names the employee,
subcontractor or record it is about. Every adjustment and every record the allocation relies on is covered by at least
one question.
"""


def codes_csv(result: Result) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_HEADER)
    for code, amount, ref in result.lines():
        w.writerow([code, f"{amount:.2f}", ref])
    return buf.getvalue()


def _md(text: str) -> str:
    return text.replace("|", "\\|")


def _decision(r: Result) -> str:
    reg = r.employer.record_files["payroll_register"]
    if r.accepted:
        others = [f for f in r.records_used if f not in (reg, "field-notes.md")]
        checked = f", checked against {', '.join(others)}" if others else ""
        return (f"**Decision: the employer's own split is accepted.** The payroll register ({reg}) gives the same codes and "
                f"amounts to the cent{checked}, and no record shows payroll that can be measured under another code.")
    files = []
    for a in r.adjustments:
        for f in a.records:
            if f not in files:
                files.append(f)
    return (f"**Decision: the employer's own split is not accepted.** The employer's records disagree with the application, "
            f"and the records decide. The allocation rests on {', '.join(files)}.")


def report_section(r: Result) -> str:
    e = r.employer
    out = [f"## {e.name}", ""]
    files = ["application.md", "business-description.md"]
    if e.field_notes:
        files.append("field-notes.md")
    files += [f for f in e.record_files.values()]
    out.append(f"Application {e.application_id}. Audit period {e.period_start} to {e.period_end}. Classification guide "
               f"edition {r.guide.edition}. Employer file read: {', '.join(files)}.")
    if e.unused_files:
        out.append("Not used for the allocation: " + "; ".join(f"{k} ({v})" for k, v in e.unused_files.items()) + ".")
    out += ["", _decision(r), "", "### Codes and payroll allocated", "",
            "| Class code | Payroll allocated | Rationale ref | Code described as |", "|---|---:|---|---|"]
    total = ZERO
    for code, amount, ref in r.lines():
        out.append(f"| {code} | {amount:.2f} | {ref} | {r.guide.code_paragraph(code).code_name} |")
        total += amount
    out += [f"| Total | {total:.2f} | | |", "", f"Principal business code: {r.governing_code}; {r.governing_basis}.", ""]

    out += ["### Compared with the employer's own split", "",
            "| Class code | Employer reported | Allocated | Difference |", "|---|---:|---:|---:|"]
    reported, alloc = r.reported, r.by_code
    rep_total = ZERO
    for code in [c for c in r.guide.codes if c in reported or c in alloc]:
        rv, av = reported.get(code, ZERO), alloc.get(code, ZERO)
        rep_total += rv
        out.append(f"| {code} | {rv:.2f} | {av:.2f} | {av - rv:+.2f} |")
    out += [f"| Total | {rep_total:.2f} | {total:.2f} | {total - rep_total:+.2f} |", ""]
    if e.employer_note:
        out += [f"Employer's note on the application: \"{e.employer_note}\"", ""]
    if r.employer_assignment:
        names = {s.key: s.label for s in r.subjects}
        per_code: dict[str, list[str]] = {}
        for eid, code in r.employer_assignment.items():
            per_code.setdefault(code, []).append(names[eid])
        out.append("The employer's figures match these employees on the register: "
                   + "; ".join(f"{c}: {', '.join(n)}" for c, n in per_code.items()) + ".")
        out.append("")
    if not r.accepted:
        out.append("Where and why the allocation differs:")
        out.append("")
        for code in [c for c in r.guide.codes if c in reported or c in alloc]:
            diff = alloc.get(code, ZERO) - reported.get(code, ZERO)
            if diff:
                ins = [a for a in r.adjustments if a.to_code == code]
                outs = [a for a in r.adjustments if a.from_code == code]
                parts = []
                if ins:
                    parts.append("in: " + "; ".join(f"{a.subject} {a.amount:.2f}" for a in ins))
                if outs:
                    parts.append("out: " + "; ".join(f"{a.subject} {a.amount:.2f}" for a in outs))
                out.append(f"- {code} {diff:+.2f} ({' | '.join(parts)})")
        out.append("")

    out += ["### Adjustments", ""]
    if r.adjustments:
        out += ["| # | Employee or payment | Amount | From | To | Why | Records | Guide |", "|---|---|---:|---|---|---|---|---|"]
        for i, a in enumerate(r.adjustments, 1):
            out.append(f"| {i} | {_md(a.subject)} | {a.amount:.2f} | {a.from_code or 'not reported'} | {a.to_code or 'not counted'} | "
                       f"{_md(a.reason)} | {', '.join(a.records)} | {', '.join(a.refs)} |")
    else:
        out.append("None. Every employee's payroll stays under the code the employer reported.")
    out.append("")
    if r.excluded:
        out += ["### Paid but not counted as payroll", "", "| Employee or payment | Amount | Why |", "|---|---:|---|"]
        for who, amount, why in r.excluded:
            out.append(f"| {_md(who)} | {amount:.2f} | {_md(why)} |")
        out.append("")

    out += ["### Allocation by employee and payment", "", "| Employee or payment | Class code | Amount | Basis | Records |", "|---|---|---:|---|---|"]
    for s in r.subjects:
        for p in s.portions:
            out.append(f"| {_md(s.label)} | {p.code} | {p.amount:.2f} | {_md(p.basis)} | {', '.join(p.records)} |")
    out += ["", "### Records that decided this file", ""]
    for f, what in r.records_used.items():
        out.append(f"- {f}: {what}.")
    out.append("")
    if r.assumptions:
        out += ["### Assumptions where the guide is silent", ""]
        out += [f"- {a}" for a in r.assumptions]
        out.append("")
    if r.notes:
        out += ["### Notes", ""]
        out += [f"- {n}" for n in r.notes]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def questions_section(r: Result) -> str:
    out = [f"## {r.employer.name}", ""]
    for i, q in enumerate(r.questions, 1):
        out.append(f"{i}. **{q.subject}.** {q.text}")
    return "\n".join(out) + "\n"


SECTION_RE = re.compile(r"<!-- BEGIN employer:(?P<slug>[a-z0-9-]+) -->\n(?P<body>.*?)<!-- END employer:(?P=slug) -->\n", re.S)


def merge_sections(path: Path, title: str, slug: str, body: str, order: list[str]) -> None:
    """Insert or replace one employer's section; keep sections in the configured order."""
    sections: dict[str, str] = {}
    if path.exists():
        for m in SECTION_RE.finditer(path.read_text(encoding="utf-8")):
            sections[m.group("slug")] = m.group("body")
    sections[slug] = body
    ranked = sorted(sections, key=lambda s: (order.index(s) if s in order else len(order), s))
    parts = [title]
    for s in ranked:
        parts.append(f"<!-- BEGIN employer:{s} -->\n{sections[s]}<!-- END employer:{s} -->\n")
    path.write_text("\n".join(parts), encoding="utf-8")


def run_record(r: Result, sources: dict) -> dict:
    def d(x: Decimal) -> str:
        return f"{x:.2f}"

    return {
        "employer": r.employer.slug,
        "name": r.employer.name,
        "application": r.employer.application_id,
        "audit_period": [str(r.employer.period_start), str(r.employer.period_end)],
        "guide_edition": r.guide.edition,
        "sources": sources,
        "accepted_employer_split": r.accepted,
        "reported": {c: d(v) for c, v in r.reported.items()},
        "allocated": [{"class_code": c, "payroll_allocated": d(a), "rationale_ref": ref} for c, a, ref in r.lines()],
        "principal_business_code": r.governing_code,
        "subjects": [
            {"label": s.label, "kind": s.kind, "employer_code": s.employer_code,
             "portions": [{"code": p.code, "amount": d(p.amount), "basis": p.basis, "records": p.records, "refs": p.refs} for p in s.portions]}
            for s in r.subjects
        ],
        "excluded": [{"label": w, "amount": d(a), "why": y} for w, a, y in r.excluded],
        "adjustments": [{"subject": a.subject, "amount": d(a.amount), "from": a.from_code, "to": a.to_code, "reason": a.reason, "records": a.records, "refs": a.refs} for a in r.adjustments],
        "questions": [{"subject": q.subject, "text": q.text} for q in r.questions],
        "assumptions": r.assumptions,
        "records_used": r.records_used,
    }
