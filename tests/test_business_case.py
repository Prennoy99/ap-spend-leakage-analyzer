"""Business case: NPV, ROI and payback against a hand-worked example (US-02),
and the inputs against the measured figures they come from.
"""

import pandas as pd
import pytest

from src import business_case as bc
from src import impact, kpis, root_cause


@pytest.fixture(scope="module")
def invoices():
    return kpis.load_invoices()


@pytest.fixture(scope="module")
def events():
    return kpis.load_events()


@pytest.fixture(scope="module")
def case(invoices, events):
    return bc.compute_business_case(invoices, kpis.load_budgets(), events)


# --- Hand-worked example ----------------------------------------------------------

HAND_PARAMS = {"ramp_up_year_1": 0.5, "duplicate_recovery_rate": 0.5, "cost_of_capital_pct": 10.0}


def hand_levers() -> pd.DataFrame:
    return pd.DataFrame([
        {"benefit_type": bc.HARD, "annual_benefit_eur": 10_000.0, "one_off_cost_eur": 12_000.0,
         "annual_run_cost_eur": 1_000.0},
        {"benefit_type": bc.ESTIMATED, "annual_benefit_eur": 4_000.0, "one_off_cost_eur": 0.0,
         "annual_run_cost_eur": 0.0},
    ])


def test_cash_flows_by_hand():
    # Year 0: -12,000. Year 1: 10,000 x 0.5 + 2,000 x 0.5 recovery - 1,000 run = 5,000.
    # Years 2 and 3: 10,000 - 1,000 = 9,000.
    flows = bc.cash_flows(hand_levers(), HAND_PARAMS, paid_duplicates_eur=2_000.0)
    assert flows["net_eur"].tolist() == [-12_000.0, 5_000.0, 9_000.0, 9_000.0]
    # NPV at 10%: -12,000 + 5,000/1.1 + 9,000/1.21 + 9,000/1.331
    assert bc.npv(flows) == pytest.approx(6_745.30, abs=0.01)
    # ROI: (23,000 - 12,000) / 12,000
    assert bc.roi_pct(flows) == pytest.approx(91.67, abs=0.01)
    # Cumulative: -12,000, -7,000, +2,000: 12 months + 7,000 / 9,000 of year 2.
    assert bc.payback_months(flows) == pytest.approx(21.33, abs=0.01)


def test_estimated_savings_only_in_the_second_figure():
    hard = bc.cash_flows(hand_levers(), HAND_PARAMS, 2_000.0)
    with_estimated = bc.cash_flows(hand_levers(), HAND_PARAMS, 2_000.0, include_estimated=True)
    assert (with_estimated["benefit_eur"] - hard["benefit_eur"]).tolist() == [0.0, 2_000.0, 4_000.0, 4_000.0]


def test_no_payback_within_the_horizon():
    levers = pd.DataFrame([{"benefit_type": bc.HARD, "annual_benefit_eur": 1_000.0,
                            "one_off_cost_eur": 50_000.0, "annual_run_cost_eur": 0.0}])
    assert bc.payback_months(bc.cash_flows(levers, HAND_PARAMS, 0.0)) is None


# --- Inputs come from the measured figures -------------------------------------

def test_levers_address_the_measured_figures(case, invoices, events):
    pareto = root_cause.leakage_pareto(invoices, events).set_index("cause")["impact_eur"]
    levers = case["base"]["levers"]
    hard = levers[levers["benefit_type"] == bc.HARD]
    for row in hard.itertuples():
        assert row.eur_addressed == pytest.approx(pareto[row.addresses])
    # Each hard cause is addressed once, so the benefit can never exceed the hard leakage.
    assert hard["addresses"].is_unique
    assert hard["eur_addressed"].sum() == pytest.approx(pareto.sum())
    assert case["base"]["annual_hard_benefit_eur"] < pareto.sum()


def test_control_levers_have_no_benefit(case):
    levers = case["base"]["levers"]
    control = levers[levers["benefit_type"] == bc.NO_BENEFIT]
    assert len(control) >= 1
    assert (control["annual_benefit_eur"] == 0).all()
    assert (control["one_off_cost_eur"] > 0).all()


