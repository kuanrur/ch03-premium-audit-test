# Decision rules

How the Skill turns an employer file into codes and payroll. Paragraph identifiers are those of the July 2025
classification guide excerpt; the scripts find the general paragraphs by title at run time, so a renumbered guide still
works, and every code citation in the outputs is read from the guide fetched during the run.

## Rules taken from the guide

| Rule | Guide | What the Skill does |
|---|---|---|
| Records decide | (assignment) | The employer's application is compared, never copied. Where records and the application disagree, the records decide. |
| Payroll | CG-03 | Payroll is `wages_paid` on the payroll register. An allowance paid on top of wages is left out only when it is a documented expense (see assumption A3). |
| Owners | CG-05 | An owner or officer with an election of exclusion who is not on the register is not counted. An owner on the register without an election is counted under the code for the owner's own work. |
| Assigning codes | CG-02 | Each employee starts under the code that describes the job on the register (`position-map.csv`). |
| Clerical | CG-04 | The office code applies only to duties confined to an office. |
| Division | CG-07 | Payroll is divided between codes only when the employer keeps records of time in each: crew timesheets with a type of work (divided by hours), or a route log that shows office staff on delivery vehicles (divided by days, priced with the weekly payroll). |
| Subcontractors | CG-06 | A payment to a subcontractor without a workers' compensation certificate covering the payment date is payroll under the code for the subcontractor's work. |
| Citation | Code paragraphs | `rationale_ref` is the identifier of the paragraph that describes the code. |

## House assumptions where the guide is silent

The interview with the auditor was not conducted in this test, so these are stated assumptions. Each one produces a
question to the employer, and each is printed in the report section of every employer it affects.

- **A1. Office staff at job sites.** An office-coded employee who signs in at a job site is not confined to an office
  (CG-04). Without time records (CG-07) the whole payroll goes to the principal business code (CG-02), however few the
  visits. If the business has no code other than the office code, the employee stays there and the visits are asked
  about.
- **A2. Principal business.** The principal business (CG-02) is the code with the most payroll outside the office code,
  measured from the records after timesheet and route-log division. With no such payroll, it is the employer's largest
  reported code.
- **A3. Allowances.** For an allowance column with a matching days column (for example `travel_allowance_paid` and
  `travel_days`), the part backed by recorded days at the most common per-day amount is a documented expense (CG-03).
  Anything paid beyond that, or with no recorded days, is payroll under the employee's code. A per-day amount that
  differs from the common one is asked about.
- **A4. Route-log division.** A day on a delivery vehicle counts as a full day of that code's work. The days an employee
  works in a week are taken as the operating days in the route log for that week, since office staff have no
  attendance record. The question to the employer says the share rises if the employee works fewer days.
- **A5. Subcontractor names.** A payment name that is a shortened form of a certificate holder's name (for example
  without "LLC" or a second trade) is taken as the same company, and the employer is asked to confirm it.
- **A6. Subcontractor amounts and dates.** The full amount paid to an uninsured subcontractor is payroll, and the
  payment date stands for the date of the work, because the files have no labor and material split and no work dates.
- **A7. Mixed duties without time records.** Payroll is never divided on a narrative, a job title or sales figures
  (for example receipts split between dining room and catering). The employee stays under the code of the job on the
  register, and the employer is asked for time records.

## Narrative check

Field notes are read sentence by sentence. A sentence that names a position on the register together with a word from
the title of another code the employer reports (for example "restaurant" for F-710 next to "catering lead") is reported
as an open point with a question. It never changes the allocation by itself (A7).

## Out of scope

Rates and premium (CG-01 describes the premium basis only so the payroll basis is clear). The Skill does not set rates,
apply experience modifiers or quote premium.
