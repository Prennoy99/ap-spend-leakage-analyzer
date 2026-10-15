"""Synthetic finance-ops data generator.

Produces vendor invoices, monthly department/category budgets, and a
ground-truth anomaly label file. Ground truth is written separately from
the raw invoice/budget data on purpose: real invoice data would never carry
a "this row is fraudulent" column, and src/anomalies.py must detect these
cases from statistical signal alone, not read the label. Ground truth
exists only so tests/test_kpis.py can check detection results against
what was actually planted.

The extension (payment terms, purchase orders, process events, the extract
date) draws from its own random generator, so adding it left every original
date, amount and planted anomaly exactly as it was.
"""

import json
import random
import re
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

SEED = 42
N_VENDORS = 40
N_BASE_INVOICES = 2500
MONTHS_BACK = 12

DEPARTMENTS = ["Finance", "IT", "Marketing", "Operations", "HR", "Legal"]
CATEGORIES = ["Consulting", "Software & IT Services", "Facilities", "Travel", "Office Supplies", "Professional Services"]
CURRENCY = "EUR"

DUPLICATE_RATE = 0.02
PROCESSING_OUTLIER_RATE = 0.03
OVERRUN_GROUP_RATE = 0.10

DEPT_CASE_MESSY_RATE = 0.15
CATEGORY_CASE_MESSY_RATE = 0.15
STATUS_CASE_MESSY_RATE = 0.10
DATE_FORMAT_MESSY_RATE = 0.08
MISSING_SUBMITTED_DATE_RATE = 0.01
VENDOR_NAME_WHITESPACE_RATE = 0.15

OUT_DIR = Path(__file__).parent / "raw"

# Fixed, not today(): with a moving end date, re-running this script
# shifts every date and anomaly, so data/raw would no longer match the
# included data/processed parquet and the ground-truth tests would fail.
END_DATE = pd.Timestamp("2026-08-31")

# --- Extension: payment terms, POs, process events, extract date ------------
# Everything from here on draws from its own generator seeded with
# EXTENSION_SEED, never from the global random/np.random state. The global
# stream (and so every original column) is the same as before the extension.
EXTENSION_SEED = SEED + 100

# The ERP extract is taken at the end of the last data day. Approvals and
# payments that would happen later are not in it: those invoices are open,
# as in a real AP ledger on extract day.
EXTRACT_DATE = END_DATE

# Terms as written on the supplier master. "2/10 Net 30" = 2% discount if paid
# within 10 days of the invoice date, otherwise due in 30 days. Preferred
# suppliers more often have a negotiated discount; others more often Net 14.
PREFERRED_VENDOR_SHARE = 0.6
PAYMENT_TERMS_PREFERRED = {"2/10 Net 30": 0.40, "Net 30": 0.40, "Net 45": 0.20}
PAYMENT_TERMS_OTHER = {"Net 14": 0.30, "Net 30": 0.50, "2/10 Net 30": 0.10, "Net 45": 0.10}
PAYMENT_TERMS_MESSY_RATE = 0.20

# Maverick spend (no purchase order) is far more common with non-preferred
# suppliers (hypothesis C2) and in Marketing and HR, where ad-hoc buying is typical.
NO_PO_RATE_PREFERRED = 0.06
NO_PO_RATE_OTHER = 0.30
NO_PO_DEPARTMENT_MULTIPLIER = {"Marketing": 1.5, "HR": 1.5}
PO_NUMBER_PREFIX = "45"  # SAP's default purchase-order number range (EBELN 45xxxxxxxx)
PO_MISSING_SPELLINGS = ["", "N/A", "-", "none", "n/a"]
PO_PADDED_RATE = 0.08
PO_PREFIXED_RATE = 0.05

# Control breaches for the conformance check: urgent invoices paid before the
# approval was recorded (approved retroactively), and a few never approved.
N_PAID_BEFORE_APPROVAL = 8
N_PAID_WITHOUT_APPROVAL = 5