def test_data_based_effectiveness(case, invoices):
    data = case["data_based"]
    # 46 of 50 duplicates reused a PO; the share is by €.
    assert data["duplicate_prevention"] == pytest.approx(57_731.17 / 60_264.78, abs=1e-6)
    # Wrong cost centre (154) and Missing PO (92) of 446 rejections.
    assert data["entry_validation"] == pytest.approx(246 / 446, abs=1e-6)
    current = kpis.po_compliance(invoices)
    assert data["po_compliance"] == pytest.approx((90.0 - current) / (100.0 - current))


def test_costs_are_days_times_rates(case):
    params = bc.scenario_params("base", case["data_based"])
    expected = sum(l["cost_it_days"] * bc.IT_DAY_RATE_EUR + l["cost_business_days"] * bc.INTERNAL_DAY_RATE_EUR
                   for l in bc.LEVERS) * params["cost_multiplier"]
    assert case["base"]["investment_eur"] == pytest.approx(expected)


def test_recovery_uses_the_paid_duplicates(case, invoices):
    flows = case["base"]["hard"]["flows"]
    paid = impact.duplicate_payments(invoices).query("copy_paid")["impact_eur"].sum()
    assert flows.loc[flows["year"] == 1, "recovery_eur"].iloc[0] == pytest.approx(paid * impact.DUPLICATE_RECOVERY_RATE)
    assert (flows.loc[flows["year"] != 1, "recovery_eur"] == 0).all()


# --- Scenarios and sensitivity -----------------------------------------------------

def test_scenarios_are_ordered(case):
    table = case["scenarios"].set_index("scenario")
    for column in ["npv_hard_eur", "npv_hard_without_recovery_eur", "npv_with_estimated_eur", "roi_hard_pct"]:
        assert table.loc["Worst", column] < table.loc["Base", column] < table.loc["Best", column]
    assert table.loc["Worst", "payback_hard_months"] > table.loc["Best", "payback_hard_months"]
    # Hard benefits never include the estimated savings.
    assert (table["npv_hard_eur"] < table["npv_with_estimated_eur"]).all()


def test_base_scenario_uses_the_measure_assumptions(case):
    params = case["base"]["params"]
    assert params["cost_of_capital_pct"] == impact.COST_OF_CAPITAL_PCT
    assert params["duplicate_recovery_rate"] == impact.DUPLICATE_RECOVERY_RATE
    assert params["po_premium_pct"] == impact.PO_PREMIUM_PCT


def test_tornado_brackets_the_base_and_is_sorted(case):
    table = case["tornado"]
    assert table["swing_eur"].is_monotonic_decreasing
    low = table[["npv_worst_eur", "npv_best_eur"]].min(axis=1)
    high = table[["npv_worst_eur", "npv_best_eur"]].max(axis=1)
    assert ((low <= table["npv_base_eur"] + 0.01) & (table["npv_base_eur"] <= high + 0.01)).all()
    assert set(table["assumption"]) == {a["label"] for a in bc.ASSUMPTIONS.values()}


def test_estimated_only_assumptions_do_not_move_the_hard_npv(case):
    swings = case["tornado"].set_index("assumption")["swing_eur"]
    for name in ["po_compliance", "po_premium_pct"]:
        assert swings[bc.ASSUMPTIONS[name]["label"]] == 0


def test_headline_quotes_the_computed_figures(case):
    text = bc.headline(case)
    assert f"€{case['base']['investment_eur'] / 1000:,.0f}k once" in text
    assert f"{case['base']['hard']['payback_months']:.0f} months" in text
    assert "before any estimated savings" in text


def test_break_even_cost_multiplier_gives_zero_npv(case):
    multiplier = bc.break_even_cost_multiplier(case["measured"], case["base"]["params"])
    params = {**case["base"]["params"], "cost_multiplier": multiplier}
    assert bc.evaluate(case["measured"], params)["hard"]["npv_eur"] == pytest.approx(0, abs=0.01)
    assert case["base"]["break_even_cost_multiplier"] == round(multiplier, 2)
