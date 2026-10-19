# BI layer: Excel, Power BI and Tableau

The Streamlit app stays the main interactive view. This folder gives the same results to the tools a
finance team already uses. **No BI tool re-derives a rule:** every flag, cause and € figure is computed in
Python and exported here, so the tools only filter, aggregate and display.

| Folder | What | Built by |
|---|---|---|
| [`data/`](data/) | CSV extracts that Excel (Power Query), Power BI and Tableau read | `python scripts/export_bi_data.py` |
| [`excel/`](excel/) | The business case as a live Excel model, plus a guide for pivot tables and Power Query | `python scripts/build_excel_workbook.py bi/excel/AP_business_case.xlsx` |
| [`powerbi/`](powerbi/) | Power Query scripts (one per CSV, typed with the en-US locale), the Date table, 40 DAX measures, a theme and a page-by-page build guide with the value each visual must show | Queries: `python scripts/export_bi_data.py`; the rest by hand |

The generated files are rebuilt from the code, and `tests/test_bi_exports.py` and `tests/test_powerbi.py` fail if a
committed file no longer matches it, so the BI views can't silently show old numbers.

## The files in `data/`

All files are UTF-8, comma-separated, with `.` as the decimal separator and dates as `YYYY-MM-DD`.
In a German-locale Excel or Power BI, set number and date types **using locale English (United States)**,
or amounts and dates are misread.

| File | One row per | Use it for |
|---|---|---|
| `invoices.csv` | Invoice | Spend, payment timing, PO compliance, discount capture, process path. Flags: `paid_on_time`, `discount_taken` (blank when not applicable), `has_po`, `path_type`, `rework_loops` |
| `vendors.csv` | Supplier | Supplier names, payment terms, preferred flag |
| `budgets.csv` | Department, category and month | Budget vs actual |
| `invoice_events.csv` | Process event | Process steps by role (never a person) |
| `leakage_by_driver.csv` | Driver | € leakage per driver, in two tiers (never add the tiers up) |
| `leakage_by_cause.csv` | Root cause | The Pareto of hard leakage by cause |
| `leakage_by_invoice.csv` | Invoice and driver | Hard leakage per invoice with its cause, for drill-down |
| `business_case_levers.csv` | Fix | Cost and benefit per fix (base case) |
| `business_case_scenarios.csv` | Scenario | Worst, base and best NPV, ROI and payback |
| `business_case_tornado.csv` | Assumption | Sensitivity of the NPV |
| `impact_effort_matrix.csv` | Fix | Quadrant and roadmap wave |
| `ctq_baseline.csv` | CTQ measure | The frozen Measure baseline with targets and owners |
| `control_report.csv` | Month and CTQ measure | The monthly control report for every month |
| `headline_figures.csv` | Figure | **The numbers every view must show** (task 6.5) |

## The cross-check (task 6.5)

Each tool shows the headline figures from `headline_figures.csv`. Before a view is shared, its numbers are
compared with that file:

| Figure | Value |
|---|---|
| Total spend | €3,699,592 |
| Hard leakage | €73,553 (2.0% of spend) |
| Controllable spend at risk | €389,395 |
| Days to pay (DPO) | 11.4 days, against agreed terms of 29.9 |
| Discount capture | 53.4% |
| PO compliance | 78.4% of spend |
| 3-year NPV, hard benefits | €118,772 |
