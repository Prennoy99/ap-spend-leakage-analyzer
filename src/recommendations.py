"""Recommendations for the Executive Summary: what to fix first, who owns it, and the € it addresses.

Each recommendation closes one of the ownership gaps in the process RACI
(docs/04_stakeholders_and_raci.md, section 4) and names the leakage drivers it
addresses. The € figures come from src/impact.py; nothing here estimates new numbers.

A driver's € counts in one of three ways, and recommendations are ranked in
that order, so an estimate never outranks certain cash:

1. **Hard leakage**: cash lost (the hard tier of the driver tree).
2. **Estimated saving**: a saving that rests on an assumption (PO premium %, cost of capital).
3. **Spend to review**: spend above budget. Some overruns are justified, so it is
   not a saving at all until budget owners have reviewed it.

Effort is a consultant's first estimate (Low = a setting in the ERP, Medium =
a policy change with supplier or staff communication). Task 5.4 refines it
in the impact/effort matrix.
"""

import pandas as pd

from src.impact import HARD_LEAKAGE

HARD = "hard_leakage_eur"
ESTIMATED = "estimated_saving_eur"
REVIEW = "spend_to_review_eur"

# Spend at risk splits into savings and spend to review; hard drivers are always HARD.
SPEND_AT_RISK_TYPE = {
    "Purchase-order premium": ESTIMATED,
    "Working capital given away": ESTIMATED,
    "Spend above budget": REVIEW,
}

EFFORT_ORDER = {"Low": 0, "Medium": 1, "High": 2}

RECOMMENDATIONS = [
    {
        "title": "Stop duplicate payments before they go out",
        "action": "Switch on the ERP's duplicate-invoice check (same supplier, amount and date) before "
                  "payment, have AP clerks clear its flags daily, and claim back the copies already paid.",
        "drivers": ["Duplicate payments"],
        "owner": "AP Manager",
        "effort": "Low",
    },
    {
        "title": "Pay to terms, not on approval",
        "action": "Let the payment run pick invoices by discount date and due date instead of paying "
                  "everything approved: take discounts on day 10, pay the rest on the due date.",
        "drivers": ["Missed early-payment discounts", "Late-payment interest and fees", "Working capital given away"],
        "owner": "AP Manager (Treasury consulted)",
        "effort": "Low",
    },
    {
        "title": "No PO, no pay",
        "action": "Route invoices without a purchase order back to the requester, starting with "
                  "non-preferred suppliers, with a named exception route for urgent cases.",
        "drivers": ["Purchase-order premium"],
        "owner": "Procurement lead",
        "effort": "Medium",
    },
    {
        "title": "Show approvers their remaining budget",
        "action": "Put remaining monthly budget next to every approval, so overruns are stopped "
                  "or approved knowingly instead of found after month-end.",
        "drivers": ["Spend above budget"],
        "owner": "Controlling",
        "effort": "Medium",
    },
]


def _benefit_type(driver: str, tier: str) -> str:
    return HARD if tier == HARD_LEAKAGE else SPEND_AT_RISK_TYPE[driver]


def rank_recommendations(summary: pd.DataFrame) -> pd.DataFrame:
    """Every recommendation with the € it addresses, by type, ranked: hard
    leakage first, then estimated saving, then spend to review, then lower effort.
    `summary` is impact.leakage_summary().
    """
    impact_by_driver = summary.set_index("driver")
    rows = []
    for rec in RECOMMENDATIONS:
        row = {**rec, HARD: 0.0, ESTIMATED: 0.0, REVIEW: 0.0, "drivers": ", ".join(rec["drivers"])}
        for driver in rec["drivers"]:
            benefit_type = _benefit_type(driver, impact_by_driver.at[driver, "tier"])
            row[benefit_type] += impact_by_driver.at[driver, "impact_eur"]
        rows.append(row)

    ranked = pd.DataFrame(rows)
    ranked[[HARD, ESTIMATED, REVIEW]] = ranked[[HARD, ESTIMATED, REVIEW]].round(2)
    ranked["effort_order"] = ranked["effort"].map(EFFORT_ORDER)
    ranked = ranked.sort_values(
        [HARD, ESTIMATED, REVIEW, "effort_order"], ascending=[False, False, False, True]
    ).drop(columns="effort_order").reset_index(drop=True)
    ranked.insert(0, "rank", ranked.index + 1)
    return ranked


def _eur_k(value: float) -> str:
    return f"€{value / 1000:,.1f}k"


def headline(impact: dict, ranked: pd.DataFrame, top_n: int = 3) -> str:
    """The answer-first sentence for the CFO, built only from computed figures.
    `impact` is impact.compute_all_impact().
    """
    summary = impact["summary"].set_index("driver")
    hard = impact["hard_leakage_eur"]
    duplicates = summary.at["Duplicate payments", "impact_eur"]
    covered = ranked.head(top_n)[HARD].sum()
    covered_text = "all of it" if round(covered, 2) >= round(hard, 2) else f"{covered / hard:.0%} of it"
    return (
        f"AP lost {_eur_k(hard)} in cash over the last 12 months, {impact['hard_leakage_pct_of_spend']:.1f}% "
        f"of indirect spend. Duplicate payments are {duplicates / hard:.0%} of that, and about "
        f"{_eur_k(impact['expected_duplicate_recovery_eur'])} can still be claimed back. "
        f"The top {top_n} fixes below address {covered_text}."
    )
