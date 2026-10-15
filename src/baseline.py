"""Measure-phase baseline: where each critical-to-quality (CTQ) metric in the
project charter stands today, with its target and owner.

Improve sizes the gap to target from these figures, and Control compares later
months against them, so the baseline is frozen in dated CSV files under
data/baseline/. tests/test_baseline.py recomputes it and fails if the data no
longer matches the frozen files: re-baselining must be a deliberate decision
(`python -m src.baseline --freeze`), never a side effect of a data change.

Yes/no defects also get DPMO (defects per million opportunities) and a sigma
level, the Six Sigma way of putting different defects on one scale. Times and
DPO are continuous, so they are reported as medians and percentiles instead.

Every figure comes from kpis.py, impact.py and anomalies.py. This module only
adds the defect counts, the targets and the reasons behind them.
"""

import math
import sys
from pathlib import Path
from statistics import NormalDist

import pandas as pd

from src import impact, kpis
from src.anomalies import detect_budget_overruns, find_duplicate_pairs

BASELINE_DIR = Path(__file__).resolve().parent.parent / "data" / "baseline"
CTQ_BASELINE_FILE = BASELINE_DIR / "ctq_baseline.csv"
LEAKAGE_BASELINE_FILE = BASELINE_DIR / "leakage_baseline.csv"

# The conventional 1.5-sigma allowance for long-term drift: a process that is
# 6 sigma in the short term delivers 3.4 DPMO in the long run. Sigma tables
# quoted in Lean Six Sigma training include it, so the levels here compare
# directly with them.
SIGMA_SHIFT = 1.5

# Proposed targets for the metrics the charter left "Set in Measure". They go to
# the AP Manager for sign-off at the Measure tollgate; the reason for each one
# is written next to it in the baseline table (see ctq_baseline).
REWORK_TARGET_PCT = 8.0
ON_TIME_TARGET_PCT = 98.0
DISCOUNT_CAPTURE_TARGET_PCT = 90.0
PO_COMPLIANCE_TARGET_PCT = 90.0

# Reject reasons a check at invoice entry would catch: an invoice without a PO
# is returned to the supplier before it reaches an approver, and the cost
# centre is taken from the PO instead of typed in.
PREVENTABLE_AT_ENTRY = ["Missing PO", "Wrong cost centre"]

AP_MANAGER = "AP Manager"
PROCUREMENT = "Procurement lead"
CONTROLLING = "Controlling"


def sigma_level(defects: int, opportunities: int) -> float | None:
    """Short-term sigma level for a defect rate, including the 1.5 shift.
    None when there are no defects: a sample with no defects puts no upper
    bound on the sigma level.
    """
    if defects == 0:
        return None
    defect_rate = defects / opportunities
    return round(NormalDist().inv_cdf(1 - defect_rate) + SIGMA_SHIFT, 2)


def dpmo(defects: int, opportunities: int) -> int:
    return round(defects / opportunities * 1_000_000)


def discount_annual_return_pct(discount_pct: float, discount_days: int, net_days: int) -> float:
    """What taking an early-payment discount earns, as a simple annual rate.
    Paying 98 on day 10 instead of 100 on day 30 earns 2/98 over 20 days.
    """
    period_return = discount_pct / (100 - discount_pct)
    return round(period_return * 365 / (net_days - discount_days) * 100, 1)


def terms_based_dpo(invoices: pd.DataFrame) -> float:
    """DPO if every paid invoice had been paid on its latest sensible date:
    the discount date where discount terms apply, otherwise the due date.
    The ceiling for paying to terms, so the natural DPO target.
    """
    paid = invoices[invoices["paid_date"].notna()]
    pay_date = paid["discount_date"].where(paid["discount_date"].notna(), paid["due_date"])
    days = (pay_date - paid["invoice_date"]).dt.days
    return round(float((days * paid["amount"]).sum() / paid["amount"].sum()), 1)


def rework_without(events: pd.DataFrame, invoices: pd.DataFrame, reasons: list[str]) -> float:
    """% of invoices that would still be rejected at least once if rejections
    for `reasons` no longer happened. An invoice rejected for one of those
    reasons and another one still counts.
    """
    rejects = events[events["activity"] == kpis.REJECT_ACTIVITY]
    remaining = rejects.loc[~rejects["reject_reason"].isin(reasons), "invoice_id"].nunique()
    return round(remaining / len(invoices) * 100, 1)