# Reject -> correct -> resubmit loops. The chance of a loop rises with the
# approval time already in the data, so rework explains part of the slow
# approvals instead of adding delay on top (the original dates stay as they
# are). Invoices without a PO are rejected more often, mostly for "Missing PO".
REWORK_BASE_RATE = 0.02
REWORK_RATE_PER_APPROVAL_DAY = 0.025
REWORK_MAX_RATE = 0.5
REWORK_NO_PO_MULTIPLIER = 1.8
REWORK_MIN_APPROVAL_DAYS = 3
SECOND_LOOP_RATE = 0.2
SECOND_LOOP_MIN_APPROVAL_DAYS = 6
REJECT_REASONS_NO_PO = {"Missing PO": 0.7, "Wrong cost centre": 0.3}
REJECT_REASONS_WITH_PO = {"Amount differs from PO": 0.35, "Wrong cost centre": 0.35, "Missing goods receipt": 0.30}

# The invoice table holds dates only, but an event log needs a strict order
# within a day, so each activity gets its own band of working hours.
ACTIVITY_HOURS = {
    "Receive invoice": (8, 10),
    "Submit for approval": (10, 12),
    "Reject invoice": (12, 13),
    "Correct and resubmit": (13, 14),
    "Approve invoice": (14, 16),
    "Pay invoice": (16, 17),
}
# Roles only, never people: person-level logs would need a works agreement.
ACTIVITY_ROLE = {
    "Receive invoice": "AP clerk",
    "Submit for approval": "AP clerk",
    "Reject invoice": "Budget owner",
    "Correct and resubmit": "AP clerk",
    "Approve invoice": "Budget owner",
    "Pay invoice": "Treasury",
}

# A planted processing-time outlier that is still open at extract only counts
# as detectable once it has been open longer than this. Normal invoices are
# approved and paid well within it, so younger ones look like normal open items.
OPEN_OUTLIER_MIN_AGE_DAYS = 30


def make_vendors(fake: Faker) -> pd.DataFrame:
    rows = []
    for i in range(1, N_VENDORS + 1):
        rows.append({
            "vendor_id": f"V{i:03d}",
            "vendor_name": fake.company(),
            "category": random.choice(CATEGORIES),
        })
    return pd.DataFrame(rows)


def make_budgets(end_date: pd.Timestamp) -> pd.DataFrame:
    months = pd.date_range(end=end_date, periods=MONTHS_BACK, freq="MS")
    rows = []
    for month in months:
        for dept in DEPARTMENTS:
            for cat in CATEGORIES:
                base = random.uniform(8000, 35000)
                rows.append({
                    "department": dept,
                    "category": cat,
                    "month": month.strftime("%Y-%m"),
                    "budget_amount": round(base, 2),
                })
    return pd.DataFrame(rows)


