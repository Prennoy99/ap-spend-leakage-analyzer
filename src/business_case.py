"""Business case for the Improve phase: what the fixes cost, what they return,
and how sure we can be. ROI, 3-year NPV and payback, with best, base and worst
cases and a tornado of the assumptions (US-02).

Each lever is one fix from the root-cause analysis (docs/09_root_cause_analysis.md).
Its € at stake is a measured figure, never a new estimate: the cause € from
root_cause.py for hard leakage, and the driver € from impact.py for estimated
savings. What a lever removes of that € (its effectiveness) is an assumption,
taken from the data where the data can say it.

The two tiers stay apart (see impact.py). The headline NPV counts **hard
benefits only**. Estimated savings (purchase-order premium, working capital)
are added in a second, clearly labelled figure. Spend above budget is not a
saving at all, so it is left out.

Deliberately conservative: staff time is priced as a cost (implementation and
running), but the AP time saved by less rework is not counted as a benefit,
because no hourly handling cost has been agreed (Decisions log, Define).

The data covers 12 months, so the measured € are annual. Benefits are assumed
to recur at the same level each year (flat invoice volume). Every number is
computed here in Python; Gemini only ever narrates the results.
"""

import pandas as pd

from src import impact, root_cause
from src.anomalies import find_duplicate_pairs, find_po_reuse
from src.baseline import PO_COMPLIANCE_TARGET_PCT
from src.kpis import load_budgets, load_events, load_invoices, po_compliance

YEARS = 3

# Cost rates. External SAP consultant for configuration and workflow changes,
# a typical German day rate; internal staff at a fully loaded AP or
# Procurement cost (about €50 an hour). To confirm with IT and HR controlling.
IT_DAY_RATE_EUR = 1_000.0
INTERNAL_DAY_RATE_EUR = 400.0

HARD = "Hard benefit"
ESTIMATED = "Estimated saving"
NO_BENEFIT = "Control only"

# The levers. `cost_it_days` and `cost_business_days` are one-off (design,
# configuration, test, training, communication); `run_business_days` is the
# yearly effort to operate the fix. First estimates by the consultant, varied
# together by the cost multiplier in the sensitivity analysis.
LEVERS = [
    {
        "lever": "Block duplicates at invoice entry",
        "action": "Block an invoice on a PO that is already invoiced; same supplier and amount within "
                  "5 days goes on a review list that AP clears daily",
        "owner": "AP Manager, IT",
        "benefit_type": HARD,
        "addresses": root_cause.NO_DUPLICATE_CHECK,
        "effectiveness": "duplicate_prevention",
        "cost_it_days": 8, "cost_business_days": 3, "run_business_days": 4,
    },
    {
        "lever": "Pay to terms",
        "action": "Payment proposal selected by discount date and due date instead of paying everything "
                  "approved",
        "owner": "AP Manager (Treasury consulted)",
        "benefit_type": HARD,
        "addresses": root_cause.PAYMENT_RUN_IGNORES_TERMS,
        "effectiveness": "pay_to_terms",
        "cost_it_days": 5, "cost_business_days": 3, "run_business_days": 0,
    },
    {
        "lever": "Approval deadline for discount invoices",
        "action": "Workflow reminder to the budget owner, escalation to the AP Manager two days before "
                  "the discount date",
        "owner": "Budget owners, AP Manager",
        "benefit_type": HARD,
        "addresses": root_cause.SLOW_APPROVAL,
        "effectiveness": "approval_deadline",
        "cost_it_days": 10, "cost_business_days": 5, "run_business_days": 2,
    },
    {
        "lever": "Validate cost centre and PO at entry",
        "action": "Entry screen checks the cost centre against the department and requires a PO "
                  "number or an exception reason",
        "owner": "IT, AP clerks",
        "benefit_type": HARD,
        "addresses": root_cause.REWORK_DELAYS_APPROVAL,
        "effectiveness": "entry_validation",
        "cost_it_days": 12, "cost_business_days": 3, "run_business_days": 0,
    },
    {
        "lever": "No PO, no pay",
        "action": "Invoices without a PO go back to the requester, starting with non-preferred suppliers; "
                  "named exception route for urgent cases",
        "owner": "Procurement lead",
        "benefit_type": ESTIMATED,
        "addresses": "Purchase-order premium",
        "effectiveness": "po_compliance",
        "cost_it_days": 3, "cost_business_days": 20, "run_business_days": 15,
    },
    {
        "lever": "Pay to terms: working capital",
        "action": "Same payment-run change: invoices without a discount are paid on the due date, not "
                  "on approval (no extra cost)",
        "owner": "AP Manager (Treasury consulted)",
        "benefit_type": ESTIMATED,
        "addresses": "Working capital given away",
        "effectiveness": "pay_to_terms",
        "cost_it_days": 0, "cost_business_days": 0, "run_business_days": 0,
    },
    {
        "lever": "Payment block without approval",
        "action": "ERP blocks payment of an invoice with no recorded approval",
        "owner": "AP Manager, Internal Audit",
        "benefit_type": NO_BENEFIT,
        "addresses": "Paid before or without approval (control)",
        "effectiveness": None,
        "cost_it_days": 2, "cost_business_days": 1, "run_business_days": 0,
    },
    {
        "lever": "Programme management and training",
        "action": "Plan, test and roll out the changes; train AP clerks and budget owners",
        "owner": "AP Manager",
        "benefit_type": NO_BENEFIT,
        "addresses": "All",
        "effectiveness": None,
        "cost_it_days": 0, "cost_business_days": 15, "run_business_days": 0,
    },
]