def approval_breaches(invoices: pd.DataFrame) -> pd.DataFrame:
    """Paid invoices with no approval, or paid before they were approved."""
    paid = invoices[invoices["paid_date"].notna()]
    return paid[paid["approved_date"].isna() | (paid["paid_date"] < paid["approved_date"])]


def _row(ctq: str, measure: str, unit: str, value: float, direction: str, target: float,
         source: str, basis: str, owner: str, defects: int | None = None,
         opportunities: int | None = None) -> dict:
    row = {
        "ctq": ctq,
        "measure": measure,
        "unit": unit,
        "baseline": value,
        "defects": defects,
        "opportunities": opportunities,
        "defect_rate_pct": None,
        "dpmo": None,
        "sigma_level": None,
        "target_direction": direction,
        "target": target,
        "target_source": source,
        "target_basis": basis,
        "owner": owner,
    }
    if defects is not None:
        row.update({
            "defect_rate_pct": round(defects / opportunities * 100, 2),
            "dpmo": dpmo(defects, opportunities),
            "sigma_level": sigma_level(defects, opportunities),
        })
    return row


def ctq_baseline(invoices: pd.DataFrame, budgets: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """One row per CTQ metric, in the charter's order. Defects are counted per
    invoice, except budget overruns (per department-category-month).
    """
    paid = invoices[invoices["paid_date"].notna()]
    discount_eligible = paid[paid["discount_date"].notna()]
    stages = kpis.stage_durations(invoices).set_index("stage")
    reasons = kpis.reject_reasons(events)

    duplicates = len(find_duplicate_pairs(invoices))
    overruns = len(detect_budget_overruns(invoices, budgets))
    missing_submission = int(invoices["missing_submitted_date"].sum())
    rejected = events.loc[events["activity"] == kpis.REJECT_ACTIVITY, "invoice_id"].nunique()
    late = int((paid["paid_date"] > paid["due_date"]).sum())
    missed = int((discount_eligible["paid_date"] > discount_eligible["discount_date"]).sum())
    no_po = int((~invoices["has_po"]).sum())

    preventable = reasons.loc[reasons["reject_reason"].isin(PREVENTABLE_AT_ENTRY), "rejections"].sum()
    preventable_pct = preventable / reasons["rejections"].sum() * 100
    # The most common discount terms (all of them are 2/10 Net 30 in this extract).
    terms = discount_eligible[["discount_pct", "discount_days", "net_days"]].value_counts().index[0]
    terms = dict(zip(["discount_pct", "discount_days", "net_days"], terms))
    annual_return = discount_annual_return_pct(terms["discount_pct"], int(terms["discount_days"]), int(terms["net_days"]))
    target_dpo = terms_based_dpo(invoices)
    submit_to_pay = stages.loc["Submit → pay"]

    rows = [
        _row("Duplicate payments", "Suspected duplicate copies", "invoices", duplicates, "≤", 0, "Charter",
             "Stopped before payment", AP_MANAGER, duplicates, len(invoices)),
        _row("Processing time", "Median, submission to payment", "days", submit_to_pay["median_days"], "≤", 4,
             "Charter", "Roughly halve the median", AP_MANAGER),
        _row("Processing time", "90th percentile, submission to payment", "days", submit_to_pay["p90_days"], "≤", 8,
             "Charter", "Roughly halve the slow tail", AP_MANAGER),
        _row("Unapproved budget overruns", "Department-category-months over 115% of budget", "months", overruns,
             "≤", 0, "Charter", "Every overrun approved by the budget owner before month-end", CONTROLLING,
             overruns, len(budgets)),
        _row("Missing process timestamps", "Invoices with no submission date", "invoices", missing_submission,
             "≤", 0, "Charter", "Submission date required at entry", AP_MANAGER,
             missing_submission, len(invoices)),
        _row("Payments breaching approval", "Paid before approval or never approved", "invoices",
             len(approval_breaches(invoices)), "≤", 0, "Charter", "Payment run releases approved invoices only",
             AP_MANAGER, len(approval_breaches(invoices)), len(paid)),
        _row("Rework rate", "Invoices rejected at least once", "% of invoices", kpis.rework_rate(invoices, events),
             "≤", REWORK_TARGET_PCT, "Proposed",
             f"{' and '.join(PREVENTABLE_AT_ENTRY)} cause {preventable_pct:.0f}% of rejections and can be "
             f"caught at invoice entry; without them {rework_without(events, invoices, PREVENTABLE_AT_ENTRY):g}% "
             "of invoices would still be reworked, so the target leaves a margin",
             AP_MANAGER, rejected, len(invoices)),
        _row("PO compliance", "Invoice spend with a purchase order", "% of spend", kpis.po_compliance(invoices),
             "≥", PO_COMPLIANCE_TARGET_PCT, "Proposed",
             "No PO, no pay, with an exception list agreed with Procurement (defects counted per invoice)",
             PROCUREMENT, no_po, len(invoices)),
        _row("Early-payment discount capture", "Discount invoices paid inside the discount window",
             "% of discount invoices", kpis.discount_capture_rate(invoices), "≥", DISCOUNT_CAPTURE_TARGET_PCT,
             "Proposed",
             f"A {terms['discount_pct']:g}/{int(terms['discount_days'])} Net {int(terms['net_days'])} discount earns "
             f"{annual_return:g}% a year against an {impact.COST_OF_CAPITAL_PCT:g}% cost of capital, so take "
             "every one; the gap allows for disputed invoices",
             AP_MANAGER, missed, len(discount_eligible)),
        _row("On-time payment rate", "Paid on or before the due date", "% of paid invoices",
             kpis.on_time_payment_rate(invoices), "≥", ON_TIME_TARGET_PCT, "Proposed",
             "Payment run selects by due date; the gap allows for invoices held back on purpose (disputes)",
             AP_MANAGER, late, len(paid)),
        _row("Days payable outstanding", "Invoice to payment, weighted by amount", "days",
             kpis.days_payable_outstanding(invoices), "≥", math.floor(target_dpo), "Proposed",
             f"Paying every invoice on its due date, or its discount date where a discount applies, "
             f"gives {target_dpo:g} days (agreed terms: {kpis.agreed_payment_days(invoices):g})",
             AP_MANAGER),
    ]
    result = pd.DataFrame(rows)
    counts = ["defects", "opportunities", "dpmo"]
    result[counts] = result[counts].astype("Int64")
    return result


def leakage_baseline(invoices: pd.DataFrame, budgets: pd.DataFrame) -> pd.DataFrame:
    """The € leakage per driver from impact.py, without the rule text (it lives
    in the code and the driver-tree doc, not in the frozen figures).
    """
    return impact.leakage_summary(invoices, budgets).drop(columns="rule")


def compute_baseline(invoices: pd.DataFrame | None = None, budgets: pd.DataFrame | None = None,
                     events: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    if invoices is None:
        invoices = kpis.load_invoices()
    if budgets is None:
        budgets = kpis.load_budgets()
    if events is None:
        events = kpis.load_events()
    return {
        "ctq": ctq_baseline(invoices, budgets, events),
        "leakage": leakage_baseline(invoices, budgets),
    }


def freeze(baseline: dict[str, pd.DataFrame]) -> None:
    # Fixed encoding and line endings, so the file is byte-identical whichever
    # OS freezes it (the BI tools read it on Windows).
    BASELINE_DIR.mkdir(exist_ok=True)
    for frame, path in [(baseline["ctq"], CTQ_BASELINE_FILE), (baseline["leakage"], LEAKAGE_BASELINE_FILE)]:
        frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


if __name__ == "__main__":
    result = compute_baseline()
    columns = ["ctq", "measure", "baseline", "defects", "opportunities", "dpmo", "sigma_level",
               "target_direction", "target", "target_source", "owner"]
    print(result["ctq"][columns].to_string(index=False))
    print()
    print(result["leakage"].to_string(index=False))
    if "--freeze" in sys.argv:
        freeze(result)
        print(f"\nfrozen to {CTQ_BASELINE_FILE.parent}")
