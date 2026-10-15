"""€ impact of each leakage driver in the driver tree (docs/03_issue_and_driver_tree.md).

The drivers fall into two tiers that are reported side by side and never added up:

- **Hard leakage**: cash lost or recoverable (duplicate payments, missed
  early-payment discounts, late-payment interest and fees). The business case rests on this.
- **Controllable spend at risk**: money spent against policy (above budget, without a
  purchase order, paid earlier than needed). Some of it is waste, but not all of it, so
  adding it to hard leakage would inflate the headline.

Every assumption is a named constant below, so the business case and sensitivity
analysis (Phase 5) vary them in one place. The data covers 12 months, so every figure
is already annual. Discounts, lateness and early payment are judged on payment: an
open invoice has neither missed nor taken anything yet.

Like kpis.py this reads only data/processed/, and like the rest of the pipeline it
computes every number in Python. Gemini only ever narrates the results.
"""

import pandas as pd

from src.anomalies import BUDGET_OVERRUN_THRESHOLD, find_duplicate_pairs
from src.kpis import budget_vs_actual, load_budgets, load_invoices

HARD_LEAKAGE = "Hard leakage"
SPEND_AT_RISK = "Controllable spend at risk"

# Share of paid duplicates the suppliers credit back once asked. Most re-sent
# invoices are settled by credit note, but some suppliers dispute or net it off
# against later invoices. An assumption to agree with the AP Manager; the
# gross figure is always reported next to it.
DUPLICATE_RECOVERY_RATE = 0.80

# § 288(2) BGB: in business-to-business transactions, default interest is
# 9 percentage points above the base rate (§ 247 BGB).
LATE_INTEREST_MARGIN_PP = 9.0

# § 288(5) BGB: a supplier may claim a €40 flat fee per late invoice.
LATE_PAYMENT_FLAT_FEE_EUR = 40.0

# Bundesbank base rate (Basiszinssatz), % p.a., by the date it took effect.
# It moves each 1 January and 1 July. Sources: bundesbank.de, "Basiszinssatz
# nach § 247 BGB" and the 1 July 2026 announcement (1.52%).
BASE_RATE_SCHEDULE = pd.Series(
    [2.27, 1.27, 1.27, 1.52],
    index=pd.to_datetime(["2025-01-01", "2025-07-01", "2026-01-01", "2026-07-01"]),
)

# Price premium on spend without a purchase order: buying off-contract skips
# the negotiated price. Kept at a conservative 5%; Procurement should confirm
# it, and Phase 5 varies it in the sensitivity analysis.
PO_PREMIUM_PCT = 5.0

# What a euro of cash is worth to Rheinwerk for a year, used to price paying
# suppliers earlier than the terms require. A typical WACC for a German
# mid-size manufacturer; the CFO should supply the real figure.
COST_OF_CAPITAL_PCT = 8.0

DAYS_PER_YEAR = 365


def _paid(invoices: pd.DataFrame) -> pd.DataFrame:
    return invoices[invoices["paid_date"].notna()]


def duplicate_payments(invoices: pd.DataFrame) -> pd.DataFrame:
    """Suspected duplicate pairs with the copy's € amount as the exposure.
    `copy_paid` separates cash to recover (paid) from payments still to block (open).
    """
    pairs = find_duplicate_pairs(invoices)
    paid_ids = set(_paid(invoices)["invoice_id"])
    return pairs.assign(
        copy_paid=pairs["second_invoice_id"].isin(paid_ids),
        impact_eur=pairs["amount"],
    )


def expected_duplicate_recovery(duplicates: pd.DataFrame) -> float:
    """€ AP can expect back from suppliers for duplicates already paid."""
    paid_copies = duplicates.loc[duplicates["copy_paid"], "impact_eur"].sum()
    return round(float(paid_copies * DUPLICATE_RECOVERY_RATE), 2)


def missed_discounts(invoices: pd.DataFrame) -> pd.DataFrame:
    """Invoices with discount terms paid after the discount window: the discount was forfeited."""
    paid = _paid(invoices)
    missed = paid[paid["discount_date"].notna() & (paid["paid_date"] > paid["discount_date"])]
    return missed.assign(impact_eur=missed["amount"] * missed["discount_pct"] / 100)


def base_rate_on(dates: pd.Series) -> pd.Series:
    """The base rate in force on each date."""
    positions = BASE_RATE_SCHEDULE.index.searchsorted(dates, side="right") - 1
    return pd.Series(BASE_RATE_SCHEDULE.to_numpy()[positions], index=dates.index)


def late_payment_cost(invoices: pd.DataFrame) -> pd.DataFrame:
    """Statutory interest plus the flat fee on invoices paid after the due date.

    This is exposure, not booked cost: many suppliers never claim. The rate is
    the one in force on the first day of default; a default that spans a
    1 January or 1 July change is priced at the opening rate.
    """
    paid = _paid(invoices)
    late = paid[paid["paid_date"] > paid["due_date"]].copy()
    late["days_late"] = (late["paid_date"] - late["due_date"]).dt.days
    late["interest_rate_pct"] = base_rate_on(late["due_date"] + pd.Timedelta(days=1)) + LATE_INTEREST_MARGIN_PP
    interest = late["amount"] * late["interest_rate_pct"] / 100 * late["days_late"] / DAYS_PER_YEAR
    return late.assign(impact_eur=interest + LATE_PAYMENT_FLAT_FEE_EUR)


