# Class Code and Premium Audit Assistant

A reusable Agent Skill that does the premium audit team's first pass on a Linden Shore Mutual workers' compensation
employer file: it suggests the class codes, allocates the payroll to them, compares the result with the employer's own
split, and drafts the questions the auditor should put to the employer. It classifies and allocates payroll only; it
does not set rates or quote premium.

The Skill lives in [`skills/class-code-assistant/`](skills/class-code-assistant/SKILL.md). Its rules and the
assumptions made where the classification guide is silent are in
[`references/decision-rules.md`](skills/class-code-assistant/references/decision-rules.md).

## Before you work

**Interview rule.** You conduct the stakeholder interview yourself, and the questions are yours. Do not connect a coding
agent or any other AI to the interview to run, script, or automate it. The interview transcript is assessed together
with the code; a project whose interview was run by an agent is not scored.

**No interview was conducted in this test.** This repository is an end-to-end test of the learner path. The program
lead decided to skip the stakeholder interview and to read the employer files and the classification guide directly
from the audit team's Drive folder. There is therefore no `interviews/` folder. Every point where the auditor's house
practice would normally decide a case is handled by a stated assumption in
[`decision-rules.md`](skills/class-code-assistant/references/decision-rules.md), printed in the report section of each
employer it affects, and turned into a question for the employer.

## Setup

- Python 3.9 or later. No third-party packages.
- Network access to Google Drive. The guide and employer files are read from the publicly shared Drive folder
  "CH03 premium audit" (id in [`sources.json`](skills/class-code-assistant/sources.json)) at the start of every run and
  downloaded to `.cache/drive/` (ignored by git). If your Python has no CA certificates (python.org builds on macOS),
  the download falls back to the system `curl`.
- No secrets are needed or stored.

## Run

From the repository root:

```sh
# One employer
python3 skills/class-code-assistant/scripts/run_audit.py --employer harbor-point-legal

# All six employers (every folder under employer-files/ in the Drive folder)
python3 skills/class-code-assistant/scripts/run_audit.py --all

# Check the outputs
python3 skills/class-code-assistant/scripts/verify_outputs.py
```

Each run writes `deliverables/codes/<employer>.csv`, replaces the employer's section in
`deliverables/audit-report.md` and `deliverables/audit-questions.md`, and writes a run record to `runs/<employer>.json`
with the SHA-256 of every source file read.

### A new employer file

- If the auditor adds the employer's folder to `employer-files/` in the Drive folder (same file layout as the others),
  run `--employer <folder-name>` or `--all`.
- If the folder is only on your machine, run
  `python3 skills/class-code-assistant/scripts/run_audit.py --employer-dir path/to/new-employer`. The guide is still read
  from Drive. Use `--source-dir path/to/copy` to read a local copy of the whole audit folder instead.
- The required and optional files are listed under Inputs in [`SKILL.md`](skills/class-code-assistant/SKILL.md). Records
  are recognised by their columns, so renamed exports still load. A job title or type of work that matches no code
  stops nothing: it is placed under the principal business code and a question is drafted. Add the title or work type to
  `references/position-map.csv` or `references/work-type-map.csv` once the auditor has confirmed the code; the run
  refuses any code that the guide does not describe.

## Results

| Employer | Employer's own split | Allocation (class_code payroll) | What decided it |
|---|---|---|---|
| Harbor Point Legal | Accepted | C-110 425148.16 | Payroll register; the paralegal's six site sign-ins do not change the code because the firm has no code but C-110 |
| Bay Crest Exteriors | Not accepted | C-110 44812.35, R-310 327491.05, R-320 169194.65 | Crew timesheets (hours by roofing, siding, gutters) and the estimator's site sign-ins |
| Severn Homebuilders | Not accepted | C-110 46118.25, R-310 31645.65, H-420 456917.10 | Site sign-ins of the office manager and estimator; subcontractor payments against the insurance certificates |
| Patuxent Electric | Not accepted | C-110 43905.60, E-510 424414.85 | Payroll register (owner without an election, travel days and allowance) and the owner's site sign-ins |
| Annapolis Courier | Not accepted | C-110 121206.50, T-610 163308.90 | Route log (ride-along days) priced with the weekly payroll |
| Larkspur Lane Bistro | Accepted | F-710 226431.55, F-720 114293.80 | Payroll register; no time records for the catering crew's restaurant shifts, receipts are not time records |

Details, every adjustment to the cent, and the records behind each are in
[`deliverables/audit-report.md`](deliverables/audit-report.md); the questions for each employer are in
[`deliverables/audit-questions.md`](deliverables/audit-questions.md).

## How the results were verified

1. **Automated checks.** `verify_outputs.py` re-reads the guide and each payroll register from the downloaded source and
   checks, for all six employers: the exact CSV header; one row per code; no zero rows; dollars to the cent without
   separators; each `rationale_ref` is the guide paragraph that describes the code; the CSV total equals the register
   total plus the additions the run reports (uninsured subcontractors, undocumented allowances); every employee's
   portions add up to the register wages; one report and one question section per employer; every code, amount,
   adjustment and record appears in the report; every adjustment and every record relied on has at least one question;
   every question names its subject. Result on the committed outputs: 330 of 330 checks passed.
2. **The checker catches errors.** On a copy of the outputs with a thousands separator, a wrong `rationale_ref`, a zero
   row and a renamed subcontractor in the questions, it reported 9 failures and exited 1.
3. **Hand recalculation.** The figures were recomputed independently from the source files: Bay Crest roofing 8016
   hours, siding 4864, gutters 928; Darnell Price 61240.55 x 272 / 1776 = 9379.18 to R-320. Severn uninsured payments
   Tidewater Drywall 18240.55 + 22915.10 and Kent Island Roofing after 2026-01-31 19880.45 + 11765.20. Patuxent travel
   allowance 65.00 a day for 40 days (2600.00), Kyle Brandt 390.00 with no travel days. Annapolis Lena Ortiz 60 ride-along
   days x 912.35 / 6 = 9123.50; the weekly payroll totals equal the register for all six employees.
4. **Same result on Python 3.9 and 3.10**, and the error paths were exercised: unknown employer, a folder missing a
   required file, and a non-numeric timesheet value each stop that employer with a clear message and write nothing for
   it.

## Coding-session capture

This repository records coding sessions with Entire (`entire status` shows it enabled for Claude Code). Checkpoints are
created on commit and listed with `entire checkpoint list`.
