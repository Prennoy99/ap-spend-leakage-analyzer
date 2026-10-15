"""Deterministic KPI calculations over the cleaned finance-ops data.

Pure aggregation only — no anomaly logic (see anomalies.py) and no LLM calls.
Everything here must be independently reproducible from data/processed/.
"""

from pathlib import Path

import pandas as pd

PROCESSED_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"


def load_invoices() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIR / "invoices_clean.parquet")


def load_budgets() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIR / "budgets.parquet")


def load_vendors() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIR / "vendors_clean.parquet")


def load_events() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIR / "invoice_events.parquet")


def total_spend(invoices: pd.DataFrame) -> float:
    return round(float(invoices["amount"].sum()), 2)


def spend_by_department(invoices: pd.DataFrame) -> pd.DataFrame:
    return (
        invoices.groupby("department")
        .agg(total_spend=("amount", "sum"), invoice_count=("invoice_id", "count"))
        .round(2)
        .reset_index()
        .sort_values("total_spend", ascending=False)
    )


def spend_by_category(invoices: pd.DataFrame) -> pd.DataFrame:
    return (
        invoices.groupby("category")
        .agg(total_spend=("amount", "sum"), invoice_count=("invoice_id", "count"))
        .round(2)
        .reset_index()
        .sort_values("total_spend", ascending=False)
    )


