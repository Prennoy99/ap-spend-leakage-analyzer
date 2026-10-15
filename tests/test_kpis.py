from pathlib import Path

import pandas as pd
import pytest

from src import anomalies, kpis

GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "anomaly_ground_truth.csv"


@pytest.fixture(scope="module")
def invoices():
    return kpis.load_invoices()


@pytest.fixture(scope="module")
def budgets():
    return kpis.load_budgets()


@pytest.fixture(scope="module")
def ground_truth():
    return pd.read_csv(GROUND_TRUTH_PATH)


@pytest.fixture(scope="module")
def detected(invoices, budgets):
    return anomalies.detect_all(invoices, budgets)


# --- KPI sanity checks ------------------------------------------------

def test_total_spend_matches_sum_of_amounts(invoices):
    assert kpis.total_spend(invoices) == pytest.approx(invoices["amount"].sum(), abs=0.01)


def test_spend_by_department_covers_every_invoice(invoices):
    by_dept = kpis.spend_by_department(invoices)
    assert by_dept["invoice_count"].sum() == len(invoices)
    assert by_dept["total_spend"].sum() == pytest.approx(kpis.total_spend(invoices), abs=0.5)


def test_avg_processing_days_excludes_missing_submitted_date(invoices):
    result = kpis.avg_processing_days(invoices)
    valid = invoices[~invoices["missing_submitted_date"]]
    assert result == pytest.approx(valid["processing_days"].mean(), abs=0.1)


def test_budget_vs_actual_covers_every_budget_row(invoices, budgets):
    result = kpis.budget_vs_actual(invoices, budgets)
    assert len(result) == len(budgets)


# --- Anomaly detection vs. known planted cases -------------------------
# Ground truth is only used here, in tests, to check what anomalies.py
# found against what generate_data.py actually planted. anomalies.py never
# reads this file itself.

def test_duplicate_payment_detection_matches_ground_truth_exactly(detected, ground_truth):
    dup_truth = ground_truth[ground_truth["anomaly_type"] == "duplicate_payment"]
    planted_dup_ids = set(dup_truth["invoice_id"])
    planted_original_ids = set(dup_truth["detail"].str.split().str[-1])
    expected_pair_members = planted_dup_ids | planted_original_ids

    detected_ids = set(detected.loc[detected["anomaly_type"] == "duplicate_payment", "invoice_id"])
    assert detected_ids == expected_pair_members


def test_po_reuse_finds_only_planted_duplicates_and_misses_only_those_without_a_po(invoices, ground_truth):
    planted_copies = set(ground_truth.loc[ground_truth["anomaly_type"] == "duplicate_payment", "invoice_id"])
    found = set(anomalies.find_po_reuse(invoices)["second_invoice_id"])
    assert found <= planted_copies  # precision 100%
    missed = planted_copies - found
    assert not invoices.loc[invoices["invoice_id"].isin(missed), "has_po"].any()
    # Every PO pair is also an amount-and-date pair, with the same copy.
    pairs = anomalies.find_duplicate_pairs(invoices)
    assert found <= set(pairs["second_invoice_id"])


def test_po_reuse_takes_the_later_invoice_as_the_copy():
    invoices = pd.DataFrame({
        "invoice_id": ["INV2", "INV1", "INV3"],
        "po_number": ["PO1", "PO1", "PO2"],
        "has_po": True,
        "invoice_date": pd.to_datetime(["2026-01-05", "2026-01-02", "2026-01-03"]),
        "vendor_id": "V001",
        "amount": 100.0,
    })
    reuse = anomalies.find_po_reuse(invoices)
    assert reuse[["first_invoice_id", "second_invoice_id"]].values.tolist() == [["INV1", "INV2"]]


def test_processing_time_outlier_detection_has_no_false_negatives(detected, ground_truth):
    planted = set(ground_truth.loc[ground_truth["anomaly_type"] == "processing_time_outlier", "invoice_id"])
    detected_ids = set(detected.loc[detected["anomaly_type"] == "processing_time_outlier", "invoice_id"])
    assert planted <= detected_ids


def test_processing_time_outlier_detection_precision_is_reasonable(detected, ground_truth):
    planted = set(ground_truth.loc[ground_truth["anomaly_type"] == "processing_time_outlier", "invoice_id"])
    detected_ids = set(detected.loc[detected["anomaly_type"] == "processing_time_outlier", "invoice_id"])
    false_positives = detected_ids - planted
    assert len(false_positives) <= 10


def test_budget_overrun_detection_has_no_false_negatives(detected, ground_truth):
    overrun_truth = ground_truth[ground_truth["anomaly_type"] == "budget_overrun"]
    planted = set(zip(overrun_truth["department"], overrun_truth["category"], overrun_truth["month"]))

    overrun_detected = detected[detected["anomaly_type"] == "budget_overrun"]
    detected_keys = set(zip(overrun_detected["department"], overrun_detected["category"], overrun_detected["month"]))
    assert planted <= detected_keys