def spend_above_budget(invoices: pd.DataFrame, budgets: pd.DataFrame,
                       threshold: float = BUDGET_OVERRUN_THRESHOLD) -> pd.DataFrame:
    """Department-category-months over the overrun threshold, with the full
    amount above budget (not just above the tolerance) as the impact. Uses the
    same threshold as the budget-overrun detector, so the two always agree.
    """
    bva = budget_vs_actual(invoices, budgets)
    over = bva[bva["actual_amount"] > bva["budget_amount"] * threshold]
    return over.assign(impact_eur=over["actual_amount"] - over["budget_amount"])


def po_premium(invoices: pd.DataFrame) -> pd.DataFrame:
    """Invoices without a purchase order, priced at the assumed off-contract premium."""
    no_po = invoices[~invoices["has_po"]]
    return no_po.assign(impact_eur=no_po["amount"] * PO_PREMIUM_PCT / 100)


def early_payment_cost(invoices: pd.DataFrame) -> pd.DataFrame:
    """Cost of capital on invoices paid before they had to be.

    The latest sensible pay date is the discount date when the discount was
    taken (paying then still earns it), otherwise the net due date.
    """
    paid = _paid(invoices)
    discount_taken = paid["discount_date"].notna() & (paid["paid_date"] <= paid["discount_date"])
    target = paid["discount_date"].where(discount_taken, paid["due_date"])
    early = paid.assign(days_early=(target - paid["paid_date"]).dt.days)
    early = early[early["days_early"] > 0]
    cost = early["amount"] * COST_OF_CAPITAL_PCT / 100 * early["days_early"] / DAYS_PER_YEAR
    return early.assign(impact_eur=cost)


def leakage_summary(invoices: pd.DataFrame, budgets: pd.DataFrame) -> pd.DataFrame:
    """One row per driver: tier, number of cases, € base and € impact, and the rule in plain words."""
    drivers = [
        ("Duplicate payments", HARD_LEAKAGE, duplicate_payments(invoices), "amount",
         "Second invoice of each same-supplier, same-amount pair within 5 days"),
        ("Missed early-payment discounts", HARD_LEAKAGE, missed_discounts(invoices), "amount",
         "Discount forfeited on invoices paid after the discount window"),
        ("Late-payment interest and fees", HARD_LEAKAGE, late_payment_cost(invoices), "amount",
         f"Base rate + {LATE_INTEREST_MARGIN_PP:g} pp per day late, plus €{LATE_PAYMENT_FLAT_FEE_EUR:g} "
         "per invoice (§ 288 BGB); exposure if suppliers claim"),
        ("Spend above budget", SPEND_AT_RISK, spend_above_budget(invoices, budgets), "actual_amount",
         f"Amount above budget in department-category-months over {BUDGET_OVERRUN_THRESHOLD:.0%} of budget"),
        ("Purchase-order premium", SPEND_AT_RISK, po_premium(invoices), "amount",
         f"{PO_PREMIUM_PCT:g}% assumed premium on spend without a purchase order"),
        ("Working capital given away", SPEND_AT_RISK, early_payment_cost(invoices), "amount",
         f"{COST_OF_CAPITAL_PCT:g}% cost of capital on days paid before the due or discount date"),
    ]
    return pd.DataFrame([
        {
            "driver": name,
            "tier": tier,
            "cases": len(detail),
            "base_eur": round(float(detail[base_column].sum()), 2),
            "impact_eur": round(float(detail["impact_eur"].sum()), 2),
            "rule": rule,
        }
        for name, tier, detail, base_column, rule in drivers
    ])


def tier_totals(summary: pd.DataFrame) -> dict:
    """€ impact per tier. Kept as two numbers on purpose: see the module docstring."""
    totals = summary.groupby("tier")["impact_eur"].sum().round(2)
    return {tier: float(totals.get(tier, 0.0)) for tier in [HARD_LEAKAGE, SPEND_AT_RISK]}


def assumptions() -> dict:
    """The assumptions behind the € figures, for display next to them."""
    return {
        "duplicate_recovery_rate_pct": DUPLICATE_RECOVERY_RATE * 100,
        "late_interest_margin_pp": LATE_INTEREST_MARGIN_PP,
        "late_payment_flat_fee_eur": LATE_PAYMENT_FLAT_FEE_EUR,
        "po_premium_pct": PO_PREMIUM_PCT,
        "cost_of_capital_pct": COST_OF_CAPITAL_PCT,
    }


def compute_all_impact(invoices: pd.DataFrame | None = None, budgets: pd.DataFrame | None = None) -> dict:
    if invoices is None:
        invoices = load_invoices()
    if budgets is None:
        budgets = load_budgets()

    summary = leakage_summary(invoices, budgets)
    totals = tier_totals(summary)
    spend = float(invoices["amount"].sum())
    return {
        "summary": summary,
        "hard_leakage_eur": totals[HARD_LEAKAGE],
        "spend_at_risk_eur": totals[SPEND_AT_RISK],
        # Scale before rounding, as in kpis.budget_vs_actual.
        "hard_leakage_pct_of_spend": round(totals[HARD_LEAKAGE] / spend * 100, 2),
        "expected_duplicate_recovery_eur": expected_duplicate_recovery(duplicate_payments(invoices)),
        "assumptions": assumptions(),
    }


if __name__ == "__main__":
    impact = compute_all_impact()
    print(impact["summary"].drop(columns="rule").to_string(index=False))
    print()
    print(f"hard leakage:     EUR {impact['hard_leakage_eur']:>12,.2f}  ({impact['hard_leakage_pct_of_spend']}% of spend)")
    print(f"spend at risk:    EUR {impact['spend_at_risk_eur']:>12,.2f}")
    print(f"expected duplicate recovery: EUR {impact['expected_duplicate_recovery_eur']:,.2f}")
