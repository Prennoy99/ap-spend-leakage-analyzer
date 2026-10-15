# Requirements: AP Spend Leakage Analyzer

> **Portfolio note.** Rheinwerk Komponenten GmbH is a fictional client and all data is synthetic.

A lightweight business requirements document (BRD). It turns the charter goals and the issue-tree
hypotheses into user stories with testable acceptance criteria, prioritised with MoSCoW.

**Users** are the stakeholders from the [stakeholder map](04_stakeholders_and_raci.md). **Scope** is as in the
[project charter](01_project_charter.md): HQ indirect spend, invoice-to-pay, analysis and decision support.
The solution reads ERP extracts. It does not change the ERP or block payments.

## 1. Business requirements

The charter goals, restated as what the solution must make possible.

| ID | Business requirement | Charter goal |
|---|---|---|
| BR-1 | Size the € leakage per driver, so the CFO can decide on AP automation against hard numbers | Business case (section 6) |
| BR-2 | Find suspected duplicate payments so they can be recovered now and stopped before payment later | Goal 1 |
| BR-3 | Measure processing time per stage and find where invoices wait | Goal 2 |
| BR-4 | Flag budget overruns while the month is still open | Goal 3 |
| BR-5 | Give the AP Manager a monthly control report they can run without the consultant | Goal 4 |

## 2. Priorities (MoSCoW)

| Priority | Meaning in this project |
|---|---|
| **Must** | Without it, a charter goal cannot be met or the € figures cannot be defended |
| **Should** | Important and planned, but a workaround exists for the first release |
| **Could** | Useful extra; done only if time allows |
| **Won't (this time)** | Explicitly out of scope for this engagement, with the reason recorded |

**Status:** *Built* = in the app today; *Partly built* = some acceptance criteria met; otherwise the
PLAN task that delivers it.

## 3. User stories

### CFO (sponsor)

**US-01 · Must · Hard-leakage headline** · BR-1 · Task 3.1, 3.3
> As the **CFO**, I want one € figure for hard leakage, split by driver, so that I can judge whether AP
> automation is worth the investment.

- **Given** the 12-month extract, **when** I open the app, **then** the first tab shows hard leakage in €,
  split into duplicates, missed discounts and late-payment cost.
- Controllable spend at risk (above budget, PO premium, working capital) is shown **separately** and is
  never added to hard leakage.
- Each figure states its assumptions (e.g. recovery rate) and links to the rule that produced it.
- Every figure equals the output of `src/impact.py` to the cent (pytest).

**US-02 · Must · Business case** · BR-1 · *Built* (Business case tab, task 5.2)
> As the **CFO**, I want ROI, a 3-year NPV and the payback period for the proposed fixes, with best, base
> and worst cases, so that I can take the investment to the board.

- Implementation cost, annual benefit and cost of capital are named inputs, not hidden constants. *(Built: day rates, days per fix and every assumption are named in `src/business_case.py`; benefits come from the measured leakage.)*
- NPV uses the cost of capital as the discount rate. The base case reproduces a hand-calculated example (pytest). *(Built: `tests/test_business_case.py`.)*
- A tornado chart shows which assumption moves NPV most. *(Built: implementation cost moves it most; break-even at 2.45 times the cost estimate. See [business case](10_business_case.md).)*

**US-03 · Should · Recommendations with € impact** · BR-1 · Task 3.3, 5.4
> As the **CFO**, I want the top three recommendations ranked by € impact and effort, so that I know what
> to approve first.