def test_budget_overrun_detection_precision_is_reasonable(detected, ground_truth):
    overrun_truth = ground_truth[ground_truth["anomaly_type"] == "budget_overrun"]
    planted = set(zip(overrun_truth["department"], overrun_truth["category"], overrun_truth["month"]))

    overrun_detected = detected[detected["anomaly_type"] == "budget_overrun"]
    detected_keys = set(zip(overrun_detected["department"], overrun_detected["category"], overrun_detected["month"]))
    false_positives = detected_keys - planted
    assert len(false_positives) <= 15


# --- Payment timing, discounts, POs, suppliers, stages (Measure) -----------

def planted(ground_truth: pd.DataFrame, anomaly_type: str) -> set:
    return set(ground_truth.loc[ground_truth["anomaly_type"] == anomaly_type, "invoice_id"])


def paid_invoice(invoice_id: str, amount: float, invoice_date: str, paid_date: str | None,
                 net_days: int = 30) -> dict:
    invoice_date = pd.Timestamp(invoice_date)
    return {
        "invoice_id": invoice_id,
        "amount": amount,
        "invoice_date": invoice_date,
        "paid_date": pd.Timestamp(paid_date) if paid_date else pd.NaT,
        "due_date": invoice_date + pd.Timedelta(days=net_days),
        "net_days": net_days,
    }


def test_dpo_is_weighted_by_amount_and_ignores_open_invoices():
    invoices = pd.DataFrame([
        paid_invoice("SMALL", 1_000.0, "2026-03-01", "2026-03-11", net_days=14),   # 10 days
        paid_invoice("LARGE", 3_000.0, "2026-03-01", "2026-03-31", net_days=30),   # 30 days
        paid_invoice("OPEN", 50_000.0, "2026-03-01", None, net_days=45),
    ])
    assert kpis.days_payable_outstanding(invoices) == pytest.approx((1_000 * 10 + 3_000 * 30) / 4_000)
    assert kpis.agreed_payment_days(invoices) == pytest.approx((1_000 * 14 + 3_000 * 30) / 4_000)


def test_on_time_rate_matches_the_planted_late_payments(invoices, ground_truth):
    paid = invoices[invoices["paid_date"].notna()]
    late = len(planted(ground_truth, "late_payment"))
    assert kpis.on_time_payment_rate(invoices) == pytest.approx((1 - late / len(paid)) * 100, abs=0.05)


def test_discount_capture_matches_the_planted_missed_discounts(invoices, ground_truth):
    eligible = invoices[invoices["paid_date"].notna() & invoices["discount_date"].notna()]
    missed = len(planted(ground_truth, "missed_discount"))
    assert kpis.discount_capture_rate(invoices) == pytest.approx((1 - missed / len(eligible)) * 100, abs=0.05)


def test_payment_timing_by_vendor_covers_every_paid_invoice(invoices):
    timing = kpis.payment_timing(invoices, by=["vendor_id", "vendor_name"])
    assert timing["paid_invoices"].sum() == invoices["paid_date"].notna().sum()


def test_discount_deadlines_lists_only_open_invoices_still_in_their_window():
    extract = pd.Timestamp("2026-08-31")
    invoices = pd.DataFrame({
        "invoice_id": ["LATER", "SOONER", "WINDOW_CLOSED", "ALREADY_PAID", "NO_TERMS"],
        "vendor_id": "V001",
        "vendor_name": "Supplier",
        "status": ["Received", "Pending approval", "Approved", "Paid", "Received"],
        "amount": [1_000.0, 500.0, 800.0, 900.0, 700.0],
        "discount_pct": [2.0, 2.0, 2.0, 2.0, 0.0],
        "discount_date": pd.to_datetime(["2026-09-08", "2026-09-02", "2026-08-30", "2026-09-05", None]),
        "paid_date": pd.to_datetime([None, None, None, "2026-08-29", None]),
        "extract_date": extract,
    })
    deadlines = kpis.discount_deadlines(invoices)
    assert deadlines["invoice_id"].tolist() == ["SOONER", "LATER"]
    assert deadlines["days_left"].tolist() == [2, 8]
    assert deadlines["discount_eur"].tolist() == [10.0, 20.0]


def test_po_compliance_matches_the_planted_maverick_spend(invoices, ground_truth):
    maverick = invoices[invoices["invoice_id"].isin(planted(ground_truth, "maverick_spend"))]
    expected = (1 - maverick["amount"].sum() / invoices["amount"].sum()) * 100
    assert kpis.po_compliance(invoices) == pytest.approx(expected, abs=0.05)

    by_department = kpis.po_compliance(invoices, by="department")
    assert by_department["no_po_spend"].sum() == pytest.approx(maverick["amount"].sum(), abs=0.5)


