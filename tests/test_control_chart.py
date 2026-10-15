"""I-MR control chart: limits checked by hand on small series, and the
signal on the real data traced back to the planted processing-time outliers.
"""

import pandas as pd
import pytest

from src import anomalies, kpis
from src import control_chart as cc


@pytest.fixture(scope="module")
def invoices():
    return kpis.load_invoices()


@pytest.fixture(scope="module")
def chart(invoices):
    return cc.imr_chart(cc.weekly_processing_time(invoices))


def weekly(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "week_start": pd.date_range("2026-01-05", periods=len(values), freq="7D"),
        "invoices": 50,
        "mean_days": values,
    })


def test_limits_by_hand():
    limits = cc.imr_limits(pd.Series([10.0, 12.0, 11.0, 13.0]))
    # Moving ranges 2, 1, 2: average 5/3.
    assert limits["centre"] == pytest.approx(11.5)
    assert limits["mr_bar"] == pytest.approx(5 / 3)
    assert limits["ucl"] == pytest.approx(11.5 + 2.66 * 5 / 3)
    assert limits["lcl"] == pytest.approx(11.5 - 2.66 * 5 / 3)
    assert limits["mr_ucl"] == pytest.approx(3.267 * 5 / 3)


def test_lower_limit_never_below_zero():
    assert cc.imr_limits(pd.Series([1.0, 9.0, 1.0, 9.0]))["lcl"] == 0.0


def test_one_extreme_week_does_not_widen_the_limits():
    values = [10.0, 10.5, 9.5, 10.2, 9.8, 10.1, 30.0, 10.0, 9.9, 10.3]
    table, limits = cc.imr_chart(weekly(values))
    assert limits["weeks_set_aside"] == 1
    without = cc.imr_limits(pd.Series([v for v in values if v != 30.0]))
    assert limits["ucl"] == pytest.approx(without["ucl"], abs=0.01)
    assert table["beyond_limits"].tolist() == [v == 30.0 for v in values]


def test_run_rule_needs_eight_in_a_row():
    seven_high = [10.0, 9.0] * 4 + [10.4] * 7 + [9.0, 10.0] * 4
    eight_high = [10.0, 9.0] * 4 + [10.4] * 8 + [9.0, 10.0] * 4
    assert not cc.imr_chart(weekly(seven_high))[0]["run_signal"].any()
    assert cc.imr_chart(weekly(eight_high))[0]["run_signal"].sum() == 8


def test_warmup_covers_the_slow_tail(invoices):
    paid = invoices[~invoices["missing_submitted_date"] & invoices["processing_days"].notna()]
    assert paid["processing_days"].quantile(0.95) <= cc.WARMUP_DAYS


def test_only_full_weeks_after_warmup(invoices):
    table = cc.weekly_processing_time(invoices)
    first_submission = invoices["submitted_date"].min()
    assert (table["week_start"] >= first_submission + pd.Timedelta(days=cc.WARMUP_DAYS)).all()
    assert (table["week_start"] + pd.Timedelta(days=6) <= invoices["extract_date"].max()).all()
    assert (table["week_start"].dt.dayofweek == 0).all()
    assert table["week_start"].diff().dropna().eq(pd.Timedelta(days=7)).all()


def test_signal_week_is_explained_by_detected_outliers(invoices, chart):
    table, _ = chart
    flagged = cc.signal_invoices(invoices, table)
    outliers = set(anomalies.detect_processing_time_outliers(invoices)["invoice_id"])
    assert table["beyond_limits"].sum() >= 1
    assert flagged["invoice_id"].isin(outliers).all()
