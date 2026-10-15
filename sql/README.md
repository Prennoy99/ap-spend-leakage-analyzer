# SQL layer

Every KPI the app shows, written as a DuckDB SQL query that runs straight on the
cleaned parquet files. It is the version of the logic that moves to a data
warehouse (Snowflake, BigQuery, SAP Datasphere) with only the table names changed.
`tests/test_sql_parity.py` checks that each query returns the same result as the
pandas function the app uses, so the dashboard and the warehouse can't disagree.

## Run it

From the project root, with the venv active:

```bash
python -m src.sql_kpis          # runs every query and prints the first rows
```

```python
from src import sql_kpis
sql_kpis.run_query("vendor_pareto")
sql_kpis.run_query("spend_by_vendor", top_n=5)
```

Or with the DuckDB command-line tool, from the project root:

```bash
cat sql/00_views.sql sql/vendor_pareto.sql | duckdb
```

`00_views.sql` defines four views (`invoices`, `vendors`, `budgets`,
`invoice_events`) over the parquet files. The KPI queries read only those views.

## Queries

| Query | Business question | pandas equivalent |
|---|---|---|
| `total_spend` | How much did we spend? | `kpis.total_spend` |
| `spend_by_department`, `spend_by_category`, `spend_by_month` | Where and when does the money go? | `kpis.spend_by_*` |
| `spend_by_vendor` | Who are our largest suppliers? (`$top_n`, default 10) | `kpis.spend_by_vendor` |
| `vendor_pareto` | How concentrated is our supplier base? (running total with a window function) | `kpis.vendor_pareto` |
| `budget_vs_actual` | Which department, category and month is over budget? | `kpis.budget_vs_actual` |
| `repeat_overruns` | Which budgets are overrun month after month? (gaps and islands; `$threshold`) | `kpis.repeat_overruns` |
| `days_payable_outstanding`, `agreed_payment_days` | Do we pay earlier than our terms require? | `kpis.days_payable_outstanding`, `kpis.agreed_payment_days` |
| `on_time_payment_rate` | Do we pay on time? | `kpis.on_time_payment_rate` |
| `payment_timing_by_vendor`, `payment_timing_by_month` | Which suppliers and months are paid early or late? | `kpis.payment_timing` |
| `discount_capture_rate` | How many early-payment discounts do we take? | `kpis.discount_capture_rate` |
| `discount_deadlines` | Which open invoices still qualify for a discount? | `kpis.discount_deadlines` |
| `po_compliance`, `po_compliance_by_department`, `po_compliance_by_vendor` | How much spend has no purchase order? | `kpis.po_compliance` |
| `no_po_spend_by_preferred` | Is no-PO spend going to non-preferred suppliers? | `kpis.no_po_spend_by_preferred` |
| `avg_processing_days`, `avg_processing_days_by_department` | How long does an invoice take from submission to payment? | `kpis.avg_processing_days` |
| `stage_durations` | Where do invoices wait? (median and P90 per stage) | `kpis.stage_durations` |
| `rework_rate`, `reject_reasons` | How many invoices are sent back, and why? (from the event log) | `kpis.rework_rate`, `kpis.reject_reasons` |
| `duplicate_pairs` | Which invoices look like duplicate payments? (`LAG` over supplier and amount; `$window_days`) | `anomalies.find_duplicate_pairs` |
| `process_variants` | Which paths do invoices take through the process? (`STRING_AGG … ORDER BY timestamp` over the event log) | `process_mining.variants` (pm4py) |
| `approval_breaches` | Which invoices were paid before or without an approval? (conditional aggregation with `FILTER`) | `process_mining.conformance` (pm4py alignments) |

`$parameters` default to the thresholds in `src/anomalies.py` (see
`DEFAULT_PARAMS` in `src/sql_kpis.py`), so a threshold is changed in one place only.

## Rounding

SQL's `ROUND` rounds a half away from zero (€6.645 → €6.65, as finance teams
round). pandas rounds a half to the nearest even digit (€6.64). On this data
that changes 2 of about 2,300 rounded figures by one unit of the last digit,
so the parity test allows one unit and nothing more. IDs, counts, dates and
row order must match exactly.