# Assumptions as (worst, base, best). None for a base means "from the data"
# (see data_based_effectiveness). Shares are of the € the lever addresses.
ASSUMPTIONS = {
    # The PO block alone stops the duplicates that reused a PO (data); the
    # review list can catch the rest if AP clears it, or less if POs are
    # bypassed after go-live.
    "duplicate_prevention": {"worst": 0.80, "base": None, "best": 1.00,
                             "label": "Duplicates prevented", "source": "Data: € share of duplicates that reused a PO"},
    # Every invoice in this cause was approved with at least a day to spare;
    # a weekly run can still miss the ones approved just before the deadline.
    "pay_to_terms": {"worst": 0.60, "base": 0.80, "best": 1.00,
                     "label": "Pay-to-terms effectiveness", "source": "Consultant estimate; depends on run frequency"},
    "approval_deadline": {"worst": 0.25, "base": 0.50, "best": 0.75,
                          "label": "Late approvals avoided", "source": "Consultant estimate; confirm with budget owners"},
    # Share of rejections whose reason an entry check catches (data); the
    # range allows for checks that are bypassed or only partly effective.
    "entry_validation": {"worst": 0.30, "base": None, "best": 0.70,
                         "label": "Rework prevented at entry", "source": "Data: share of rejections preventable at entry"},
    # Share of no-PO spend that reaching the PO-compliance target covers (data).
    "po_compliance": {"worst": 0.25, "base": None, "best": 0.75,
                      "label": "No-PO spend brought under PO", "source": "Data: gap closed by the 90% PO-compliance target"},
    "duplicate_recovery_rate": {"worst": 0.60, "base": impact.DUPLICATE_RECOVERY_RATE, "best": 0.95,
                                "label": "Paid duplicates recovered", "source": "Open question Q1 (CFO, AP Manager)"},
    # Only moves the estimated savings: impact.py prices no-PO spend at this premium.
    "po_premium_pct": {"worst": 2.0, "base": impact.PO_PREMIUM_PCT, "best": 8.0,
                       "label": "Premium paid without a PO", "source": "Assumption in Measure; confirm with Procurement"},
    "cost_multiplier": {"worst": 1.50, "base": 1.00, "best": 0.90,
                        "label": "Implementation and running cost", "source": "Consultant estimate; IT overruns are common"},
    "cost_of_capital_pct": {"worst": 10.0, "base": impact.COST_OF_CAPITAL_PCT, "best": 6.0,
                            "label": "Cost of capital (discount rate)", "source": "Open question Q3 (CFO)"},
    # Go-live early in year 1, so year 1 gets most but not all of a full year.
    "ramp_up_year_1": {"worst": 0.50, "base": 0.75, "best": 0.90,
                       "label": "Year-1 benefit realised", "source": "Go-live in the first quarter (charter goal date)"},
}

