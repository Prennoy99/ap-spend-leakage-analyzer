# Measure baseline: invoice-to-pay at Rheinwerk HQ

> **Portfolio note.** Rheinwerk Komponenten GmbH is a fictional client and all data is synthetic.

**Answer first.** Today the invoice-to-pay process runs at **1.6 to 4.1 sigma**, and every critical-to-quality
(CTQ) metric in the [charter](01_project_charter.md#5-critical-to-quality-metrics) misses its target. It loses
**€73.6k a year in hard leakage** (2.0% of spend), and **€389k of spend is at risk** (reported separately,
never added to the €73.6k). The weakest controls are early-payment discounts (only half are taken),
purchase-order discipline and rework. The most expensive one is the missing duplicate check.

This is the reference point for the rest of the project. Improve sizes each gap to target from it, and Control
measures every later month against it. It is frozen on purpose (see [section 6](#6-how-the-baseline-is-kept)).

## 1. Data basis

| | |
|---|---|
| Period | 12 months to 31 August 2026 (invoice dates 31 August 2025 – 31 August 2026) |
| Extract date | 31 August 2026 |
| Invoices | 2,550 from 40 suppliers, €3.70M; 2,457 paid, 93 open (€197k) |
| Budget lines | 432 department-category-months (6 departments × 6 categories × 12 months) |
| Process events | 10,882 events at role level (AP clerk, budget owner, Treasury); no names, see [stakeholder doc](04_stakeholders_and_raci.md) |
| Source | `data/processed/`, the cleaned output of `notebooks/01_ingest_transform.ipynb` |

**Exclusions are counted, not hidden.** 24 invoices have no submission date and are left out of processing
times; 13 paid invoices have no valid approval date and are left out of the approve → pay stage. Seven invoices
are dated 31 August 2025, one day before the first budget month, and so are missing from budget vs actual
(€6.9k). The app's **Data quality** tab lists them all, and shows for every figure how many invoices it leaves out and why.

## 2. CTQ baseline and targets

| CTQ | Baseline | Target | Target from | Owner |
|---|---|---|---|---|
| Duplicate payments | 50 suspected copies (€60.3k) | 0 paid | Charter | AP Manager |
| Processing time, median | 7 days | ≤ 4 days | Charter | AP Manager |
| Processing time, 90th percentile | 15 days | ≤ 8 days | Charter | AP Manager |
| Unapproved budget overruns | 50 of 432 department-category-months over 115% | 0 without approval | Charter | Controlling |
| Missing process timestamps | 24 invoices with no submission date | 0 | Charter | AP Manager |
| Payments breaching approval | 13 (8 paid before approval, 5 never approved) | 0 | Charter | AP Manager |
| Rework rate | 15.2% of invoices rejected at least once | ≤ 8% | **Proposed** | AP Manager |
| PO compliance | 78.4% of spend | ≥ 90% | **Proposed** | Procurement lead |
| Early-payment discount capture | 53.4% of discount invoices | ≥ 90% | **Proposed** | AP Manager |
| On-time payment rate | 95.0% of paid invoices | ≥ 98% | **Proposed** | AP Manager |
| Days payable outstanding (DPO) | 11.4 days (agreed terms: 29.9) | ≥ 24 days | **Proposed** | AP Manager |

Owners follow the proposed owners in the [process RACI](04_stakeholders_and_raci.md#4-process-raci-invoice-to-pay-today).
Treasury is consulted on the three payment-timing targets.

### Proposed targets, for sign-off at the Measure tollgate

The charter left five targets to be set once the baseline was known. Each proposal below is based on the data:

- **Rework ≤ 8%.** "Missing PO" and "Wrong cost centre" cause 55% of rejections, and both can be caught when
  the invoice is entered (no PO, no entry; cost centre taken from the PO). Without them, 7.1% of invoices
  would still be reworked, so 8% leaves a margin.
- **PO compliance ≥ 90% of spend.** A "no PO, no pay" rule, with an exception list agreed with Procurement
  (for example travel booked through the travel portal, or one-off fees).
- **Discount capture ≥ 90%.** A 2/10 Net 30 discount earns 37.2% a year, against an 8% cost of capital, so
  every discount is worth taking. The gap to 100% allows for disputed invoices.
- **On-time payment ≥ 98%.** The payment run selects invoices by due date. The gap allows for invoices held
  back on purpose.
- **DPO ≥ 24 days.** Paying every invoice on its due date, or on its discount date where a discount applies,
  gives 24.8 days. The target rounds that down, so it never asks AP to pay later than the terms allow.

## 3. Sigma levels: how often the process fails

For the yes/no defects, DPMO (defects per million opportunities) puts different failures on one scale.
Sigma levels include the conventional 1.5-sigma shift, so they compare directly with standard sigma tables.

| CTQ | Defects | Opportunities | DPMO | Sigma level |
|---|---:|---:|---:|---:|
| Early-payment discount missed | 284 | 610 discount invoices | 465,574 | **1.6** |
| Invoice without a PO | 517 | 2,550 invoices | 202,745 | **2.3** |
| Invoice reworked | 387 | 2,550 invoices | 151,765 | **2.5** |
| Budget overrun above 115% | 50 | 432 department-category-months | 115,741 | **2.7** |
| Paid after the due date | 123 | 2,457 paid invoices | 50,061 | **3.1** |
| Suspected duplicate payment | 50 | 2,550 invoices | 19,608 | **3.6** |
| No submission date | 24 | 2,550 invoices | 9,412 | **3.8** |
| Paid before or without approval | 13 | 2,457 paid invoices | 5,291 | **4.1** |

**Sigma ranks how often a control fails; € ranks what the failures cost.** The two lists don't agree.
Discount capture is the worst-performing control, but costs €7.6k. Duplicates fail far less often, yet
cost €60.3k. The recommendations are ranked by € ([`src/recommendations.py`](../src/recommendations.py)).
Sigma levels are for tracking whether each control improves.

PO compliance is reported by spend (78.4%), because one large invoice without a PO matters more than many small
ones. Its sigma level counts invoices, because DPMO needs countable units. By invoice count, 20.3% have no PO.

## 4. Where invoices wait

| Stage | Median | 90th percentile | Invoices measured | Left out |
|---|---:|---:|---:|---|
| Submit → approve | 4 days | 10 days | 2,458 | 24 with no submission date |
| Approve → pay | 3 days | 8 days | 2,444 | 5 never approved, 8 paid before approval |
| Submit → pay | 7 days | 15 days | 2,433 | 24 with no submission date |

Approval is the longer wait, and rework makes it longer: the [as-is process](06_as_is_process.md) shows that
a rejected invoice takes about twice as long to approve. Which causes matter most is tested in Analyze
(process mining and root cause). Rejections by reason:

| Reject reason | Rejections | Share | Invoices affected | Can be caught at entry |
|---|---:|---:|---:|---|
| Wrong cost centre | 154 | 35% | 150 | Yes: cost centre from the PO |
| Amount differs from PO | 101 | 23% | 95 | No: needs a price check with the supplier |
| Missing goods receipt | 99 | 22% | 94 | No: needs the receiving department |
| Missing PO | 92 | 21% | 85 | Yes: no PO, no entry |
| **Total** | **446** | | **387 invoices** | |

An invoice can be rejected more than once, so invoices affected add up to more than 387.

## 5. € leakage baseline

Two tiers, reported side by side and never added together (see the [driver tree](03_issue_and_driver_tree.md#2-driver-tree)).

| Driver | Tier | Cases | € impact per year |
|---|---|---:|---:|
| Duplicate payments | Hard leakage | 50 | 60,265 |
| Missed early-payment discounts | Hard leakage | 284 | 7,591 |
| Late-payment interest and fees | Hard leakage | 123 | 5,697 |
| **Hard leakage** | | | **73,553** |
| Spend above budget | Controllable spend at risk | 50 | 336,975 |
| Purchase-order premium (5% assumed) | Controllable spend at risk | 517 | 39,889 |
| Working capital given away (8% cost of capital) | Controllable spend at risk | 2,261 | 12,532 |
| **Controllable spend at risk** | | | **389,395** |

Of the €60.3k in duplicates, €48.2k is expected back from suppliers (80% recovery rate, an assumption to
confirm with the AP Manager). The assumptions are listed in the [driver tree](03_issue_and_driver_tree.md#assumptions-used-in-measure).

## 6. How the baseline is kept

- **Frozen files:** [`data/baseline/ctq_baseline.csv`](../data/baseline/ctq_baseline.csv) and
  [`data/baseline/leakage_baseline.csv`](../data/baseline/leakage_baseline.csv). They also hold DPMO, the
  reason for each target, and the figures behind every row of this page. Power BI, Tableau and Excel (Control)
  read the same files.
- **Computed, not typed:** [`src/baseline.py`](../src/baseline.py) builds both tables from the same KPI and
  impact functions the app uses. `python -m src.baseline` prints them.
- **A data change cannot move it silently:** [`tests/test_baseline.py`](../tests/test_baseline.py) recomputes
  the baseline and fails if it no longer matches the frozen files. Re-baselining is then a decision for the
  process owner, made on purpose with `python -m src.baseline --freeze`.
- **Checked against the answer key:** every defect count equals the number of cases the data generator planted.

*Targets marked "Proposed" become final once the AP Manager signs them off at the Measure tollgate; the
charter is updated then.*
