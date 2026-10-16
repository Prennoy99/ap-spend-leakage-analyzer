"""Control report: monthly figures use the baseline definitions, the frozen
limits match the data, and the statuses and signals fire when they should.
"""

import pandas as pd
import pytest

from src import baseline, control, kpis


@pytest.fixture(scope="module")
def data():
    return kpis.load_invoices(), kpis.load_budgets(), kpis.load_events()


@pytest.fixture(scope="module")
def frozen_ctq():
    return baseline.load_frozen_ctq()


def test_full_year_reproduces_the_frozen_baseline(data, frozen_ctq):
    year = control.monthly_values(*data, "all")
    for row in frozen_ctq.itertuples():
        value = year[(row.ctq, row.measure)][0]
        assert round(float(value), 1) == pytest.approx(row.baseline, abs=0.05), row.measure


def test_frozen_control_limits_match_the_data(data):
    """Like the frozen baseline: a data change must not move the limits silently.
    Re-freeze only after deciding to (python -m src.control --freeze)."""
    computed = control.control_limits(*data).to_csv(index=False, lineterminator="\n")
    assert computed == control.CONTROL_LIMITS_FILE.read_text(encoding="utf-8")


def test_monthly_counts_add_up_to_the_year(data):
    invoices, budgets, events = data
    key = ("Duplicate payments", "Suspected duplicate copies")
    invoice_months = sorted(invoices["invoice_date"].dt.to_period("M").astype(str).unique())
    total = sum(control.monthly_values(invoices, budgets, events, m)[key][0] for m in invoice_months)
    assert total == control.monthly_values(invoices, budgets, events, "all")[key][0]


def test_p_limits_by_hand():
    low, high = control.p_limits(0.2, 100)
    # 3 x sqrt(0.2 x 0.8 / 100) = 0.12
    assert low == pytest.approx(0.08) and high == pytest.approx(0.32)
    assert control.p_limits(0.01, 10)[0] == 0.0


def test_every_ctq_has_a_reaction_plan(frozen_ctq):
    assert set(frozen_ctq["ctq"]) <= set(control.REACTION_PLAN)


def test_outlier_week_shows_as_a_processing_time_signal(data):
    report = control.control_report(*data, "2026-04").set_index("measure")
    assert report.loc["Median, submission to payment", "signal"] == control.WORSE
    assert report.loc["Median, submission to payment", "reaction"]


def test_reaction_only_when_off_target_or_worse(data):
    report = control.control_report(*data, "2026-08")
    needs = (report["status"] == control.OFF_TARGET) | (report["signal"] == control.WORSE)
    assert (report.loc[needs, "reaction"] != "").all()
    assert (report.loc[~needs, "reaction"] == "").all()


def test_an_improved_month_is_on_target_and_better_than_baseline(data):
    """Simulate the fixes for August: every discount taken on the discount date."""
    invoices, budgets, events = data
    improved = invoices.copy()
    august = improved["paid_date"].dt.to_period("M").astype(str) == "2026-08"
    discount = august & improved["discount_date"].notna()
    improved.loc[discount, "paid_date"] = improved.loc[discount, "discount_date"]
    report = control.control_report(improved, budgets, events, "2026-08").set_index("ctq")
    row = report.loc["Early-payment discount capture"]
    assert row["this_month"] == 100.0
    assert row["status"] == control.ON_TARGET and row["signal"] == control.BETTER
    assert row["reaction"] == ""


def test_trend_shows_three_months(data):
    report = control.control_report(*data, "2026-08")
    assert (report["trend"].str.count("→") == 2).all()
    first = control.control_report(*data, control.months(data[0])[0])
    assert (first["trend"].str.count("→") == 0).all()


def test_headline(data):
    report = control.control_report(*data, "2026-04")
    text = control.headline(report, "2026-04")
    on_target = int((report["status"] == control.ON_TARGET).sum())
    assert text.startswith(f"2026-04: {on_target} of 11 CTQ measures on target")
    assert "worse than baseline" in text and "baseline year" in text
    assert "baseline year" not in control.headline(report, "2027-05", go_live="2027-04")