def spend_by_vendor(invoices: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    result = (
        invoices.groupby(["vendor_id", "vendor_name"])
        .agg(total_spend=("amount", "sum"), invoice_count=("invoice_id", "count"))
        .round(2)
        .reset_index()
        .sort_values("total_spend", ascending=False)
    )
    return result.head(top_n)


def spend_by_month(invoices: pd.DataFrame) -> pd.DataFrame:
    monthly = invoices.copy()
    monthly["month"] = monthly["invoice_date"].dt.strftime("%Y-%m")
    return (
        monthly.groupby("month")
        .agg(total_spend=("amount", "sum"), invoice_count=("invoice_id", "count"))
        .round(2)
        .reset_index()
        .sort_values("month")
    )


def avg_processing_days(invoices: pd.DataFrame, by: str | None = None) -> pd.DataFrame | float:
    valid = invoices[~invoices["missing_submitted_date"]]
    if by is None:
        return round(float(valid["processing_days"].mean()), 1)
    return (
        valid.groupby(by)["processing_days"]
        .mean()
        .round(1)
        .reset_index(name="avg_processing_days")
        .sort_values("avg_processing_days", ascending=False)
    )


def budget_vs_actual(invoices: pd.DataFrame, budgets: pd.DataFrame) -> pd.DataFrame:
    monthly = invoices.copy()
    monthly["month"] = monthly["invoice_date"].dt.strftime("%Y-%m")
    actual = (
        monthly.groupby(["department", "category", "month"])["amount"]
        .sum()
        .reset_index(name="actual_amount")
    )
    merged = budgets.merge(actual, on=["department", "category", "month"], how="left")
    merged["actual_amount"] = merged["actual_amount"].fillna(0.0).round(2)
    merged["variance"] = (merged["actual_amount"] - merged["budget_amount"]).round(2)
    # Round after scaling: rounding first then * 100 reintroduces float noise
    # (59.160000000000004) that ends up verbatim in the facts sent to Gemini.
    merged["variance_pct"] = (((merged["actual_amount"] / merged["budget_amount"]) - 1) * 100).round(2)
    return merged.sort_values("variance_pct", ascending=False)


def budget_variance_extremes(invoices: pd.DataFrame, budgets: pd.DataFrame, n: int = 6) -> pd.DataFrame:
    """The n most-over-budget and n most-under-budget department/category/month
    groups. A full-department annual aggregate washes out to "under budget"
    almost everywhere, since overruns are localized to specific months/categories
    — this instead surfaces the actual extremes the anomaly detector flags on.
    """
    bva = budget_vs_actual(invoices, budgets)
    extremes = pd.concat([bva.head(n), bva.tail(n)]).drop_duplicates()
    extremes = extremes.copy()
    extremes["label"] = extremes["department"] + " · " + extremes["category"] + " (" + extremes["month"] + ")"
    return extremes.sort_values("variance_pct", ascending=False)


# --- Payment timing (Treasury) ------------------------------------------------
# Judged on paid invoices only: an open invoice has no payment date yet. That
# leaves out the slowest invoices still in the queue, so read DPO together
# with the open-invoice count and the stuck-invoice flags.

def _paid(invoices: pd.DataFrame) -> pd.DataFrame:
    return invoices[invoices["paid_date"].notna()]


def _with_month(invoices: pd.DataFrame) -> pd.DataFrame:
    return invoices.assign(month=invoices["invoice_date"].dt.strftime("%Y-%m"))


def days_payable_outstanding(invoices: pd.DataFrame) -> float:
    """Days from invoice date to payment, weighted by amount.

    This is transactional DPO, the AP view: it shows whether invoices are paid
    in line with their terms. Balance-sheet DPO (AP balance ÷ purchases × 365)
    needs cost of goods sold, which this indirect-spend extract doesn't have.
    Weighting by amount means a large invoice paid early moves the figure more
    than a small one, which is what matters for cash.
    """
    paid = _paid(invoices)
    days = (paid["paid_date"] - paid["invoice_date"]).dt.days
    return round(float((days * paid["amount"]).sum() / paid["amount"].sum()), 1)


def agreed_payment_days(invoices: pd.DataFrame) -> float:
    """Net payment terms in days, weighted by amount, over the same paid
    invoices as DPO. DPO well below this means cash leaves earlier than the
    suppliers require (hypothesis B3).
    """
    paid = _paid(invoices)
    return round(float((paid["net_days"] * paid["amount"]).sum() / paid["amount"].sum()), 1)


def on_time_payment_rate(invoices: pd.DataFrame) -> float:
    """% of paid invoices paid on or before the due date."""
    paid = _paid(invoices)
    return round(float((paid["paid_date"] <= paid["due_date"]).mean() * 100), 1)


def payment_timing(invoices: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    """DPO, on-time % and average days paid relative to the due date per group
    (negative = before the due date). `by` is e.g. ["vendor_id", "vendor_name"] or "month".
    """
    paid = _with_month(_paid(invoices))
    paid = paid.assign(
        days_to_pay=(paid["paid_date"] - paid["invoice_date"]).dt.days,
        days_vs_due=(paid["paid_date"] - paid["due_date"]).dt.days,
        on_time=paid["paid_date"] <= paid["due_date"],
    )
    paid = paid.assign(weighted_days=paid["days_to_pay"] * paid["amount"])
    grouped = paid.groupby(by).agg(
        paid_invoices=("invoice_id", "count"),
        paid_amount=("amount", "sum"),
        weighted_days=("weighted_days", "sum"),
        on_time_pct=("on_time", "mean"),
        avg_days_vs_due=("days_vs_due", "mean"),
    ).reset_index()
    grouped["dpo_days"] = (grouped["weighted_days"] / grouped["paid_amount"]).round(1)
    grouped["on_time_pct"] = (grouped["on_time_pct"] * 100).round(1)
    grouped["avg_days_vs_due"] = grouped["avg_days_vs_due"].round(1)
    grouped["paid_amount"] = grouped["paid_amount"].round(2)
    return grouped.drop(columns="weighted_days")


def discount_capture_rate(invoices: pd.DataFrame) -> float:
    """% of paid invoices with discount terms that were paid within the discount window."""
    paid = _paid(invoices)
    eligible = paid[paid["discount_date"].notna()]
    return round(float((eligible["paid_date"] <= eligible["discount_date"]).mean() * 100), 1)


def discount_deadlines(invoices: pd.DataFrame) -> pd.DataFrame:
    """Open invoices whose discount can still be taken, most urgent first.
    The AP clerk's work list: `status` shows what is holding each one up.
    """
    open_invoices = invoices[invoices["paid_date"].isna() & invoices["discount_date"].notna()]
    claimable = open_invoices[open_invoices["discount_date"] >= open_invoices["extract_date"]]
    result = claimable.assign(
        days_left=(claimable["discount_date"] - claimable["extract_date"]).dt.days,
        discount_eur=(claimable["amount"] * claimable["discount_pct"] / 100).round(2),
    )
    columns = ["invoice_id", "vendor_id", "vendor_name", "status", "amount",
               "discount_date", "days_left", "discount_eur"]
    return result[columns].sort_values(["discount_date", "discount_eur"], ascending=[True, False])


# --- Purchase orders and suppliers (Procurement) ------------------------------

def po_compliance(invoices: pd.DataFrame, by: str | list[str] | None = None) -> pd.DataFrame | float:
    """% of invoice spend covered by a purchase order. By spend, not invoice
    count, because one large no-PO invoice matters more than many small ones.
    """
    with_po = invoices["amount"].where(invoices["has_po"], 0.0)
    if by is None:
        return round(float(with_po.sum() / invoices["amount"].sum() * 100), 1)
    grouped = (
        invoices.assign(po_amount=with_po, no_po_amount=invoices["amount"] - with_po)
        .groupby(by)
        .agg(total_spend=("amount", "sum"), no_po_spend=("no_po_amount", "sum"), po_amount=("po_amount", "sum"))
        .reset_index()
    )
    grouped["po_compliance_pct"] = (grouped["po_amount"] / grouped["total_spend"] * 100).round(1)
    grouped[["total_spend", "no_po_spend"]] = grouped[["total_spend", "no_po_spend"]].round(2)
    return grouped.drop(columns="po_amount").sort_values("po_compliance_pct")


def no_po_spend_by_preferred(invoices: pd.DataFrame, vendors: pd.DataFrame) -> pd.DataFrame:
    """Spend without a PO, split by whether the supplier is on the preferred
    list. No-PO spend with a non-preferred supplier is the clearest maverick
    case: no order and no negotiated terms (hypothesis C2).
    """
    no_po = invoices[~invoices["has_po"]].merge(vendors[["vendor_id", "preferred_vendor"]], on="vendor_id")
    return (
        no_po.groupby("preferred_vendor")
        .agg(no_po_spend=("amount", "sum"), invoice_count=("invoice_id", "count"))
        .round(2)
        .reset_index()
    )


def vendor_pareto(invoices: pd.DataFrame) -> pd.DataFrame:
    """Every supplier ranked by spend, with its cumulative share of total spend."""
    by_vendor = (
        invoices.groupby(["vendor_id", "vendor_name"])
        .agg(total_spend=("amount", "sum"), invoice_count=("invoice_id", "count"))
        .reset_index()
        .sort_values(["total_spend", "vendor_id"], ascending=[False, True])
        .reset_index(drop=True)
    )
    by_vendor["rank"] = by_vendor.index + 1
    # Round after scaling, as in budget_vs_actual.
    by_vendor["cumulative_pct"] = (by_vendor["total_spend"].cumsum() / by_vendor["total_spend"].sum() * 100).round(2)
    by_vendor["total_spend"] = by_vendor["total_spend"].round(2)
    return by_vendor


def vendors_for_spend_share(pareto: pd.DataFrame, share_pct: float = 80.0) -> int:
    """How many of the largest suppliers it takes to reach `share_pct` of spend."""
    return int((pareto["cumulative_pct"] < share_pct).sum() + 1)


# --- Process stages (AP Manager) ------------------------------------------------

STAGES = {
    "Submit → approve": ("submitted_date", "approved_date"),
    "Approve → pay": ("approved_date", "paid_date"),
    "Submit → pay": ("submitted_date", "paid_date"),
}


def stage_durations(invoices: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Median and 90th-percentile days per stage, over invoices that have
    completed it. Excluded invoices are counted, not hidden: a missing start
    timestamp (no submission date, or paid without approval) and an end
    before the start (paid before approval) are reported separately.
    """
    rows = []
    groups = [(None, invoices)] if by is None else invoices.groupby(by)
    for key, group in groups:
        for stage, (start, end) in STAGES.items():
            completed = group[group[end].notna()]
            days = (completed[end] - completed[start]).dt.days
            measured = days[days >= 0]
            row = {} if by is None else {by: key}
            row.update({
                "stage": stage,
                "median_days": float(measured.median()),
                "p90_days": round(float(measured.quantile(0.9)), 1),
                "invoices_measured": len(measured),
                "excluded_missing_start": int(completed[start].isna().sum()),
                "excluded_out_of_order": int((days < 0).sum()),
            })
            rows.append(row)
    return pd.DataFrame(rows)


# --- Budgets (Controlling) ------------------------------------------------------

def repeat_overruns(overruns: pd.DataFrame) -> pd.DataFrame:
    """Months over budget per department and category, and the longest run of
    consecutive months. Takes the output of anomalies.detect_budget_overruns,
    so it always uses the detector's threshold. A long run points at a wrong
    budget; a single month at a one-off overspend.
    """
    columns = ["department", "category", "months_over", "longest_run", "months"]
    if overruns.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for (department, category), group in overruns.groupby(["department", "category"]):
        months = sorted(group["month"])
        periods = [pd.Period(m, freq="M").ordinal for m in months]
        longest = run = 1
        for previous, current in zip(periods, periods[1:]):
            run = run + 1 if current == previous + 1 else 1
            longest = max(longest, run)
        rows.append({
            "department": department,
            "category": category,
            "months_over": len(months),
            "longest_run": longest,
            "months": ", ".join(months),
        })
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["longest_run", "months_over", "department", "category"], ascending=[False, False, True, True]
    )


def compute_all_kpis(invoices: pd.DataFrame | None = None, budgets: pd.DataFrame | None = None,
                     vendors: pd.DataFrame | None = None) -> dict:
    if invoices is None:
        invoices = load_invoices()
    if budgets is None:
        budgets = load_budgets()
    if vendors is None:
        vendors = load_vendors()

    pareto = vendor_pareto(invoices)
    return {
        "total_spend": total_spend(invoices),
        "spend_by_department": spend_by_department(invoices),
        "spend_by_category": spend_by_category(invoices),
        "spend_by_vendor": spend_by_vendor(invoices),
        "spend_by_month": spend_by_month(invoices),
        "avg_processing_days": avg_processing_days(invoices),
        "avg_processing_days_by_department": avg_processing_days(invoices, by="department"),
        "budget_vs_actual": budget_vs_actual(invoices, budgets),
        "dpo_days": days_payable_outstanding(invoices),
        "agreed_payment_days": agreed_payment_days(invoices),
        "on_time_payment_pct": on_time_payment_rate(invoices),
        "payment_timing_by_vendor": payment_timing(invoices, by=["vendor_id", "vendor_name"]),
        "payment_timing_by_month": payment_timing(invoices, by="month"),
        "discount_capture_pct": discount_capture_rate(invoices),
        "discount_deadlines": discount_deadlines(invoices),
        "po_compliance_pct": po_compliance(invoices),
        "po_compliance_by_department": po_compliance(invoices, by="department"),
        "po_compliance_by_vendor": po_compliance(invoices, by=["vendor_id", "vendor_name"]),
        "no_po_spend_by_preferred": no_po_spend_by_preferred(invoices, vendors),
        "vendor_pareto": pareto,
        "vendors_for_80pct_spend": vendors_for_spend_share(pareto),
        "stage_durations": stage_durations(invoices),
        "stage_durations_by_department": stage_durations(invoices, by="department"),
    }


if __name__ == "__main__":
    kpis = compute_all_kpis()
    print(f"total_spend: EUR {kpis['total_spend']:,.2f}")
    print(f"avg_processing_days: {kpis['avg_processing_days']}")
    print(f"DPO: {kpis['dpo_days']} days (terms {kpis['agreed_payment_days']}) · on time: {kpis['on_time_payment_pct']}% · "
          f"discount capture: {kpis['discount_capture_pct']}% · PO compliance: {kpis['po_compliance_pct']}%")
    print(f"suppliers making up 80% of spend: {kpis['vendors_for_80pct_spend']} of {len(kpis['vendor_pareto'])}")
    print()
    print(kpis["stage_durations"].to_string(index=False))
    print()
    print(kpis["spend_by_department"].to_string(index=False))