# Rejection reasons an entry check stops: a cost centre that doesn't match the
# department, and an invoice without a PO number.
PREVENTABLE_AT_ENTRY = ["Wrong cost centre", "Missing PO"]


def data_based_effectiveness(invoices: pd.DataFrame, events: pd.DataFrame) -> dict:
    """The base-case effectiveness the data can give, as shares (0–1)."""
    pairs = find_duplicate_pairs(invoices)
    po_blocked = find_po_reuse(invoices)
    rejects = events[events["activity"] == "Reject invoice"]
    current_po = po_compliance(invoices)
    return {
        "duplicate_prevention": float(po_blocked["amount"].sum() / pairs["amount"].sum()),
        "entry_validation": float(rejects["reject_reason"].isin(PREVENTABLE_AT_ENTRY).mean()),
        "po_compliance": max(0.0, (PO_COMPLIANCE_TARGET_PCT - current_po) / (100.0 - current_po)),
    }


def scenario_params(scenario: str, data_based: dict) -> dict:
    """All assumptions for "worst", "base" or "best"."""
    params = {}
    for name, values in ASSUMPTIONS.items():
        value = values[scenario]
        params[name] = data_based[name] if value is None else value
    return params


def measured_eur(invoices: pd.DataFrame, budgets: pd.DataFrame, events: pd.DataFrame) -> dict:
    """€ a year each lever can address: the hard causes from root_cause, the
    estimated drivers from impact, and the duplicates already paid (one-off).
    """
    pareto = root_cause.leakage_pareto(invoices, events).set_index("cause")["impact_eur"]
    drivers = impact.leakage_summary(invoices, budgets).set_index("driver")["impact_eur"]
    duplicates = impact.duplicate_payments(invoices)
    return {
        **{cause: float(pareto.get(cause, 0.0)) for cause in root_cause.CAUSES},
        "Purchase-order premium": float(drivers["Purchase-order premium"]),
        "Working capital given away": float(drivers["Working capital given away"]),
        "paid_duplicates": float(duplicates.loc[duplicates["copy_paid"], "impact_eur"].sum()),
    }


def _addressed_eur(measured: dict, params: dict, addresses: str) -> float:
    """Measured € for a lever. The two estimated drivers were priced in impact.py
    at the base premium and cost of capital, so they move with those assumptions.
    """
    addressed = measured.get(addresses, 0.0)
    if addresses == "Purchase-order premium":
        return addressed * params["po_premium_pct"] / impact.PO_PREMIUM_PCT
    if addresses == "Working capital given away":
        return addressed * params["cost_of_capital_pct"] / impact.COST_OF_CAPITAL_PCT
    return addressed


def lever_table(measured: dict, params: dict) -> pd.DataFrame:
    """One row per lever: € addressed, effectiveness, annual benefit, one-off and running cost."""
    rows = []
    for lever in LEVERS:
        addressed = _addressed_eur(measured, params, lever["addresses"])
        share = params[lever["effectiveness"]] if lever["effectiveness"] else 0.0
        rows.append({
            "lever": lever["lever"],
            "benefit_type": lever["benefit_type"],
            "addresses": lever["addresses"],
            "owner": lever["owner"],
            "action": lever["action"],
            "eur_addressed": addressed,
            "effectiveness": share,
            "annual_benefit_eur": addressed * share,
            "one_off_cost_eur": (lever["cost_it_days"] * IT_DAY_RATE_EUR
                                 + lever["cost_business_days"] * INTERNAL_DAY_RATE_EUR) * params["cost_multiplier"],
            "annual_run_cost_eur": lever["run_business_days"] * INTERNAL_DAY_RATE_EUR * params["cost_multiplier"],
        })
    return pd.DataFrame(rows)


