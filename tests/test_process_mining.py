"""Process mining: checked against the planted data (approval breaches, rework
loops, missing submission dates) and against small hand-built logs.
"""

from pathlib import Path

import pandas as pd
import pytest

from src import kpis
from src import process_mining as pm

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


@pytest.fixture(scope="module")
def deviations(events, invoices):
    return pm.conformance(events, invoices)


def planted(ground_truth: pd.DataFrame, anomaly_type: str) -> set:
    return set(ground_truth.loc[ground_truth["anomaly_type"] == anomaly_type, "invoice_id"])


def make_log(cases: dict[str, list[str]]) -> pd.DataFrame:
    """A log with one event per day per case, in the order given."""
    rows = []
    for invoice_id, activities in cases.items():
        for day, activity in enumerate(activities):
            rows.append({
                "invoice_id": invoice_id,
                "activity": activity,
                "timestamp": pd.Timestamp("2026-01-01") + pd.Timedelta(days=day),
            })
    return pd.DataFrame(rows)


def make_invoices(ids: list[str], amount: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame({
        "invoice_id": ids,
        "amount": amount,
        "department": "IT",
        "vendor_id": "V001",
        "vendor_name": "Supplier",
        "approved_date": pd.NaT,
        "paid_date": pd.NaT,
    })


HAPPY = [pm.RECEIVE, pm.SUBMIT, pm.APPROVE, pm.PAY]
ONE_LOOP = [pm.RECEIVE, pm.SUBMIT, pm.REJECT, pm.CORRECT, pm.APPROVE, pm.PAY]


# --- Against the planted data ---------------------------------------------------

def test_paid_before_approval_is_exactly_the_planted_set(deviations, ground_truth):
    found = set(deviations.loc[deviations["category"] == pm.PAID_BEFORE_APPROVAL, "invoice_id"])
    assert found == planted(ground_truth, "paid_before_approval")


def test_paid_without_approval_is_exactly_the_planted_set(deviations, ground_truth):
    found = set(deviations.loc[deviations["category"] == pm.PAID_WITHOUT_APPROVAL, "invoice_id"])
    assert found == planted(ground_truth, "paid_without_approval")


def test_missing_submissions_are_the_paid_invoices_without_a_submitted_date(deviations, invoices):
    # A missing submission date is a data gap, not a control breach; the one
    # invoice that has both counts as a breach (the bigger risk).
    breaches = set(deviations.loc[deviations["category"] != pm.NO_SUBMISSION, "invoice_id"])
    no_date = invoices.loc[invoices["missing_submitted_date"] & invoices["paid_date"].notna(), "invoice_id"]
    expected = set(no_date) - breaches
    assert set(deviations.loc[deviations["category"] == pm.NO_SUBMISSION, "invoice_id"]) == expected
    assert len(set(no_date) & breaches) == 1


def test_every_other_paid_invoice_conforms(events, invoices, deviations):
    summary = pm.conformance_summary(events, invoices)
    assert summary["paid_invoices"] == invoices["paid_date"].notna().sum()
    assert summary["conforming_invoices"] == summary["paid_invoices"] - len(deviations)
    assert summary["by_category"]["invoices"].sum() == len(deviations)
    breach_spend = summary["by_category"].set_index("category").loc[
        [pm.PAID_BEFORE_APPROVAL, pm.PAID_WITHOUT_APPROVAL], "spend"].sum()
    breach_ids = deviations.loc[deviations["category"] != pm.NO_SUBMISSION, "invoice_id"]
    assert breach_spend == pytest.approx(invoices.set_index("invoice_id").loc[breach_ids, "amount"].sum())


def test_rework_path_types_match_the_planted_rework_loops(events, invoices, ground_truth):
    cases = pm.case_table(events, invoices)
    looped = set(cases.loc[cases["rework_loops"] > 0, "invoice_id"])
    assert looped == planted(ground_truth, "rework_loop")


def test_open_invoices_are_the_unpaid_ones(events, invoices):
    cases = pm.case_table(events, invoices).set_index("invoice_id")
    unpaid = set(invoices.loc[invoices["paid_date"].isna(), "invoice_id"])
    assert set(cases.index[cases["path_type"] == pm.OPEN]) == unpaid
    assert cases.loc[list(unpaid), "throughput_days"].isna().all()


def test_variants_cover_every_invoice_once(events, invoices):
    table = pm.variants(events, invoices)
    assert table["invoices"].sum() == len(invoices)
    assert table["path"].is_unique
    assert table["cumulative_pct"].iloc[-1] == 100.0
    assert table["spend"].sum() == pytest.approx(invoices["amount"].sum(), abs=0.05)
    assert table["invoices"].is_monotonic_decreasing


def test_process_map_counts_every_transition(events):
    edges = pm.process_map(events)
    # Each case of n events has n - 1 transitions.
    per_case = events.groupby("invoice_id").size()
    assert edges["transitions"].sum() == (per_case - 1).sum()
    assert (edges.groupby("source")["share_of_source_pct"].sum().round(0) == 100).all()


def test_rework_slows_payment(events, invoices):
    by_loops = pm.throughput_by_rework_loops(events, invoices).set_index("rework_loops")
    assert by_loops["median_days"].is_monotonic_increasing
    assert by_loops["invoices"].sum() == len(
        pm.case_table(events, invoices).query("path_type in [@pm.STRAIGHT_THROUGH, @pm.REWORK]")
    )


def test_path_types_add_up(events, invoices):
    table = pm.throughput_by_path_type(events, invoices)
    assert table["invoices"].sum() == len(invoices)
    assert table["share_pct"].sum() == pytest.approx(100, abs=0.2)


# --- Hand-built logs ------------------------------------------------------------

def test_path_type_precedence():
    assert pm.path_type(tuple(HAPPY)) == pm.STRAIGHT_THROUGH
    assert pm.path_type(tuple(ONE_LOOP)) == pm.REWORK
    assert pm.path_type((pm.RECEIVE, pm.SUBMIT)) == pm.OPEN
    assert pm.path_type((pm.RECEIVE, pm.APPROVE, pm.PAY)) == pm.NO_SUBMISSION
    # A breach outranks a missing submission.
    assert pm.path_type((pm.RECEIVE, pm.PAY, pm.APPROVE)) == pm.BREACH
    assert pm.path_type((pm.RECEIVE, pm.SUBMIT, pm.PAY)) == pm.BREACH


def test_conformance_names_the_deviation():
    log = make_log({
        "A": HAPPY,
        "B": ONE_LOOP,
        "C": [pm.RECEIVE, pm.SUBMIT, pm.PAY, pm.APPROVE],
        "D": [pm.RECEIVE, pm.SUBMIT, pm.PAY],
        "E": [pm.RECEIVE, pm.SUBMIT],
    })
    result = pm.conformance(log, make_invoices(list("ABCDE"))).set_index("invoice_id")
    # A and B follow the approved process (a rework loop is allowed); E is open, so not checked.
    assert list(result.index) == ["C", "D"]
    assert result.loc["C", "category"] == pm.PAID_BEFORE_APPROVAL
    assert result.loc["C", "deviation"] == "Pay invoice out of order"
    assert result.loc["D", "category"] == pm.PAID_WITHOUT_APPROVAL
    assert result.loc["D", "deviation"] == "Approve invoice missing"


def test_conformance_does_not_depend_on_row_order():
    log = make_log({"A": HAPPY, "B": ONE_LOOP, "C": [pm.RECEIVE, pm.SUBMIT, pm.PAY, pm.APPROVE]})
    shuffled = log.sample(frac=1, random_state=0)
    invoices = make_invoices(list("ABC"))
    pd.testing.assert_frame_equal(pm.conformance(shuffled, invoices), pm.conformance(log, invoices))
    pd.testing.assert_frame_equal(pm.process_map(shuffled), pm.process_map(log))


def test_throughput_is_receipt_to_payment():
    log = make_log({"A": HAPPY, "B": ONE_LOOP})
    table = pm.throughput_by_rework_loops(log, make_invoices(["A", "B"])).set_index("rework_loops")
    # One event per day: happy path pays on day 3, one loop on day 5.
    assert table.loc[0, "median_days"] == 3.0
    assert table.loc[1, "median_days"] == 5.0


def test_process_map_waits():
    log = make_log({"A": HAPPY})
    edges = pm.process_map(log).set_index(["source", "target"])
    assert edges.loc[(pm.RECEIVE, pm.SUBMIT), "median_wait_days"] == 1.0
    assert edges["transitions"].sum() == 3


def test_normative_transitions_are_what_conforming_invoices_do(events, invoices, deviations):
    """NORMATIVE_TRANSITIONS (for the map) must match NORMATIVE_PROCESS (for conformance)."""
    cases = pm.case_table(events, invoices)
    conforming = cases[cases["path_type"].isin([pm.STRAIGHT_THROUGH, pm.REWORK])]
    seen = {pair for path in conforming["path"] for pair in zip(path, path[1:])}
    assert seen == pm.NORMATIVE_TRANSITIONS
    edges = pm.process_map(events)
    assert edges.loc[~edges["allowed"], "transitions"].sum() > 0
