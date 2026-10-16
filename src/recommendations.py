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

Effort comes from the one-off cost of the matching fix in the business case
(see EFFORT_BANDS); a test keeps the two in step. The impact/effort matrix and
the roadmap below (Improve, task 5.4) put the business-case fixes in order.
"""

import pandas as pd

from src import business_case as bc
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
        "action": "Block an invoice on a PO that is already invoiced, put same-supplier, same-amount "
                  "invoices within 5 days on a review list AP clears daily, and claim back the copies already paid.",
        "drivers": ["Duplicate payments"],
        "owner": "AP Manager",
        "effort": "Low",
        "lever": "Block duplicates at invoice entry",
    },
    {
        "title": "Pay to terms, not on approval",
        "action": "Let the payment run pick invoices by discount date and due date instead of paying "
                  "everything approved: take discounts on day 10, pay the rest on the due date.",
        "drivers": ["Missed early-payment discounts", "Late-payment interest and fees", "Working capital given away"],
        "owner": "AP Manager (Treasury consulted)",
        "effort": "Low",
        "lever": "Pay to terms",
    },
    {
        "title": "No PO, no pay",
        "action": "Route invoices without a purchase order back to the requester, starting with "
                  "non-preferred suppliers, with a named exception route for urgent cases.",
        "drivers": ["Purchase-order premium"],
        "owner": "Procurement lead",
        "effort": "Medium",
        "lever": "No PO, no pay",
    },
    {
        "title": "Show approvers their remaining budget",
        "action": "Put remaining monthly budget next to every approval, so overruns are stopped "
                  "or approved knowingly instead of found after month-end.",
        "drivers": ["Spend above budget"],
        "owner": "Controlling",
        "effort": "Medium",
        "lever": "Approval deadline for discount invoices",  # the budget view is built into this approval step
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
        row = {**{k: v for k, v in rec.items() if k != "lever"}, HARD: 0.0, ESTIMATED: 0.0, REVIEW: 0.0,
               "drivers": ", ".join(rec["drivers"])}
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


# --- Impact/effort matrix and roadmap (Improve, task 5.4) ------------------------

# Effort by one-off cost. €10k is about 10 IT days: what the ERP team can
# deliver in one two-week sprint. Above €20k a fix needs its own project.
EFFORT_BANDS = [(10_000.0, "Low"), (20_000.0, "Medium"), (float("inf"), "High")]

# A fix above €10k a year repays a typical €10k implementation within a year.
IMPACT_THRESHOLD_EUR = 10_000.0
EFFORT_THRESHOLD_EUR = EFFORT_BANDS[0][0]

QUICK_WIN = "Quick win"
MAJOR_PROJECT = "Major project"
FILL_IN = "Fill-in"
QUESTIONABLE = "Do for the process, not the €"

# Wave by quadrant: quick wins first, then what they make possible.
WAVES = {QUICK_WIN: 1, FILL_IN: 1, QUESTIONABLE: 2, MAJOR_PROJECT: 3}
WAVE_NAMES = {1: "Wave 1: months 1–2", 2: "Wave 2: months 2–4", 3: "Wave 3: months 4–6"}

# What a fix delivers beyond € (from the root-cause analysis and the to-be process).
OTHER_BENEFITS = {
    "Block duplicates at invoice entry": "Goal 1: no paid duplicates",
    "Pay to terms": "On-time payment; DPO towards agreed terms",
    "Approval deadline for discount invoices": "Discount capture target; remaining budget visible (C1)",
    "Validate cost centre and PO at entry": "Up to 55% fewer rejections; rework target",
    "No PO, no pay": "PO compliance target; prerequisite for three-way match and automatic approval",
    "Payment block without approval": "Control: no payment without approval (13 today)",
}


def effort_band(one_off_cost_eur: float) -> str:
    for limit, label in EFFORT_BANDS:
        if one_off_cost_eur <= limit:
            return label
    raise ValueError(one_off_cost_eur)


def quadrant(annual_benefit_eur: float, one_off_cost_eur: float) -> str:
    high_impact = annual_benefit_eur >= IMPACT_THRESHOLD_EUR
    low_effort = one_off_cost_eur <= EFFORT_THRESHOLD_EUR
    if high_impact:
        return QUICK_WIN if low_effort else MAJOR_PROJECT
    return FILL_IN if low_effort else QUESTIONABLE


def impact_effort_matrix(levers: pd.DataFrame) -> pd.DataFrame:
    """One row per fix: annual benefit (hard and estimated kept apart), one-off
    cost, effort band, quadrant and wave. `levers` is business_case.lever_table();
    the working-capital row is the same change as pay to terms and is folded into
    it, and programme management is not a fix.
    """
    rows = {}
    for lever in levers.itertuples():
        if lever.lever == "Programme management and training":
            continue
        name = "Pay to terms" if lever.lever == "Pay to terms: working capital" else lever.lever
        row = rows.setdefault(name, {"fix": name, "hard_benefit_eur": 0.0, "estimated_saving_eur": 0.0,
                                     "one_off_cost_eur": 0.0, "annual_run_cost_eur": 0.0, "owner": lever.owner})
        if lever.benefit_type == bc.HARD:
            row["hard_benefit_eur"] += lever.annual_benefit_eur
        elif lever.benefit_type == bc.ESTIMATED:
            row["estimated_saving_eur"] += lever.annual_benefit_eur
        row["one_off_cost_eur"] += lever.one_off_cost_eur
        row["annual_run_cost_eur"] += lever.annual_run_cost_eur
    table = pd.DataFrame(rows.values())
    table["annual_benefit_eur"] = table["hard_benefit_eur"] + table["estimated_saving_eur"]
    table["effort"] = table["one_off_cost_eur"].map(effort_band)
    table["quadrant"] = [quadrant(b, c) for b, c in zip(table["annual_benefit_eur"], table["one_off_cost_eur"])]
    table["wave"] = table["quadrant"].map(WAVES)
    table["other_benefits"] = table["fix"].map(OTHER_BENEFITS)
    money = ["hard_benefit_eur", "estimated_saving_eur", "annual_benefit_eur", "one_off_cost_eur",
             "annual_run_cost_eur"]
    table[money] = table[money].round(2)
    return table.sort_values(["wave", "hard_benefit_eur", "annual_benefit_eur"],
                             ascending=[True, False, False]).reset_index(drop=True)


def roadmap(matrix: pd.DataFrame) -> pd.DataFrame:
    """Fixes per wave, with the € each wave adds and its one-off cost."""
    table = matrix.groupby("wave").agg(
        fixes=("fix", " · ".join),
        hard_benefit_eur=("hard_benefit_eur", "sum"),
        estimated_saving_eur=("estimated_saving_eur", "sum"),
        one_off_cost_eur=("one_off_cost_eur", "sum"),
    ).reset_index()
    table.insert(1, "when", table["wave"].map(WAVE_NAMES))
    return table
