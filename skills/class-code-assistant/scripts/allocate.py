"""First-pass classification and payroll allocation for one employer.

The rules are written against the classification guide's paragraphs, found by their
titles at run time, so the citations in the outputs always come from the guide that
was read during the run. Where the guide leaves a case open, the house assumption
used is recorded on the result (see references/decision-rules.md).
"""

from __future__ import annotations

import collections
import csv
import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from itertools import combinations
from pathlib import Path

from employer import Employer, money, number, parse_date
from guide import Guide, GuideError

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
REFERENCES = Path(__file__).resolve().parent.parent / "references"

# General paragraphs the rules rely on, found by title so a renumbered guide still works.
GENERAL_TITLES = {
    "assigning": "Assigning codes",
    "payroll": "Payroll",
    "owners": "Owners and executive officers",
    "subs": "Subcontractors",
    "division": "Division of payroll",
}

NARRATIVE_STOPWORDS = {"employees", "office", "clerical", "shop", "home", "care"}


@dataclass
class Portion:
    code: str
    amount: Decimal
    basis: str
    records: list[str]
    refs: list[str]


@dataclass
class Subject:
    """An employee, or a payment that is counted as payroll."""

    key: str
    label: str
    kind: str  # employee | subcontractor
    portions: list[Portion] = field(default_factory=list)
    employer_code: str | None = None

    @property
    def total(self) -> Decimal:
        return sum((p.amount for p in self.portions), ZERO)


@dataclass
class Adjustment:
    subject: str
    amount: Decimal
    from_code: str | None
    to_code: str | None
    reason: str
    records: list[str]
    refs: list[str]

    def sentence(self) -> str:
        if self.from_code and self.to_code:
            move = f"moved {self.amount} from {self.from_code} to {self.to_code}"
        elif self.to_code:
            move = f"added {self.amount} under {self.to_code}"
        else:
            move = f"removed {self.amount} from {self.from_code}"
        return f"{self.subject}: {move}. {self.reason}"


@dataclass
class Question:
    subject: str
    text: str


