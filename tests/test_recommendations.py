"""Recommendations: ranking rules on hand-made figures, and consistency with src/impact.py."""

import re

import pandas as pd
import pytest

from src import impact, kpis, recommendations


@pytest.fixture(scope="module")
def impact_result():
    return impact.compute_all_impact(kpis.load_invoices(), kpis.load_budgets())


def make_summary(overrides: dict | None = None) -> pd.DataFrame:
    """A leakage summary with every driver at €1,000 unless overridden."""
    tiers = {
        "Duplicate payments": impact.HARD_LEAKAGE,
        "Missed early-payment discounts": impact.HARD_LEAKAGE,
        "Late-payment interest and fees": impact.HARD_LEAKAGE,
        "Spend above budget": impact.SPEND_AT_RISK,
        "Purchase-order premium": impact.SPEND_AT_RISK,
        "Working capital given away": impact.SPEND_AT_RISK,
    }
    overrides = overrides or {}
    return pd.DataFrame([
        {"driver": driver, "tier": tier, "impact_eur": overrides.get(driver, 1_000.0)}
        for driver, tier in tiers.items()
    ])


def test_every_driver_is_addressed_by_exactly_one_recommendation(impact_result):
    addressed = [d for rec in recommendations.RECOMMENDATIONS for d in rec["drivers"]]
    assert sorted(addressed) == sorted(impact_result["summary"]["driver"])


def test_hard_leakage_outranks_a_larger_estimate_or_spend_to_review():
    summary = make_summary({"Duplicate payments": 10.0, "Missed early-payment discounts": 0.0,
                            "Late-payment interest and fees": 0.0, "Working capital given away": 0.0,
                            "Purchase-order premium": 50_000.0, "Spend above budget": 900_000.0})
    ranked = recommendations.rank_recommendations(summary)
    assert ranked["title"].tolist() == [
        "Stop duplicate payments before they go out",
        "No PO, no pay",
        "Show approvers their remaining budget",
        "Pay to terms, not on approval",   # addresses €0 here
    ]


def test_spend_above_budget_is_never_counted_as_a_saving():
    ranked = recommendations.rank_recommendations(make_summary({"Spend above budget": 5_000.0}))
    budget = ranked.set_index("title").loc["Show approvers their remaining budget"]
    assert budget[recommendations.REVIEW] == 5_000.0
    assert budget[recommendations.HARD] == 0.0
    assert budget[recommendations.ESTIMATED] == 0.0


def test_recommendation_euros_add_up_to_the_impact_figures(impact_result):
    ranked = recommendations.rank_recommendations(impact_result["summary"])
    assert ranked[recommendations.HARD].sum() == pytest.approx(impact_result["hard_leakage_eur"], abs=0.01)
    at_risk = ranked[recommendations.ESTIMATED].sum() + ranked[recommendations.REVIEW].sum()
    assert at_risk == pytest.approx(impact_result["spend_at_risk_eur"], abs=0.01)


def test_every_recommendation_has_an_owner_and_an_effort():
    for rec in recommendations.RECOMMENDATIONS:
        assert rec["owner"]
        assert rec["effort"] in recommendations.EFFORT_ORDER


def test_headline_quotes_only_computed_figures(impact_result):
    ranked = recommendations.rank_recommendations(impact_result["summary"])
    text = recommendations.headline(impact_result, ranked)
    hard_k = f"€{impact_result['hard_leakage_eur'] / 1000:,.1f}k"
    recovery_k = f"€{impact_result['expected_duplicate_recovery_eur'] / 1000:,.1f}k"
    assert hard_k in text
    assert recovery_k in text
    assert f"{impact_result['hard_leakage_pct_of_spend']:.1f}%" in text
    assert re.search(r"Duplicate payments are \d+% of that", text)


# --- Impact/effort matrix (task 5.4) ------------------------------------------------

@pytest.fixture(scope="module")
def case():
    from src import business_case
    return business_case.compute_business_case()


@pytest.fixture(scope="module")
def matrix(case):
    return recommendations.impact_effort_matrix(case["base"]["levers"])


def test_effort_labels_agree_with_the_business_case_costs(matrix):
    costs = matrix.set_index("fix")["one_off_cost_eur"]
    for rec in recommendations.RECOMMENDATIONS:
        assert rec["effort"] == recommendations.effort_band(costs[rec["lever"]]), rec["title"]


def test_matrix_keeps_every_euro_of_the_business_case(matrix, case):
    levers = case["base"]["levers"]
    assert matrix["hard_benefit_eur"].sum() == pytest.approx(case["base"]["annual_hard_benefit_eur"], abs=0.05)
    assert matrix["estimated_saving_eur"].sum() == pytest.approx(case["base"]["annual_estimated_saving_eur"], abs=0.05)
    programme = levers.loc[levers["lever"] == "Programme management and training", "one_off_cost_eur"].sum()
    assert matrix["one_off_cost_eur"].sum() == pytest.approx(case["base"]["investment_eur"] - programme)
    assert matrix["fix"].is_unique


def test_quadrant_rule_by_hand():
    q = recommendations.quadrant
    assert q(20_000, 5_000) == recommendations.QUICK_WIN
    assert q(20_000, 15_000) == recommendations.MAJOR_PROJECT
    assert q(2_000, 5_000) == recommendations.FILL_IN
    assert q(2_000, 15_000) == recommendations.QUESTIONABLE
    # On the line counts as high impact and low effort.
    assert q(recommendations.IMPACT_THRESHOLD_EUR, recommendations.EFFORT_THRESHOLD_EUR) == recommendations.QUICK_WIN


def test_duplicate_block_is_the_first_quick_win(matrix):
    first = matrix.iloc[0]
    assert first["fix"] == "Block duplicates at invoice entry"
    assert first["quadrant"] == recommendations.QUICK_WIN and first["wave"] == 1


def test_roadmap_adds_up(matrix):
    plan = recommendations.roadmap(matrix)
    assert plan["one_off_cost_eur"].sum() == pytest.approx(matrix["one_off_cost_eur"].sum())
    assert plan["hard_benefit_eur"].sum() == pytest.approx(matrix["hard_benefit_eur"].sum())
    assert plan["wave"].is_monotonic_increasing
