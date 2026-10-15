"""Root cause of hard leakage: every euro attributed once, and the rules
checked on hand-built invoices.
"""

import pandas as pd
import pytest

from src import impact, kpis
from src import root_cause as rc


@pytest.fixture(scope="module")
def invoices():
    return kpis.load_invoices()


@pytest.fixture(scope="module")
def events():
    return kpis.load_events()


@pytest.fixture(scope="module")
def summary(invoices):
    return impact.leakage_summary(invoices, kpis.load_budgets()).set_index("driver")


def test_pareto_adds_up_to_hard_leakage(invoices, events, summary):
    pareto = rc.leakage_pareto(invoices, events)
    hard = impact.tier_totals(summary.reset_index())[impact.HARD_LEAKAGE]
    assert pareto["impact_eur"].sum() == pytest.approx(hard, abs=0.05)
    assert pareto["cumulative_pct"].iloc[-1] == 100.0
    assert pareto["impact_eur"].is_monotonic_decreasing


def test_each_driver_is_attributed_in_full(invoices, events, summary):
    by_driver = rc.leakage_by_invoice(invoices, events).groupby("driver").agg(
        impact_eur=("impact_eur", "sum"), cases=("invoice_id", "count"))
    for driver, row in by_driver.iterrows():
        assert row["impact_eur"] == pytest.approx(summary.loc[driver, "impact_eur"], abs=0.01)
        assert row["cases"] == summary.loc[driver, "cases"]


def test_all_duplicates_go_to_the_entry_check(invoices, events):
    detail = rc.leakage_by_invoice(invoices, events)
    duplicates = detail[detail["driver"] == "Duplicate payments"]
    assert (duplicates["cause"] == rc.NO_DUPLICATE_CHECK).all()
    assert set(detail.loc[detail["cause"] == rc.NO_DUPLICATE_CHECK, "driver"]) == {"Duplicate payments"}


def test_every_cause_has_a_step_and_hypothesis(invoices, events):
    pareto = rc.leakage_pareto(invoices, events)
    assert set(pareto["cause"]) <= set(rc.CAUSES)
    assert pareto[["process_step", "hypothesis"]].notna().all().all()


def make(invoice_id: str, approved: str | None, paid: str, deadline: str = "2026-01-10") -> dict:
    return {
        "invoice_id": invoice_id,
        "approved_date": pd.Timestamp(approved) if approved else pd.NaT,
        "paid_date": pd.Timestamp(paid),
        "discount_date": pd.Timestamp(deadline),
    }


def test_deadline_cause_rules():
    late = pd.DataFrame([
        make("in_time", "2026-01-05", "2026-01-15"),
        make("day_before_deadline", "2026-01-09", "2026-01-12"),
        make("on_deadline_day", "2026-01-10", "2026-01-12"),
        make("slow", "2026-01-12", "2026-01-14"),
        make("reworked", "2026-01-12", "2026-01-14"),
        make("paid_before_approval", "2026-01-20", "2026-01-15"),
    ])
    cause = rc.deadline_cause(late, "discount_date", reworked={"reworked"}).set_axis(late["invoice_id"])
    assert cause["in_time"] == rc.PAYMENT_RUN_IGNORES_TERMS
    # One day is enough for the payment step; the deadline day itself is not.
    assert cause["day_before_deadline"] == rc.PAYMENT_RUN_IGNORES_TERMS
    assert cause["on_deadline_day"] == rc.SLOW_APPROVAL
    assert cause["slow"] == rc.SLOW_APPROVAL
    assert cause["reworked"] == rc.REWORK_DELAYS_APPROVAL
    # The payment didn't wait for the approval, so approval wasn't what made it late.
    assert cause["paid_before_approval"] == rc.PAYMENT_RUN_IGNORES_TERMS


def test_payment_lead_time_is_the_fastest_the_payment_step_has_paid(invoices):
    paid = invoices[invoices["paid_date"].notna() & (invoices["paid_date"] >= invoices["approved_date"])]
    assert (paid["paid_date"] - paid["approved_date"]).dt.days.min() == rc.PAYMENT_LEAD_DAYS


def test_headline_quotes_the_computed_figures(invoices, events):
    from src import process_mining as pm
    pareto = rc.leakage_pareto(invoices, events)
    text = rc.headline(pareto, pm.throughput_by_path_type(events, invoices),
                       pm.throughput_by_rework_loops(events, invoices))
    assert f"{pareto['cumulative_pct'].iloc[1]:.0f}% of hard leakage" in text
    assert rc.NO_DUPLICATE_CHECK.lower() in text