@dataclass
class Result:
    employer: Employer
    guide: Guide
    office_code: str
    governing_code: str
    governing_basis: str
    subjects: list[Subject]
    excluded: list[tuple[str, Decimal, str]]
    adjustments: list[Adjustment]
    questions: list[Question]
    assumptions: list[str]
    records_used: dict[str, str]
    notes: list[str]
    employer_assignment: dict[str, str] | None

    @property
    def by_code(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = collections.defaultdict(lambda: ZERO)
        for s in self.subjects:
            for p in s.portions:
                totals[p.code] += p.amount
        order = [c for c in self.guide.codes if c in totals]
        return {c: totals[c] for c in order if totals[c] != ZERO}

    @property
    def reported(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = collections.defaultdict(lambda: ZERO)
        for line in self.employer.reported:
            out[line.code] += line.payroll
        return dict(out)

    @property
    def accepted(self) -> bool:
        return not self.adjustments and self.by_code == self.reported

    def lines(self) -> list[tuple[str, Decimal, str]]:
        return [(c, a, self.guide.code_paragraph(c).id) for c, a in self.by_code.items()]


# ---------------------------------------------------------------- helpers


def load_map(name: str) -> list[tuple[str, str]]:
    with (REFERENCES / name).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    return [(r[0].strip().lower(), r[1].strip()) for r in rows[1:] if r and r[0].strip()]


def validate_maps(guide: Guide, *maps: list[tuple[str, str]]) -> None:
    missing = sorted({code for m in maps for _, code in m if not guide.has_code(code)})
    if missing:
        raise GuideError(
            "the vocabulary maps in references/ use class codes the guide does not describe: "
            + ", ".join(missing)
        )


def lookup(text: str, mapping: list[tuple[str, str]]) -> str | None:
    low = text.lower()
    for pattern, code in mapping:
        if pattern in low:
            return code
    return None


def split_amount(total: Decimal, weights: dict[str, Decimal]) -> dict[str, Decimal]:
    """Split total in proportion to weights, to the cent, keeping the exact total."""
    wsum = sum(weights.values())
    raw = {k: total * w / wsum for k, w in weights.items()}
    out = {k: v.quantize(CENT, rounding=ROUND_DOWN) for k, v in raw.items()}
    left = int(((total - sum(out.values())) / CENT).to_integral_value())
    for k in sorted(raw, key=lambda k: raw[k] - out[k], reverse=True)[:left]:
        out[k] += CENT
    return out


def week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def norm_company(name: str) -> list[str]:
    name = name.lower().replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", name)
    return [w for w in words if w not in {"llc", "inc", "co", "company", "corp", "ltd"}]


def match_certificate(name: str, certs: list[dict]) -> tuple[dict | None, str]:
    """Return (certificate, 'exact'|'probable'|'none'). Probable: one name is a word prefix of the other."""
    target = norm_company(name)
    for c in certs:
        if norm_company(c["subcontractor"]) == target:
            return c, "exact"
    for c in certs:
        other = norm_company(c["subcontractor"])
        short, long_ = sorted((target, other), key=len)
        if short and long_[: len(short)] == short:
            return c, "probable"
    return None, "none"


def infer_employer_assignment(employees: list[tuple[str, Decimal]], reported) -> dict[str, str] | None:
    """Find which employees the employer put under each reported code (counts and totals must match)."""
    if len(employees) > 16:
        return None
    wages = dict(employees)

    def solve(i: int, remaining: frozenset) -> dict[str, str] | None:
        if i == len(reported):
            return {} if not remaining else None
        line = reported[i]
        for combo in combinations(sorted(remaining), line.employees):
            if sum((wages[e] for e in combo), ZERO) == line.payroll:
                rest = solve(i + 1, remaining - set(combo))
                if rest is not None:
                    return {**{e: line.code for e in combo}, **rest}
        return None

    return solve(0, frozenset(wages))


def stems(words: list[str]) -> list[str]:
    return [w[: max(5, len(w) - 3)] for w in words]


def hrs(h: Decimal) -> str:
    return str(int(h)) if h == h.to_integral_value() else str(h)


def days_text(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def site_text(counter: collections.Counter) -> str:
    return ", ".join(f"{s} ({days_text(n)})" for s, n in counter.most_common())


def note_quote(emp: Employer, name: str) -> str:
    """The employer's own statement about this person on the application, if there is one."""
    first = name.split()[0]
    if emp.employer_note and (name in emp.employer_note or re.search(rf"\b{re.escape(first)}\b", emp.employer_note)):
        return f" The application says: \"{emp.employer_note}\""
    return ""


# ---------------------------------------------------------------- the rules


def allocate(emp: Employer, guide: Guide) -> Result:
    positions = load_map("position-map.csv")
    work_types = load_map("work-type-map.csv")
    validate_maps(guide, positions, work_types)
    office = guide.office_code()
    refs = {}
    for key, title in GENERAL_TITLES.items():
        hit = [p.id for p in guide.paragraphs.values() if not p.code and p.title.lower() == title.lower()]
        if len(hit) != 1:
            raise GuideError(f"the guide has no single general paragraph titled '{title}'")
        refs[key] = hit[0]
    office_ref = guide.code_paragraph(office).id

    files = emp.record_files
    reg_file = files["payroll_register"]
    records_used: dict[str, str] = {reg_file: "gross wages per employee for the audit period"}
    assumptions: list[str] = []
    notes: list[str] = []
    questions: list[Question] = []
    excluded: list[tuple[str, Decimal, str]] = []

    def assume(text: str) -> None:
        if text not in assumptions:
            assumptions.append(text)

    # Employees on the register.
    register = emp.records["payroll_register"]
    by_id: dict[str, dict] = {}
    for row in register:
        if row["employee_id"] in by_id:
            raise ValueError(f"{emp.slug}: employee {row['employee_id']} appears twice in {reg_file}")
        by_id[row["employee_id"]] = row
    label = {eid: f"{r['name']} ({eid})" for eid, r in by_id.items()}
    wages = {eid: money(r["wages_paid"], f"{reg_file} {eid}") for eid, r in by_id.items()}
    title_code = {eid: lookup(r["position"], positions) for eid, r in by_id.items()}

    # Owners and officers (CG-05).
    owner_ids: set[str] = set()
    name_to_id = {r["name"].lower(): eid for eid, r in by_id.items()}
    for o in emp.owners:
        eid = name_to_id.get(o.name.lower())
        if o.excluded and eid is None:
            notes.append(f"{o.name} has filed an election of exclusion and is not on the payroll register; not counted ({refs['owners']}).")
            questions.append(Question(o.name, f"Please send a copy of {o.name}'s election of exclusion so we can confirm it covers the whole audit period; the allocation does not count {o.name}'s pay ({refs['owners']})."))
        elif o.excluded and eid is not None:
            excluded.append((label[eid], wages.pop(eid), f"owner with an election of exclusion is not counted ({refs['owners']})"))
            questions.append(Question(label[eid], f"{o.name} is described as having filed an election of exclusion but appears on {reg_file}. Please confirm the election and whether these wages belong to the owner; they are left out of the allocation ({refs['owners']})."))
        elif not o.excluded and eid is not None:
            owner_ids.add(eid)
        else:
            questions.append(Question(o.name, f"{o.name} has not filed an election of exclusion but is not on {reg_file}. Please provide {o.name}'s remuneration for the period so it can be classified ({refs['owners']})."))
    for eid in list(wages):
        if eid not in owner_ids and "owner" in by_id[eid]["position"].lower():
            owner_ids.add(eid)

    subjects: dict[str, Subject] = {eid: Subject(eid, label[eid], "employee") for eid in wages}
    decided: set[str] = set()

    # Time records with a type of work: divide payroll by hours (CG-07).
    hours: dict[str, dict[str, Decimal]] = collections.defaultdict(lambda: collections.defaultdict(Decimal))
    kinds: dict[str, dict[str, collections.Counter]] = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    if "timesheets" in emp.records:
        tfile = files["timesheets"]
        unknown_types: collections.Counter = collections.Counter()
        outside = 0
        for row in emp.records["timesheets"]:
            day = parse_date(row["date"], tfile)
            if not emp.in_period(day):
                outside += 1
                continue
            eid = row["employee_id"]
            code = lookup(row["work_type"], work_types)
            if code is None:
                unknown_types[row["work_type"]] += 1
            h = number(row["hours"], f"{tfile} {row['date']} {eid}")
            hours[eid][code or "?"] += h
            kinds[eid][code or "?"][row["work_type"]] += h
        if outside:
            notes.append(f"{outside} rows of {tfile} fall outside the audit period and were not used.")
        for wt, n in unknown_types.items():
            questions.append(Question(tfile, f"{tfile} has {n} rows with work type '{wt}', which this Skill cannot match to a code in the guide. Please describe that work."))
        for eid, per in hours.items():
            if eid not in wages:
                questions.append(Question(tfile, f"{tfile} records hours for {eid}, who is not on {reg_file}. Please explain whose pay covers those hours."))
                continue
            merged: dict[str, Decimal] = collections.defaultdict(Decimal)
            types: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
            for c, h in per.items():
                target = c if c != "?" else title_code[eid] or office
                merged[target] += h
                types[target].update(kinds[eid][c])
            parts = split_amount(wages[eid], merged)
            total_h = sum(merged.values())
            for c, amt in parts.items():
                if amt:
                    what = ", ".join(f"{t} {hrs(h)}" for t, h in types[c].most_common())
                    subjects[eid].portions.append(Portion(c, amt, f"{hrs(merged[c])} of {hrs(total_h)} hours in {tfile} recorded as {what} ({c})", [tfile, reg_file], [refs["division"], guide.code_paragraph(c).id]))
            decided.add(eid)
            all_types = collections.Counter()
            for t in types.values():
                all_types.update(t)
            split_text = ", ".join(f"{c} {amt:.2f} ({guide.code_paragraph(c).id})" for c, amt in parts.items() if amt)
            questions.append(Question(label[eid], f"{tfile} records {hrs(total_h)} hours for {label[eid]} in the period: "
                                      + ", ".join(f"{t} {hrs(h)}" for t, h in all_types.most_common())
                                      + f". Under {refs['division']} we divided the {wages[eid]} on {reg_file} by those hours: {split_text}. "
                                      + f"Please confirm the hours and the type of work recorded for {by_id[eid]['name']}.{note_quote(emp, by_id[eid]['name'])}"))
        records_used[tfile] = "hours by type of work, used to divide crew payroll between codes"

    # Route log: office staff who drive or ride on delivery vehicles (CG-07).
    vehicle_code = lookup("delivery route", work_types)
    vehicle_days: dict[str, set] = collections.defaultdict(set)
    if "route_log" in emp.records:
        rfile = files["route_log"]
        op_days: dict[dt.date, set] = collections.defaultdict(set)
        for row in emp.records["route_log"]:
            day = parse_date(row["date"], rfile)
            if not emp.in_period(day):
                continue
            op_days[week_start(day)].add(day)
            for col in ("driver_id", "ride_along_id"):
                if row.get(col):
                    vehicle_days[row[col]].add(day)
        records_used[rfile] = "every route day with its driver and ride-along"
        weekly = emp.records.get("weekly_payroll")
        wfile = files.get("weekly_payroll")
        for eid, days in sorted(vehicle_days.items()):
            if eid not in wages or eid in decided or title_code[eid] == vehicle_code:
                continue
            base = title_code[eid] or office
            if weekly:
                rows = [r for r in weekly if r["employee_id"] == eid]
                wsum = sum((money(r["gross_pay"], wfile) for r in rows), ZERO)
                if wsum != wages[eid]:
                    questions.append(Question(label[eid], f"{wfile} totals {wsum} for {label[eid]} but {reg_file} shows {wages[eid]}. Please reconcile."))
                vehicle_amt = Decimal(0)
                for r in rows:
                    ws = parse_date(r["week_start"], wfile)
                    we = parse_date(r["week_end"], wfile)
                    on_vehicle = len([d for d in days if ws <= d <= we])
                    worked = len({d for wk in op_days for d in op_days[wk] if ws <= d <= we})
                    if on_vehicle and worked:
                        vehicle_amt += money(r["gross_pay"], wfile) * on_vehicle / worked
                vehicle_amt = vehicle_amt.quantize(CENT, rounding=ROUND_HALF_UP)
                basis_rec = [rfile, wfile]
                records_used[wfile] = "weekly gross pay, used to price each route day"
            else:
                total_days = sum(len(v) for v in op_days.values())
                vehicle_amt = (wages[eid] * len(days) / total_days).quantize(CENT, rounding=ROUND_HALF_UP)
                basis_rec = [rfile, reg_file]
            n = len(days)
            subjects[eid].portions.append(Portion(vehicle_code, vehicle_amt, f"{days_text(n)} on a delivery vehicle in {rfile}, each priced at that week's gross pay divided by the week's operating days", basis_rec, [refs["division"], guide.code_paragraph(vehicle_code).id]))
            if wages[eid] - vehicle_amt:
                subjects[eid].portions.append(Portion(base, wages[eid] - vehicle_amt, "remaining days in the employee's own job", basis_rec, [refs["division"], guide.code_paragraph(base).id]))
            decided.add(eid)
            per_week = collections.Counter(week_start(d) for d in days)
            busiest = max(per_week.values())
            assume(f"Route-log division: a day on a delivery vehicle counts as a full day of {vehicle_code} work, and the days an employee works in a week are taken as the operating days in {rfile} for that week (the records hold no attendance for office staff).")
            peak = f", in {len(per_week)} weeks, up to {days_text(busiest)} in one week" if busiest > 1 else ""
            questions.append(Question(label[eid], f"{rfile} shows {label[eid]} on a delivery vehicle on {days_text(n)} in the period{peak}. We moved {vehicle_amt} of this pay to {vehicle_code} ({guide.code_paragraph(vehicle_code).id}) on that basis.{note_quote(emp, by_id[eid]['name'])} Please confirm those days and how many days a week {by_id[eid]['name']} works; if fewer than the operating days in {rfile}, the {vehicle_code} share rises."))

    # Site sign-ins (office staff who go to job sites are not confined to an office).
    signins: dict[str, list[dt.date]] = collections.defaultdict(list)
    sites: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    if "site_signins" in emp.records:
        sfile = files["site_signins"]
        visitors = 0
        for row in emp.records["site_signins"]:
            day = parse_date(row["date"], sfile)
            if not emp.in_period(day):
                continue
            if not row["employee_id"]:
                visitors += 1
                continue
            signins[row["employee_id"]].append(day)
            sites[row["employee_id"]][row["site"]] += 1
        if visitors:
            notes.append(f"{visitors} rows of {sfile} are visitors with no employee id (for example inspectors); not used.")
        records_used[sfile] = "dates and sites each employee signed in at a job site"

    deferred: list[str] = []
    for eid in wages:
        if eid in decided:
            continue
        code = title_code[eid]
        if code == office and signins.get(eid):
            deferred.append(eid)
            continue
        if code is None:
            deferred.append(eid)
            questions.append(Question(label[eid], f"The position '{by_id[eid]['position']}' on {reg_file} does not match a code in the guide. Please describe {by_id[eid]['name']}'s duties."))
            continue
        basis = f"position '{by_id[eid]['position']}' on {reg_file}"
        cites = [refs["assigning"], guide.code_paragraph(code).id]
        if eid in owner_ids:
            basis += f"; owner included in payroll, counted under the code for the owner's own work ({refs['owners']})"
            cites.insert(0, refs["owners"])
        recs = [reg_file]
        if signins.get(eid):
            basis += f"; {len(signins[eid])} job-site sign-ins in {files['site_signins']}"
            recs.append(files["site_signins"])
        subjects[eid].portions.append(Portion(code, wages[eid], basis, recs, cites))
        decided.add(eid)
        if eid in owner_ids:
            seen = f" and {len(signins[eid])} job-site sign-ins in {files['site_signins']}" if signins.get(eid) else ""
            questions.append(Question(label[eid], f"{by_id[eid]['name']} is an owner who has not filed an election of exclusion, so the owner's {wages[eid]} is counted under the code for the owner's own work ({refs['owners']}): {code} ({guide.code_paragraph(code).id}), from the position '{by_id[eid]['position']}'{seen}. Please confirm the owner's duties in the period; if part of the time was office-only work, send time records for it ({refs['division']})."))

    # Governing code: the employer's principal business, judged by payroll outside the office code (CG-02).
    ops: dict[str, Decimal] = collections.defaultdict(lambda: ZERO)
    for eid in decided:
        for p in subjects[eid].portions:
            if p.code != office:
                ops[p.code] += p.amount
    if ops:
        governing = max(ops, key=lambda c: ops[c])
        governing_basis = (
            f"{governing} carries the most payroll outside {office} in the records ("
            + ", ".join(f"{c} {ops[c]}" for c in sorted(ops, key=lambda c: -ops[c]))
            + ")"
        )
        assume(f"Principal business ({refs['assigning']}): taken as the code with the most payroll outside {office}, measured from the records.")
    else:
        governing = max(emp.reported, key=lambda line: line.payroll).code
        if not guide.has_code(governing):
            governing = office
        governing_basis = f"no payroll outside {office} in the records; the employer's principal business is described by {governing}"
    for eid in deferred:
        recs = [reg_file]
        if signins.get(eid):
            recs.append(files["site_signins"])
            site_list = site_text(sites[eid])
            n = len(signins[eid])
            basis = (f"{n} job-site sign-ins in {files['site_signins']} ({site_list}): duties are not confined to an office "
                     f"({office_ref}) and no time records divide them ({refs['division']}), so the payroll follows the principal business code {governing}")
            assume(f"Office staff who sign in at job sites are not confined to an office ({office_ref}); without time records ({refs['division']}) their whole payroll goes to the principal business code ({refs['assigning']}), however few the visits.")
            said = note_quote(emp, by_id[eid]["name"])
            if governing == office:
                questions.append(Question(label[eid], f"{files['site_signins']} shows {label[eid]} signing in at {site_list}. We kept this pay under {office} because the business has no other code.{said} Please confirm what {by_id[eid]['name']} did on those visits and that it involved no physical work."))
            else:
                questions.append(Question(label[eid], f"{files['site_signins']} shows {label[eid]} signing in at job sites on {days_text(n)}: {site_list}. Because the work is not confined to the office, all {wages[eid]} goes under the principal business code {governing} ({guide.code_paragraph(governing).id}); {governing_basis}.{said} Please confirm what {by_id[eid]['name']} does at the sites and whether you keep time records that separate site time from office time."))
        else:
            basis = "position does not match a code in the guide; placed under the principal business code until the duties are confirmed"
        subjects[eid].portions.append(Portion(governing, wages[eid], basis, recs, [refs["assigning"], guide.code_paragraph(governing).id]))

    # Allowances paid on top of wages (CG-03).
    reg_cols = set(register[0].keys()) if register else set()
    for col in sorted(c for c in reg_cols if c.endswith("_allowance_paid")):
        prefix = col[: -len("_allowance_paid")]
        days_col = f"{prefix}_days"
        rates = collections.Counter()
        for row in register:
            days = number(row.get(days_col, ""), f"{reg_file} {row['employee_id']}")
            paid = money(row[col] or "0", reg_file)
            if days and paid:
                rates[(paid / days).quantize(CENT)] += 1
        modal = rates.most_common(1)[0][0] if rates else None
        if modal is not None:
            assume(f"{prefix.capitalize()} allowance ({refs['payroll']}): the part backed by recorded {prefix} days, at the most common per-day amount ({modal}), is a documented expense and not payroll; anything paid beyond that, or with no recorded days, is payroll under the employee's code.")
        for row in register:
            eid = row["employee_id"]
            if eid not in wages:
                continue
            paid = money(row[col] or "0", reg_file)
            if not paid:
                continue
            days = number(row.get(days_col, ""), f"{reg_file} {row['employee_id']}")
            documented = min(paid, (days * modal).quantize(CENT)) if (days and modal) else ZERO
            payroll_part = paid - documented
            if documented:
                excluded.append((label[eid], documented, f"{prefix} allowance for {days} recorded {prefix} days is a documented expense ({refs['payroll']})"))
                rate = (paid / days).quantize(CENT)
                extra = f" That is {rate} a day, against {modal} a day for most employees; please explain the difference." if rate != modal else ""
                questions.append(Question(label[eid], f"{reg_file} shows {paid} of {prefix} allowance for {days} {prefix} days for {label[eid]}, left out of payroll as a documented expense. Please send the {prefix} records (dates and job) behind those days.{extra}"))
            if payroll_part:
                weights: dict[str, Decimal] = collections.defaultdict(Decimal)
                for p in subjects[eid].portions:
                    weights[p.code] += p.amount
                split = split_amount(payroll_part, weights)
                for c, amt in split.items():
                    if amt:
                        subjects[eid].portions.append(Portion(c, amt, f"{prefix} allowance not backed by recorded {prefix} days ({days} days recorded)", [reg_file], [refs["payroll"], guide.code_paragraph(c).id]))
                questions.append(Question(label[eid], f"{reg_file} shows {payroll_part} of {prefix} allowance for {label[eid]} with {days} {prefix} days recorded. Without a record of {prefix} it counts as payroll ({refs['payroll']}). Please send the dates and receipts if this was a {prefix} expense."))
        records_used[reg_file] += f"; {prefix} days and {prefix} allowance per employee"

    # Subcontractors (CG-06).
    sub_subjects: list[Subject] = []
    if "subcontractor_payments" in emp.records:
        pfile = files["subcontractor_payments"]
        certs = emp.records.get("certificates", [])
        cfile = files.get("certificates", "certificates of insurance (none in the file)")
        records_used[pfile] = "payments to subcontractors, with the work and date"
        if certs:
            records_used[cfile] = "subcontractors' workers' compensation certificates and coverage dates"
        uninsured_by_sub: dict[str, list] = collections.defaultdict(list)
        insured_by_sub: dict[str, list] = collections.defaultdict(list)
        for row in emp.records["subcontractor_payments"]:
            day = parse_date(row["date"], pfile)
            if not emp.in_period(day):
                notes.append(f"{pfile}: payment {row.get('invoice', '')} on {day} is outside the audit period; not used.")
                continue
            amount = money(row["amount_paid"], pfile)
            cert, how = match_certificate(row["subcontractor"], certs)
            who = f"{row['subcontractor']}, invoice {row.get('invoice', '?')} of {day}"
            if cert and how == "probable":
                assume(f"Subcontractor names ({refs['subs']}): a payment name that is a shortened form of a certificate holder's name (for example without 'LLC' or a trade) is taken as the same company.")
            covered = bool(cert) and parse_date(cert["coverage_from"], cfile) <= day <= parse_date(cert["coverage_to"], cfile)
            if covered:
                excluded.append((who, amount, f"covered by certificate {cert['certificate_no']} ({cert['coverage_from']} to {cert['coverage_to']}); not payroll ({refs['subs']})"))
                insured_by_sub[row["subcontractor"]].append((who, amount, cert, how))
                continue
            code = lookup(row["work"], work_types)
            if code is None:
                code = governing
                questions.append(Question(row["subcontractor"], f"{pfile} describes {who} as '{row['work']}', which does not match a code in the guide. Please describe the work."))
            reason = (f"certificate {cert['certificate_no']} ended {cert['coverage_to']}" if cert and day > parse_date(cert["coverage_to"], cfile)
                      else f"certificate {cert['certificate_no']} starts {cert['coverage_from']}" if cert
                      else "no certificate of insurance in the file")
            subj = Subject(f"{row['subcontractor']}|{row.get('invoice', day)}", who, "subcontractor")
            subj.portions.append(Portion(code, amount, f"{row['work']} work by an uninsured subcontractor ({reason})", [pfile] + ([cfile] if certs else []), [refs["subs"], guide.code_paragraph(code).id]))
            sub_subjects.append(subj)
            uninsured_by_sub[row["subcontractor"]].append((who, amount, code, reason, cert, how))
        for sub, items in insured_by_sub.items():
            cert, how = items[0][2], items[0][3]
            invoices = "; ".join(f"{i[0]} ({i[1]})" for i in items)
            text = (f"We relied on certificate {cert['certificate_no']} ({cert['coverage_from']} to {cert['coverage_to']}) and did not count "
                    f"these payments to {sub} as payroll ({refs['subs']}): {invoices}.")
            if how == "probable":
                text += f" The certificate is issued to '{cert['subcontractor']}'; please confirm it is the same company as '{sub}'."
            questions.append(Question(sub, text + " Please confirm the work was done within the coverage dates and send the certificate itself."))
        for sub, items in uninsured_by_sub.items():
            total = sum((i[1] for i in items), ZERO)
            invoices = "; ".join(f"{i[0]} ({i[1]})" for i in items)
            cert, how = items[0][4], items[0][5]
            if cert:
                ask = (f"Certificate {cert['certificate_no']} (issued to '{cert['subcontractor']}') covers {cert['coverage_from']} to {cert['coverage_to']}. "
                       f"Please send a renewed certificate covering these payments, or the dates the work was done if it was within the coverage.")
            else:
                ask = f"There is no certificate of insurance for {sub} in the file. Please send one covering the dates of the work, if it exists."
            questions.append(Question(sub, f"We counted {total} paid to {sub} as payroll under {items[0][2]} ({refs['subs']}): {invoices}. {ask}"))
        if uninsured_by_sub:
            assume(f"Uninsured subcontractors ({refs['subs']}): the full amount paid is treated as payroll under the code for the work, and the payment date is taken as the date of the work, because the file has no labor and material split and no work dates.")

    # Narrative check: field notes that tie a position to work under another code the employer reports.
    reported_codes = {line.code for line in emp.reported}
    code_words = {}
    for c in reported_codes - {office}:
        if guide.has_code(c):
            words = [w for w in re.findall(r"[a-z]+", guide.code_paragraph(c).code_name.lower()) if len(w) >= 5 and w not in NARRATIVE_STOPWORDS]
            code_words[c] = stems(words)
    flat_notes = " ".join(emp.field_notes.split())
    flagged: set[str] = set()
    for sentence in re.split(r"(?<=[.!?])\s+", flat_notes):
        low = sentence.lower()
        for eid, row in by_id.items():
            pos = row["position"].lower()
            if eid not in subjects or not re.search(rf"\b{re.escape(pos)}s?\b", low):
                continue
            own = {p.code for p in subjects[eid].portions}
            if len(own) != 1:
                continue
            rest = re.sub(rf"\b{re.escape(pos)}s?\b", " ", low)
            tokens = re.findall(r"[a-z]+", rest)
            for c, sts in code_words.items():
                if c in own or not any(t.startswith(s) for t in tokens for s in sts):
                    continue
                group = [e for e in subjects if {p.code for p in subjects[e].portions} == own and title_code.get(e) in own]
                key = f"{c}|{','.join(group)}"
                if key in flagged:
                    continue
                flagged.add(key)
                names = ", ".join(label[e] for e in group)
                (own_code,) = own
                notes.append(f"Field notes: \"{sentence}\" This points to {c} work by {names}, but no time records divide their payroll ({refs['division']}), so it stays under {own_code}.")
                assume(f"Mixed duties without time records ({refs['division']}): payroll is not divided on a narrative or on sales figures; the employee stays under the code of the job on the register until time records are produced.")
                questions.append(Question(names, f"The field notes say: \"{sentence}\" Please tell us how many hours or shifts {names} worked as {c} ({guide.code_paragraph(c).code_name}) in the period, and send any time or shift records. Without them the payroll stays under {own_code}."))
    if emp.field_notes:
        records_used["field-notes.md"] = "auditor's visit notes, read for duties the records do not show"

    # Compare with the employer's own split.
    emp_list = [(eid, wages[eid]) for eid in wages]
    assignment = infer_employer_assignment(emp_list, emp.reported)
    adjustments: list[Adjustment] = []
    all_subjects = list(subjects.values()) + sub_subjects
    if assignment is not None:
        for eid, code in assignment.items():
            subjects[eid].employer_code = code
        for s in subjects.values():
            for p in s.portions:
                if "allowance not backed" in p.basis:
                    adjustments.append(Adjustment(s.label, p.amount, None, p.code, p.basis + ".", p.records, p.refs))
                elif p.code != s.employer_code:
                    adjustments.append(Adjustment(s.label, p.amount, s.employer_code, p.code, p.basis + ".", p.records, p.refs))
        for s in subjects.values():
            if s.employer_code and any(p.code != s.employer_code and "allowance not backed" not in p.basis for p in s.portions):
                for q in questions:
                    if q.subject == s.label:
                        q.text += f" The application reported this pay under {s.employer_code}."
                        break
    else:
        notes.append("The employer's split could not be matched to individual employees on the register, so differences are shown by code only.")
        for s in subjects.values():
            for p in s.portions:
                if "allowance not backed" in p.basis:
                    adjustments.append(Adjustment(s.label, p.amount, None, p.code, p.basis + ".", p.records, p.refs))
    for s in sub_subjects:
        for p in s.portions:
            adjustments.append(Adjustment(s.label, p.amount, None, p.code, p.basis + ".", p.records, p.refs))

    # Employees classified on their position alone.
    by_code_title: dict[str, list[str]] = collections.defaultdict(list)
    for eid, s in subjects.items():
        if len(s.portions) == 1 and s.portions[0].basis.startswith("position '") and "sign-ins" not in s.portions[0].basis:
            by_code_title[s.portions[0].code].append(eid)
    for c, eids in by_code_title.items():
        names = ", ".join(label[e] for e in eids)
        who = "this employee" if len(eids) == 1 else "any of them"
        questions.append(Question(names, f"From the positions on {reg_file}, we placed {names} under {c} ({guide.code_paragraph(c).code_name}, {guide.code_paragraph(c).id}). Please confirm the duties in the period were only of that kind; if {who} did other work, tell us what and send time records for it."))

    # Every adjustment has a question; every record relied on has a question.
    for a in adjustments:
        if not any(a.subject.split(" (")[0] in q.subject or a.subject.split(" (")[0] in q.text for q in questions):
            questions.append(Question(a.subject, f"Please confirm the record behind this change: {a.sentence()}"))
    total_reg = sum(wages.values(), ZERO)
    questions.append(Question(reg_file, f"Please confirm that {reg_file} (total {total_reg} for {len(wages)} employees) is the gross pay for the audit period {emp.period_start} to {emp.period_end}, including all commissions and bonuses, and that it agrees with your payroll tax filings."))
    for f, what in records_used.items():
        if f in (reg_file, "field-notes.md"):
            continue
        if not any(f in q.text for q in questions):
            questions.append(Question(f, f"Please confirm that {f} ({what}) is complete for the audit period."))

    return Result(emp, guide, office, governing, governing_basis, all_subjects, excluded, adjustments, questions, assumptions, records_used, notes, assignment)
