"""Control phase: the monthly control report and the frozen control limits.

Every CTQ from the charter is measured for one month, compared with its target
and with control limits from the frozen Measure baseline, and given a status.
A value off target, or a signal that the process got worse, names the
reaction-plan step and its owner (US-07). The plan itself is in
docs/12_control_plan.md.

Each monthly figure reuses the function that produced the baseline, on a
one-month slice, so the report can't drift from the baseline definitions
(over the full year it reproduces the frozen baseline; tested). A CTQ is
assigned to a month by when it happens: payments by payment month, entry
measures by invoice month, overruns by budget month. Rework is counted by
payment month, once an invoice has finished: by invoice month the latest
month would look better only because its invoices haven't been reviewed yet.

Control limits:
- Rates (rework, discount capture, on-time payment) get p-chart limits from the
  baseline defect rate: p ± 3·√(p(1−p)/n), with n the month's invoices. A month
  below the lower limit is a signal the process improved; above the upper
  limit, that it got worse.
- Processing time uses the weekly I-MR limits from Analyze (src/control_chart.py).
- Counts with a target of 0 (duplicates, breaches, overruns, missing dates)
  need no limits: any case is a reaction.

The limits are frozen to data/baseline/control_limits.csv like the baseline,
so a data change can't move them silently. Like kpis.py this reads only
data/processed/ (and the frozen baseline).
"""

import math
import sys

import pandas as pd

from src import baseline, kpis
from src.anomalies import detect_budget_overruns, find_duplicate_pairs
from src.control_chart import imr_chart, weekly_processing_time

CONTROL_LIMITS_FILE = baseline.BASELINE_DIR / "control_limits.csv"

P_CHART_SIGMAS = 3

ON_TARGET = "On target"
OFF_TARGET = "Off target"
WORSE = "Signal: worse than baseline"
BETTER = "Signal: better than baseline"
NO_SIGNAL = "Within control limits"
NO_DATA = "No data this month"

# CTQ (as named in the baseline) → p-chart on its defect rate.
P_CHARTS = ["Rework rate", "Early-payment discount capture", "On-time payment rate"]

# What to do when a CTQ is off target or worse than baseline. First step,
# owner (from the baseline), and when to escalate.
REACTION_PLAN = {
    "Duplicate payments": (
        "Block the copy or claim it back this week; check why the PO block let it through (no PO? a second "
        "supplier number?) and have IT close the gap", "CFO if a copy was paid"),
    "Processing time": (
        "Open the slowest invoices of the month on the Process tab; check the approval queue and rework "
        "first", "Budget owners' line managers if approvals cause it two months running"),
    "Unapproved budget overruns": (
        "Controlling asks the budget owner for written approval before month-end close", "Reforecast the "
        "budget if the same department-category is over two months running"),
    "Missing process timestamps": (
        "AP clerk completes the date; IT checks why the entry screen accepted the invoice without it",
        "IT lead if it repeats"),
    "Payments breaching approval": (
        "Stop and review: the payment block failed. Internal Audit checks every case", "CFO and Internal "
        "Audit, same day"),
    "Rework rate": (
        "Look at the month's reject reasons; fix the top one at entry or with the supplier", "IT if the top "
        "reason is one the entry check should stop"),
    "PO compliance": (
        "Procurement lists no-PO spend by requester and supplier and talks to the top three", "Head of the "
        "requesting department"),
    "Early-payment discount capture": (
        "List the missed discounts: approved late → chase approval-deadline adherence; approved in time → "
        "check the payment schedule", "Below 90% two months after wave 2: widen automatic approval of "
        "matched PO invoices (the business case's base case reaches about 83%)"),
    "On-time payment rate": (
        "List the late payments; check due-date scheduling and invoices held back for disputes",
        "Treasury if the payment run itself was late"),
    "Days payable outstanding": (
        "Check for early payments: the payment run should not pay before the discount or due date",
        "AP Manager with Treasury"),
}


# --- One month's figures ---------------------------------------------------------

def _month(dates: pd.Series) -> pd.Series:
    return dates.dt.to_period("M").astype(str)


def months(invoices: pd.DataFrame) -> list[str]:
    """Report months: every month with payments, oldest first."""
    return sorted(_month(invoices.loc[invoices["paid_date"].notna(), "paid_date"]).unique())