def cash_flows(levers: pd.DataFrame, params: dict, paid_duplicates_eur: float,
               include_estimated: bool = False) -> pd.DataFrame:
    """Year 0 (investment) to year 3. Year 1 realises `ramp_up_year_1` of the
    annual benefit, plus the one-off recovery of duplicates already paid
    (claims take a few months). Running costs start in year 1 in full.
    """
    types = [HARD, ESTIMATED] if include_estimated else [HARD]
    annual_benefit = levers.loc[levers["benefit_type"].isin(types), "annual_benefit_eur"].sum()
    run_cost = levers["annual_run_cost_eur"].sum()
    rate = params["cost_of_capital_pct"] / 100
    rows = []
    for year in range(YEARS + 1):
        if year == 0:
            benefit, recovery, cost = 0.0, 0.0, levers["one_off_cost_eur"].sum()
        else:
            benefit = annual_benefit * (params["ramp_up_year_1"] if year == 1 else 1.0)
            recovery = paid_duplicates_eur * params["duplicate_recovery_rate"] if year == 1 else 0.0
            cost = run_cost
        net = benefit + recovery - cost
        rows.append({
            "year": year,
            "benefit_eur": benefit,
            "recovery_eur": recovery,
            "cost_eur": cost,
            "net_eur": net,
            "discounted_eur": net / (1 + rate) ** year,
        })
    flows = pd.DataFrame(rows)
    flows["cumulative_eur"] = flows["net_eur"].cumsum()
    return flows


def npv(flows: pd.DataFrame) -> float:
    return float(flows["discounted_eur"].sum())


def roi_pct(flows: pd.DataFrame) -> float:
    """3-year return on the one-off investment: (total net return − investment) / investment."""
    investment = -flows.loc[flows["year"] == 0, "net_eur"].iloc[0]
    returns = flows.loc[flows["year"] > 0, "net_eur"].sum()
    return float((returns - investment) / investment * 100)


def payback_months(flows: pd.DataFrame) -> float | None:
    """Months until the cumulative cash flow turns positive, assuming each
    year's net flow arrives evenly over its 12 months. None if not within the horizon.
    """
    previous = flows["cumulative_eur"].iloc[0]
    for row in flows.iloc[1:].itertuples():
        if row.cumulative_eur >= 0:
            return float((row.year - 1) * 12 + (-previous) / row.net_eur * 12)
        previous = row.cumulative_eur
    return None


def break_even_cost_multiplier(measured: dict, params: dict) -> float:
    """How many times the cost estimate (one-off and running) the hard-benefit
    NPV can absorb before it reaches zero. Costs scale linearly with the
    multiplier, so NPV(m) = PV(benefits) - m x PV(costs at m = 1).
    """
    at_one = {**params, "cost_multiplier": 1.0}
    flows = cash_flows(lever_table(measured, at_one), at_one, measured["paid_duplicates"])
    discount = (1 + at_one["cost_of_capital_pct"] / 100) ** flows["year"]
    pv_costs = float((flows["cost_eur"] / discount).sum())
    pv_benefits = float(((flows["benefit_eur"] + flows["recovery_eur"]) / discount).sum())
    return pv_benefits / pv_costs


def evaluate(measured: dict, params: dict) -> dict:
    """Levers, cash flows and headline figures for one set of assumptions."""
    levers = lever_table(measured, params)
    result = {"levers": levers, "params": params}
    for key, include in [("hard", False), ("with_estimated", True)]:
        flows = cash_flows(levers, params, measured["paid_duplicates"], include_estimated=include)
        result[key] = {
            "flows": flows,
            "npv_eur": round(npv(flows), 2),
            "roi_pct": round(roi_pct(flows), 1),
            "payback_months": None if (p := payback_months(flows)) is None else round(p, 1),
        }
    result["break_even_cost_multiplier"] = round(break_even_cost_multiplier(measured, params), 2)
    result["investment_eur"] = round(float(levers["one_off_cost_eur"].sum()), 2)
    result["annual_run_cost_eur"] = round(float(levers["annual_run_cost_eur"].sum()), 2)
    result["annual_hard_benefit_eur"] = round(
        float(levers.loc[levers["benefit_type"] == HARD, "annual_benefit_eur"].sum()), 2)
    result["annual_estimated_saving_eur"] = round(
        float(levers.loc[levers["benefit_type"] == ESTIMATED, "annual_benefit_eur"].sum()), 2)
    return result


