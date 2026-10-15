"""€ impact per driver: checked against the planted data where the generator
knows the answer, and against hand-worked examples for the formulas.
"""

from pathlib import Path

import pandas as pd
import pytest

from src import anomalies, impact, kpis

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


def planted(ground_truth: pd.DataFrame, anomaly_type: str) -> set:
    return set(ground_truth.loc[ground_truth["anomaly_type"] == anomaly_type, "invoice_id"])


def make_invoice(invoice_id: str, amount: float, invoice_date: str, paid_date: str | None,
                 net_days: int = 30, discount_days: int | None = None, discount_pct: float = 0.0) -> dict:
    invoice_date = pd.Timestamp(invoice_date)
    return {
        "invoice_id": invoice_id,
        "amount": amount,
        "invoice_date": invoice_date,
        "paid_date": pd.Timestamp(paid_date) if paid_date else pd.NaT,
        "due_date": invoice_date + pd.Timedelta(days=net_days),
        "discount_date": invoice_date + pd.Timedelta(days=discount_days) if discount_days else pd.NaT,
        "discount_pct": discount_pct,
    }


# --- Against the planted data ---------------------------------------------------

def test_duplicate_copies_are_exactly_the_planted_duplicates(invoices, ground_truth):
    duplicates = impact.duplicate_payments(invoices)
    assert set(duplicates["second_invoice_id"]) == planted(ground_truth, "duplicate_payment")


def test_duplicate_exposure_is_the_amount_of_each_planted_copy(invoices, ground_truth):
    copies = invoices[invoices["invoice_id"].isin(planted(ground_truth, "duplicate_payment"))]
    duplicates = impact.duplicate_payments(invoices)
    assert duplicates["impact_eur"].sum() == pytest.approx(copies["amount"].sum(), abs=0.01)


def test_expected_recovery_applies_the_rate_to_paid_copies_only():
    duplicates = pd.DataFrame({"impact_eur": [1000.0, 500.0], "copy_paid": [True, False]})
    assert impact.expected_duplicate_recovery(duplicates) == pytest.approx(1000.0 * impact.DUPLICATE_RECOVERY_RATE)


def test_missed_discounts_match_the_answer_key(invoices, ground_truth):
    missed = impact.missed_discounts(invoices)
    assert set(missed["invoice_id"]) == planted(ground_truth, "missed_discount")
    assert missed["impact_eur"].sum() == pytest.approx((missed["amount"] * missed["discount_pct"] / 100).sum())


def test_late_payments_match_the_answer_key(invoices, ground_truth):
    late = impact.late_payment_cost(invoices)
    assert set(late["invoice_id"]) == planted(ground_truth, "late_payment")


def test_spend_above_budget_covers_exactly_the_flagged_overruns(invoices, budgets):
    over = impact.spend_above_budget(invoices, budgets)
    flagged = anomalies.detect_budget_overruns(invoices, budgets)
    assert set(zip(over["department"], over["category"], over["month"])) == \
        set(zip(flagged["department"], flagged["category"], flagged["month"]))
    assert (over["impact_eur"] > 0).all()


def test_po_premium_applies_to_the_planted_maverick_spend(invoices, ground_truth):
    no_po = impact.po_premium(invoices)
    assert set(no_po["invoice_id"]) == planted(ground_truth, "maverick_spend")
    assert no_po["impact_eur"].sum() == pytest.approx(no_po["amount"].sum() * impact.PO_PREMIUM_PCT / 100)


def test_open_invoices_never_count_as_missed_late_or_early(invoices):
    open_ids = set(invoices.loc[invoices["paid_date"].isna(), "invoice_id"])
    assert open_ids
    for detail in [impact.missed_discounts(invoices), impact.late_payment_cost(invoices),
                   impact.early_payment_cost(invoices)]:
        assert not open_ids & set(detail["invoice_id"])


# --- Formulas, worked by hand --------------------------------------------------------

