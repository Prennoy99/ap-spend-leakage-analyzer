# Data dictionary

> **Portfolio note.** Rheinwerk Komponenten GmbH is a fictional client and all data is synthetic.

Every field in the extract, what it means, what is wrong with it in the raw files, and where the same
data lives in SAP, the most common ERP for a company of Rheinwerk's size. The SAP column is what an
analyst would ask IT to extract on a real engagement.

**Files:** raw CSVs in `data/raw/` (as extracted, with the mess), cleaned Parquet in `data/processed/`
(written by `notebooks/01_ingest_transform.ipynb`). The analysis code reads only `data/processed/`.

**Extract date: 31 August 2026** (`extract_metadata.json`). Anything that happened later is not in the
data. Invoices not yet paid on that date are **open items**.

## Invoices

`invoices.csv` → `invoices_clean.parquet` · 2,550 rows · one row per supplier invoice

| Field | Type | Description | Raw-file quirks (cleaned in the notebook) | SAP equivalent |
|---|---|---|---|---|
| `invoice_id` | text | Invoice document number | | `BKPF-BELNR` (accounting document number) |
| `vendor_id` | text | Supplier key; joins to vendors | | `BSEG-LIFNR` / `LFA1-LIFNR` |
| `po_number` | text | Purchase order the invoice is billed against. Empty = **maverick spend** | Missing POs written as empty, `N/A`, `-` or `none`; valid ones with spaces or a `PO ` prefix | `RSEG-EBELN` / `EKKO-EBELN` (POs are numbered `45…`) |
| `department` | text | HQ department that bears the cost | Mixed case, padded spaces (`" it "`, `"HR"`, `"Hr"`) | Cost centre `BSEG-KOSTL`, rolled up to department through the cost-centre hierarchy |
| `category` | text | Spend category | Mixed case, padded spaces | No single field: usually mapped from the G/L account (`BSEG-HKONT`) or material group (`EKPO-MATKL`) |
| `invoice_date` | date | Date on the supplier's invoice; baseline for payment terms | 8% in non-ISO formats (`MM/DD/YYYY`, `DD-Mon-YYYY`, `YYYY/MM/DD`) | `BKPF-BLDAT` (document date); baseline date `BSEG-ZFBDT` |
| `submitted_date` | date | Entered and sent for approval | Missing for 24 submitted invoices (workflow gap); empty by design for the 21 not yet submitted | Entry date of the parked document (`BKPF-CPUDT`) or workflow start |
| `approved_date` | date | Budget owner approved | Empty if not yet approved, or paid without approval | Workflow approval step completed (`SWWWIHEAD`), or posting of the parked document |
| `paid_date` | date | Payment made, invoice cleared | Empty for open invoices | Clearing date `BSAK-AUGDT` |
| `amount` | number | Invoice amount, EUR | | `BSEG-WRBTR` (amount in document currency) |
| `currency` | text | Always `EUR` | | `BKPF-WAERS` |
| `status` | text | `Paid`, or an open state at the extract date: `Approved`, `Pending approval`, `Received` | Mixed case, padded spaces | Derived: cleared items in `BSAK`, open items in `BSIK`, parked documents in `VBKPF` |

**Derived in the notebook** (not in the raw file):

| Field | Type | Rule | SAP equivalent |
|---|---|---|---|
| `has_po` | yes/no | `po_number` is a valid 10-digit `45…` number | |
| `missing_submitted_date` | yes/no | No `submitted_date`, although the invoice is past the `Received` stage | |
| `processing_days` | number | `paid_date − submitted_date`; empty if either is missing | |
| `extract_date` | date | Extract date, on every row | Extraction run date |
| `payment_terms`, `discount_pct`, `discount_days`, `net_days` | text, numbers | Copied from the vendor (see below) | `BSEG-ZTERM`, with days and % per term level in `ZBD1T`/`ZBD1P`, `ZBD2T` |
| `due_date` | date | `invoice_date + net_days` | Net due date, calculated from `ZFBDT` and the terms |
| `discount_date` | date | `invoice_date + discount_days`; empty if no discount terms | `ZFBDT + ZBD1T` |
| `vendor_name` | text | Joined from vendors, for display only | `LFA1-NAME1` |

## Vendors

`vendors.csv` → `vendors_clean.parquet` · 40 rows · supplier master data

