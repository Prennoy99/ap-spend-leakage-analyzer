"""Checks the cleaned data against what generate_data.py planted.

The generator labels maverick spend, missed discounts, late payments, approval
breaches and rework loops from its own clean values. The notebook works from
the messy raw files (re-typed payment terms, PO numbers written several ways,
mixed date formats). If its cleaning or date derivation is wrong, these sets
stop matching.
"""

from pathlib import Path

import pandas as pd
import pytest

from src import anomalies, kpis

GROUND_TRUTH_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "anomaly_ground_truth.csv"


@pytest.fixture(scope="module")
def invoices():
    return kpis.load_invoices()


@pytest.fixture(scope="module")
def events():
    return kpis.load_events()


@pytest.fixture(scope="module")
def ground_truth():
    return pd.read_csv(GROUND_TRUTH_PATH)


def planted(ground_truth: pd.DataFrame, anomaly_type: str) -> set:
    return set(ground_truth.loc[ground_truth["anomaly_type"] == anomaly_type, "invoice_id"])


def ids(df: pd.DataFrame) -> set:
    return set(df["invoice_id"])


# --- Extract date and open invoices ------------------------------------------

def test_an_invoice_is_paid_exactly_when_it_has_a_paid_date(invoices):
    assert (invoices["status"].eq("Paid") == invoices["paid_date"].notna()).all()


def test_nothing_happens_after_the_extract_date(invoices, events):
    extract = invoices["extract_date"].iloc[0]
    assert invoices["extract_date"].nunique() == 1
    for column in ["invoice_date", "submitted_date", "approved_date", "paid_date"]:
        assert (invoices[column].dropna() <= extract).all(), column
    assert (events["timestamp"].dt.normalize() <= extract).all()


def test_not_yet_submitted_is_not_counted_as_a_missing_date(invoices):
    received = invoices[invoices["status"] == "Received"]
    assert len(received) > 0
    assert not received["missing_submitted_date"].any()


# --- Payment terms and POs -----------------------------------------------------

def test_maverick_spend_matches_invoices_without_a_po(invoices, ground_truth):
    assert ids(invoices[~invoices["has_po"]]) == planted(ground_truth, "maverick_spend")


def test_po_numbers_are_normalised(invoices):
    assert invoices["po_number"].dropna().str.fullmatch(r"45\d{8}").all()


def test_missed_discounts_match_the_answer_key(invoices, ground_truth):
    missed = invoices[invoices["paid_date"] > invoices["discount_date"]]
    assert ids(missed) == planted(ground_truth, "missed_discount")


def test_late_payments_match_the_answer_key(invoices, ground_truth):
    late = invoices[invoices["paid_date"] > invoices["due_date"]]
    assert ids(late) == planted(ground_truth, "late_payment")


# --- Approval breaches (conformance) -------------------------------------------

def test_paid_before_approval_matches_the_answer_key(invoices, ground_truth):
    breached = invoices[invoices["approved_date"] > invoices["paid_date"]]
    assert ids(breached) == planted(ground_truth, "paid_before_approval")


def test_paid_without_approval_matches_the_answer_key(invoices, ground_truth):
    breached = invoices[invoices["paid_date"].notna() & invoices["approved_date"].isna()]
    assert ids(breached) == planted(ground_truth, "paid_without_approval")


# --- Event log -------------------------------------------------------------------

def test_every_case_starts_with_receiving_the_invoice(events, invoices):
    first = events.sort_values(["invoice_id", "timestamp"]).groupby("invoice_id")["activity"].first()
    assert (first == "Receive invoice").all()
    assert set(first.index) == ids(invoices)


def test_rework_loops_match_the_answer_key(events, ground_truth):
    loops = events[events["activity"] == "Reject invoice"].groupby("invoice_id").size()
    truth = ground_truth[ground_truth["anomaly_type"] == "rework_loop"].set_index("invoice_id")["detail"]
    planted_loops = truth.str.extract(r"^(\d+) loop", expand=False).astype(int)
    assert loops.sort_index().to_dict() == planted_loops.sort_index().to_dict()


def test_event_log_holds_roles_never_people(events):
    assert set(events["resource_role"]) == {"AP clerk", "Budget owner", "Treasury"}


# --- Stuck open invoices -----------------------------------------------------------

def test_open_invoice_waiting_longer_than_the_fence_is_flagged():
    extract = pd.Timestamp("2026-08-31")
    paid = pd.DataFrame({
        "invoice_id": [f"P{i}" for i in range(8)],
        "submitted_date": pd.Timestamp("2026-06-01"),
        "paid_date": pd.Timestamp("2026-06-05"),
        "processing_days": [2, 3, 4, 4, 4, 5, 5, 6],
    })
    still_open = pd.DataFrame({
        "invoice_id": ["STUCK", "YOUNG"],
        "submitted_date": [extract - pd.Timedelta(days=60), extract - pd.Timedelta(days=3)],
        "paid_date": pd.NaT,
        "processing_days": float("nan"),
    })
    invoices = pd.concat([paid, still_open], ignore_index=True).assign(
        missing_submitted_date=False, extract_date=extract
    )
    flagged = anomalies.detect_processing_time_outliers(invoices)
    assert ids(flagged) == {"STUCK"}
    assert flagged.iloc[0]["detail"].startswith("still open after 60d")
