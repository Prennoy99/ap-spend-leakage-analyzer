"""Rule-based anomaly detection over the cleaned finance-ops data.

Deterministic stats/rules only — no LLM involvement. Thresholds below were
tuned by checking precision/recall against data/raw/anomaly_ground_truth.csv
during development; anomalies.py itself never reads that file — it only sees
data/processed/, exactly like a real detector would.
"""

import pandas as pd

from src.kpis import load_budgets, load_invoices

DUPLICATE_DATE_WINDOW_DAYS = 5

# Tukey's "extreme outlier" fence (vs. the more common 1.5x "mild outlier"
# fence). 1.5x flagged 35 false positives on the natural gamma-distributed
# processing-time tail; 3.0x still catches every planted outlier (0 misses)
# while cutting false positives to 1.
PROCESSING_TIME_IQR_MULTIPLIER = 3.0

# Real budgets are targets with some normal slack, not a statistical
# distribution — a fixed tolerance is more explainable than a z-score here.
# 1.15 catches every planted overrun (0 misses); tightening further starts
# missing planted cases that landed near the injection floor (1.15x-1.6x).
BUDGET_OVERRUN_THRESHOLD = 1.15


def find_duplicate_pairs(invoices: pd.DataFrame) -> pd.DataFrame:
    """One row per suspected duplicate pair: same vendor and amount within a
    short date window, a classic AP double-payment signature.

    The later invoice is taken as the copy. On a same-day tie the higher
    document number is, since it was entered last. Which one is the copy
    doesn't change the € exposure (both have the same amount), but it
    decides which invoice AP asks the supplier to credit.
    """
    keys = ["vendor_id", "amount"]
    ordered = (
        invoices[["vendor_id", "invoice_id", "invoice_date"]]
        .assign(amount=invoices["amount"].round(2))
        .sort_values(keys + ["invoice_date", "invoice_id"])
    )
    # Each invoice against the one just before it with the same supplier and amount.
    previous = ordered.groupby(keys)[["invoice_id", "invoice_date"]].shift(1)
    days_apart = (ordered["invoice_date"] - previous["invoice_date"]).dt.days
    is_pair = days_apart <= DUPLICATE_DATE_WINDOW_DAYS
    return pd.DataFrame({
        "vendor_id": ordered.loc[is_pair, "vendor_id"],
        "amount": ordered.loc[is_pair, "amount"],
        "first_invoice_id": previous.loc[is_pair, "invoice_id"],
        "second_invoice_id": ordered.loc[is_pair, "invoice_id"],
        "days_apart": days_apart[is_pair].astype(int),
    }).reset_index(drop=True)


def detect_duplicate_payments(invoices: pd.DataFrame) -> pd.DataFrame:
    """Flag both invoices of every suspected duplicate pair, since a reviewer
    has to look at the two side by side to confirm which one to reverse.
    """
    flagged = []
    for pair in find_duplicate_pairs(invoices).itertuples():
        for this_id, other_id in [(pair.first_invoice_id, pair.second_invoice_id),
                                  (pair.second_invoice_id, pair.first_invoice_id)]:
            flagged.append({
                "anomaly_type": "duplicate_payment",
                "invoice_id": this_id,
                "department": None,
                "category": None,
                "month": None,
                "detail": f"matches {other_id}: vendor {pair.vendor_id}, amount {pair.amount:.2f}, "
                          f"{pair.days_apart}d apart",
            })

    return pd.DataFrame(flagged)


def detect_processing_time_outliers(invoices: pd.DataFrame) -> pd.DataFrame:
    """Flag paid invoices whose submission-to-payment time is beyond the fence,
    and open invoices that have already waited longer than the fence at the
    extract date. A stuck open invoice has no final processing time yet, but
    waiting for it to be paid would hide exactly the cases AP should chase.
    """
    valid = invoices[~invoices["missing_submitted_date"]]
    paid = valid[valid["paid_date"].notna()]
    q1, q3 = paid["processing_days"].quantile(0.25), paid["processing_days"].quantile(0.75)
    iqr = q3 - q1
    fence = q3 + PROCESSING_TIME_IQR_MULTIPLIER * iqr

    still_open = valid[valid["paid_date"].isna() & valid["submitted_date"].notna()]
    days_open = (still_open["extract_date"] - still_open["submitted_date"]).dt.days
    stuck = still_open.assign(days_open=days_open)[days_open > fence]

    outliers = paid[paid["processing_days"] > fence]
    return pd.DataFrame([
        {
            "anomaly_type": "processing_time_outlier",
            "invoice_id": row.invoice_id,
            "department": None,
            "category": None,
            "month": None,
            "detail": f"{row.processing_days:.0f}d processing time (fence {fence:.1f}d)",
        }
        for row in outliers.itertuples()
    ] + [
        {
            "anomaly_type": "processing_time_outlier",
            "invoice_id": row.invoice_id,
            "department": None,
            "category": None,
            "month": None,
            "detail": f"still open after {row.days_open:.0f}d at extract (fence {fence:.1f}d)",
        }
        for row in stuck.itertuples()
    ])


def detect_budget_overruns(invoices: pd.DataFrame, budgets: pd.DataFrame) -> pd.DataFrame:
    monthly = invoices.copy()
    monthly["month"] = monthly["invoice_date"].dt.strftime("%Y-%m")
    actual = (
        monthly.groupby(["department", "category", "month"])["amount"]
        .sum()
        .reset_index(name="actual_amount")
    )
    merged = budgets.merge(actual, on=["department", "category", "month"], how="left")
    merged["actual_amount"] = merged["actual_amount"].fillna(0.0)
    merged["ratio"] = merged["actual_amount"] / merged["budget_amount"]

    overruns = merged[merged["ratio"] > BUDGET_OVERRUN_THRESHOLD]
    return pd.DataFrame([
        {
            "anomaly_type": "budget_overrun",
            "invoice_id": None,
            "department": row.department,
            "category": row.category,
            "month": row.month,
            "detail": f"actual {row.actual_amount:.2f} vs budget {row.budget_amount:.2f} ({row.ratio * 100:.0f}%)",
        }
        for row in overruns.itertuples()
    ])


def detect_all(invoices: pd.DataFrame | None = None, budgets: pd.DataFrame | None = None) -> pd.DataFrame:
    if invoices is None:
        invoices = load_invoices()
    if budgets is None:
        budgets = load_budgets()

    frames = [
        detect_duplicate_payments(invoices),
        detect_processing_time_outliers(invoices),
        detect_budget_overruns(invoices, budgets),
    ]
    non_empty = [f for f in frames if not f.empty]
    if not non_empty:
        return pd.DataFrame(columns=["anomaly_type", "invoice_id", "department", "category", "month", "detail"])
    return pd.concat(non_empty, ignore_index=True)


if __name__ == "__main__":
    anomalies = detect_all()
    print(anomalies["anomaly_type"].value_counts())
    print()
    print(anomalies.head(10).to_string(index=False))