| Field | Type | Description | Raw-file quirks | SAP equivalent |
|---|---|---|---|---|
| `vendor_id` | text | Supplier key | | `LFA1-LIFNR` |
| `vendor_name` | text | Supplier name | Padded or doubled spaces | `LFA1-NAME1` |
| `category` | text | Main spend category the supplier serves | | No standard field (vendor classification) |
| `payment_terms` | text | Agreed terms: `Net 14`, `Net 30`, `Net 45`, or `2/10 Net 30` (2% discount if paid within 10 days, otherwise due in 30) | Typed several ways (`2/10 NET30`, ` net 45 `); rewritten in one spelling | `LFB1-ZTERM` (company-code terms key), defined in table `T052` |
| `discount_pct` | number | Early-payment discount, % (0 if none) | Derived from `payment_terms` | `T052-ZPRZ1` |
| `discount_days` | number | Days from invoice date to take the discount; empty if none | Derived | `T052-ZTAG1`, when `ZPRZ1` > 0 |
| `net_days` | number | Days from invoice date until due | Derived | The last term level, which has no discount: `ZTAG1` for net-only terms, `ZTAG2` for `2/10 Net 30` |
| `preferred_vendor` | yes/no | On Procurement's preferred-supplier list | `Y`/`N` in the raw file | No standard field: often a source list (`EORD`) or vendor classification |

## Budgets

`budgets.csv` → `budgets.parquet` · 432 rows · 6 departments × 6 categories × 12 months

| Field | Type | Description | SAP equivalent |
|---|---|---|---|
| `department` | text | HQ department | Cost centre (`KOSTL`) group |
| `category` | text | Spend category | Cost element / G/L account group |
| `month` | text | `YYYY-MM`, September 2025 to August 2026 | Fiscal period |
| `budget_amount` | number | Monthly budget, EUR | Plan data (`COSP`; `ACDOCP` in S/4HANA) |

## Process event log

`invoice_events.csv` → `invoice_events.parquet` · 10,882 rows · one row per process step, for process mining

| Field | Type | Description | SAP equivalent |
|---|---|---|---|
| `invoice_id` | text | Case ID: the invoice the step belongs to | Object key in the workflow or change log |
| `activity` | text | `Receive invoice`, `Submit for approval`, `Reject invoice`, `Correct and resubmit`, `Approve invoice`, `Pay invoice` | Workflow step (`SWWLOGHIST`), change documents (`CDHDR`/`CDPOS`) |
| `timestamp` | date and time | When the step happened | Same sources; time from the log entry |
| `resource_role` | text | Role that did the step: `AP clerk`, `Budget owner`, `Treasury` | Mapped from user ID to role. **User IDs are deliberately not extracted** (works council; see the [stakeholder map](04_stakeholders_and_raci.md)) |
| `reject_reason` | text | Only on `Reject invoice`: `Wrong cost centre`, `Amount differs from PO`, `Missing goods receipt`, `Missing PO` | Workflow decision note, or a custom reason code |

The notebook checks the log against the invoice table: each step's date equals the matching invoice
date column, every case is a known invoice, and nothing happens after the extract date. The `Submit for
approval` event is missing for the same 24 invoices that have no `submitted_date`.

## Cleaning log

`cleaning_log.parquet` · 8 rows · written by the notebook, one row per kind of repair

| Field | Type | Description |
|---|---|---|
| `table`, `field` | text | Where the problem was (`invoices.po_number`, `vendors.payment_terms`, …) |
| `issue` | text | What was wrong, e.g. `Missing PO typed as text` |
| `rows` | number | Rows the repair changed |
| `examples` | text | Up to three raw values as typed, one per format, quoted so stray spaces show |
| `rule` | text | How cleaning repaired it |

The app's Data quality tab adds the fix at the source and its owner (`src/data_quality.py`). The PO count is
taken from the text as typed: `read_csv` would otherwise turn `N/A` into an empty value and hide 204 of them.

## Answer key (tests only)

`anomaly_ground_truth.csv` lists what the generator planted or knows to be true, so the tests can check the
pipeline and the detectors. **The analysis code never reads it.** A real extract has no such file.

| `anomaly_type` | Rows | Meaning |
|---|---|---|
| `duplicate_payment` | 50 | The second invoice of each planted duplicate pair |
| `processing_time_outlier` | 67 | Invoices delayed by 45–90 days (paid, or still open for over 30 days) |
| `budget_overrun` | 42 | Department-category-months pushed to 115–160% of budget |
| `maverick_spend` | 517 | Invoices without a PO |
| `missed_discount` | 284 | Paid after the discount window, although discount terms applied |
| `late_payment` | 123 | Paid after the due date |
| `paid_before_approval` | 8 | Approval recorded after payment |
| `paid_without_approval` | 5 | Paid, never approved |
| `rework_loop` | 387 | Invoices rejected and resubmitted at least once (`detail` gives the number of loops) |

## SAP notes for a real extract

- In S/4HANA, `BSIK`/`BSAK` are compatibility views over the universal journal `ACDOCA`. The fields are the same.
- Payment terms can differ between the vendor master and the individual invoice. A real analysis takes
  them from the invoice line (`BSEG-ZTERM`), not the master.
- The event log usually needs several sources joined on the document key: workflow logs, change documents,
  and the posting and clearing dates. Process-mining tools such as Celonis ship ready-made SAP connectors for this.