def test_no_po_spend_split_by_preferred_adds_up(invoices, ground_truth):
    split = kpis.no_po_spend_by_preferred(invoices, kpis.load_vendors())
    assert set(split["preferred_vendor"]) == {True, False}
    assert split["invoice_count"].sum() == len(planted(ground_truth, "maverick_spend"))


def test_vendor_pareto_counts_the_suppliers_that_make_up_80_percent():
    invoices = pd.DataFrame({
        "invoice_id": ["A1", "B1", "C1", "D1"],
        "vendor_id": ["A", "B", "C", "D"],
        "vendor_name": ["A", "B", "C", "D"],
        "amount": [50.0, 30.0, 10.0, 10.0],
    })
    pareto = kpis.vendor_pareto(invoices)
    assert pareto["cumulative_pct"].tolist() == [50.0, 80.0, 90.0, 100.0]
    assert kpis.vendors_for_spend_share(pareto, 80.0) == 2
    assert kpis.vendors_for_spend_share(pareto, 81.0) == 3


def test_vendor_pareto_covers_all_spend(invoices):
    pareto = kpis.vendor_pareto(invoices)
    assert pareto["cumulative_pct"].iloc[-1] == pytest.approx(100.0)
    assert pareto["cumulative_pct"].is_monotonic_increasing


def test_stage_durations_count_the_planted_approval_breaches(invoices, ground_truth):
    stages = kpis.stage_durations(invoices).set_index("stage")
    approve_to_pay = stages.loc["Approve → pay"]
    assert approve_to_pay["excluded_missing_start"] == len(planted(ground_truth, "paid_without_approval"))
    assert approve_to_pay["excluded_out_of_order"] == len(planted(ground_truth, "paid_before_approval"))
    assert stages.loc["Submit → pay", "excluded_missing_start"] == \
        invoices.loc[invoices["paid_date"].notna(), "missing_submitted_date"].sum()


def test_stage_durations_exclude_and_count_bad_timestamps():
    invoices = pd.DataFrame({
        "submitted_date": pd.to_datetime(["2026-03-01", "2026-03-01", None, "2026-03-01"]),
        "approved_date": pd.to_datetime(["2026-03-05", None, "2026-03-04", "2026-03-10"]),
        "paid_date": pd.to_datetime(["2026-03-08", "2026-03-09", "2026-03-06", "2026-03-07"]),
    })
    stages = kpis.stage_durations(invoices).set_index("stage")
    approve_to_pay = stages.loc["Approve → pay"]
    assert approve_to_pay["invoices_measured"] == 2           # 3 days and 2 days
    assert approve_to_pay["median_days"] == 2.5
    assert approve_to_pay["excluded_missing_start"] == 1      # paid without approval
    assert approve_to_pay["excluded_out_of_order"] == 1       # paid before approval
    assert stages.loc["Submit → approve", "excluded_missing_start"] == 1


def test_repeat_overruns_finds_the_longest_run_across_a_year_end():
    overruns = pd.DataFrame({
        "department": ["IT"] * 4 + ["HR"],
        "category": ["Software"] * 4 + ["Travel"],
        "month": ["2025-11", "2025-12", "2026-01", "2026-04", "2026-03"],
    })
    result = kpis.repeat_overruns(overruns).set_index("department")
    assert result.loc["IT", "months_over"] == 4
    assert result.loc["IT", "longest_run"] == 3
    assert result.loc["HR", "longest_run"] == 1
    assert result.index.tolist() == ["IT", "HR"]


def test_repeat_overruns_covers_every_flagged_overrun(invoices, budgets, detected):
    overruns = detected[detected["anomaly_type"] == "budget_overrun"]
    assert kpis.repeat_overruns(overruns)["months_over"].sum() == len(overruns)


# --- Rework -------------------------------------------------------------------

def test_rework_rate_matches_the_planted_rework_loops(invoices, ground_truth):
    events = kpis.load_events()
    planted_loops = len(planted(ground_truth, "rework_loop"))
    assert kpis.rework_rate(invoices, events) == pytest.approx(planted_loops / len(invoices) * 100, abs=0.05)


def test_reject_reasons_count_every_rejection_and_rank_by_frequency():
    events = pd.DataFrame({
        "invoice_id": ["A", "A", "B", "C", "C"],
        "activity": ["Reject invoice", "Reject invoice", "Reject invoice", "Reject invoice", "Approve invoice"],
        "reject_reason": ["Missing PO", "Missing PO", "Wrong cost centre", "Missing PO", None],
    })
    result = kpis.reject_reasons(events).reset_index(drop=True)
    assert list(result["reject_reason"]) == ["Missing PO", "Wrong cost centre"]
    # A was rejected twice for the same reason: two rejections, one invoice.
    assert list(result["rejections"]) == [3, 1]
    assert list(result["invoices"]) == [2, 1]