- Each recommendation names the driver it fixes, its annual € impact and an owner (from the
  [process RACI](04_stakeholders_and_raci.md#4-process-raci-invoice-to-pay-today)).

**US-04 · Could · Questions in plain English** · BR-1 · *Built*
> As the **CFO**, I want to ask a question in plain English and get a short answer, so that I don't need
> to read every chart.

- Every number in the answer exists in the facts JSON sent to the model. Raw invoice rows are never sent.
- With no API key, or when the model does not answer within 30 seconds, a saved answer for the same facts
  is shown, or a clear "AI unavailable" message.

*Why a Could:* the € figures and flags stand on their own. The AI explains them. It adds no new information.

### AP Manager (process owner)

**US-05 · Must · Suspected duplicate list** · BR-2 · *Built*
> As the **AP Manager**, I want a list of suspected duplicate pairs, so that my team can confirm each one
> with the supplier and claim the money back.

- A pair is: same `vendor_id`, same amount, invoice dates ≤ 5 days apart.
- Each row shows both invoice IDs, supplier, amount and days apart. *(Built.)*
- On the planted test data, the flags match the planted pairs exactly: every pair found, nothing else
  flagged. *(Today: 50 of 50 pairs, no false positives.)*
- The list can be downloaded as CSV for the supplier claims. *(Built: Anomalies tab, one row per pair.)*
- Gross exposure and confirmed (repaid) amounts are reported separately.

**US-06 · Must · Processing-time baseline by stage** · BR-3 · Task 3.2
> As the **AP Manager**, I want median and 90th-percentile processing time for each stage
> (submit → approve, approve → pay), so that I know where invoices wait.

- Median and P90 are shown per stage, for the whole period and by department.
- Invoices with a missing timestamp are excluded **and counted**. The count is shown next to the figure.
- Figures equal the SQL version of the same KPI (US-19). *(Built: `sql/stage_durations.sql`.)*

**US-07 · Must · Monthly control report** · BR-5 · Task 6.1, 6.3
> As the **AP Manager**, I want a monthly report of the control-plan KPIs against their targets, so that I
> can run the process without the consultant.

- One page: each CTQ metric from the charter, its target, this month's value and the trend.
- A value outside its target or control limit is highlighted and names the reaction-plan step.
- The AP Manager can refresh it from a new extract by following written steps, with no code changes.

**US-08 · Must · Data-quality report** · BR-3, BR-5 · *Built* (Data quality tab, task 3.7)
> As the **AP Manager**, I want to see which invoices have missing or inconsistent data, so that the
> baseline is trusted and the gaps get fixed at the source.

- The app lists invoices with a missing submission date (24 today) and any other failed validation check. *(Built: 8 checks, 4 find issues in 43 invoices; downloadable list for AP.)*
- No invoice is dropped silently. Every exclusion is counted in the figure it affects. *(Built: coverage table, included + left out = all invoices for each figure, with the reasons.)*
- Problems repaired in cleaning are listed with the fix at the source and its owner, because they return with every extract. *(Built: cleaning log written by the notebook.)*

**US-09 · Should · Process map and variants** · BR-3 · *Built* (Process tab, tasks 4.1, 4.2)
> As the **AP Manager**, I want to see the paths invoices actually take, including reject-and-resubmit
> loops, so that I can target the most common sources of rework.

- Shows a process map, the variants with their frequency, and the throughput time of each variant. *(Built: pm4py directly-follows graph with median waits, 16 variants, throughput by path type and by rework loops.)*
- Lists invoices paid without approval or paid before approval (conformance). *(Built: pm4py alignments against the approved process; 13 breaches, exactly the planted ones; CSV for Internal Audit.)*
- Resources are shown by **role only**, never by person (works council; see the stakeholder map). *(Built: the log has roles only.)*

**US-10 · Should · Control chart** · BR-3, BR-5 · *Built* (Process tab, task 4.4)
> As the **AP Manager**, I want a weekly control chart of processing time, so that I can tell a real
> change from normal variation.

- Individuals and moving-range (I-MR) chart, with control limits calculated from the baseline period. *(Built: `src/control_chart.py`; limits 6.0–13.1 days.)*
- Points outside the limits are flagged. *(Built: also a run of 8 weeks on one side; the one signal week is traced to its slowest invoices.)*

**US-11 · Should · What-if thresholds** · BR-2, BR-4 · *Built* (What-if tab, task 5.1)
> As the **AP Manager**, I want to change the detection thresholds and see the effect, so that I can agree
> sensible values with Controlling.

- A slider for the overrun threshold shows the number of flags, precision and recall, and € under review. *(Built: 100–150%; precision and recall from `evaluation.py`.)*
- Sliders for duplicate recovery %, days cut from approval, and number of suppliers consolidated show the €
  effect of each. *(Built: `src/what_if.py`; recovery, cost, cost of capital and ramp-up also move the business case NPV.)*

### AP clerk

**US-12 · Must · Explained flags** · BR-2, BR-4 · *Built*
> As an **AP clerk**, I want each flag to say why it was raised, so that I can check it without asking an analyst.

- Every flag states its rule and the numbers behind it, e.g. *"matches INV02502: vendor V001, amount 261.74, 1d apart"*.
- Detection uses explainable rules only, no machine learning.

**US-13 · Should · Discount deadline list** · BR-1 · Task 2.1, 2.8, 3.2
> As an **AP clerk**, I want a list of open invoices whose discount window is closing, so that I can
> process them first.

- Shows open invoices with discount terms, the last day for the discount, and the € discount at stake,
  sorted by deadline.

### Budget owner

**US-14 · Must · Budget vs actual for my department** · BR-4 · *Built*
> As a **budget owner**, I want my department's spend against budget by category and month, so that I can
> act before an overrun gets worse.

- Filter by department and category.
- Every department-category-month above 115% of budget is flagged with budget, actual and %.
- On the planted test data, overrun recall is 100%. *(Today: 42 of 42 planted overruns found. The 8 other
  flags are real overruns in the data that were not planted.)*

### Procurement lead

**US-15 · Must · PO compliance** · BR-1 · Task 2.2, 3.2
> As the **Procurement lead**, I want PO compliance (% of spend with a purchase order) by department and
> supplier, so that I can target maverick spend.

- Shows PO compliance % by department and by supplier, and the no-PO spend that went to non-preferred suppliers.

**US-16 · Should · Supplier concentration** · BR-1 · Task 3.2, 5.1
> As the **Procurement lead**, I want a Pareto chart of spend by supplier, so that I can see which small
> suppliers could be consolidated.

- Pareto chart with cumulative %; reports how many suppliers make up 80% of spend.

### Controlling

**US-17 · Should · Repeat overruns** · BR-4 · Task 3.2, 4.3
> As a **Controlling analyst**, I want to see which department-category budgets overrun month after
> month, so that I can tell a wrong budget from a one-off overspend.

- For each department and category: number of months over the threshold, and the longest run of
  consecutive months.

### Treasury

**US-18 · Should · Payment timing** · BR-1 · Task 3.1, 3.2
> As **Treasury**, I want DPO, the on-time payment rate and the cost of early payments, so that payment
> timing supports cash planning.

- DPO, on-time % and days paid before or after the due date, by supplier and by month.
- The working-capital cost of early payments uses the cost of capital agreed in US-02.

### IT and data team

**US-19 · Should · KPIs in SQL** · BR-5 · Task 3.5
> As the **IT data team**, I want each KPI as a SQL query, so that it can move to the company data warehouse later.

- One `.sql` file per KPI, running on the processed data. *(Built: 23 DuckDB queries in `sql/`, run straight on the parquet files.)*
- An automated test checks that every SQL result equals the pandas result. *(Built: `tests/test_sql_parity.py`. IDs, counts, dates and order match exactly; rounded figures to within one unit of the last digit, because SQL rounds a half away from zero and pandas to the nearest even digit: 2 of about 2,300 figures differ.)*

**US-20 · Should · Power BI dashboard** · BR-5 · Task 6.3
> As the **AP Manager**, I want the executive summary in Power BI, so that it fits into Finance's monthly
> reporting (to be confirmed: Q4).

- Headline numbers equal the app's figures to the cent.

**US-21 · Could · Tableau and Excel versions** · BR-5 · Task 6.2, 6.4
> As **Controlling**, I want the business case in Excel with live formulas, so that I can change the
> assumptions myself.

- The Excel business case gives the same ROI and NPV as `src/business_case.py`. A Tableau Public version
  shows the same KPIs.

## 4. Won't have (this time)

| Item | Why not |
|---|---|
| Blocking suspected duplicates in the ERP before payment | No ERP changes during the engagement (charter constraint). Designed in the [to-be process](11_to_be_process.md) (5.3) and costed in the [business case](10_business_case.md) instead. |
| Checking invoice prices against contract or PO prices (hypothesis A2) | The extract has no line items. Recommended as a follow-up. |
| Productivity or performance figures per employee | Would need a works agreement; the analysis stays at role level |
| E-mail or ERP alerts when a budget reaches 100% | Needs integration with the ERP and mail system; out of scope. The monitoring view (6.1) covers it manually. |
| Building the RPA or automation itself | Designed and costed only (charter scope) |
| Machine-learning anomaly detection | Rules can be explained to auditors and clerks; ML flags cannot (NFR-01) |
| The AI calculating, estimating or rounding any figure | Every figure must be traceable to code and tests (NFR-02) |

## 5. Non-functional requirements

| ID | Requirement | How it is verified |
|---|---|---|
| NFR-01 | **Explainable:** every flag names its rule and numbers; detection is rule-based | US-12 criteria; code review |
| NFR-02 | **The AI never calculates:** every number in an AI answer exists in the facts JSON; raw rows are never sent to the model | By design: retrieval sends aggregates only. `tests/test_retrieval.py` checks the request body for every question type: no invoice-level fields, at most 15 rows per list, bounded invoice IDs and size; retrieved figures equal `src/impact.py` and `src/kpis.py`. |
| NFR-03 | **Reproducible:** regenerating the data gives identical files (fixed seed, fixed end date) | Regenerate and compare files |
| NFR-04 | **Privacy:** no personal data in the event log or sent to the AI; roles only | Data dictionary review (2.5) |
| NFR-05 | **Works without the AI:** with no key or no response within 30 seconds, the app still shows every figure and a saved or "unavailable" answer | Unit tests with the API call faked |
| NFR-06 | **One version of the truth:** Streamlit, SQL, Power BI, Tableau and Excel show the same headline figures | SQL parity test (US-19); manual check for the BI tools (6.5) |
| NFR-07 | **Tested:** every calculation has an automated test; tests run without network access | `pytest` |
| NFR-08 | **Business language:** answer first, plain English, amounts in EUR | Review against the charter audience (CFO, AP Manager) |
| NFR-09 | **Detection accuracy is measured, not claimed:** precision and recall against the planted answer key are shown in the app | *Built* (How it works tab) |

## 6. Traceability

Every Must story traces to a charter goal and an issue-tree hypothesis, and on to a task and a test.

| Story | Charter goal / CTQ | Hypothesis | Delivered by | Verified by |
|---|---|---|---|---|
| US-01 | Business case | A1, B1, B2 | 3.1, 3.3 (Executive Summary tab) | `tests/test_impact.py`, `tests/test_recommendations.py` (headline quotes only computed figures) |
| US-02 | Business case | All | 5.2 (`src/business_case.py`, Business case tab, [doc](10_business_case.md)) | `tests/test_business_case.py` (hand-worked NPV, ROI and payback; levers equal the measured causes) |
| US-05 | Goal 1 · Duplicate payments | A1 | Built, incl. CSV export (3.3) | `tests/test_kpis.py`, `tests/test_impact.py` (exact match with planted pairs; copy = planted duplicate) |
| US-06 | Goal 2 · Processing time | D2 | 3.2 (`kpis.stage_durations`); 3.5 (`sql/stage_durations.sql`) | `tests/test_kpis.py` (excluded invoices equal the planted approval breaches), `tests/test_sql_parity.py` |
| US-07 | Goal 4 · Control report | All | 6.1, 6.3 | Hand-over walkthrough with the AP Manager |
| US-08 | Missing process timestamps | D2 | 3.2, 3.7 (`src/data_quality.py`, Data quality tab) | `tests/test_kpis.py` (missing dates excluded from processing time), `tests/test_data_quality.py` (coverage equals what each KPI uses; checks match the planted breaches; cleaning log matches the raw extract) |
| US-12 | Goals 1, 3 | A1, C1 | Built | Code review: every detector fills the `detail` column |
| US-14 | Goal 3 · Unapproved overruns | C1 | Built | `tests/test_kpis.py` (no planted overrun missed) |
| US-15 | PO compliance | C2 | 2.2, 3.2 (`kpis.po_compliance`, `kpis.no_po_spend_by_preferred`) | `tests/test_kpis.py` (matches planted maverick spend) |

Test files that do not exist yet are created by the task that delivers the story.

## 7. Open questions

| # | Question | Who decides | Needed by |
|---|---|---|---|
| Q1 | Which duplicate recovery rate goes into the business case: suppliers' historic repayment rate, or a flat assumption? | CFO, with the AP Manager | Improve (5.2). Measure uses a provisional flat 80%; the business case varies it from 60% to 95% (swing €19.5k in NPV) |
| Q2 | Is 115% the right overrun threshold, or should it vary by category? | AP Manager and Controlling | Improve (5.1) |
| Q3 | Which cost of capital applies (company WACC, or the credit-line rate)? | CFO | Improve (5.2). Measure uses a provisional 8% WACC; the business case varies it from 6% to 10% (swing €11.9k in NPV) |
| Q4 | What does Finance's monthly reporting use today, Power BI or Excel? This decides where US-07 lives. | AP Manager | Control (6.3) |