def make_base_invoices(fake: Faker, vendors: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    rows = []
    date_span_days = (end_date - start_date).days

    for i in range(1, N_BASE_INVOICES + 1):
        vendor = vendors.sample(1).iloc[0]
        dept = random.choice(DEPARTMENTS)

        invoice_date = start_date + pd.Timedelta(days=random.randint(0, date_span_days))
        submitted_date = invoice_date + pd.Timedelta(days=random.randint(0, 5))
        approval_lag = max(1, int(np.random.gamma(shape=2.0, scale=2.5)))
        approved_date = submitted_date + pd.Timedelta(days=approval_lag)
        payment_lag = max(1, int(np.random.gamma(shape=2.0, scale=2.0)))
        paid_date = approved_date + pd.Timedelta(days=payment_lag)

        amount = round(float(np.random.lognormal(mean=6.5, sigma=1.0)), 2)
        amount = min(amount, 50000.0)

        rows.append({
            "invoice_id": f"INV{i:05d}",
            "vendor_id": vendor["vendor_id"],
            "department": dept,
            "category": vendor["category"],
            "invoice_date": invoice_date.date().isoformat(),
            "submitted_date": submitted_date.date().isoformat(),
            "approved_date": approved_date.date().isoformat(),
            "paid_date": paid_date.date().isoformat(),
            "amount": amount,
            "currency": CURRENCY,
            "status": "Paid",
        })

    return pd.DataFrame(rows)


def inject_duplicate_payments(invoices: pd.DataFrame, next_id: int) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    n = max(1, int(len(invoices) * DUPLICATE_RATE))
    originals = invoices.sample(n, random_state=SEED)

    dup_rows = []
    ground_truth = []
    for _, orig in originals.iterrows():
        dup = orig.copy()
        dup["invoice_id"] = f"INV{next_id:05d}"
        next_id += 1

        orig_date = pd.Timestamp(orig["invoice_date"])
        dup["invoice_date"] = (orig_date + pd.Timedelta(days=random.randint(0, 2))).date().isoformat()
        dup["submitted_date"] = (pd.Timestamp(dup["invoice_date"]) + pd.Timedelta(days=random.randint(0, 3))).date().isoformat()
        dup["approved_date"] = (pd.Timestamp(dup["submitted_date"]) + pd.Timedelta(days=random.randint(1, 5))).date().isoformat()
        dup["paid_date"] = (pd.Timestamp(dup["approved_date"]) + pd.Timedelta(days=random.randint(1, 4))).date().isoformat()

        dup_rows.append(dup)
        ground_truth.append({
            "anomaly_type": "duplicate_payment",
            "invoice_id": dup["invoice_id"],
            "department": None,
            "category": None,
            "month": None,
            "detail": f"duplicate of {orig['invoice_id']}",
        })

    return pd.DataFrame(dup_rows), pd.DataFrame(ground_truth), next_id


def inject_processing_time_outliers(invoices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = max(1, int(len(invoices) * PROCESSING_OUTLIER_RATE))
    idx = invoices.sample(n, random_state=SEED + 1).index

    ground_truth = []
    for i in idx:
        submitted = pd.Timestamp(invoices.at[i, "submitted_date"])
        stretched_paid = submitted + pd.Timedelta(days=random.randint(45, 90))
        invoices.at[i, "approved_date"] = (submitted + pd.Timedelta(days=random.randint(20, 40))).date().isoformat()
        invoices.at[i, "paid_date"] = stretched_paid.date().isoformat()

        ground_truth.append({
            "anomaly_type": "processing_time_outlier",
            "invoice_id": invoices.at[i, "invoice_id"],
            "department": None,
            "category": None,
            "month": None,
            "detail": "submitted-to-paid stretched to 45-90 days",
        })

    return invoices, pd.DataFrame(ground_truth)


def inject_budget_overruns(invoices: pd.DataFrame, budgets: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    invoices = invoices.copy()
    invoices["month"] = pd.to_datetime(invoices["invoice_date"]).dt.strftime("%Y-%m")

    groups = budgets.sample(frac=1.0, random_state=SEED + 2)
    n_groups = max(1, int(len(budgets) * OVERRUN_GROUP_RATE))
    target_groups = groups.head(n_groups)

    ground_truth = []
    for _, g in target_groups.iterrows():
        mask = (
            (invoices["department"] == g["department"])
            & (invoices["category"] == g["category"])
            & (invoices["month"] == g["month"])
        )
        group_idx = invoices[mask].index
        if len(group_idx) == 0:
            continue

        current_total = invoices.loc[group_idx, "amount"].sum()
        target_total = g["budget_amount"] * random.uniform(1.15, 1.6)
        if current_total <= 0:
            continue

        scale = target_total / current_total
        invoices.loc[group_idx, "amount"] = (invoices.loc[group_idx, "amount"] * scale).round(2)

        ground_truth.append({
            "anomaly_type": "budget_overrun",
            "invoice_id": None,
            "department": g["department"],
            "category": g["category"],
            "month": g["month"],
            "detail": f"actual ~{invoices.loc[group_idx, 'amount'].sum():.2f} vs budget {g['budget_amount']:.2f}",
        })

    invoices = invoices.drop(columns=["month"])
    return invoices, pd.DataFrame(ground_truth)


def messify_case(value: str) -> str:
    variant = random.choice(["upper", "lower", "title", "pad"])
    if variant == "upper":
        return value.upper()
    if variant == "lower":
        return value.lower()
    if variant == "title":
        return value.title()
    return f"  {value}  "


def messify_invoices(invoices: pd.DataFrame, protected_ids: set) -> pd.DataFrame:
    """Add presentation-layer mess (casing, whitespace, date formats, a few
    missing timestamps) on top of already-final anomaly rows. Run only after
    duplicate/outlier/overrun injection so the planted anomalies stay intact
    and detectable in amount/date fields; this only touches text formatting.
    """
    invoices = invoices.copy()

    dept_mask = np.random.rand(len(invoices)) < DEPT_CASE_MESSY_RATE
    invoices.loc[dept_mask, "department"] = invoices.loc[dept_mask, "department"].map(messify_case)

    cat_mask = np.random.rand(len(invoices)) < CATEGORY_CASE_MESSY_RATE
    invoices.loc[cat_mask, "category"] = invoices.loc[cat_mask, "category"].map(messify_case)

    status_mask = np.random.rand(len(invoices)) < STATUS_CASE_MESSY_RATE
    invoices.loc[status_mask, "status"] = invoices.loc[status_mask, "status"].map(messify_case)

    date_formats = ["%m/%d/%Y", "%d-%b-%Y", "%Y/%m/%d"]
    date_mask = np.random.rand(len(invoices)) < DATE_FORMAT_MESSY_RATE
    for i in invoices[date_mask].index:
        fmt = random.choice(date_formats)
        invoices.at[i, "invoice_date"] = pd.Timestamp(invoices.at[i, "invoice_date"]).strftime(fmt)

    eligible = invoices.index[~invoices["invoice_id"].isin(protected_ids)]
    n_missing = max(1, int(len(eligible) * MISSING_SUBMITTED_DATE_RATE))
    missing_idx = np.random.choice(eligible, size=n_missing, replace=False)
    invoices.loc[missing_idx, "submitted_date"] = None

    return invoices


def messify_vendors(vendors: pd.DataFrame) -> pd.DataFrame:
    def messy_name(name: str) -> str:
        variant = random.choice(["pad", "double_space", "as_is"])
        if variant == "pad":
            return f"  {name}  "
        if variant == "double_space":
            return name.replace(" ", "  ", 1)
        return name

    vendors = vendors.copy()
    mask = np.random.rand(len(vendors)) < VENDOR_NAME_WHITESPACE_RATE
    vendors.loc[mask, "vendor_name"] = vendors.loc[mask, "vendor_name"].map(messy_name)
    return vendors


# --- Extension --------------------------------------------------------------

def _weighted_choice(rng: np.random.Generator, weights: dict) -> str:
    keys = list(weights)
    return keys[rng.choice(len(keys), p=list(weights.values()))]


def parse_terms(terms: str) -> tuple[float, int | None, int]:
    """(discount %, discount days or None, net days) from a clean terms string."""
    match = re.fullmatch(r"(?:(\d+(?:\.\d+)?)/(\d+) )?Net (\d+)", terms)
    pct, discount_days, net_days = match.groups()
    return (float(pct) if pct else 0.0, int(discount_days) if discount_days else None, int(net_days))


def add_vendor_terms(vendors: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    vendors = vendors.copy()
    preferred = rng.random(len(vendors)) < PREFERRED_VENDOR_SHARE
    vendors["payment_terms"] = [
        _weighted_choice(rng, PAYMENT_TERMS_PREFERRED if p else PAYMENT_TERMS_OTHER) for p in preferred
    ]
    vendors["preferred_vendor"] = np.where(preferred, "Y", "N")
    return vendors


def assign_po_numbers(invoices: pd.DataFrame, vendors: pd.DataFrame, dup_truth: pd.DataFrame,
                      rng: np.random.Generator) -> pd.DataFrame:
    invoices = invoices.copy()
    preferred = invoices["vendor_id"].map(vendors.set_index("vendor_id")["preferred_vendor"].eq("Y"))
    rate = (
        np.where(preferred, NO_PO_RATE_PREFERRED, NO_PO_RATE_OTHER)
        * invoices["department"].map(NO_PO_DEPARTMENT_MULTIPLIER).fillna(1.0).to_numpy()
    )
    no_po = rng.random(len(invoices)) < rate
    numbers = [f"{PO_NUMBER_PREFIX}{n:08d}" for n in rng.integers(0, 10**8, len(invoices))]
    invoices.insert(2, "po_number", [None if missing else n for missing, n in zip(no_po, numbers)])

    # A re-sent invoice carries the same PO reference as the original.
    original_of = dup_truth.set_index("invoice_id")["detail"].str.split().str[-1]
    po_by_id = invoices.set_index("invoice_id")["po_number"]
    is_dup = invoices["invoice_id"].isin(original_of.index)
    invoices.loc[is_dup, "po_number"] = invoices.loc[is_dup, "invoice_id"].map(original_of).map(po_by_id).to_numpy()
    return invoices


def _truth_row(anomaly_type: str, invoice_id: str, detail: str) -> dict:
    return {"anomaly_type": anomaly_type, "invoice_id": invoice_id, "department": None,
            "category": None, "month": None, "detail": detail}


def inject_approval_violations(invoices: pd.DataFrame, protected_ids: set,
                               rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    invoices = invoices.copy()
    paid = pd.to_datetime(invoices["paid_date"])
    # Paid well before extract, so a retroactive approval still lands inside it.
    eligible = invoices.index[
        ~invoices["invoice_id"].isin(protected_ids) & (paid <= EXTRACT_DATE - pd.Timedelta(days=10))
    ]
    chosen = rng.choice(eligible, size=N_PAID_BEFORE_APPROVAL + N_PAID_WITHOUT_APPROVAL, replace=False)

    truth = []
    for i in chosen[:N_PAID_BEFORE_APPROVAL]:
        approved = paid[i] + pd.Timedelta(days=int(rng.integers(1, 8)))
        invoices.at[i, "approved_date"] = approved.date().isoformat()
        truth.append(_truth_row("paid_before_approval", invoices.at[i, "invoice_id"],
                                f"paid {paid[i].date()}, approved {approved.date()}"))
    for i in chosen[N_PAID_BEFORE_APPROVAL:]:
        invoices.at[i, "approved_date"] = None
        truth.append(_truth_row("paid_without_approval", invoices.at[i, "invoice_id"],
                                f"paid {paid[i].date()}, never approved"))
    return invoices, pd.DataFrame(truth)


def _event(rng: np.random.Generator, invoice_id: str, activity: str, day: pd.Timestamp,
           reason: str | None = None) -> dict:
    low, high = ACTIVITY_HOURS[activity]
    ts = day + pd.Timedelta(hours=int(rng.integers(low, high)), minutes=int(rng.integers(0, 60)))
    return {"invoice_id": invoice_id, "activity": activity, "timestamp": ts.isoformat(),
            "resource_role": ACTIVITY_ROLE[activity], "reject_reason": reason}


def build_event_log(invoices: pd.DataFrame, no_rework_ids: set, rng: np.random.Generator) -> pd.DataFrame:
    """One row per process step, for the full lifecycle (cut at extract later)."""
    events = []
    for row in invoices.itertuples():
        submitted = pd.Timestamp(row.submitted_date)
        approved = pd.Timestamp(row.approved_date) if isinstance(row.approved_date, str) else None
        events.append(_event(rng, row.invoice_id, "Receive invoice", pd.Timestamp(row.invoice_date)))
        events.append(_event(rng, row.invoice_id, "Submit for approval", submitted))

        gap = (approved - submitted).days if approved is not None else 0
        has_po = isinstance(row.po_number, str)
        loops = 0
        if row.invoice_id not in no_rework_ids and gap >= REWORK_MIN_APPROVAL_DAYS:
            rate = REWORK_BASE_RATE + REWORK_RATE_PER_APPROVAL_DAY * gap
            rate = min(REWORK_MAX_RATE, rate * (1.0 if has_po else REWORK_NO_PO_MULTIPLIER))
            if rng.random() < rate:
                loops = 2 if gap >= SECOND_LOOP_MIN_APPROVAL_DAYS and rng.random() < SECOND_LOOP_RATE else 1

        # Each loop gets its own slice of the approval gap, so loops never overlap
        # and every resubmission comes before the final approval.
        segment = gap // max(loops, 1)
        for k in range(loops):
            start = submitted + pd.Timedelta(days=k * segment)
            reject_offset = int(rng.integers(0, segment // 2))
            reject = start + pd.Timedelta(days=reject_offset)
            resubmit = reject + pd.Timedelta(days=int(rng.integers(0, segment - reject_offset)))
            reason = _weighted_choice(rng, REJECT_REASONS_WITH_PO if has_po else REJECT_REASONS_NO_PO)
            events.append(_event(rng, row.invoice_id, "Reject invoice", reject, reason))
            events.append(_event(rng, row.invoice_id, "Correct and resubmit", resubmit))

        if approved is not None:
            events.append(_event(rng, row.invoice_id, "Approve invoice", approved))
        events.append(_event(rng, row.invoice_id, "Pay invoice", pd.Timestamp(row.paid_date)))

    # Time order within each invoice, as a real log is (a retroactive approval comes after the payment).
    return pd.DataFrame(events).sort_values(["invoice_id", "timestamp"], kind="stable").reset_index(drop=True)


def apply_extract_date(invoices: pd.DataFrame, events: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Drop everything after the extract: those invoices become open items."""
    invoices = invoices.copy()
    for column, status_if_future in [
        ("paid_date", "Approved"),
        ("approved_date", "Pending approval"),
        ("submitted_date", "Received"),
    ]:
        future = pd.to_datetime(invoices[column]) > EXTRACT_DATE
        invoices.loc[future, column] = None
        invoices.loc[future, "status"] = status_if_future

    in_extract = pd.to_datetime(events["timestamp"]).dt.normalize() <= EXTRACT_DATE
    return invoices, events[in_extract].reset_index(drop=True)


def restrict_outlier_truth(outlier_truth: pd.DataFrame, invoices: pd.DataFrame) -> pd.DataFrame:
    """Keep planted outliers that the extract can show: paid, or open long enough to stand out."""
    by_id = invoices.set_index("invoice_id")
    keep = []
    for row in outlier_truth.itertuples(index=False):
        inv = by_id.loc[row.invoice_id]
        if isinstance(inv["paid_date"], str):
            keep.append(row._asdict())
            continue
        age = (EXTRACT_DATE - pd.Timestamp(inv["submitted_date"])).days if isinstance(inv["submitted_date"], str) else 0
        if age > OPEN_OUTLIER_MIN_AGE_DAYS:
            keep.append({**row._asdict(), "detail": f"still open {age} days after submission at extract"})
    return pd.DataFrame(keep)


def label_payment_leakage(invoices: pd.DataFrame, vendors: pd.DataFrame) -> pd.DataFrame:
    """Answer key for maverick spend, missed discounts and late payments.

    Worked out here from the clean values, so the pipeline's own figures
    (after cleaning the messy formats) can be tested against them.
    Discounts and lateness are counted on payment; open items are not yet either.
    """
    terms = vendors.set_index("vendor_id")["payment_terms"].map(parse_terms)
    truth = []
    for row in invoices.itertuples():
        if not isinstance(row.po_number, str):
            truth.append(_truth_row("maverick_spend", row.invoice_id, f"no PO, vendor {row.vendor_id}"))
        if not isinstance(row.paid_date, str):
            continue
        pct, discount_days, net_days = terms[row.vendor_id]
        days_to_pay = (pd.Timestamp(row.paid_date) - pd.Timestamp(row.invoice_date)).days
        if discount_days is not None and days_to_pay > discount_days:
            truth.append(_truth_row("missed_discount", row.invoice_id,
                                    f"paid on day {days_to_pay}, {pct:g}% discount window {discount_days} days"))
        if days_to_pay > net_days:
            truth.append(_truth_row("late_payment", row.invoice_id,
                                    f"paid {days_to_pay - net_days} days late (Net {net_days})"))
    return pd.DataFrame(truth)


def label_rework(events: pd.DataFrame) -> pd.DataFrame:
    rejects = events[events["activity"] == "Reject invoice"]
    loops = rejects.groupby("invoice_id")["reject_reason"].agg(list)
    return pd.DataFrame([
        _truth_row("rework_loop", invoice_id, f"{len(reasons)} loop(s): {'; '.join(reasons)}")
        for invoice_id, reasons in loops.items()
    ])


def messify_terms(vendors: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    def messy(terms: str) -> str:
        variant = rng.choice(["lower", "upper_no_space", "pad"])
        if variant == "lower":
            return terms.lower()
        if variant == "upper_no_space":
            return terms.upper().replace("NET ", "NET")
        return f" {terms}  "

    vendors = vendors.copy()
    mask = rng.random(len(vendors)) < PAYMENT_TERMS_MESSY_RATE
    vendors.loc[mask, "payment_terms"] = vendors.loc[mask, "payment_terms"].map(messy)
    return vendors


def messify_po_numbers(invoices: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Missing POs typed several ways; some valid ones padded or prefixed."""
    invoices = invoices.copy()
    missing = invoices["po_number"].isna()
    invoices.loc[missing, "po_number"] = rng.choice(PO_MISSING_SPELLINGS, size=int(missing.sum()))
    present = invoices.index[~missing]
    draw = rng.random(len(present))
    padded = present[draw < PO_PADDED_RATE]
    prefixed = present[(draw >= PO_PADDED_RATE) & (draw < PO_PADDED_RATE + PO_PREFIXED_RATE)]
    invoices.loc[padded, "po_number"] = "  " + invoices.loc[padded, "po_number"] + " "
    invoices.loc[prefixed, "po_number"] = "PO " + invoices.loc[prefixed, "po_number"]
    return invoices


def main():
    random.seed(SEED)
    np.random.seed(SEED)
    fake = Faker()
    Faker.seed(SEED)

    end_date = END_DATE
    start_date = end_date - pd.DateOffset(months=MONTHS_BACK)

    vendors = make_vendors(fake)
    budgets = make_budgets(end_date)
    invoices = make_base_invoices(fake, vendors, start_date, end_date)

    next_id = N_BASE_INVOICES + 1
    dup_invoices, dup_truth, next_id = inject_duplicate_payments(invoices, next_id)
    invoices = pd.concat([invoices, dup_invoices], ignore_index=True)

    invoices, outlier_truth = inject_processing_time_outliers(invoices)
    invoices, overrun_truth = inject_budget_overruns(invoices, budgets)

    protected_ids = set(dup_truth["invoice_id"]) | set(outlier_truth["invoice_id"])

    # Extension: own generator, so the global stream used above and by the
    # messify steps below is unchanged.
    rng = np.random.default_rng(EXTENSION_SEED)
    vendors = add_vendor_terms(vendors, rng)
    invoices = assign_po_numbers(invoices, vendors, dup_truth, rng)
    invoices, violation_truth = inject_approval_violations(invoices, protected_ids, rng)
    events = build_event_log(invoices, set(violation_truth["invoice_id"]), rng)
    invoices, events = apply_extract_date(invoices, events)
    outlier_truth = restrict_outlier_truth(outlier_truth, invoices)
    leakage_truth = label_payment_leakage(invoices, vendors)
    rework_truth = label_rework(events)

    ground_truth = pd.concat(
        [dup_truth, outlier_truth, overrun_truth, leakage_truth, violation_truth, rework_truth],
        ignore_index=True,
    )

    n_open = int((invoices["status"] != "Paid").sum())
    submitted_before_mess = invoices["submitted_date"].notna()
    invoices = messify_invoices(invoices, protected_ids)
    vendors = messify_vendors(vendors)
    # A submission the workflow failed to log is missing from the event log too.
    unlogged = set(invoices.loc[submitted_before_mess & invoices["submitted_date"].isna(), "invoice_id"])
    events = events[~((events["activity"] == "Submit for approval") & events["invoice_id"].isin(unlogged))]
    vendors = messify_terms(vendors, rng)
    invoices = messify_po_numbers(invoices, rng)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vendors.to_csv(OUT_DIR / "vendors.csv", index=False)
    budgets.to_csv(OUT_DIR / "budgets.csv", index=False)
    invoices.to_csv(OUT_DIR / "invoices.csv", index=False)
    events.to_csv(OUT_DIR / "invoice_events.csv", index=False)
    ground_truth.to_csv(OUT_DIR / "anomaly_ground_truth.csv", index=False)
    (OUT_DIR / "extract_metadata.json").write_text(
        json.dumps({"extract_date": EXTRACT_DATE.date().isoformat()}, indent=2) + "\n"
    )

    print(f"vendors:        {len(vendors)}")
    print(f"budgets:        {len(budgets)}")
    print(f"invoices:       {len(invoices)} (base {N_BASE_INVOICES} + {len(dup_invoices)} duplicates)")
    print(f"  open at extract {EXTRACT_DATE.date()}: {n_open}")
    print(f"events:         {len(events)}")
    print(f"ground truth:   {len(ground_truth)} labelled rows")
    for anomaly_type, count in ground_truth["anomaly_type"].value_counts(sort=False).items():
        print(f"  {anomaly_type + ':':25s}{count}")
    print(f"written to {OUT_DIR}")


if __name__ == "__main__":
    main()
