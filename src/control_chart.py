"""Individuals and moving-range (I-MR) control chart of weekly processing time.

A control chart separates the normal week-to-week noise of a process (common
cause) from weeks that need a look (special cause). Without one, every bad
week starts a discussion; with one, AP only reacts to signals. In Control the
same limits become the alarm for the improved process.

Each point is one payment week: the mean submit-to-pay days of the invoices
paid that week. Weekly means are charted as individuals, the usual practical
choice when there is one figure per period.

Like kpis.py this reads only data/processed/.
"""

import pandas as pd

# I-MR constants for moving ranges of two points: 3 / d2 with d2 = 1.128 for
# the individuals limits, and D4 for the moving-range limit (Montgomery,
# Introduction to Statistical Quality Control, Appendix VI).
I_CHART_FACTOR = 2.66
MR_CHART_FACTOR = 3.267

# A payment week only counts once it can contain slow invoices too. In the
# first weeks of the extract every payment is fast because nothing was
# submitted long enough before. 95% of invoices are paid within 19 days of
# submission (tested), so the chart starts three weeks into the data.
WARMUP_DAYS = 21

# Western Electric run rule: 8 weeks in a row on one side of the centre line
# is a shift in the process even when no single week is outside the limits.
RUN_LENGTH = 8

WEEK = "W-SUN"  # Monday to Sunday


def weekly_processing_time(invoices: pd.DataFrame) -> pd.DataFrame:
    """Mean submit-to-pay days per full payment week after the warm-up.
    Invoices without a submission date are left out, as in kpis.avg_processing_days.
    """
    paid = invoices[~invoices["missing_submitted_date"] & invoices["processing_days"].notna()]
    first_submission = paid["submitted_date"].min()
    extract_date = invoices["extract_date"].max()
    weeks = paid["paid_date"].dt.to_period(WEEK)
    table = (
        paid.groupby(weeks)["processing_days"]
        .agg(invoices="count", mean_days="mean")
        .reset_index(names="week")
    )
    table["week_start"] = table["week"].dt.start_time
    week_end = table["week"].dt.end_time.dt.normalize()
    complete = (table["week_start"] >= first_submission + pd.Timedelta(days=WARMUP_DAYS)) & (week_end <= extract_date)
    return table.loc[complete, ["week_start", "invoices", "mean_days"]].reset_index(drop=True)


def imr_limits(values: pd.Series) -> dict:
    """Centre line and control limits from the average moving range."""
    centre = values.mean()
    mr_bar = values.diff().abs().mean()
    return {
        "centre": centre,
        "ucl": centre + I_CHART_FACTOR * mr_bar,
        "lcl": max(centre - I_CHART_FACTOR * mr_bar, 0.0),  # days can't be negative
        "mr_bar": mr_bar,
        "mr_ucl": MR_CHART_FACTOR * mr_bar,
    }


def _run_signal(values: pd.Series, centre: float) -> pd.Series:
    """True for every point that is part of a run of RUN_LENGTH or more on one side."""
    side = (values > centre).astype(int) - (values < centre).astype(int)
    run_id = (side != side.shift()).cumsum()
    run_length = side.groupby(run_id).transform("size")
    return (side != 0) & (run_length >= RUN_LENGTH)


def imr_chart(weekly: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """The chart table and its limits.

    Limits follow the usual Phase I practice: compute them, set aside weeks
    outside them (special causes, to be explained), and compute them once more
    from the rest, so one extreme week doesn't widen the limits for all others.
    Signals are then judged against the final limits.
    """
    values = weekly["mean_days"]
    first = imr_limits(values)
    in_control = values.between(first["lcl"], first["ucl"])
    limits = imr_limits(values[in_control])
    limits["weeks_set_aside"] = int((~in_control).sum())

    chart = weekly.copy()
    chart["moving_range"] = values.diff().abs()
    chart["beyond_limits"] = ~values.between(limits["lcl"], limits["ucl"])
    chart["mr_beyond_limit"] = chart["moving_range"] > limits["mr_ucl"]
    chart["run_signal"] = _run_signal(values, limits["centre"])
    chart["signal"] = chart["beyond_limits"] | chart["run_signal"]
    for column in ["mean_days", "moving_range"]:
        chart[column] = chart[column].round(2)
    return chart, {key: round(float(value), 2) if isinstance(value, float) else value for key, value in limits.items()}


def signal_invoices(invoices: pd.DataFrame, chart: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """The slowest invoices paid in each week beyond the limits: where to start
    looking for the special cause.
    """
    weeks = chart.loc[chart["beyond_limits"], "week_start"]
    paid = invoices[~invoices["missing_submitted_date"] & invoices["processing_days"].notna()]
    paid = paid.assign(week_start=paid["paid_date"].dt.to_period(WEEK).dt.start_time)
    flagged = paid[paid["week_start"].isin(weeks)]
    return (
        flagged.sort_values(["week_start", "processing_days"], ascending=[True, False])
        .groupby("week_start")
        .head(n)[["week_start", "invoice_id", "vendor_name", "department", "submitted_date",
                  "paid_date", "processing_days"]]
        .reset_index(drop=True)
    )
