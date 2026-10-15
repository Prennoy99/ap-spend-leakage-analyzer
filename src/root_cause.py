"""Root cause of hard leakage: which process step lost each euro.

impact.py measures € per driver (duplicates, missed discounts, late payment).
Analyze asks the next question: which step in the process caused it, so the
fix goes to the right owner. Every euro of hard leakage is attributed to one
cause by a rule on the invoice's own timestamps and the event log:

- A duplicate payment means the second invoice got through entry: there is
  no duplicate check when an invoice is keyed in (hypothesis A1).
- A missed discount or a late payment where the approval came too late to
  pay in time, and the payment waited for it, was lost in approval: split into
  approvals slowed by a rework loop (D1) and slow approvals without one (B1, B2).
- Otherwise the invoice was approved in time and the payment step paid it
  too late: the payment run takes every approved invoice, whatever its
  terms (B3; as-is process step 9).

The rules are deliberately simple, so a reader can check any invoice by hand.
Spend at risk is not attributed here: it is not lost cash (see impact.py).
Like impact.py this reads only data/processed/.
"""

import pandas as pd

from src import impact
from src.process_mining import REJECT

NO_DUPLICATE_CHECK = "No duplicate check at invoice entry"
PAYMENT_RUN_IGNORES_TERMS = "Payment run ignores discount and due dates"
REWORK_DELAYS_APPROVAL = "Rework delays approval past the deadline"
SLOW_APPROVAL = "Slow approval, no rework"

# Cause → (process step where it happens, hypothesis in docs/03_issue_and_driver_tree.md).
CAUSES = {
    NO_DUPLICATE_CHECK: ("Enter invoice in ERP", "A1"),
    PAYMENT_RUN_IGNORES_TERMS: ("Create payment proposal", "B3"),
    REWORK_DELAYS_APPROVAL: ("Correct and resubmit", "D1"),
    SLOW_APPROVAL: ("Review and approve", "B1, B2"),
}

# The as-is payment step never pays on the day of approval: the proposal, its
# release and the bank transfer take at least a day (shortest approve-to-pay
# in the data: 1 day, tested). An approval later than this before the
# deadline left no time to pay, so the approval is the cause.
PAYMENT_LEAD_DAYS = 1

# Driver → the deadline the payment missed.
DEADLINES = {
    "Missed early-payment discounts": "discount_date",
    "Late-payment interest and fees": "due_date",
}


def deadline_cause(invoices: pd.DataFrame, deadline: str, reworked: set) -> pd.Series:
    """Why each invoice paid after `deadline` was paid too late. Approval is the
    cause only if it left less than PAYMENT_LEAD_DAYS to pay and the payment
    waited for it; otherwise there was time and the payment step missed it.
    """
    last_useful_approval = invoices[deadline] - pd.Timedelta(days=PAYMENT_LEAD_DAYS)
    approval_held_it_up = (invoices["approved_date"] > last_useful_approval) & (
        invoices["paid_date"] >= invoices["approved_date"]
    )
    cause = pd.Series(PAYMENT_RUN_IGNORES_TERMS, index=invoices.index)
    cause[approval_held_it_up] = SLOW_APPROVAL
    cause[approval_held_it_up & invoices["invoice_id"].isin(reworked)] = REWORK_DELAYS_APPROVAL
    return cause


def leakage_by_invoice(invoices: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Every invoice with hard leakage: driver, € impact and the cause it is attributed to."""
    reworked = set(events.loc[events["activity"] == REJECT, "invoice_id"])
    duplicates = impact.duplicate_payments(invoices)
    parts = [pd.DataFrame({
        "invoice_id": duplicates["second_invoice_id"],
        "driver": "Duplicate payments",
        "impact_eur": duplicates["impact_eur"],
        "cause": NO_DUPLICATE_CHECK,
    })]
    late_drivers = {
        "Missed early-payment discounts": impact.missed_discounts(invoices),
        "Late-payment interest and fees": impact.late_payment_cost(invoices),
    }
    for driver, detail in late_drivers.items():
        parts.append(pd.DataFrame({
            "invoice_id": detail["invoice_id"],
            "driver": driver,
            "impact_eur": detail["impact_eur"],
            "cause": deadline_cause(detail, DEADLINES[driver], reworked),
        }))
    return pd.concat(parts, ignore_index=True)


def leakage_pareto(invoices: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Hard leakage by cause, largest first, with the cumulative share: the
    few causes that account for most of the money.
    """
    detail = leakage_by_invoice(invoices, events)
    table = (
        detail.groupby("cause")
        .agg(impact_eur=("impact_eur", "sum"), invoices=("invoice_id", "nunique"))
        .sort_values(["impact_eur"], ascending=False)
        .reset_index()
    )
    total = table["impact_eur"].sum()
    table["share_pct"] = (table["impact_eur"] / total * 100).round(1)
    table["cumulative_pct"] = (table["impact_eur"].cumsum() / total * 100).round(1)
    table["impact_eur"] = table["impact_eur"].round(2)
    table["process_step"] = table["cause"].map(lambda c: CAUSES[c][0])
    table["hypothesis"] = table["cause"].map(lambda c: CAUSES[c][1])
    return table


def leakage_by_cause_and_driver(invoices: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """€ per cause and driver, so a reader sees what each cause is made of."""
    detail = leakage_by_invoice(invoices, events)
    table = detail.groupby(["cause", "driver"]).agg(
        invoices=("invoice_id", "nunique"), impact_eur=("impact_eur", "sum")
    ).reset_index()
    table["impact_eur"] = table["impact_eur"].round(2)
    return table.sort_values(["cause", "impact_eur"], ascending=[True, False]).reset_index(drop=True)


def headline(pareto: pd.DataFrame, by_path_type: pd.DataFrame, by_rework_loops: pd.DataFrame) -> str:
    """Answer-first sentence for the Process tab: the causes behind most of the
    money, and what rework does to throughput. Every figure is computed above.
    """
    top = pareto.head(2)
    straight = by_path_type.set_index("path_type").loc["Straight through"]
    loops = by_rework_loops.set_index("rework_loops")["median_days"]
    extra_per_loop = (loops.iloc[-1] - loops.loc[0]) / loops.index[-1]
    causes = " and ".join(
        f"{row.cause.lower()} (€{row.impact_eur / 1000:,.1f}k)" for row in top.itertuples()
    )
    return (
        f"Two process gaps explain {top['cumulative_pct'].iloc[-1]:.0f}% of hard leakage: {causes}. "
        f"{straight['share_pct']:.0f}% of invoices go straight through in a median {straight['median_days']:.1f} days; "
        f"each rework loop adds about {extra_per_loop:.0f} days."
    )
