---
name: class-code-assistant
description: First-pass premium audit for a Linden Shore Mutual workers' compensation employer file. Reads the company's classification guide and the employer's records from the audit team's Drive folder, suggests class codes, allocates payroll to them, compares the result with the employer's own split, and drafts the questions the auditor should put to the employer. Use when an auditor asks to classify, allocate payroll for, or prepare audit questions on an employer file. It does not set rates or quote premium.
---

# Class code assistant

Does the first pass on an employer file for the premium audit team: suggest the class codes, allocate the payroll to
them, and list the questions to put to the employer before sign-off. The company uses its own class codes, so only the
classification guide in the audit folder is used; public classification manuals do not apply.

## Inputs

- **Classification guide**: `classification-guide.md` in the audit team's Drive folder "CH03 premium audit"
  (folder id in `sources.json`). Read fresh on every run.
- **Employer file**: one folder per employer under `employer-files/` in the same Drive folder, named with the employer
  slug (for example `harbor-point-legal`). Required: `application.md` (the employer's own split),
  `business-description.md` (audit period, owners), `payroll-register.csv`
  (`employee_id,name,position,wages_paid`, optionally `<x>_days,<x>_allowance_paid`). Used when present, recognised by
  their columns: crew timesheets (`date,employee_id,work_type,hours`), site sign-in log (`date,employee_id,site`), route
  log (`date,route_id,driver_id,ride_along_id`), weekly payroll (`week_start,week_end,employee_id,gross_pay`),
  subcontractor payments (`date,subcontractor,work,amount_paid`), insurance certificates
  (`subcontractor,coverage_from,coverage_to`), and `field-notes.md`. Any other file is listed in the report as not used.
- A local copy of the folder can be used instead of Drive with `--source-dir`, and a single employer folder outside
  Drive with `--employer-dir`.

## Invocation

From the repository root (Python 3.9 or later, standard library only):

```sh
python3 skills/class-code-assistant/scripts/run_audit.py --employer harbor-point-legal   # one employer
python3 skills/class-code-assistant/scripts/run_audit.py --all                          # every employer in the folder
python3 skills/class-code-assistant/scripts/verify_outputs.py                           # check the outputs
```

When an agent runs this Skill:

1. Run `run_audit.py` for the employer(s) asked for. It downloads the Drive folder into `.cache/drive/` first.
2. Read the employer's `field-notes.md`, `business-description.md` and the application note, then read the employer's
   section of `deliverables/audit-report.md`. Check that every statement in the narrative is either reflected in an
   adjustment, an assumption, a note or a question. If something is missing, say so to the auditor; do not edit the
   generated files by hand.
3. Run `verify_outputs.py` and report its result.
4. Tell the auditor, per employer, whether the employer's own split is accepted and which record that rests on.

## Outputs

Paths are relative to the repository root (`--out` changes the root).

| Path | Content |
|---|---|
| `deliverables/codes/<employer>.csv` | `class_code,payroll_allocated,rationale_ref`; one row per code with payroll, dollars to the cent, no separators; `rationale_ref` is the guide paragraph describing the code. |
| `deliverables/audit-report.md` | One section per employer: decision on the employer's split, codes and payroll, comparison with the employer's split, every adjustment with its amount, records relied on, assumptions, notes. |
| `deliverables/audit-questions.md` | One section per employer: questions that each name an employee, subcontractor or record. |
| `runs/<employer>.json` | Run record: where the sources were read from, SHA-256 of every file read, the allocation per employee and payment, adjustments and questions. |

A run on one employer replaces only that employer's sections in the two Markdown files.

## Error behavior

- Drive folder not reachable or not shared publicly: prints `error: ...` and exits 1 without writing anything.
- Guide missing, or missing a general paragraph the rules need (Assigning codes, Payroll, Owners and executive
  officers, Subcontractors, Division of payroll), or a vocabulary map that uses a code the guide does not describe:
  exits 1 without writing anything.
- Employer folder missing a required file, a malformed amount or date, or a duplicated employee: that employer is
  skipped with `error: <employer>: ...`, the others are still processed, and the exit status is 1.
- A position or subcontractor trade that matches no code is not guessed: the employee or payment goes under the
  principal business code and a question asks the employer to describe the work. Timesheet hours with an unknown type
  of work stay with the employee's own job code, with the same kind of question.

## Supporting files

- `scripts/fetch_drive.py`: downloads the public Drive folder (falls back to the system `curl` when Python has no CA
  certificates).
- `scripts/guide.py`: parses the guide into paragraphs and codes.
- `scripts/employer.py`: loads an employer folder; recognises records by their columns.
- `scripts/allocate.py`: the classification and allocation rules.
- `scripts/render.py`: writes the CSV, report and question sections and the run record.
- `scripts/run_audit.py`: command line entry point.
- `scripts/verify_outputs.py`: checks the outputs against the format rules and the source records.
- `references/decision-rules.md`: the rules, the guide paragraphs they rest on, and the house assumptions where the
  guide is silent.
- `references/position-map.csv`, `references/work-type-map.csv`: job titles and types of work matched to class codes;
  every code in them must exist in the guide or the run stops.
- `sources.json`: the Drive folder, file names, and the order of sections in the combined reports.