def scenarios(measured: dict, data_based: dict) -> pd.DataFrame:
    """Worst, base and best case side by side."""
    rows = []
    for scenario in ["worst", "base", "best"]:
        params = scenario_params(scenario, data_based)
        result = evaluate(measured, params)
        # The claim-back of duplicates already paid needs no investment, so the
        # recurring fixes are also shown without it: they must pay on their own.
        recurring_only = evaluate(measured, {**params, "duplicate_recovery_rate": 0.0})
        rows.append({
            "scenario": scenario.title(),
            "investment_eur": result["investment_eur"],
            "annual_hard_benefit_eur": result["annual_hard_benefit_eur"],
            "npv_hard_eur": result["hard"]["npv_eur"],
            "roi_hard_pct": result["hard"]["roi_pct"],
            "payback_hard_months": result["hard"]["payback_months"],
            "npv_hard_without_recovery_eur": recurring_only["hard"]["npv_eur"],
            "npv_with_estimated_eur": result["with_estimated"]["npv_eur"],
        })
    return pd.DataFrame(rows)


def tornado(measured: dict, data_based: dict, include_estimated: bool = False) -> pd.DataFrame:
    """NPV with each assumption moved to its worst and best value, the others
    at base. Sorted by swing, largest first: the assumptions worth confirming.
    """
    key = "with_estimated" if include_estimated else "hard"
    base = scenario_params("base", data_based)
    base_npv = evaluate(measured, base)[key]["npv_eur"]
    rows = []
    for name, values in ASSUMPTIONS.items():
        npvs = {}
        for scenario in ["worst", "best"]:
            params = {**base, name: scenario_params(scenario, data_based)[name]}
            npvs[scenario] = evaluate(measured, params)[key]["npv_eur"]
        rows.append({
            "assumption": values["label"],
            "worst_value": scenario_params("worst", data_based)[name],
            "base_value": base[name],
            "best_value": scenario_params("best", data_based)[name],
            "npv_worst_eur": npvs["worst"],
            "npv_base_eur": base_npv,
            "npv_best_eur": npvs["best"],
            "swing_eur": round(abs(npvs["best"] - npvs["worst"]), 2),
            "source": values["source"],
        })
    return pd.DataFrame(rows).sort_values("swing_eur", ascending=False).reset_index(drop=True)


def _eur_k(value: float) -> str:
    return f"€{value / 1000:,.0f}k"


def headline(case: dict) -> str:
    """Answer-first sentence for the Business case tab; every figure is computed above."""
    base, table = case["base"], case["scenarios"].set_index("scenario")
    worst = table.loc["Worst"]
    sentence = (
        f"The fixes cost {_eur_k(base['investment_eur'])} once and return {_eur_k(base['annual_hard_benefit_eur'])} "
        f"a year in hard benefits: a 3-year NPV of {_eur_k(base['hard']['npv_eur'])}, paid back in "
        f"{base['hard']['payback_months']:.0f} months. "
    )
    if worst["npv_hard_eur"] > 0:
        sentence += f"Even the worst case stays positive ({_eur_k(worst['npv_hard_eur'])})"
    else:
        sentence += f"The worst case loses money ({_eur_k(worst['npv_hard_eur'])})"
    return sentence + ", before any estimated savings."


def compute_business_case(invoices: pd.DataFrame | None = None, budgets: pd.DataFrame | None = None,
                          events: pd.DataFrame | None = None) -> dict:
    invoices = load_invoices() if invoices is None else invoices
    budgets = load_budgets() if budgets is None else budgets
    events = load_events() if events is None else events
    measured = measured_eur(invoices, budgets, events)
    data_based = data_based_effectiveness(invoices, events)
    return {
        "measured": measured,
        "data_based": data_based,
        "base": evaluate(measured, scenario_params("base", data_based)),
        "scenarios": scenarios(measured, data_based),
        "tornado": tornado(measured, data_based),
    }


if __name__ == "__main__":
    case = compute_business_case()
    base = case["base"]
    print(base["levers"].drop(columns=["action", "owner"]).round(2).to_string(index=False))
    print()
    print(base["hard"]["flows"].round(0).to_string(index=False))
    print()
    print(case["scenarios"].to_string(index=False))
    print()
    print(case["tornado"].drop(columns="source").to_string(index=False))