def monthly_values(invoices: pd.DataFrame, budgets: pd.DataFrame, events: pd.DataFrame, month: str) -> dict:
    """{(ctq, measure): (value, defects, opportunities)} for one month. `month`
    "all" gives the whole extract, which reproduces the baseline.
    """
    every = month == "all"
    paid = invoices[invoices["paid_date"].notna()]
    paid_m = paid if every else paid[_month(paid["paid_date"]) == month]
    entered = invoices if every else invoices[_month(invoices["invoice_date"]) == month]

    pairs = find_duplicate_pairs(invoices)
    copy_dates = invoices.set_index("invoice_id").loc[pairs["second_invoice_id"], "invoice_date"]
    duplicates = len(pairs) if every else int((_month(copy_dates) == month).sum())
    overruns = detect_budget_overruns(invoices, budgets)
    overrun_count = len(overruns) if every else int((overruns["month"] == month).sum()) if len(overruns) else 0
    budget_months = len(budgets) if every else int((budgets["month"] == month).sum())

    stage = kpis.stage_durations(paid_m).set_index("stage").loc["Submit → pay"] if len(paid_m) else None
    rejected = set(events.loc[events["activity"] == kpis.REJECT_ACTIVITY, "invoice_id"])
    eligible = paid_m[paid_m["discount_date"].notna()]
    breaches = baseline.approval_breaches(paid_m)

    def rate(defects: int, n: int, compliant: bool) -> tuple:
        if n == 0:
            return (None, defects, n)
        pct = (n - defects) / n * 100 if compliant else defects / n * 100
        return (round(pct, 1), defects, n)

    late = int((paid_m["paid_date"] > paid_m["due_date"]).sum())
    missed = int((eligible["paid_date"] > eligible["discount_date"]).sum())
    reworked = int(paid_m["invoice_id"].isin(rejected).sum())
    no_po = int((~entered["has_po"]).sum())
    return {
        ("Duplicate payments", "Suspected duplicate copies"): (duplicates, duplicates, len(entered)),
        ("Processing time", "Median, submission to payment"):
            (None if stage is None else stage["median_days"], None, None),
        ("Processing time", "90th percentile, submission to payment"):
            (None if stage is None else stage["p90_days"], None, None),
        ("Unapproved budget overruns", "Department-category-months over 115% of budget"):
            (overrun_count, overrun_count, budget_months),
        ("Missing process timestamps", "Invoices with no submission date"):
            (int(entered["missing_submitted_date"].sum()), int(entered["missing_submitted_date"].sum()), len(entered)),
        ("Payments breaching approval", "Paid before approval or never approved"):
            (len(breaches), len(breaches), len(paid_m)),
        ("Rework rate", "Invoices rejected at least once"): rate(reworked, len(paid_m), compliant=False),
        ("PO compliance", "Invoice spend with a purchase order"):
            (kpis.po_compliance(entered) if len(entered) else None, no_po, len(entered)),
        ("Early-payment discount capture", "Discount invoices paid inside the discount window"):
            rate(missed, len(eligible), compliant=True),
        ("On-time payment rate", "Paid on or before the due date"): rate(late, len(paid_m), compliant=True),
        ("Days payable outstanding", "Invoice to payment, weighted by amount"):
            (kpis.days_payable_outstanding(paid_m) if len(paid_m) else None, None, None),
    }


# --- Control limits -----------------------------------------------------------------

