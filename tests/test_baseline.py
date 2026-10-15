"""The Measure baseline: Six Sigma formulas against textbook values, the defect
counts against the planted answer key, and the frozen files against a fresh
calculation, so a data change can't silently move the baseline.
"""

from pathlib import Path

import pandas as pd
import pytest

from src import baseline, kpis

GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "anomaly_ground_truth.csv"


@pytest.fixture(scope="module")
def invoices():
    return kpis.load_invoices()


@pytest.fixture(scope="module")
def computed():
    return baseline.compute_baseline()


@pytest.fixture(scope="module")
def ctq(computed):
    return computed["ctq"].set_index("measure")


@pytest.fixture(scope="module")
def ground_truth():
    return pd.read_csv(GROUND_TRUTH_PATH)


def planted_count(ground_truth: pd.DataFrame, *anomaly_types: str) -> int:
    return int(ground_truth["anomaly_type"].isin(anomaly_types).sum())


# --- Formulas -----------------------------------------------------------------

@pytest.mark.parametrize("dpmo, expected_sigma", [
    # The standard sigma table, which includes the 1.5 shift.
    (3.4, 6.0), (233, 5.0), (6_210, 4.0), (66_807, 3.0), (308_538, 2.0),
])
def test_sigma_level_matches_the_standard_table(dpmo, expected_sigma):
    assert baseline.sigma_level(dpmo * 1000, 1_000_000_000) == pytest.approx(expected_sigma, abs=0.01)


def test_sigma_level_is_undefined_without_defects():
    assert baseline.sigma_level(0, 2550) is None


def test_dpmo():
    assert baseline.dpmo(50, 2550) == 19_608


def test_discount_annual_return_for_2_10_net_30():
    # 2/98 earned over 20 days, times 365/20.
    assert baseline.discount_annual_return_pct(2.0, 10, 30) == 37.2


def test_terms_based_dpo_uses_the_discount_date_where_there_is_one():
    invoices = pd.DataFrame({
        "invoice_date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-01"]),
        "paid_date": pd.to_datetime(["2026-01-05", "2026-01-05", None]),
        "due_date": pd.to_datetime(["2026-01-31", "2026-01-31", "2026-01-31"]),
        "discount_date": pd.to_datetime([None, "2026-01-11", None]),
        "amount": [100.0, 300.0, 1000.0],
    })
    # 30 days on 100, 10 days on 300; the open invoice is left out.
    assert baseline.terms_based_dpo(invoices) == pytest.approx((30 * 100 + 10 * 300) / 400, abs=0.05)


def test_rework_without_a_reason_keeps_invoices_rejected_for_another_reason():
    invoices = pd.DataFrame({"invoice_id": ["A", "B", "C", "D"]})
    events = pd.DataFrame({
        "invoice_id": ["A", "B", "B", "C"],
        "activity": ["Reject invoice"] * 4,
        "reject_reason": ["Missing PO", "Missing PO", "Missing goods receipt", "Wrong cost centre"],
    })
    # Only B still has a rejection left: 1 of 4 invoices.
    assert baseline.rework_without(events, invoices, ["Missing PO", "Wrong cost centre"]) == 25.0


# --- Against the answer key -----------------------------------------------------

@pytest.mark.parametrize("measure, anomaly_types", [
    ("Suspected duplicate copies", ["duplicate_payment"]),
    ("Paid before approval or never approved", ["paid_before_approval", "paid_without_approval"]),
    ("Invoices rejected at least once", ["rework_loop"]),
    ("Invoice spend with a purchase order", ["maverick_spend"]),
    ("Discount invoices paid inside the discount window", ["missed_discount"]),
    ("Paid on or before the due date", ["late_payment"]),
])
def test_defects_equal_the_planted_cases(ctq, ground_truth, measure, anomaly_types):
    assert ctq.loc[measure, "defects"] == planted_count(ground_truth, *anomaly_types)


def test_defect_rates_agree_with_the_kpis(ctq, invoices):
    """Where the KPI is itself a share of invoices, defects / opportunities
    must give back the same figure (the complement for 'good' rates).
    """
    on_time = ctq.loc["Paid on or before the due date"]
    assert 100 - on_time["defect_rate_pct"] == pytest.approx(kpis.on_time_payment_rate(invoices), abs=0.05)
    capture = ctq.loc["Discount invoices paid inside the discount window"]
    assert 100 - capture["defect_rate_pct"] == pytest.approx(kpis.discount_capture_rate(invoices), abs=0.05)
    rework = ctq.loc["Invoices rejected at least once"]
    assert rework["defect_rate_pct"] == pytest.approx(rework["baseline"], abs=0.05)


# --- Targets --------------------------------------------------------------------

def test_charter_targets_are_carried_over(ctq):
    assert ctq.loc["Suspected duplicate copies", "target"] == 0
    assert ctq.loc["Median, submission to payment", "target"] == 4
    assert ctq.loc["90th percentile, submission to payment", "target"] == 8
    assert (ctq.loc[ctq["target_source"] == "Charter", "target_direction"] == "≤").all()


def test_every_target_has_a_reason_and_an_owner(ctq):
    assert ctq["target_basis"].str.len().gt(0).all()
    assert ctq["owner"].isin([baseline.AP_MANAGER, baseline.PROCUREMENT, baseline.CONTROLLING]).all()


def test_every_baseline_misses_its_target(ctq):
    """A metric already on target doesn't belong in an improvement project."""
    below = ctq["target_direction"] == "≥"
    assert (ctq.loc[below, "baseline"] < ctq.loc[below, "target"]).all()
    assert (ctq.loc[~below, "baseline"] > ctq.loc[~below, "target"]).all()


def test_dpo_target_does_not_exceed_the_terms_based_dpo(ctq, invoices):
    assert ctq.loc["Invoice to payment, weighted by amount", "target"] <= baseline.terms_based_dpo(invoices)


# --- Frozen files -----------------------------------------------------------------

@pytest.mark.parametrize("key, path", [
    ("ctq", baseline.CTQ_BASELINE_FILE),
    ("leakage", baseline.LEAKAGE_BASELINE_FILE),
])
def test_frozen_baseline_matches_the_data(computed, key, path):
    """If this fails after a data change, decide whether to re-baseline, then
    run `python -m src.baseline --freeze`. Never update the file to make the
    test pass without that decision: Control measures progress against it.
    """
    assert computed[key].to_csv(index=False) == path.read_text(encoding="utf-8")