def test_late_payment_cost_uses_the_base_rate_in_force_when_default_starts():
    invoices = pd.DataFrame([
        # Due 2026-03-31, paid 30 days late; base rate 1.27% -> 10.27% p.a.
        make_invoice("SPRING", 10_000.0, "2026-03-01", "2026-04-30"),
        # Due 2026-06-30, default starts 1 July when the rate rose to 1.52% -> 10.52% p.a.
        make_invoice("SUMMER", 10_000.0, "2026-05-31", "2026-07-10"),
        make_invoice("ON_TIME", 10_000.0, "2026-05-01", "2026-05-31"),
    ])
    late = impact.late_payment_cost(invoices).set_index("invoice_id")
    assert set(late.index) == {"SPRING", "SUMMER"}
    assert late.at["SPRING", "impact_eur"] == pytest.approx(10_000 * 0.1027 * 30 / 365 + 40)
    assert late.at["SUMMER", "impact_eur"] == pytest.approx(10_000 * 0.1052 * 10 / 365 + 40)


def test_early_payment_is_measured_to_the_discount_date_when_the_discount_was_taken():
    invoices = pd.DataFrame([
        make_invoice("NET30_DAY10", 36_500.0, "2026-03-01", "2026-03-11"),               # 20 days early
        make_invoice("DISCOUNT_DAY4", 36_500.0, "2026-03-01", "2026-03-05",
                     discount_days=10, discount_pct=2.0),                                # 6 days before discount date
        make_invoice("DISCOUNT_MISSED_DAY20", 36_500.0, "2026-03-01", "2026-03-21",
                     discount_days=10, discount_pct=2.0),                                # 10 days before due date
        make_invoice("LATE", 36_500.0, "2026-03-01", "2026-04-15"),
        make_invoice("OPEN", 36_500.0, "2026-03-01", None),
    ])
    early = impact.early_payment_cost(invoices).set_index("invoice_id")
    assert early["days_early"].to_dict() == {"NET30_DAY10": 20, "DISCOUNT_DAY4": 6, "DISCOUNT_MISSED_DAY20": 10}
    # 36,500 at 8% is €8 per day.
    assert early.at["NET30_DAY10", "impact_eur"] == pytest.approx(20 * 36_500 * 0.08 / 365)


def test_missed_discount_is_the_discount_on_invoices_paid_after_the_window():
    invoices = pd.DataFrame([
        make_invoice("TAKEN", 1_000.0, "2026-03-01", "2026-03-11", discount_days=10, discount_pct=2.0),
        make_invoice("MISSED", 1_000.0, "2026-03-01", "2026-03-12", discount_days=10, discount_pct=2.0),
        make_invoice("NO_TERMS", 1_000.0, "2026-03-01", "2026-03-25"),
    ])
    missed = impact.missed_discounts(invoices)
    assert missed["invoice_id"].tolist() == ["MISSED"]
    assert missed["impact_eur"].sum() == pytest.approx(20.0)


# --- Summary -------------------------------------------------------------------------

def test_summary_keeps_the_two_tiers_apart(invoices, budgets):
    summary = impact.leakage_summary(invoices, budgets)
    by_tier = summary.groupby("tier")["driver"].apply(set).to_dict()
    assert by_tier == {
        impact.HARD_LEAKAGE: {"Duplicate payments", "Missed early-payment discounts",
                              "Late-payment interest and fees"},
        impact.SPEND_AT_RISK: {"Spend above budget", "Purchase-order premium", "Working capital given away"},
    }


def test_compute_all_impact_totals_add_up(invoices, budgets):
    result = impact.compute_all_impact(invoices, budgets)
    summary = result["summary"]
    hard = summary.loc[summary["tier"] == impact.HARD_LEAKAGE, "impact_eur"].sum()
    assert result["hard_leakage_eur"] == pytest.approx(hard, abs=0.01)
    assert result["hard_leakage_pct_of_spend"] == pytest.approx(hard / invoices["amount"].sum() * 100, abs=0.01)
    assert 0 < result["expected_duplicate_recovery_eur"] <= result["hard_leakage_eur"]
