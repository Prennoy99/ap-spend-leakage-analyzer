"""What-if scenarios for the Improve phase: move one lever, see what changes.

Each scenario re-runs the real calculation on changed inputs; nothing here
uses a shortcut formula, so a what-if answer always agrees with the rest of the
app at the current setting (tested):

- **Overrun threshold**: re-runs the budget-overrun detector and the € above
  budget at another tolerance. Precision and recall come from evaluation.py,
  the only code allowed to read the answer key.
- **Faster approval**: moves each invoice's approval, and the payment after
  it, N days earlier, then recomputes discounts and late payments with impact.py.
- **Supplier consolidation**: moves the spend of the smallest non-preferred
  suppliers to preferred ones, at an assumed volume saving.
- **Business case levers** reuse business_case.evaluate with slider values.

Like kpis.py this reads only data/processed/.
"""

import pandas as pd

from src import impact
from src.anomalies import detect_budget_overruns
from src.kpis import discount_capture_rate, on_time_payment_rate

# Volume discount when the spend of small suppliers moves to a preferred
# supplier in a framework agreement. Tail-spend consolidation is usually
# quoted at a few percent; a cautious base, to confirm with Procurement.
CONSOLIDATION_SAVING_PCT = 5.0

OVERRUN_THRESHOLDS = [1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.40, 1.50]


# --- Overrun threshold (Controlling) -------------------------------------------

def overrun_threshold_scenario(invoices: pd.DataFrame, budgets: pd.DataFrame, threshold: float) -> dict:
    """Flags and € above budget at one threshold."""
    flags = detect_budget_overruns(invoices, budgets, threshold=threshold)
    over = impact.spend_above_budget(invoices, budgets, threshold=threshold)
    return {
        "threshold": threshold,
        "flags": flags,
        "months_flagged": len(flags),
        "spend_to_review_eur": round(float(over["impact_eur"].sum()), 2),
    }


def overrun_threshold_sweep(invoices: pd.DataFrame, budgets: pd.DataFrame,
                            thresholds: list[float] | None = None) -> pd.DataFrame:
    """Months flagged and € to review across thresholds (no answer key here)."""
    rows = []
    for threshold in thresholds or OVERRUN_THRESHOLDS:
        result = overrun_threshold_scenario(invoices, budgets, threshold)
        rows.append({k: result[k] for k in ["threshold", "months_flagged", "spend_to_review_eur"]})
    return pd.DataFrame(rows)


# --- Faster approval (AP Manager, budget owners) --------------------------------

def shift_approval(invoices: pd.DataFrame, days: int) -> pd.DataFrame:
    """Invoices as if approval had taken up to `days` fewer days. The payment
    moves with it, since the payment step follows the approval. An approval
    never moves before the submission, so a fast approval gains less than a
    slow one. Invoices paid before or without an approval, without a
    submission date, or still open, are left as they are.
    """
    shifted = invoices.copy()
    eligible = (
        shifted["paid_date"].notna()
        & shifted["approved_date"].notna()
        & shifted["submitted_date"].notna()
        & (shifted["paid_date"] >= shifted["approved_date"])
    )
    approval_days = (shifted["approved_date"] - shifted["submitted_date"]).dt.days
    cut = pd.to_timedelta(approval_days.clip(upper=days).where(eligible, 0), unit="D")
    shifted["approved_date"] = shifted["approved_date"] - cut
    shifted["paid_date"] = shifted["paid_date"] - cut
    shifted["processing_days"] = (shifted["paid_date"] - shifted["submitted_date"]).dt.days
    return shifted


def approval_cut_scenario(invoices: pd.DataFrame, days: int) -> dict:
    """Discounts, late payments and processing time with approval `days` faster."""
    shifted = shift_approval(invoices, days)
    missed = impact.missed_discounts(shifted)
    late = impact.late_payment_cost(shifted)
    valid = shifted[~shifted["missing_submitted_date"]]
    return {
        "days_cut": days,
        "discount_capture_pct": discount_capture_rate(shifted),
        "missed_discounts": len(missed),
        "missed_discount_eur": round(float(missed["impact_eur"].sum()), 2),
        "on_time_pct": on_time_payment_rate(shifted),
        "late_payments": len(late),
        "late_payment_eur": round(float(late["impact_eur"].sum()), 2),
        "median_processing_days": float(valid["processing_days"].median()),
    }


def approval_cut_sweep(invoices: pd.DataFrame, max_days: int = 7) -> pd.DataFrame:
    return pd.DataFrame([approval_cut_scenario(invoices, days) for days in range(max_days + 1)])


# --- Supplier consolidation (Procurement) ---------------------------------------

def consolidation_candidates(invoices: pd.DataFrame, vendors: pd.DataFrame) -> pd.DataFrame:
    """Non-preferred suppliers, smallest spend first: the tail to move to
    preferred suppliers. Preferred suppliers are never consolidated away.
    """
    spend = invoices.groupby("vendor_id").agg(spend=("amount", "sum"), invoices=("invoice_id", "count"))
    table = vendors[["vendor_id", "vendor_name", "preferred_vendor"]].join(spend, on="vendor_id")
    table = table[~table["preferred_vendor"]].dropna(subset=["spend"])
    table = table.sort_values(["spend", "vendor_id"]).reset_index(drop=True)
    table["cumulative_spend"] = table["spend"].cumsum()
    return table.drop(columns="preferred_vendor")


def consolidation_scenario(invoices: pd.DataFrame, vendors: pd.DataFrame, n: int,
                           saving_pct: float = CONSOLIDATION_SAVING_PCT) -> dict:
    """Move the spend of the `n` smallest non-preferred suppliers to preferred ones."""
    candidates = consolidation_candidates(invoices, vendors)
    moved = candidates.head(n)
    spend = float(moved["spend"].sum())
    return {
        "suppliers_moved": len(moved),
        "suppliers_after": int(invoices["vendor_id"].nunique() - len(moved)),
        "spend_moved_eur": round(spend, 2),
        "invoices_moved": int(moved["invoices"].sum()),
        "estimated_saving_eur": round(spend * saving_pct / 100, 2),
        "moved": moved,
    }
