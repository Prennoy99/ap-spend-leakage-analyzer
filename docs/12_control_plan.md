# Control plan: keeping the gains

> **Portfolio note.** Rheinwerk Komponenten GmbH is a fictional client and all data is synthetic.

## The answer first

After go-live the AP Manager runs **one monthly control report** (the app's **Control** tab), and it answers
two questions for each of the 11 CTQ measures in the charter: *is it on target?* and *did the process change?*
Every measure has an owner, a frequency and a written reaction step. The detectors built in this project run
on every new extract and act as the daily and weekly checks.

- **Targets** come from the charter and the [Measure baseline](08_measure_baseline.md#2-ctq-baseline-and-targets).
- **Control limits** come from the baseline year and are frozen in `data/baseline/control_limits.csv`.
  A month outside them on the good side is the evidence that a fix works.
- **One known gap:** at the business case's base assumptions, discount capture reaches about 83%, not the
  90% target ([to-be process](11_to_be_process.md#what-it-does-to-the-process)). The reaction plan says what
  happens if it stalls there.

The report is computed by [`src/control.py`](../src/control.py). Each monthly figure reuses the function that
produced the baseline, on a one-month slice; over the full year it reproduces the frozen baseline exactly
(tested).

## 1. The control plan

| CTQ | Measure | Target | Baseline | How it is watched | Frequency | Owner | Reaction step |
|---|---|---|---|---|---|---|---|
| Duplicate payments | Suspected duplicate copies | 0 | 50 a year | PO block at entry; review list of same supplier and amount within 5 days | Daily list, monthly count | AP Manager | Block or claim back the copy this week; find out why the PO block let it through. Escalate to the CFO if a copy was paid |
| Processing time | Median, submission to payment | ≤ 4 days | 7 days | I-MR chart of weekly means (Process tab); median in the monthly report | Weekly chart, monthly figure | AP Manager | Open the slowest invoices of the week; check the approval queue and rework first |
| Processing time | 90th percentile | ≤ 8 days | 15 days | As above | Monthly | AP Manager | As above |
| Unapproved budget overruns | Department-category-months over 115% | 0 without approval | 50 | Live budget view; overrun detector | Weekly review, monthly count | Controlling | Written budget-owner approval before month-end close; reforecast if the same budget is over two months running |
| Missing process timestamps | Invoices with no submission date | 0 | 24 | Data quality tab; entry-screen rule | Monthly | AP Manager | Complete the date; IT checks why the entry screen accepted it |
| Payments breaching approval | Paid before or without approval | 0 | 13 | Payment block; conformance check (Process tab) | Every payment run, monthly count | AP Manager | Stop and review: the payment block failed. Internal Audit checks every case, same day |
| Rework rate | Invoices rejected at least once (by payment month) | ≤ 8% | 15.2% | p-chart; reject-reason Pareto | Monthly | AP Manager | Fix the month's top reject reason at entry or with the supplier |
| PO compliance | Spend with a purchase order | ≥ 90% | 78.4% | Monthly figure; no-PO spend by requester and supplier | Monthly | Procurement lead | Talk to the three requesters with the most no-PO spend |
| Discount capture | Discount invoices paid inside the window | ≥ 90% | 53.4% | p-chart; daily list of open invoices whose discount can still be taken (Control tab) | Daily list, monthly figure | AP Manager | Approved late → chase approval-deadline adherence; approved in time → check the payment schedule |
| On-time payment | Paid on or before the due date | ≥ 98% | 95.0% | p-chart; list of late payments | Monthly | AP Manager | Check due-date scheduling and invoices held back for disputes |
| Days payable outstanding | Invoice to payment, weighted by amount | ≥ 24 days | 11.4 days | Monthly figure against agreed terms (29.9 days) | Monthly | AP Manager | Look for early payments: nothing should be paid before its discount or due date |

## 2. Control limits

| Measure | Chart | Centre (baseline year) | Limits in a typical month |
|---|---|---|---|
| Rework rate | p-chart (≈213 paid invoices a month) | 15.2% | 7.8% to 22.6% |
| Discount capture | p-chart (≈53 discount invoices a month) | 53.4% | 32.9% to 74.0% |
| On-time payment | p-chart (≈213 paid invoices a month) | 95.0% | 90.5% to 99.5% |
| Weekly processing time | I-MR (49 weeks) | 9.57 days | 6.03 to 13.10 days; moving range up to 4.34 |

**How to read them.** p-chart limits are p ± 3·√(p(1−p)/n), so they depend on each month's volume; the
report computes them for the actual month. A month **above the target but inside the limits** has not yet
shown a real change. A month **outside the limits on the good side** is a signal that the process changed:
for discount capture, the 90% target lies far above the 74% upper limit, so a working fix shows up in its
first month. A month outside on the bad side calls for the reaction step even if it is still on target.

The counts with a target of 0 (duplicates, breaches, overruns without approval, missing dates) need no
limits: any case triggers the reaction step.

## 3. Monitoring calendar

| When | Who | What | Where |
|---|---|---|---|
| Daily | AP clerk | Clear the duplicate review list; work through the discount deadline list | ERP; Control tab (daily work list) |
| Every payment run | AP Manager | Release only approved invoices that are due; the payment block must hold | ERP |
| Weekly (Monday) | AP Manager | Weekly processing-time chart: any week outside the limits? | Process tab |
| Weekly (Monday) | Controlling | Live budget view: overruns approved or stopped before month-end | Budget view |
| Monthly (working day 3) | AP Manager | Run the control report; act on every reaction step; send it to the CFO | Control tab, CSV |
| Quarterly | Internal Audit | Sample payments for approval; review the month's conformance list | Process tab |
| Yearly | Procurement lead | Review supplier payment terms in the supplier master | Supplier master |

## 4. The detectors as ongoing monitoring

The rules built in Measure and Analyze run unchanged on every new extract:

| Check | Built in | Watches |
|---|---|---|
| Duplicate pairs (same supplier and amount within 5 days) | `anomalies.py` | Duplicates without a PO, which the entry block can't stop |
| PO reuse | `anomalies.find_po_reuse` | Whether the PO block works: should find nothing after go-live |
| Processing-time outliers | `anomalies.py` | Invoices stuck far beyond the normal range, open or paid |
| Budget overruns | `anomalies.py` | Overruns the weekly review missed |
| Conformance (alignments) | `process_mining.py` | Payments before or without approval; new paths in the process |
| Data-quality checks | `data_quality.py` | Gaps that would make any figure above wrong |

## 5. Refreshing the report (no code changes)

1. Export the four files from the ERP in the same layout as the files in `data/raw/` (`invoices.csv`,
   `vendors.csv`, `budgets.csv`, `invoice_events.csv`), put them in `data/raw/`, and set the extract date in
   `extract_metadata.json`. (`anomaly_ground_truth.csv` belongs to the synthetic data: with a real extract
   there is no answer key, and the detection scorecard on the How it works tab no longer applies.)
2. Run the cleaning notebook: `jupyter nbconvert --to notebook --execute --inplace notebooks/01_ingest_transform.ipynb`.
   It stops at the first failed validation check, which names the column to fix in the export.
3. Start the app (`streamlit run app.py`), open the **Control** tab, pick the month, and download the CSV.
4. Do **not** re-freeze the baseline or the limits as part of a refresh (see section 6).

## 6. When to re-baseline

The baseline and the limits describe the process **before** the fixes. Once the fixes have run for three
full months and the control report shows them holding, the AP Manager decides to re-baseline:

1. Agree the new reference period (the three or more months after go-live) and sign it off.
2. Re-freeze: `python -m src.baseline --freeze` and `python -m src.control --freeze`.
3. From then on, limits describe the improved process, and a signal means it has drifted back.

Re-freezing is always a decision, never a side effect: the tests fail if the data and the frozen files
disagree.

## 7. Known limits of the control report

- **Unapproved overruns** are counted as all overruns: the extract has no record of budget-owner approval.
  Once approvals are logged in the budget view, the measure counts only the unapproved ones.
- **Discount capture may stall around 83%** at the business case's base assumptions. If it is below 90% two
  months after wave 2, the escalation is to widen automatic approval of matched PO invoices, which removes
  the approval wait for most invoices.
- **Monthly p-charts on about 53 discount invoices** are wide; a small change takes a few months to show.
  The daily discount deadline list catches individual misses before they happen.

## 8. Hand-over checklist (Control tollgate)

- [ ] AP Manager has run the control report on a new extract alone, following section 5.
- [ ] Each owner in section 1 has accepted their measure and reaction step.
- [ ] Internal Audit has agreed the quarterly sample.
- [ ] The CFO receives the first monthly report.
- [ ] Re-baseline date set (three months after go-live).
