"""The SQL layer (sql/*.sql run by src/sql_kpis.py) must give the same answer
as the pandas KPIs the app uses. A KPI that differs between the dashboard and
the warehouse query is worse than having only one of them.
"""

import numpy as np
import pandas as pd
import pytest

from src import anomalies, kpis, process_mining, sql_kpis


@pytest.fixture(scope="module")
def con():
    return sql_kpis.connect()


@pytest.fixture(scope="module")
def invoices():
    return kpis.load_invoices()


@pytest.fixture(scope="module")
def budgets():
    return kpis.load_budgets()


@pytest.fixture(scope="module")
def vendors():
    return kpis.load_vendors()


# Decimals each figure is rounded to, in both the SQL and the pandas version.
# Listed rather than inferred from the data: a total that happens to be whole
# euros must still be checked to the cent. A new float column fails with a
# KeyError until it is added here.
DECIMALS = {
    # EUR
    "total_spend": 2, "paid_amount": 2, "no_po_spend": 2, "budget_amount": 2, "actual_amount": 2,
    "variance": 2, "amount": 2, "discount_eur": 2,
    # %
    "variance_pct": 2, "cumulative_pct": 2, "on_time_payment_pct": 1, "on_time_pct": 1,
    "discount_capture_pct": 1, "po_compliance_pct": 1, "share_pct": 1,
    # days
    "avg_processing_days": 1, "dpo_days": 1, "agreed_payment_days": 1, "avg_days_vs_due": 1,
    "median_days": 1, "p90_days": 1, "rework_pct": 1,
}


def assert_close(sql_values, pandas_values, places: int):
    """Equal to within one unit of the last rounded digit. SQL ROUND rounds a
    half away from zero (6.645 -> 6.65, commercial rounding); numpy rounds it
    to the nearest even digit (6.64). Both are right; they differ only when the
    unrounded value sits exactly on a half, and then by one unit.
    """
    np.testing.assert_allclose(sql_values, pandas_values, rtol=0, atol=10.0 ** -places + 1e-9)


def assert_same(sql_result: pd.DataFrame, pandas_result: pd.DataFrame, sort_by: list[str] | None = None):
    """Same columns, rows and order; IDs, counts and dates exactly equal, and
    rounded figures equal to within one unit of their last digit. Where
    `sort_by` is given, the result is ranked by a rounded figure that can tie
    (two departments at 9.6 days, several months at -100% of budget); pandas
    leaves the order of tied rows undefined, so both are sorted by their keys
    first and the caller checks the SQL ranking on its own.
    """
    if sort_by:
        sql_result = sql_result.sort_values(sort_by)
        pandas_result = pandas_result.sort_values(sort_by)
    sql_result, pandas_result = sql_result.reset_index(drop=True), pandas_result.reset_index(drop=True)
    assert list(sql_result.columns) == list(pandas_result.columns)

    rounded = [c for c in pandas_result.columns if pd.api.types.is_float_dtype(pandas_result[c])]
    for column in rounded:
        assert_close(sql_result[column], pandas_result[column], DECIMALS[column])
    # dtypes differ harmlessly (Int64 vs int64, timestamp ns vs us); values must not.
    pd.testing.assert_frame_equal(
        sql_result.drop(columns=rounded), pandas_result.drop(columns=rounded), check_dtype=False,
    )


# --- Scalar KPIs --------------------------------------------------------------

SCALAR_KPIS = {
    "total_spend": kpis.total_spend,
    "avg_processing_days": kpis.avg_processing_days,
    "days_payable_outstanding": kpis.days_payable_outstanding,
    "agreed_payment_days": kpis.agreed_payment_days,
    "on_time_payment_rate": kpis.on_time_payment_rate,
    "discount_capture_rate": kpis.discount_capture_rate,
    "po_compliance": kpis.po_compliance,
}


@pytest.mark.parametrize("name", SCALAR_KPIS)
def test_scalar_kpi_matches_pandas(con, invoices, name):
    result = sql_kpis.run_query(name, con)
    assert result.shape == (1, 1)
    assert_close(result.iloc[0, 0], SCALAR_KPIS[name](invoices), DECIMALS[result.columns[0]])


# --- Table KPIs ---------------------------------------------------------------

def test_spend_by_department(con, invoices):
    assert_same(sql_kpis.run_query("spend_by_department", con), kpis.spend_by_department(invoices))


def test_spend_by_category(con, invoices):
    assert_same(sql_kpis.run_query("spend_by_category", con), kpis.spend_by_category(invoices))


@pytest.mark.parametrize("top_n", [10, 3])
def test_spend_by_vendor(con, invoices, top_n):
    assert_same(sql_kpis.run_query("spend_by_vendor", con, top_n=top_n), kpis.spend_by_vendor(invoices, top_n))


def test_spend_by_month(con, invoices):
    assert_same(sql_kpis.run_query("spend_by_month", con), kpis.spend_by_month(invoices))


def test_avg_processing_days_by_department(con, invoices):
    sql_result = sql_kpis.run_query("avg_processing_days_by_department", con)
    assert sql_result["avg_processing_days"].is_monotonic_decreasing
    assert_same(sql_result, kpis.avg_processing_days(invoices, by="department"), sort_by=["department"])


