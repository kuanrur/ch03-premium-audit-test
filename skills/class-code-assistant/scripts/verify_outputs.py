"""Check the Skill's outputs against the assignment's format rules and the source records.

Run after run_audit.py. It re-reads the guide and the payroll registers from the same
source the run used (the Drive cache by default) and checks, for every employer:

- deliverables/codes/<employer>.csv exists, has exactly the header
  class_code,payroll_allocated,rationale_ref, one row per code, no zero rows,
  dollars to the cent without separators, and a rationale_ref that is the guide
  paragraph describing that code;
- the CSV total equals the payroll register total plus the additions the run reports
  (uninsured subcontractors, undocumented allowances), and every employee's portions
  add up to the register wages;
- audit-report.md and audit-questions.md have one section per employer; the report
  shows every code, amount and adjustment; every adjustment and every record relied on
  is named in at least one question, and every question names its subject.

Exit status 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
REPO = SKILL_DIR.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from guide import load_guide  # noqa: E402
from render import SECTION_RE  # noqa: E402

AMOUNT_RE = re.compile(r"^\d+\.\d{2}$")


def sections(path: Path) -> dict[str, str]:
    return {m.group("slug"): m.group("body") for m in SECTION_RE.finditer(path.read_text(encoding="utf-8"))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source-dir", type=Path, default=REPO / ".cache" / "drive")
    ap.add_argument("--out", type=Path, default=REPO)
    args = ap.parse_args(argv)
    config = json.loads((SKILL_DIR / "sources.json").read_text(encoding="utf-8"))
    src, out = args.source_dir.resolve(), args.out.resolve()
    guide = load_guide(src / config["guide_file"])
    failures: list[str] = []
    checks = 0

    def check(ok: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(message)

    runs = sorted((out / "runs").glob("*.json"))
    check(bool(runs), "no run records in runs/; run run_audit.py first")
    slugs = [r.stem for r in runs]
    for expected in config.get("report_order", []):
        check(expected in slugs, f"no run for {expected}")
    report = sections(out / "deliverables" / "audit-report.md")
    questions = sections(out / "deliverables" / "audit-questions.md")

    for run_path in runs:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        slug = run["employer"]
        where = slug

        # CSV format.
        csv_path = out / "deliverables" / "codes" / f"{slug}.csv"
        check(csv_path.exists(), f"{where}: {csv_path.name} missing")
        if not csv_path.exists():
            continue
        raw = csv_path.read_text(encoding="utf-8")
        check(raw.splitlines()[0] == "class_code,payroll_allocated,rationale_ref", f"{where}: CSV header is not exact")
        rows = list(csv.DictReader(raw.splitlines()))
        codes_seen = set()
        csv_total = Decimal("0")
        for row in rows:
            code, amount, ref = row["class_code"], row["payroll_allocated"], row["rationale_ref"]
            check(code not in codes_seen, f"{where}: {code} appears twice")
            codes_seen.add(code)
            check(guide.has_code(code), f"{where}: {code} is not in the guide")
            check(bool(AMOUNT_RE.match(amount)), f"{where}: {code} amount {amount!r} is not dollars to the cent without separators")
            check(Decimal(amount) > 0, f"{where}: {code} has zero payroll")
            if guide.has_code(code):
                check(ref == guide.code_paragraph(code).id, f"{where}: {code} cites {ref}, the guide describes it in {guide.code_paragraph(code).id}")
            check(ref in guide.paragraphs, f"{where}: rationale_ref {ref} is not a paragraph of the guide")
            csv_total += Decimal(amount)

        # Totals against the payroll register read again from the source.
        reg_name = next((f for f, what in run["records_used"].items() if what.startswith("gross wages")), "payroll-register.csv")
        reg_rows = list(csv.DictReader((src / config["employers_folder"] / slug / reg_name).open(encoding="utf-8")))
        reg_total = sum(Decimal(r["wages_paid"]) for r in reg_rows)
        additions = sum(Decimal(a["amount"]) for a in run["adjustments"] if a["from"] is None and a["to"])
        owners_out = sum(Decimal(e["amount"]) for e in run["excluded"] if "election of exclusion" in e["why"])
        check(csv_total == reg_total + additions - owners_out,
              f"{where}: CSV total {csv_total} != register {reg_total} + additions {additions} - excluded owners {owners_out}")
        wages = {f"{r['name']} ({r['employee_id']})": Decimal(r["wages_paid"]) for r in reg_rows}
        for s in run["subjects"]:
            if s["kind"] != "employee":
                continue
            base = sum(Decimal(p["amount"]) for p in s["portions"] if "allowance not backed" not in p["basis"])
            check(base == wages.get(s["label"]), f"{where}: {s['label']} portions {base} != register wages {wages.get(s['label'])}")
        check(len([s for s in run["subjects"] if s["kind"] == "employee"]) + sum(1 for e in run["excluded"] if "election of exclusion" in e["why"]) == len(reg_rows),
              f"{where}: not every employee on the register was allocated")

        # Report section.
        body = report.get(slug, "")
        check(bool(body), f"{where}: no section in audit-report.md")
        check(f"## {run['name']}" in body, f"{where}: report section heading is not the employer name")
        for row in rows:
            check(f"| {row['class_code']} | {row['payroll_allocated']} | {row['rationale_ref']} |" in body, f"{where}: report does not show {row['class_code']} {row['payroll_allocated']}")
        decision = "accepted.**" if run["accepted_employer_split"] else "not accepted.**"
        check(decision in body, f"{where}: report decision does not match the run")
        for a in run["adjustments"]:
            check(a["amount"] in body and a["subject"] in body, f"{where}: report misses adjustment {a['subject']} {a['amount']}")
        for f in run["records_used"]:
            check(f in body, f"{where}: report does not name record {f}")

        # Questions section.
        qbody = questions.get(slug, "")
        check(bool(qbody), f"{where}: no section in audit-questions.md")
        items = re.findall(r"^\d+\. \*\*(.+?)\.\*\* (.+)$", qbody, re.M)
        check(len(items) == len(run["questions"]), f"{where}: question count differs from the run")
        names = [s["label"].split(" (")[0] for s in run["subjects"]] + [s["label"].split(",")[0] for s in run["subjects"]]
        files = list(run["records_used"])
        for subject, text in items:
            check(any(n in subject for n in names) or any(f in subject for f in files) or re.search(r"[A-Z][a-z]+ [A-Z][a-z]+", subject) is not None,
                  f"{where}: question subject '{subject}' does not name an employee, subcontractor or record")
        for a in run["adjustments"]:
            who = a["subject"].split(" (")[0].split(",")[0]
            check(any(who in s or who in t for s, t in items), f"{where}: no question covers adjustment for {a['subject']}")
        for f in files:
            if f == "field-notes.md":
                continue
            check(any(f in s or f in t for s, t in items), f"{where}: no question asks the employer to confirm {f}")

    for f in failures:
        print(f"FAIL {f}")
    print(f"{checks - len(failures)} of {checks} checks passed for {len(runs)} employers")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
