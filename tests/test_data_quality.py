"""Data-quality view (US-08): the checks against the planted answer key, the
coverage counts against what each KPI really uses, and the cleaning log
against the raw extract it was made from.
"""

import re
from pathlib import Path

import pandas as pd
import pytest

from src import data_quality as dq
from src import kpis

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


@pytest.fixture(scope="module")
def invoices():
    return kpis.load_invoices()


@pytest.fixture(scope="module")
def budgets():
    return kpis.load_budgets()


@pytest.fixture(scope="module")
def vendors():
    return kpis.load_vendors()


@pytest.fixture(scope="module")
def summary(invoices, budgets, vendors):
    return dq.issue_summary(invoices, budgets, vendors).set_index("check")


@pytest.fixture(scope="module")
def coverage(invoices, budgets):
    return dq.kpi_coverage(invoices, budgets).set_index("figure")


@pytest.fixture(scope="module")
def cleaning_log():
    return dq.load_cleaning_log()


# --- Open issues ------------------------------------------------------------------

def test_approval_checks_find_the_planted_breaches(summary):
    ground_truth = pd.read_csv(RAW_DIR / "anomaly_ground_truth.csv")
    planted = ground_truth["anomaly_type"].value_counts()
    assert summary.loc["Paid without an approval date", "invoices"] == planted["paid_without_approval"]
    assert summary.loc["Paid before the approval date", "invoices"] == planted["paid_before_approval"]


def test_missing_submission_and_pre_budget_invoices(summary, invoices):
    assert summary.loc["No submission date", "invoices"] == invoices["missing_submitted_date"].sum() == 24
    assert summary.loc["Invoice dated before the first budget month", "invoices"] == 7


def test_invoice_list_matches_the_summary(invoices, budgets, vendors, summary):
    issues = dq.invoice_issues(invoices, budgets, vendors)
    per_check = issues["check"].value_counts()
    failed = summary[summary["invoices"] > 0]["invoices"]
    assert per_check.sort_index().to_dict() == failed.sort_index().to_dict()


def test_headline_counts_an_invoice_once_even_if_it_fails_two_checks(invoices, budgets, vendors, coverage):
    issues = dq.invoice_issues(invoices, budgets, vendors)
    assert issues["invoice_id"].duplicated().any(), "the data has an invoice failing two checks"
    summary = dq.issue_summary(invoices, budgets, vendors)
    text = dq.headline(issues, summary, coverage.reset_index())
    assert f"issues in {issues['invoice_id'].nunique()} invoices" in text


# --- Coverage per figure -------------------------------------------------------------

def test_every_invoice_is_either_included_or_excluded(coverage):
    assert (coverage["included"] + coverage["excluded"] == coverage["invoices"]).all()


def test_included_counts_equal_what_each_kpi_uses(coverage, invoices, budgets):
    stages = kpis.stage_durations(invoices).set_index("stage")["invoices_measured"]
    paid = invoices["paid_date"].notna()
    assert coverage.loc["Processing time (submission to payment)", "included"] == stages["Submit → pay"]
    assert coverage.loc["Submit → approve", "included"] == stages["Submit → approve"]
    assert coverage.loc["Approve → pay", "included"] == stages["Approve → pay"]
    assert coverage.loc["Days payable outstanding, on-time payment rate", "included"] == paid.sum()
    assert coverage.loc["Early-payment discount capture (invoices with discount terms)", "included"] == (paid & invoices["discount_date"].notna()).sum()
    in_budget_months = invoices["invoice_date"].dt.strftime("%Y-%m").isin(budgets["month"])
    assert coverage.loc["Budget vs actual, budget-overrun check", "included"] == in_budget_months.sum()


def test_an_invoice_with_two_reasons_is_excluded_once():
    invoices = pd.DataFrame({
        "invoice_date": pd.to_datetime(["2026-01-05"] * 3),
        "submitted_date": pd.to_datetime([None, "2026-01-06", "2026-01-06"]),
        "approved_date": pd.to_datetime([None, "2026-01-08", "2026-01-08"]),
        "paid_date": pd.to_datetime([None, None, "2026-01-10"]),
        # The first invoice is open and has no submission date: excluded once, as "not paid yet".
        "missing_submitted_date": [True, False, False],
        "discount_date": pd.to_datetime([None, None, None]),
    })
    budgets = pd.DataFrame({"month": ["2026-01"]})
    row = dq.kpi_coverage(invoices, budgets).set_index("figure").loc["Processing time (submission to payment)"]
    assert (row["included"], row["excluded"]) == (1, 2)
    assert row["excluded_because"] == "2 not paid yet"


# --- Repaired in cleaning ---------------------------------------------------------------

def test_every_repair_has_a_fix_at_source_and_an_owner(cleaning_log):
    repairs = dq.cleaning_repairs(cleaning_log)
    assert repairs["fix_at_source"].str.len().gt(0).all()
    assert repairs["owner"].notna().all()


@pytest.fixture(scope="module")
def raw_as_typed():
    """The raw extract exactly as typed: by default read_csv would turn 'N/A' into an empty value."""
    return pd.read_csv(RAW_DIR / "invoices.csv", dtype=str, keep_default_na=False)


def test_cleaning_log_counts_match_the_raw_extract(cleaning_log, raw_as_typed):
    log = cleaning_log.set_index(["field", "issue"])["rows"]
    iso = raw_as_typed["invoice_date"].str.match(re.compile(r"^\d{4}-\d{2}-\d{2}$"))
    assert log[("invoice_date", "Date not in ISO format (YYYY-MM-DD)")] == (~iso).sum()
    typed_none = raw_as_typed["po_number"].str.strip().str.lower().isin(["-", "none", "n/a"])
    assert log[("po_number", "Missing PO typed as text")] == typed_none.sum()


def test_no_po_spellings_plus_empty_fields_equal_the_maverick_invoices(cleaning_log, invoices, raw_as_typed):
    typed = cleaning_log.set_index("issue").loc["Missing PO typed as text", "rows"]
    empty = raw_as_typed["po_number"].str.strip().eq("").sum()
    assert typed + empty == (~invoices["has_po"]).sum()


def test_a_repair_without_a_known_fix_is_refused():
    log = pd.DataFrame({"table": ["invoices"], "field": ["new_field"]})
    with pytest.raises(KeyError):
        dq.cleaning_repairs(log)