def test_budget_vs_actual(con, invoices, budgets):
    sql_result = sql_kpis.run_query("budget_vs_actual", con)
    assert sql_result["variance_pct"].is_monotonic_decreasing
    assert_same(sql_result, kpis.budget_vs_actual(invoices, budgets), sort_by=["department", "category", "month"])


def test_payment_timing_by_vendor(con, invoices):
    assert_same(sql_kpis.run_query("payment_timing_by_vendor", con),
                kpis.payment_timing(invoices, by=["vendor_id", "vendor_name"]))


def test_payment_timing_by_month(con, invoices):
    assert_same(sql_kpis.run_query("payment_timing_by_month", con), kpis.payment_timing(invoices, by="month"))


def test_discount_deadlines(con, invoices):
    assert_same(sql_kpis.run_query("discount_deadlines", con), kpis.discount_deadlines(invoices))


def test_po_compliance_by_department(con, invoices):
    sql_result = sql_kpis.run_query("po_compliance_by_department", con)
    assert sql_result["po_compliance_pct"].is_monotonic_increasing
    assert_same(sql_result, kpis.po_compliance(invoices, by="department"), sort_by=["department"])


def test_po_compliance_by_vendor(con, invoices):
    sql_result = sql_kpis.run_query("po_compliance_by_vendor", con)
    assert sql_result["po_compliance_pct"].is_monotonic_increasing
    assert_same(sql_result, kpis.po_compliance(invoices, by=["vendor_id", "vendor_name"]), sort_by=["vendor_id"])


def test_no_po_spend_by_preferred(con, invoices, vendors):
    assert_same(sql_kpis.run_query("no_po_spend_by_preferred", con), kpis.no_po_spend_by_preferred(invoices, vendors))


def test_vendor_pareto(con, invoices):
    assert_same(sql_kpis.run_query("vendor_pareto", con), kpis.vendor_pareto(invoices))


def test_stage_durations(con, invoices):
    assert_same(sql_kpis.run_query("stage_durations", con), kpis.stage_durations(invoices))


def test_repeat_overruns(con, invoices, budgets):
    overruns = anomalies.detect_budget_overruns(invoices, budgets)
    assert_same(sql_kpis.run_query("repeat_overruns", con), kpis.repeat_overruns(overruns))


def test_rework_rate(con, invoices):
    result = sql_kpis.run_query("rework_rate", con)
    assert_close(result.iloc[0, 0], kpis.rework_rate(invoices, kpis.load_events()), DECIMALS["rework_pct"])


def test_reject_reasons(con):
    assert_same(sql_kpis.run_query("reject_reasons", con), kpis.reject_reasons(kpis.load_events()))


def test_duplicate_pairs(con, invoices):
    assert_same(sql_kpis.run_query("duplicate_pairs", con), anomalies.find_duplicate_pairs(invoices))


def test_process_variants(con, invoices):
    columns = ["variant", "path", "steps", "invoices", "share_pct", "cumulative_pct"]
    pandas_result = process_mining.variants(kpis.load_events(), invoices)[columns]
    assert_same(sql_kpis.run_query("process_variants", con), pandas_result)


def test_approval_breaches(con, invoices):
    deviations = process_mining.conformance(kpis.load_events(), invoices)
    breaches = deviations[deviations["category"] != process_mining.NO_SUBMISSION]
    pandas_result = breaches[["invoice_id", "category", "amount"]].sort_values(["category", "invoice_id"])
    assert_same(sql_kpis.run_query("approval_breaches", con), pandas_result)


# --- The layer as a whole -----------------------------------------------------

def test_every_query_has_a_parity_test():
    """A new sql/*.sql file without a pandas comparison here fails this test."""
    tested = set(SCALAR_KPIS) | {
        "spend_by_department", "spend_by_category", "spend_by_vendor", "spend_by_month",
        "avg_processing_days_by_department", "budget_vs_actual", "payment_timing_by_vendor",
        "payment_timing_by_month", "discount_deadlines", "po_compliance_by_department",
        "po_compliance_by_vendor", "no_po_spend_by_preferred", "vendor_pareto", "stage_durations",
        "repeat_overruns", "duplicate_pairs", "rework_rate", "reject_reasons",
        "process_variants", "approval_breaches",
    }
    assert set(sql_kpis.query_names()) == tested


def test_thresholds_come_from_the_python_constants():
    assert sql_kpis.DEFAULT_PARAMS["duplicate_pairs"]["window_days"] == anomalies.DUPLICATE_DATE_WINDOW_DAYS
    assert sql_kpis.DEFAULT_PARAMS["repeat_overruns"]["threshold"] == anomalies.BUDGET_OVERRUN_THRESHOLD


def test_changing_a_threshold_changes_the_sql_result(con):
    """The parameter really reaches the query (it isn't hard-coded in the SQL)."""
    same_day_only = sql_kpis.run_query("duplicate_pairs", con, window_days=0)
    default = sql_kpis.run_query("duplicate_pairs", con)
    assert 0 < len(same_day_only) < len(default)
