"""What-if scenarios: at today's setting each one reproduces the app's current
figures, and each moves in the direction it should.
"""

import pandas as pd
import pytest

from src import anomalies, evaluation, impact, kpis
from src import what_if as wi


@pytest.fixture(scope="module")
def invoices():
    return kpis.load_invoices()


@pytest.fixture(scope="module")
def budgets():
    return kpis.load_budgets()


@pytest.fixture(scope="module")
def vendors():
    return kpis.load_vendors()


# --- Overrun threshold ------------------------------------------------------------

def test_threshold_at_the_constant_reproduces_detector_and_impact(invoices, budgets):
    result = wi.overrun_threshold_scenario(invoices, budgets, anomalies.BUDGET_OVERRUN_THRESHOLD)
    detected = anomalies.detect_all(invoices, budgets)
    assert result["months_flagged"] == (detected["anomaly_type"] == "budget_overrun").sum()
    summary = impact.leakage_summary(invoices, budgets).set_index("driver")
    assert result["spend_to_review_eur"] == pytest.approx(summary.loc["Spend above budget", "impact_eur"], abs=0.01)


def test_higher_threshold_flags_less(invoices, budgets):
    sweep = wi.overrun_threshold_sweep(invoices, budgets)
    assert sweep["months_flagged"].is_monotonic_decreasing
    assert sweep["spend_to_review_eur"].is_monotonic_decreasing


def test_threshold_scores_match_the_scorecard(invoices, budgets):
    ground_truth = evaluation.load_ground_truth()
    scores = evaluation.overrun_threshold_scores(
        invoices, budgets, ground_truth, [anomalies.BUDGET_OVERRUN_THRESHOLD, 1.5]).set_index("threshold")
    card = evaluation.detection_scorecard(anomalies.detect_all(invoices, budgets), ground_truth)
    card = card.set_index("anomaly_type").loc["budget_overrun"]
    assert scores.loc[anomalies.BUDGET_OVERRUN_THRESHOLD, "precision"] == card["precision"]
    assert scores.loc[anomalies.BUDGET_OVERRUN_THRESHOLD, "recall"] == card["recall"]
    assert scores.loc[1.5, "recall"] < card["recall"]


# --- Faster approval --------------------------------------------------------------

def test_no_cut_reproduces_today(invoices):
    result = wi.approval_cut_scenario(invoices, 0)
    assert result["discount_capture_pct"] == kpis.discount_capture_rate(invoices)
    assert result["on_time_pct"] == kpis.on_time_payment_rate(invoices)
    assert result["missed_discount_eur"] == pytest.approx(impact.missed_discounts(invoices)["impact_eur"].sum(), abs=0.01)
    assert result["late_payment_eur"] == pytest.approx(impact.late_payment_cost(invoices)["impact_eur"].sum(), abs=0.01)


def test_faster_approval_only_helps(invoices):
    sweep = wi.approval_cut_sweep(invoices, max_days=7)
    assert sweep["discount_capture_pct"].is_monotonic_increasing
    assert sweep["missed_discount_eur"].is_monotonic_decreasing
    assert sweep["late_payments"].is_monotonic_decreasing
    assert sweep["median_processing_days"].is_monotonic_decreasing


def test_shift_never_moves_approval_before_submission(invoices):
    shifted = wi.shift_approval(invoices, 30)
    both = shifted["approved_date"].notna() & shifted["submitted_date"].notna()
    assert (shifted.loc[both, "approved_date"] >= shifted.loc[both, "submitted_date"]).all()


def test_shift_leaves_breaches_open_and_missing_dates_alone(invoices):
    shifted = wi.shift_approval(invoices, 5)
    untouched = (
        invoices["paid_date"].isna()
        | invoices["approved_date"].isna()
        | invoices["submitted_date"].isna()
        | (invoices["paid_date"] < invoices["approved_date"])
    )
    for column in ["approved_date", "paid_date"]:
        pd.testing.assert_series_equal(shifted.loc[untouched, column], invoices.loc[untouched, column])


def test_shift_by_hand():
    invoices = pd.DataFrame({
        "submitted_date": pd.to_datetime(["2026-01-01", "2026-01-01"]),
        "approved_date": pd.to_datetime(["2026-01-06", "2026-01-03"]),
        "paid_date": pd.to_datetime(["2026-01-09", "2026-01-05"]),
    })
    shifted = wi.shift_approval(invoices, 3)
    # 5-day approval loses 3 days; a 2-day approval can only lose 2.
    assert shifted["approved_date"].dt.day.tolist() == [3, 1]
    assert shifted["paid_date"].dt.day.tolist() == [6, 3]
    assert shifted["processing_days"].tolist() == [5, 2]


# --- Supplier consolidation -----------------------------------------------------------

def test_consolidation_moves_only_non_preferred_tail(invoices, vendors):
    candidates = wi.consolidation_candidates(invoices, vendors)
    preferred = set(vendors.loc[vendors["preferred_vendor"], "vendor_id"])
    assert not set(candidates["vendor_id"]) & preferred
    assert candidates["spend"].is_monotonic_increasing


def test_consolidation_figures(invoices, vendors):
    assert wi.consolidation_scenario(invoices, vendors, 0)["estimated_saving_eur"] == 0
    result = wi.consolidation_scenario(invoices, vendors, 5, saving_pct=10.0)
    candidates = wi.consolidation_candidates(invoices, vendors)
    assert result["spend_moved_eur"] == pytest.approx(candidates["spend"].head(5).sum(), abs=0.01)
    assert result["estimated_saving_eur"] == pytest.approx(result["spend_moved_eur"] * 0.10, abs=0.01)
    assert result["suppliers_after"] == invoices["vendor_id"].nunique() - 5