def control_limits(invoices: pd.DataFrame, budgets: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """The limits Control judges each month against: the baseline-year defect
    rate for each p-chart (measured exactly as each month is), and the weekly
    I-MR limits for processing time.
    """
    year = monthly_values(invoices, budgets, events, "all")
    rows = []
    for (ctq, measure), (_, defects, n) in year.items():
        if ctq not in P_CHARTS:
            continue
        rows.append({"chart": "p", "ctq": ctq, "measure": measure,
                     "centre": round(defects / n, 6), "lcl": None, "ucl": None, "mr_ucl": None,
                     "basis": f"Baseline-year defect rate, {defects} of {n}; limits depend on each "
                              "month's number of invoices"})
    _, imr = imr_chart(weekly_processing_time(invoices))
    rows.append({"chart": "I-MR", "ctq": "Processing time", "measure": "Weekly mean, submission to payment",
                 "centre": imr["centre"], "lcl": imr["lcl"], "ucl": imr["ucl"], "mr_ucl": imr["mr_ucl"],
                 "basis": "Weekly means of the baseline year, Phase I limits (see docs/09)"})
    return pd.DataFrame(rows)


def load_control_limits() -> pd.DataFrame:
    return pd.read_csv(CONTROL_LIMITS_FILE)


def p_limits(p_bar: float, n: int) -> tuple[float, float]:
    """Lower and upper p-chart limits for a sample of n."""
    spread = P_CHART_SIGMAS * math.sqrt(p_bar * (1 - p_bar) / n)
    return max(0.0, p_bar - spread), min(1.0, p_bar + spread)


def _signal(ctq: str, defects, n, month: str, limits: pd.DataFrame, weekly: pd.DataFrame) -> str | None:
    if ctq in P_CHARTS:
        if not n:
            return None
        p_bar = float(limits.loc[(limits["chart"] == "p") & (limits["ctq"] == ctq), "centre"].iloc[0])
        low, high = p_limits(p_bar, n)
        rate = defects / n
        return WORSE if rate > high else BETTER if rate < low else NO_SIGNAL
    if ctq == "Processing time":
        imr = limits[limits["chart"] == "I-MR"].iloc[0]
        weeks = weekly[_month(weekly["week_start"]) == month]
        if weeks.empty:
            return None
        above = int((weeks["mean_days"] > imr["ucl"]).sum())
        below = int((weeks["mean_days"] < imr["lcl"]).sum())
        return WORSE if above else BETTER if below else NO_SIGNAL
    return None


def _on_target(value, direction: str, target: float) -> bool:
    return value <= target if direction == "≤" else value >= target


# --- The report -----------------------------------------------------------------------

def control_report(invoices: pd.DataFrame, budgets: pd.DataFrame, events: pd.DataFrame, month: str,
                   ctq_baseline: pd.DataFrame | None = None, limits: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per CTQ for `month` (YYYY-MM): target, baseline, this month,
    the last three months, status, control-limit signal and the reaction step.
    """
    ctq_baseline = baseline.load_frozen_ctq() if ctq_baseline is None else ctq_baseline
    limits = load_control_limits() if limits is None else limits
    all_months = months(invoices)
    recent = all_months[max(0, all_months.index(month) - 2): all_months.index(month) + 1]
    history = {m: monthly_values(invoices, budgets, events, m) for m in recent}
    weekly = weekly_processing_time(invoices)

    rows = []
    for row in ctq_baseline.itertuples():
        key = (row.ctq, row.measure)
        value, defects, n = history[month][key]
        trend = [history[m][key][0] for m in recent]
        signal = _signal(row.ctq, defects, n, month, limits, weekly)
        if value is None:
            status = NO_DATA
        else:
            status = ON_TARGET if _on_target(value, row.target_direction, row.target) else OFF_TARGET
        act = status == OFF_TARGET or signal == WORSE
        action, escalation = REACTION_PLAN[row.ctq]
        rows.append({
            "ctq": row.ctq,
            "measure": row.measure,
            "unit": row.unit,
            "target": f"{row.target_direction} {row.target:g}",
            "baseline": row.baseline,
            "this_month": value,
            "trend": " → ".join("–" if v is None else f"{v:g}" for v in trend),
            "status": status,
            "signal": signal,
            "owner": row.owner,
            "reaction": action if act else "",
            "escalation": escalation if act else "",
        })
    return pd.DataFrame(rows)



def headline(report: pd.DataFrame, month: str, go_live: str | None = None) -> str:
    """Answer-first line for the Control tab. Before go-live every month is the
    baseline, so the line says so instead of reporting a failure.
    """
    measured = report[report["status"] != NO_DATA]
    on_target = int((measured["status"] == ON_TARGET).sum())
    worse = int((report["signal"] == WORSE).sum())
    better = int((report["signal"] == BETTER).sum())
    text = f"{month}: {on_target} of {len(measured)} CTQ measures on target"
    if worse or better:
        parts = [f"{worse} worse than baseline" if worse else "", f"{better} better" if better else ""]
        text += " (" + ", ".join(p for p in parts if p) + ")"
    text += "."
    if go_live is None or month < go_live:
        text += (" This month is part of the baseline year, before any fix is live: from go-live the same "
                 "report shows month by month whether the fixes work.")
    return text

def freeze_limits(invoices: pd.DataFrame, budgets: pd.DataFrame, events: pd.DataFrame) -> None:
    control_limits(invoices, budgets, events).to_csv(
        CONTROL_LIMITS_FILE, index=False, encoding="utf-8", lineterminator="\n")


if __name__ == "__main__":
    invoices, budgets, events = kpis.load_invoices(), kpis.load_budgets(), kpis.load_events()
    if "--freeze" in sys.argv:
        freeze_limits(invoices, budgets, events)
        print(f"frozen to {CONTROL_LIMITS_FILE}")
    month = next((a for a in sys.argv[1:] if a[:2] == "20"), months(invoices)[-1])
    report = control_report(invoices, budgets, events, month)
    print(f"Control report {month}")
    print(report.drop(columns=["reaction", "escalation"]).to_string(index=False))
