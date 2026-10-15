"""Streamlit dashboard: KPI overview, anomaly review, a grounded AI chat, and a
"How it works" tab that shows the pipeline, the guardrail, and live detection
accuracy against the synthetic data's answer key.

Chart design follows a validated categorical/sequential/diverging palette
(fixed hue order, colorblind-checked) rather than default chart colors.
Colors are defined once below and reused everywhere so the whole dashboard
reads as one system.
"""

import time

import altair as alt
import pandas as pd
import streamlit as st

from src.anomalies import (
    BUDGET_OVERRUN_THRESHOLD,
    DUPLICATE_DATE_WINDOW_DAYS,
    PROCESSING_TIME_IQR_MULTIPLIER,
    detect_all,
)
from src.answers import BRIEFING_QUESTION, SUGGESTED_QUESTIONS, answer
from src.business_case import (
    ASSUMPTIONS,
    INTERNAL_DAY_RATE_EUR,
    IT_DAY_RATE_EUR,
    compute_business_case,
    headline as business_case_headline,
)
from src.control_chart import RUN_LENGTH, WARMUP_DAYS, imr_chart, signal_invoices, weekly_processing_time
from src.data_quality import (
    cleaning_repairs,
    headline as data_quality_headline,
    invoice_issues,
    issue_summary,
    kpi_coverage,
    load_cleaning_log,
)
from src.evaluation import detection_scorecard, load_ground_truth
from src.impact import (
    DUPLICATE_RECOVERY_RATE,
    HARD_LEAKAGE,
    SPEND_AT_RISK,
    assumptions,
    compute_all_impact,
    duplicate_payments,
)
from src.insights import GEMINI_MODELS
from src.kpis import (
    agreed_payment_days,
    avg_processing_days,
    budget_variance_extremes,
    days_payable_outstanding,
    load_budgets,
    load_events,
    load_invoices,
    load_vendors,
    reject_reasons,
    spend_by_category,
    spend_by_department,
    spend_by_month,
    total_spend,
)
from src.process_mining import (
    activity_counts,
    conformance,
    conformance_summary,
    process_map,
    throughput_by_path_type,
    throughput_by_rework_loops,
    variants,
)
from src.recommendations import ESTIMATED, HARD, REVIEW, headline, rank_recommendations
from src.root_cause import headline as process_headline, leakage_by_cause_and_driver, leakage_pareto
from src.retrieval import enrich_anomalies_with_dims, retrieve

st.set_page_config(page_title="AP Spend Leakage Analyzer", page_icon="📊", layout="wide")

# --- Design tokens (validated palette) -----------------------------------

SERIES_1 = "#2a78d6"       # blue — single-hue bars/area (magnitude, one series)
DIVERGE_UNDER = "#2a78d6"  # blue — under budget
DIVERGE_OVER = "#e34948"   # red — over budget
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
TEXT_SECONDARY = "#52514e"

ANOMALY_LABELS = {
    "duplicate_payment": "Duplicate Payment",
    "processing_time_outlier": "Processing Delay",
    "budget_overrun": "Budget Overrun",
}
ANOMALY_COLORS = {
    "duplicate_payment": "#2a78d6",        # categorical slot 1
    "processing_time_outlier": "#eb6834",  # categorical slot 2
    "budget_overrun": "#1baf7a",           # categorical slot 3
}
ANOMALY_RULES = {
    "duplicate_payment": f"Same vendor and same amount, paid within {DUPLICATE_DATE_WINDOW_DAYS} days of each other.",
    "processing_time_outlier": (
        f"Submit-to-pay time beyond the extreme-outlier fence (Q3 + {PROCESSING_TIME_IQR_MULTIPLIER:g} × IQR), "
        "or still unpaid that long after submission at the extract date."
    ),
    "budget_overrun": (
        f"A department's monthly spend in a category exceeds {BUDGET_OVERRUN_THRESHOLD:.0%} of its budget."
    ),
}

st.markdown(
    """
    <style>
    .block-container, [data-testid="stMainBlockContainer"] { padding-top: 2.5rem; }
    .pill {
        display: inline-block;
        padding: 4px 12px;
        margin: 0 8px 6px 0;
        border-radius: 999px;
        background: rgba(42, 120, 214, 0.10);
        color: #184f95;
        font-size: 12.5px;
        font-weight: 600;
    }
    .step-num {
        display: inline-block;
        width: 24px;
        height: 24px;
        line-height: 24px;
        text-align: center;
        border-radius: 50%;
        background: #2a78d6;
        color: #fff;
        font-size: 13px;
        font-weight: 700;
        margin-right: 8px;
    }
    .step-title { font-weight: 700; font-size: 15px; }
    .step-body { color: #52514e; font-size: 13.5px; margin-top: 6px; }
    .anomaly-card { border-left: 4px solid; padding: 2px 0 2px 12px; }
    .anomaly-count { font-size: 30px; font-weight: 700; line-height: 1.2; }
    .anomaly-rule { color: #52514e; font-size: 13px; }
    div[data-testid="stMetricLabel"] { font-size: 13px; }
    .headline { font-size: 21px; font-weight: 600; line-height: 1.45; margin: 4px 0 2px 0; }
    .rec-rank { color: #52514e; font-size: 12.5px; font-weight: 700; letter-spacing: 0.04em; }
    .rec-euro { font-size: 24px; font-weight: 700; line-height: 1.3; margin-top: 2px; }
    .rec-meta { color: #52514e; font-size: 13px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- Charts ---------------------------------------------------------------

def style_chart(chart: alt.Chart) -> alt.Chart:
    return (
        chart.configure_view(strokeWidth=0)
        .configure_axis(
            gridColor=GRID,
            domainColor=AXIS,
            tickColor=AXIS,
            labelColor=TEXT_SECONDARY,
            titleColor=TEXT_SECONDARY,
            labelFontSize=11,
            titleFontSize=12,
        )
        .configure_legend(labelColor=TEXT_SECONDARY, titleColor=TEXT_SECONDARY)
    )


def hbar_chart(df: pd.DataFrame, category_field: str) -> alt.Chart:
    # Horizontal bars so long labels ("Software & IT Services") stay readable.
    chart = (
        alt.Chart(df)
        .mark_bar(color=SERIES_1, cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=20)
        .encode(
            y=alt.Y(f"{category_field}:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
            x=alt.X("total_spend:Q", title="Spend (EUR)", axis=alt.Axis(format="~s")),
            tooltip=[
                alt.Tooltip(f"{category_field}:N", title=category_field.title()),
                alt.Tooltip("total_spend:Q", title="Spend (EUR)", format=",.0f"),
                alt.Tooltip("invoice_count:Q", title="Invoices"),
            ],
        )
        .properties(height=alt.Step(34))
    )
    return style_chart(chart)


def trend_chart(df: pd.DataFrame) -> alt.Chart:
    base = alt.Chart(df).encode(x=alt.X("month:O", title=None))
    area = base.mark_area(color=SERIES_1, opacity=0.12).encode(
        y=alt.Y("total_spend:Q", title="Spend (EUR)", axis=alt.Axis(format="~s"))
    )
    line = base.mark_line(color=SERIES_1, strokeWidth=2).encode(y="total_spend:Q")
    points = base.mark_circle(color=SERIES_1, size=45).encode(
        y="total_spend:Q",
        tooltip=[
            alt.Tooltip("month:O", title="Month"),
            alt.Tooltip("total_spend:Q", title="Spend", format=",.0f"),
            alt.Tooltip("invoice_count:Q", title="Invoices"),
        ],
    )
    return style_chart((area + line + points).properties(height=260))


def diverging_variance_chart(df: pd.DataFrame) -> alt.Chart:
    df = df.copy()
    df["direction"] = df["variance_pct"].apply(lambda v: "Over budget" if v > 0 else "Under budget")
    chart = (
        alt.Chart(df)
        .mark_bar(cornerRadius=3, size=18)
        .encode(
            y=alt.Y(
                "label:N",
                sort=alt.EncodingSortField(field="variance_pct", order="descending"),
                title=None,
                axis=alt.Axis(labelLimit=260),
            ),
            x=alt.X("variance_pct:Q", title="Variance vs. budget (%)", axis=alt.Axis(format="+.0f")),
            color=alt.Color(
                "direction:N",
                scale=alt.Scale(domain=["Under budget", "Over budget"], range=[DIVERGE_UNDER, DIVERGE_OVER]),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=[
                alt.Tooltip("label:N", title="Department · Category (Month)"),
                alt.Tooltip("variance_pct:Q", title="Variance", format="+.1f"),
                alt.Tooltip("actual_amount:Q", title="Actual", format=",.0f"),
                alt.Tooltip("budget_amount:Q", title="Budget", format=",.0f"),
            ],
        )
        .properties(height=alt.Step(26))
    )
    return style_chart(chart)


def impact_bar_chart(df: pd.DataFrame) -> alt.Chart:
    # One tier per chart: the tiers are never added up, so they never share an axis.
    base = alt.Chart(df).encode(
        y=alt.Y("driver:N", sort="-x", title=None, axis=alt.Axis(labelLimit=220)),
        # Headroom past the longest bar so its value label isn't clipped.
        x=alt.X("impact_eur:Q", title="€ per year", axis=alt.Axis(format="~s"),
                scale=alt.Scale(domain=[0, float(df["impact_eur"].max()) * 1.2], nice=False)),
    )
    bars = base.mark_bar(color=SERIES_1, cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=20).encode(
        tooltip=[
            alt.Tooltip("driver:N", title="Driver"),
            alt.Tooltip("impact_eur:Q", title="€ per year", format=",.0f"),
            alt.Tooltip("cases:Q", title="Cases"),
            alt.Tooltip("rule:N", title="Rule"),
        ]
    )
    labels = base.mark_text(align="left", dx=4, color=TEXT_SECONDARY, fontSize=11).encode(
        text=alt.Text("impact_eur:Q", format=",.0f")
    )
    return style_chart((bars + labels).properties(height=alt.Step(40)))


def labelled_bar_chart(df: pd.DataFrame, category: str, value: str, axis_title: str, label: str,
                       tooltip: list, sort: str | list = "-x") -> alt.Chart:
    """Horizontal bars with a text label at the end of each bar (the label column is preformatted)."""
    base = alt.Chart(df).encode(
        y=alt.Y(f"{category}:N", sort=sort, title=None, axis=alt.Axis(labelLimit=280)),
        x=alt.X(f"{value}:Q", title=axis_title, axis=alt.Axis(format="~s"),
                scale=alt.Scale(domain=[0, float(df[value].max()) * 1.45], nice=False)),
    )
    bars = base.mark_bar(color=SERIES_1, cornerRadiusTopRight=4, cornerRadiusBottomRight=4, size=20).encode(
        tooltip=tooltip
    )
    labels = base.mark_text(align="left", dx=4, color=TEXT_SECONDARY, fontSize=11).encode(text=f"{label}:N")
    return style_chart((bars + labels).properties(height=alt.Step(40)))


def individuals_chart(chart: pd.DataFrame, limits: dict) -> alt.Chart:
    """I chart: weekly mean days with centre line and control limits; signals in red."""
    base = alt.Chart(chart).encode(x=alt.X("week_start:T", title=None, axis=alt.Axis(format="%b %y")))
    line = base.mark_line(color=SERIES_1, strokeWidth=2).encode(
        y=alt.Y("mean_days:Q", title="Mean days, submit to pay", scale=alt.Scale(zero=False))
    )
    points = base.mark_circle(size=64, opacity=1).encode(
        y="mean_days:Q",
        color=alt.Color(
            "status:N",
            scale=alt.Scale(domain=["Normal week", "Signal"], range=[SERIES_1, DIVERGE_OVER]),
            legend=alt.Legend(title=None, orient="top"),
        ),
        tooltip=[
            alt.Tooltip("week_start:T", title="Week of", format="%d %b %Y"),
            alt.Tooltip("mean_days:Q", title="Mean days", format=".1f"),
            alt.Tooltip("invoices:Q", title="Invoices paid"),
            alt.Tooltip("status:N", title="Status"),
        ],
    ).transform_calculate(status="datum.signal ? 'Signal' : 'Normal week'")
    lines = pd.DataFrame({
        "week_start": chart["week_start"].max(),
        "value": [limits["ucl"], limits["centre"], limits["lcl"]],
        "label": [f"UCL {limits['ucl']:.1f}", f"Centre {limits['centre']:.1f}", f"LCL {limits['lcl']:.1f}"],
        "dash": ["limit", "centre", "limit"],
    })
    rules = alt.Chart(lines).mark_rule(color=TEXT_SECONDARY, strokeWidth=1).encode(
        y="value:Q",
        strokeDash=alt.StrokeDash("dash:N", scale=alt.Scale(domain=["centre", "limit"], range=[[1, 0], [5, 4]]),
                                  legend=None),
    )
    # Labelled at the right end of each line, where the most recent weeks are read against them.
    rule_labels = alt.Chart(lines).mark_text(align="right", baseline="bottom", dy=-2, color=TEXT_SECONDARY,
                                             fontSize=11).encode(x="week_start:T", y="value:Q", text="label:N")
    return style_chart((rules + line + points + rule_labels).properties(height=280))


def moving_range_chart(chart: pd.DataFrame, limits: dict) -> alt.Chart:
    """MR chart: week-to-week change, with its upper limit."""
    base = alt.Chart(chart.dropna(subset=["moving_range"])).encode(
        x=alt.X("week_start:T", title=None, axis=alt.Axis(format="%b %y"))
    )
    line = base.mark_line(color=SERIES_1, strokeWidth=2).encode(
        y=alt.Y("moving_range:Q", title="Moving range (days)")
    )
    points = base.mark_circle(size=40, color=SERIES_1, opacity=1).encode(
        y="moving_range:Q",
        tooltip=[alt.Tooltip("week_start:T", title="Week of", format="%d %b %Y"),
                 alt.Tooltip("moving_range:Q", title="Change vs previous week", format=".1f")],
    )
    ucl = alt.Chart(pd.DataFrame({"value": [limits["mr_ucl"]]})).mark_rule(
        color=TEXT_SECONDARY, strokeDash=[5, 4]).encode(y="value:Q")
    return style_chart((ucl + line + points).properties(height=150))


def eur(value: float, thousands: bool = False) -> str:
    """€ with the minus sign in front: −€60k, not €-60k."""
    text = f"€{abs(value) / 1000:,.0f}k" if thousands else f"€{abs(value):,.0f}"
    return f"−{text}" if value < 0 else text


def cash_flow_chart(flows: pd.DataFrame) -> alt.Chart:
    """Net cash flow per year (investment in year 0), labelled with the running total."""
    df = flows.assign(
        year_label=flows["year"].map(lambda y: "Year 0 (invest)" if y == 0 else f"Year {y}"),
        direction=flows["net_eur"].map(lambda v: "Cash out" if v < 0 else "Cash in"),
        label=flows["cumulative_eur"].map(lambda v: f"running total {eur(v, thousands=True)}"),
    )
    base = alt.Chart(df).encode(x=alt.X("year_label:N", title=None, sort=None, axis=alt.Axis(labelAngle=0)))
    bars = base.mark_bar(size=46, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        y=alt.Y("net_eur:Q", title="Net cash flow (EUR)", axis=alt.Axis(format="~s")),
        color=alt.Color("direction:N", scale=alt.Scale(domain=["Cash out", "Cash in"],
                                                       range=[DIVERGE_OVER, SERIES_1]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[
            alt.Tooltip("year_label:N", title="Year"),
            alt.Tooltip("benefit_eur:Q", title="Benefit", format=",.0f"),
            alt.Tooltip("recovery_eur:Q", title="Duplicates recovered", format=",.0f"),
            alt.Tooltip("cost_eur:Q", title="Cost", format=",.0f"),
            alt.Tooltip("net_eur:Q", title="Net", format=",.0f"),
            alt.Tooltip("cumulative_eur:Q", title="Running total", format=",.0f"),
        ],
    )
    labels = base.mark_text(dy=-8, color=TEXT_SECONDARY, fontSize=11).encode(
        y=alt.Y("label_y:Q"), text="label:N"
    ).transform_calculate(label_y="max(datum.net_eur, 0)")
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=AXIS).encode(y="y:Q")
    return style_chart((bars + zero + labels).properties(height=280))


def tornado_chart(table: pd.DataFrame) -> alt.Chart:
    """NPV range per assumption: from base to its worst value (red) and to its best value (blue)."""
    rows = []
    for row in table.itertuples():
        for side, npv_value, value in [("Worst value", row.npv_worst_eur, row.worst_value),
                                       ("Best value", row.npv_best_eur, row.best_value)]:
            rows.append({"assumption": row.assumption, "side": side, "start": row.npv_base_eur,
                         "end": npv_value, "value": value, "swing": row.swing_eur})
    df = pd.DataFrame(rows)
    order = list(table["assumption"])
    bars = alt.Chart(df).mark_bar(size=18).encode(
        y=alt.Y("assumption:N", sort=order, title=None, axis=alt.Axis(labelLimit=260)),
        x=alt.X("start:Q", title="3-year NPV, hard benefits (EUR)", axis=alt.Axis(format="~s"),
                scale=alt.Scale(zero=False)),
        x2="end:Q",
        color=alt.Color("side:N", scale=alt.Scale(domain=["Worst value", "Best value"],
                                                  range=[DIVERGE_OVER, SERIES_1]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[
            alt.Tooltip("assumption:N", title="Assumption"),
            alt.Tooltip("side:N", title="Set to"),
            alt.Tooltip("value:Q", title="Value", format=",.2f"),
            alt.Tooltip("end:Q", title="NPV", format=",.0f"),
            alt.Tooltip("swing:Q", title="Swing", format=",.0f"),
        ],
    )
    base_rule = alt.Chart(pd.DataFrame({"x": [float(table["npv_base_eur"].iloc[0])]})).mark_rule(
        color=TEXT_SECONDARY, strokeDash=[4, 3]).encode(x="x:Q")
    return style_chart((bars + base_rule).properties(height=alt.Step(30)))


def process_map_dot(edges: pd.DataFrame, nodes: pd.DataFrame) -> str:
    """Graphviz source for the discovered process map. Line width follows the
    number of invoices; transitions the approved process doesn't allow are red and dashed.
    """
    widest = edges["transitions"].max()
    lines = [
        'digraph { rankdir=LR; bgcolor="transparent"; nodesep=0.35; ranksep=0.55;',
        'node [shape=box, style="rounded,filled", fillcolor="#eef4fc", color="#2a78d6", '
        'fontname="sans-serif", fontsize=11, margin="0.15,0.08"];',
        'edge [fontname="sans-serif", fontsize=9, fontcolor="#52514e", arrowsize=0.6];',
    ]
    for row in nodes.itertuples():
        lines.append(f'"{row.activity}" [label="{row.activity}\\n{row.invoices:,} invoices"];')
    for row in edges.itertuples():
        width = 0.8 + 4.5 * row.transitions / widest
        style = f'color="{AXIS}"' if row.allowed else f'color="{DIVERGE_OVER}", style=dashed, fontcolor="{DIVERGE_OVER}"'
        lines.append(
            f'"{row.source}" -> "{row.target}" [label=" {row.transitions:,} · {row.median_wait_days:.1f} d", '
            f"penwidth={width:.2f}, {style}];"
        )
    lines.append("}")
    return "\n".join(lines)


# --- Data (cached: deterministic, computed once per process) --------------

@st.cache_data
def get_invoices():
    return load_invoices()


@st.cache_data
def get_budgets():
    return load_budgets()


@st.cache_data
def get_data_quality():
    invoices, budgets, vendors = get_invoices(), get_budgets(), load_vendors()
    return {
        "issues": invoice_issues(invoices, budgets, vendors),
        "summary": issue_summary(invoices, budgets, vendors),
        "coverage": kpi_coverage(invoices, budgets),
        "repairs": cleaning_repairs(load_cleaning_log()),
    }


@st.cache_data
def get_anomalies():
    invoices, budgets = get_invoices(), get_budgets()
    return enrich_anomalies_with_dims(detect_all(invoices, budgets), invoices)


@st.cache_data
def get_impact():
    return compute_all_impact(get_invoices(), get_budgets())


@st.cache_data
def get_process():
    invoices, events = get_invoices(), load_events()
    weekly_chart, limits = imr_chart(weekly_processing_time(invoices))
    by_path_type = throughput_by_path_type(events, invoices)
    by_rework_loops = throughput_by_rework_loops(events, invoices)
    pareto = leakage_pareto(invoices, events)
    return {
        "headline": process_headline(pareto, by_path_type, by_rework_loops),
        "pareto": pareto,
        "by_cause_and_driver": leakage_by_cause_and_driver(invoices, events),
        "edges": process_map(events),
        "nodes": activity_counts(events),
        "variants": variants(events, invoices),
        "by_path_type": by_path_type,
        "by_rework_loops": by_rework_loops,
        "reject_reasons": reject_reasons(events),
        "conformance": conformance(events, invoices),
        "conformance_summary": conformance_summary(events, invoices),
        "control_chart": weekly_chart,
        "limits": limits,
        "signal_invoices": signal_invoices(invoices, weekly_chart),
    }


@st.cache_data
def get_business_case():
    case = compute_business_case(get_invoices(), get_budgets(), load_events())
    case["headline"] = business_case_headline(case)
    return case


@st.cache_data
def get_scorecard():
    return detection_scorecard(detect_all(get_invoices(), get_budgets()), load_ground_truth())


@st.cache_resource
def live_briefing_store():
    return {}


def get_briefing():
    # A *live* briefing is shared across all visitors for a day, so the landing
    # page costs one Gemini call per day, not one per visitor. Pre-generated
    # fallbacks are never stored here, so the next click tries live again.
    store = live_briefing_store()
    cached = store.get("briefing")
    if cached and time.time() - cached["at"] < 24 * 3600:
        return cached["facts"], cached["result"]
    facts = retrieve(BRIEFING_QUESTION, get_invoices(), get_budgets())
    result = answer(facts)
    if result["source"] == "live":
        store["briefing"] = {"at": time.time(), "facts": facts, "result": result}
    return facts, result


def source_caption(result):
    if result["source"] == "live":
        return f"Live answer · {result['model']}"
    return (
        f"Gemini's free tier is busy, so this is a pre-generated answer ({result['model']}, "
        f"{result['generated_on']}) for exactly these facts."
    )


def duplicate_claims_table(invoices_in_scope: pd.DataFrame) -> pd.DataFrame:
    """Suspected duplicate pairs laid out for the supplier claims (US-05): one
    row per pair, both invoices side by side. A pair is in scope if its copy is.
    """
    dates = invoices.set_index("invoice_id")["invoice_date"]
    names = invoices.drop_duplicates("vendor_id").set_index("vendor_id")["vendor_name"]
    pairs = duplicate_payments(invoices)
    pairs = pairs[pairs["second_invoice_id"].isin(invoices_in_scope["invoice_id"])]
    return pd.DataFrame({
        "Supplier ID": pairs["vendor_id"],
        "Supplier": pairs["vendor_id"].map(names),
        "Amount (EUR)": pairs["amount"],
        "Original invoice": pairs["first_invoice_id"],
        "Original date": pairs["first_invoice_id"].map(dates).dt.date,
        "Suspected copy": pairs["second_invoice_id"],
        "Copy date": pairs["second_invoice_id"].map(dates).dt.date,
        "Days apart": pairs["days_apart"],
        "Copy already paid": pairs["copy_paid"].map({True: "Yes", False: "No"}),
    }).sort_values(["Supplier ID", "Original date"])


def filter_by_dims(df, department, category):
    if department != "All":
        df = df[df["department"] == department]
    if category != "All":
        df = df[df["category"] == category]
    return df


invoices = get_invoices()
budgets = get_budgets()
anomalies = get_anomalies()

# --- Header ----------------------------------------------------------------

st.title("AP Spend Leakage Analyzer")
st.markdown(
    "Where Rheinwerk Komponenten's accounts-payable process leaks cash, and what to fix first. "
    "**pandas computes every number; Gemini only narrates them**, so every AI answer can be checked."
)
st.markdown(
    f'<span class="pill">{len(invoices):,} synthetic invoices</span>'
    f'<span class="pill">Rule-based anomaly detection · {get_scorecard()["recall"].min():.0%} recall</span>'
    '<span class="pill">LLM narrates, never calculates</span>',
    unsafe_allow_html=True,
)

# --- Sidebar ---------------------------------------------------------------

with st.sidebar:
    st.header("Filters")
    department = st.selectbox("Department", ["All"] + sorted(invoices["department"].unique()))
    category = st.selectbox("Category", ["All"] + sorted(invoices["category"].unique()))
    st.caption(
        "Filters apply to the Overview and Anomalies tabs. In **Ask the AI**, just name a "
        "department or category in your question."
    )
    st.divider()
    st.markdown("**About this demo**")
    st.caption(
        "All data is synthetic (generated with Faker), with anomalies deliberately planted so "
        "detection accuracy can be measured. See the **How it works** tab."
    )

scoped_invoices = filter_by_dims(invoices, department, category)
scoped_anomalies = filter_by_dims(anomalies, department, category)
flagged_invoice_share = (
    scoped_anomalies["invoice_id"].nunique() / len(scoped_invoices) * 100 if len(scoped_invoices) else 0.0
)

(summary_tab, overview_tab, anomalies_tab, process_tab, case_tab, quality_tab, chat_tab,
 how_tab) = st.tabs(
    ["Executive Summary", "Overview", "Anomalies", "Process", "Business case", "Data quality", "Ask the AI",
     "How it works"]
)

# --- Executive Summary -------------------------------------------------------

with summary_tab:
    impact = get_impact()
    ranked = rank_recommendations(impact["summary"])
    st.markdown(f'<div class="headline">{headline(impact, ranked)}</div>', unsafe_allow_html=True)
    st.caption(
        "Company-wide, 12 months to 31 August 2026 (the sidebar filters don't apply here). "
        "Hard leakage and controllable spend at risk are reported separately and never added together."
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1, st.container(border=True):
        st.metric(
            "Hard leakage",
            f"€{impact['hard_leakage_eur']:,.0f}",
            delta=f"{impact['hard_leakage_pct_of_spend']:.1f}% of spend",
            delta_color="off",
            delta_arrow="off",
            help="Cash lost: duplicate payments, missed early-payment discounts, late-payment interest and fees.",
        )
    with col2, st.container(border=True):
        st.metric(
            "Recoverable now",
            f"€{impact['expected_duplicate_recovery_eur']:,.0f}",
            delta="duplicates already paid",
            delta_color="off",
            delta_arrow="off",
            help=f"Duplicate copies already paid × {impact['assumptions']['duplicate_recovery_rate_pct']:.0f}% "
            "assumed supplier repayment rate.",
        )
    with col3, st.container(border=True):
        st.metric(
            "Controllable spend at risk",
            f"€{impact['spend_at_risk_eur']:,.0f}",
            delta="reported separately",
            delta_color="off",
            delta_arrow="off",
            help="Spend against policy: above budget, without a purchase order, or paid earlier than needed. "
            "Not all of it is waste, so it is never added to hard leakage.",
        )
    with col4, st.container(border=True):
        st.metric(
            "Days to pay",
            f"{days_payable_outstanding(invoices):.1f} days",
            delta=f"agreed terms {agreed_payment_days(invoices):.1f} days",
            delta_color="off",
            delta_arrow="off",
            help="Days from invoice to payment, weighted by amount, for paid invoices (transactional DPO), "
            "against the suppliers' agreed net terms.",
        )

    st.subheader("What to fix first")
    rec_cols = st.columns(3)
    for col, rec in zip(rec_cols, ranked.head(3).itertuples()):
        # Lead with the most certain € the fix addresses; never add the types together.
        if getattr(rec, HARD) > 0:
            euro, euro_note = getattr(rec, HARD), "hard leakage a year"
            if getattr(rec, ESTIMATED) > 0:
                euro_note += f", plus €{getattr(rec, ESTIMATED):,.0f} estimated saving"
        elif getattr(rec, ESTIMATED) > 0:
            euro, euro_note = getattr(rec, ESTIMATED), "estimated saving a year"
        else:
            euro, euro_note = getattr(rec, REVIEW), "of spend to review"
        with col, st.container(border=True):
            st.markdown(
                f'<div class="rec-rank">#{rec.rank} · {rec.effort.upper()} EFFORT</div>'
                f'<div class="step-title">{rec.title}</div>'
                f'<div class="rec-euro">€{euro:,.0f}</div>'
                f'<div class="rec-meta">{euro_note}</div>'
                f'<div class="rec-meta" style="margin-top:6px"><b>Owner:</b> {rec.owner}</div>'
                f'<div class="step-body">{rec.action}</div>'
                f'<div class="rec-meta" style="margin-top:6px">Fixes: {rec.drivers}</div>',
                unsafe_allow_html=True,
            )
    rest = ranked.iloc[3:]
    if not rest.empty:
        with st.expander(f"Further recommendations ({len(rest)})"):
            for rec in rest.itertuples():
                st.markdown(
                    f"**#{rec.rank} {rec.title}** · €{getattr(rec, REVIEW):,.0f} of spend to review · "
                    f"Owner: {rec.owner} · {rec.effort} effort  \n{rec.action}"
                )

    tier_cols = st.columns(2)
    for col, tier, note in [
        (tier_cols[0], HARD_LEAKAGE, "Cash lost or recoverable. The business case rests on this."),
        (tier_cols[1], SPEND_AT_RISK, "Spend against policy. Some is justified, so it is reported separately."),
    ]:
        with col, st.container(border=True):
            st.subheader(tier)
            st.caption(note)
            tier_rows = impact["summary"][impact["summary"]["tier"] == tier]
            st.altair_chart(impact_bar_chart(tier_rows), width="stretch")

    with st.expander("How each figure is calculated, and the assumptions behind it"):
        st.dataframe(
            impact["summary"].rename(
                columns={"driver": "Driver", "tier": "Tier", "cases": "Cases", "base_eur": "€ base",
                         "impact_eur": "€ impact", "rule": "Rule"}
            ),
            width="stretch",
            hide_index=True,
            column_config={
                "€ base": st.column_config.NumberColumn(format="%.0f"),
                "€ impact": st.column_config.NumberColumn(format="%.0f"),
            },
        )
        st.dataframe(
            pd.DataFrame(
                [
                    ("Duplicate recovery rate", f"{assumptions()['duplicate_recovery_rate_pct']:.0f}%",
                     "To confirm with the AP Manager"),
                    ("Late-payment interest", f"Base rate + {assumptions()['late_interest_margin_pp']:g} pp, "
                     f"plus €{assumptions()['late_payment_flat_fee_eur']:g} per invoice", "§ 288 BGB"),
                    ("Purchase-order premium", f"{assumptions()['po_premium_pct']:g}% of no-PO spend",
                     "To confirm with Procurement"),
                    ("Cost of capital", f"{assumptions()['cost_of_capital_pct']:g}% a year", "To confirm with the CFO"),
                ],
                columns=["Assumption", "Value", "Source or owner"],
            ),
            width="stretch",
            hide_index=True,
        )

    with st.container(border=True):
        brief_col, button_col = st.columns([4, 1], vertical_alignment="center")
        brief_col.markdown("**AI briefing**: the same data in plain English. Gemini narrates; it calculates nothing.")
        if button_col.button("Generate briefing", type="primary", width="stretch"):
            try:
                with st.spinner("Asking Gemini..."):
                    st.session_state.briefing = get_briefing()
            except Exception as e:
                st.session_state.briefing = None
                st.warning(f"Couldn't generate the briefing: {e}")
        if st.session_state.get("briefing"):
            briefing_facts, briefing_result = st.session_state.briefing
            st.markdown(briefing_result["text"])
            st.caption(source_caption(briefing_result))
            with st.expander("Facts Gemini was given (every number above comes from here)"):
                st.json(briefing_facts)

# --- Overview --------------------------------------------------------------

with overview_tab:
    col1, col2, col3, col4 = st.columns(4)
    with col1, st.container(border=True):
        st.metric("Total Spend", f"€{total_spend(scoped_invoices):,.0f}", help="Sum of all invoice amounts in scope.")
    with col2, st.container(border=True):
        st.metric("Invoices", f"{len(scoped_invoices):,}")
    with col3, st.container(border=True):
        st.metric(
            "Avg Processing Time",
            f"{avg_processing_days(scoped_invoices):.1f} days",
            help="Average days from submission to payment. Invoices with no submission date are excluded.",
        )
    with col4, st.container(border=True):
        st.metric(
            "Anomalies Flagged",
            f"{len(scoped_anomalies):,}",
            delta=f"{flagged_invoice_share:.1f}% of invoices affected",
            delta_color="off",
            delta_arrow="off",
            help="Duplicate payments and processing delays (per invoice) plus budget overruns "
            "(per department, category and month). Details in the Anomalies tab.",
        )

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1, st.container(border=True):
        st.subheader("Spend by Department")
        st.altair_chart(hbar_chart(spend_by_department(scoped_invoices), "department"), width="stretch")
    with chart_col2, st.container(border=True):
        st.subheader("Spend by Category")
        st.altair_chart(hbar_chart(spend_by_category(scoped_invoices), "category"), width="stretch")

    chart_col3, chart_col4 = st.columns(2)
    with chart_col3, st.container(border=True):
        st.subheader("Monthly Spend Trend")
        # The dataset starts mid-month; plotting that stub month would look like a spend collapse.
        first_day = invoices["invoice_date"].min()
        monthly = spend_by_month(scoped_invoices)
        if first_day.day != 1:
            monthly = monthly[monthly["month"] != first_day.strftime("%Y-%m")]
            st.caption(f"Data starts {first_day:%d %b %Y}; that partial first month is omitted.")
        st.altair_chart(trend_chart(monthly), width="stretch")
    with chart_col4, st.container(border=True):
        st.subheader("Largest Budget Variances")
        st.caption("Biggest over- and under-spends vs. budget, company-wide (not affected by filters).")
        st.altair_chart(diverging_variance_chart(budget_variance_extremes(invoices, budgets)), width="stretch")

# --- Anomalies ---------------------------------------------------------------

with anomalies_tab:
    st.caption(
        "Three simple, explainable rules — no machine learning, so every flag can be justified to an auditor."
    )
    card_cols = st.columns(3)
    for col, (anomaly_type, label) in zip(card_cols, ANOMALY_LABELS.items()):
        count = int((scoped_anomalies["anomaly_type"] == anomaly_type).sum())
        with col, st.container(border=True):
            st.markdown(
                f'<div class="anomaly-card" style="border-color:{ANOMALY_COLORS[anomaly_type]}">'
                f'<div class="step-title">{label}</div>'
                f'<div class="anomaly-count">{count}</div>'
                f'<div class="anomaly-rule">{ANOMALY_RULES[anomaly_type]}</div></div>',
                unsafe_allow_html=True,
            )

    with st.container(border=True):
        st.subheader("Suspected Duplicate Pairs")
        claims = duplicate_claims_table(scoped_invoices)
        paid_copies = claims.loc[claims["Copy already paid"] == "Yes", "Amount (EUR)"].sum()
        st.caption(
            f"{len(claims)} pairs · gross exposure €{claims['Amount (EUR)'].sum():,.0f} · "
            f"€{paid_copies:,.0f} already paid, of which about €{paid_copies * DUPLICATE_RECOVERY_RATE:,.0f} "
            f"is expected back at an assumed {DUPLICATE_RECOVERY_RATE:.0%} recovery rate. Confirm each pair "
            "with the supplier before claiming; confirmed repayments are tracked outside this extract."
        )
        st.dataframe(
            claims,
            width="stretch",
            hide_index=True,
            column_config={"Amount (EUR)": st.column_config.NumberColumn(format="%.2f")},
        )
        st.download_button(
            "Download for supplier claims (CSV)",
            claims.to_csv(index=False).encode("utf-8"),
            file_name="suspected_duplicate_pairs.csv",
            mime="text/csv",
        )

    with st.container(border=True):
        st.subheader("Flagged Records")
        anomaly_type_filter = st.multiselect(
            "Show types",
            options=list(ANOMALY_LABELS),
            default=list(ANOMALY_LABELS),
            format_func=ANOMALY_LABELS.get,
        )
        display_anomalies = scoped_anomalies[scoped_anomalies["anomaly_type"].isin(anomaly_type_filter)].copy()
        display_anomalies["anomaly_type"] = display_anomalies["anomaly_type"].map(ANOMALY_LABELS)
        display_anomalies = display_anomalies.rename(
            columns={
                "anomaly_type": "Type",
                "invoice_id": "Invoice ID",
                "department": "Department",
                "category": "Category",
                "month": "Month",
                "detail": "Why it was flagged",
            }
        ).fillna("—")

        label_to_hex = {v: ANOMALY_COLORS[k] for k, v in ANOMALY_LABELS.items()}

        def tint_type(val):
            hex_color = label_to_hex.get(val)
            return f"background-color: {hex_color}22; color: {hex_color}; font-weight: 600;" if hex_color else ""

        st.dataframe(display_anomalies.style.map(tint_type, subset=["Type"]), width="stretch", hide_index=True)

# --- Process -----------------------------------------------------------------

with process_tab:
    process = get_process()
    st.markdown(f'<div class="headline">{process["headline"]}</div>', unsafe_allow_html=True)
    st.caption(
        "Company-wide, from the invoice event log (the sidebar filters don't apply here). The log records roles, "
        "never people, so nothing here measures individual employees."
    )

    paths = process["by_path_type"].set_index("path_type")
    loops = process["by_rework_loops"].set_index("rework_loops")["median_days"]
    conf = process["conformance_summary"]
    breaches = conf["by_category"].set_index("category")
    breach_count = int(breaches.loc[["Paid before approval", "Paid without approval"], "invoices"].sum())
    breach_spend = float(breaches.loc[["Paid before approval", "Paid without approval"], "spend"].sum())
    limits = process["limits"]
    signal_weeks = int(process["control_chart"]["signal"].sum())

    col1, col2, col3, col4 = st.columns(4)
    with col1, st.container(border=True):
        st.metric(
            "Invoices straight through",
            f"{paths.loc['Straight through', 'share_pct']:.0f}%",
            delta=f"paid in a median {paths.loc['Straight through', 'median_days']:.1f} days",
            delta_color="off",
            delta_arrow="off",
            help="Received, submitted, approved and paid with no rejection or deviation.",
        )
    with col2, st.container(border=True):
        st.metric(
            "Invoices sent back",
            f"{paths.loc['Rework', 'share_pct']:.1f}%",
            delta=f"1 loop {loops.loc[1]:.1f} d · 2 loops {loops.iloc[-1]:.1f} d",
            delta_color="off",
            delta_arrow="off",
            help="Rejected by the budget owner at least once, corrected by AP and resubmitted. "
            "Median days from receipt to payment by number of loops.",
        )
    with col3, st.container(border=True):
        st.metric(
            "Process conformance",
            f"{conf['conformance_pct']:.1f}%",
            delta=f"{breach_count} control breaches · €{breach_spend / 1000:,.1f}k",
            delta_color="off",
            delta_arrow="off",
            help="Paid invoices checked against the approved process with pm4py alignments. "
            "A control breach is an invoice paid before or without an approval.",
        )
    with col4, st.container(border=True):
        st.metric(
            "Weekly processing time",
            f"{limits['centre']:.1f} days",
            delta=f"limits {limits['lcl']:.1f}–{limits['ucl']:.1f} · {signal_weeks} signal",
            delta_color="off",
            delta_arrow="off",
            help="Mean submit-to-pay days per payment week, with control limits (I-MR chart below).",
        )

    with st.container(border=True):
        st.subheader("Where the money is lost: hard leakage by cause")
        st.caption(
            "Each euro of hard leakage is traced to the process step that let it happen, by a rule on the "
            "invoice's own dates. Bars are sorted largest first; the label shows the running share."
        )
        pareto = process["pareto"].assign(
            label=lambda d: [f"€{v:,.0f} · {c:.0f}% cumulative" for v, c in zip(d["impact_eur"], d["cumulative_pct"])]
        )
        st.altair_chart(
            labelled_bar_chart(
                pareto, "cause", "impact_eur", "€ per year", "label",
                tooltip=[
                    alt.Tooltip("cause:N", title="Cause"),
                    alt.Tooltip("impact_eur:Q", title="€ per year", format=",.0f"),
                    alt.Tooltip("invoices:Q", title="Invoices"),
                    alt.Tooltip("process_step:N", title="Process step"),
                    alt.Tooltip("hypothesis:N", title="Hypothesis"),
                ],
            ),
            width="stretch",
        )
        with st.expander("What each cause is made of, and the rule behind it"):
            st.dataframe(
                process["by_cause_and_driver"].rename(columns={
                    "cause": "Cause", "driver": "Driver", "invoices": "Invoices", "impact_eur": "€ per year"}),
                width="stretch",
                hide_index=True,
                column_config={"€ per year": st.column_config.NumberColumn(format="%.0f")},
            )
            st.markdown(
                "- **No duplicate check at invoice entry**: every duplicate payment got through entry.\n"
                "- **Payment run ignores discount and due dates**: approved with at least a day to spare, "
                "still paid too late. Approve-to-pay takes a median 3 days whether a discount is at stake or not.\n"
                "- **Slow approval** and **rework delays approval**: approved too late to pay in time, and the "
                "payment waited for the approval."
            )

    with st.container(border=True):
        st.subheader("How invoices actually flow")
        st.caption(
            "Discovered from the event log with pm4py (directly-follows graph). Each arrow: invoices that took "
            "that step next · median wait in days. Thicker = more invoices. "
            "**Red dashed arrows are not allowed by the approved process.**"
        )
        st.graphviz_chart(process_map_dot(process["edges"], process["nodes"]), width="stretch")

    var_col, loop_col = st.columns([3, 2])
    with var_col, st.container(border=True):
        st.subheader("Process variants")
        st.caption("Every distinct path, most frequent first. Days are receipt to payment, paid invoices only.")
        variant_table = process["variants"].rename(columns={
            "variant": "Variant", "path": "Path", "path_type": "Type", "steps": "Steps", "invoices": "Invoices",
            "share_pct": "Share %", "cumulative_pct": "Cumulative %", "spend": "Spend (EUR)",
            "median_days": "Median days", "p90_days": "P90 days",
        }).drop(columns=["Steps", "Cumulative %"])
        st.dataframe(
            variant_table,
            width="stretch",
            hide_index=True,
            column_config={
                "Path": st.column_config.TextColumn(width="large"),
                "Spend (EUR)": st.column_config.NumberColumn(format="%.0f"),
            },
        )
    with loop_col, st.container(border=True):
        st.subheader("What a rejection costs in time")
        by_loops = process["by_rework_loops"].assign(
            loops=lambda d: d["rework_loops"].map({0: "No rework", 1: "1 loop", 2: "2 loops"}).fillna(
                d["rework_loops"].astype(str) + " loops"),
            label=lambda d: [f"{m:.1f} d · {n:,} invoices" for m, n in zip(d["median_days"], d["invoices"])],
        )
        st.altair_chart(
            labelled_bar_chart(
                by_loops, "loops", "median_days", "Median days, receipt to payment", "label",
                tooltip=[alt.Tooltip("loops:N", title="Rework"),
                         alt.Tooltip("median_days:Q", title="Median days", format=".1f"),
                         alt.Tooltip("p90_days:Q", title="90th percentile", format=".1f"),
                         alt.Tooltip("invoices:Q", title="Invoices")],
                sort=list(by_loops["loops"]),
            ),
            width="stretch",
        )
        reasons = process["reject_reasons"].assign(label=lambda d: d["rejections"].map("{:,} rejections".format))
        st.markdown("**Why invoices are sent back**")
        st.altair_chart(
            labelled_bar_chart(
                reasons, "reject_reason", "rejections", "Rejections", "label",
                tooltip=[alt.Tooltip("reject_reason:N", title="Reason"),
                         alt.Tooltip("rejections:Q", title="Rejections"),
                         alt.Tooltip("invoices:Q", title="Invoices")],
            ),
            width="stretch",
        )

    with st.container(border=True):
        st.subheader("Is the process stable? Weekly processing time")
        chart, signals = process["control_chart"], process["signal_invoices"]
        st.caption(
            f"Individuals and moving-range (I-MR) chart: one point per payment week, the mean submit-to-pay days "
            f"of the invoices paid that week. A point outside the limits, or {RUN_LENGTH} weeks in a row on one "
            f"side of the centre line, is a signal worth investigating; everything else is normal variation. "
            f"Starts {WARMUP_DAYS} days into the data, so early weeks aren't fast just because nothing older existed."
        )
        st.altair_chart(individuals_chart(chart, limits), width="stretch")
        st.altair_chart(moving_range_chart(chart, limits), width="stretch")
        if not signals.empty:
            weeks = ", ".join(f"{w:%d %b %Y}" for w in signals["week_start"].unique())
            st.markdown(
                f"**Signal: week of {weeks}.** The slowest invoices paid that week are below; all are flagged "
                "by the processing-delay rule on the Anomalies tab. Without them the week is normal. "
                "Apart from that the process is stable: invoices are not slow because of bad weeks, but because "
                "of how the process is built. Faster payment needs a process change, not firefighting."
            )
            st.dataframe(
                signals.assign(
                    week_start=signals["week_start"].dt.date,
                    submitted_date=signals["submitted_date"].dt.date,
                    paid_date=signals["paid_date"].dt.date,
                ).rename(columns={
                    "week_start": "Week of", "invoice_id": "Invoice", "vendor_name": "Supplier",
                    "department": "Department", "submitted_date": "Submitted", "paid_date": "Paid",
                    "processing_days": "Days",
                }),
                width="stretch",
                hide_index=True,
            )

    with st.container(border=True):
        st.subheader("Paid outside the approved process")
        st.caption(
            f"{conf['paid_invoices']:,} paid invoices checked against the approved process (receive, submit, "
            "any number of reject-and-correct loops, approve, pay) with pm4py alignments. A missing submission "
            "is a data gap (see Data quality); paying before or without an approval is a control breach for "
            "Internal Audit."
        )
        st.dataframe(
            conf["by_category"].rename(columns={"category": "Deviation", "invoices": "Invoices",
                                                "spend": "Amount (EUR)"}),
            width="stretch",
            hide_index=True,
            column_config={"Amount (EUR)": st.column_config.NumberColumn(format="%.0f")},
        )
        deviations = process["conformance"].assign(
            approved_date=lambda d: d["approved_date"].dt.date, paid_date=lambda d: d["paid_date"].dt.date
        ).rename(columns={
            "invoice_id": "Invoice", "category": "Deviation", "deviation": "What the alignment found",
            "fitness": "Fitness", "path": "Path", "vendor_name": "Supplier", "department": "Department",
            "amount": "Amount (EUR)", "approved_date": "Approved", "paid_date": "Paid",
        })
        with st.expander(f"The {len(deviations)} invoices"):
            st.dataframe(
                deviations,
                width="stretch",
                hide_index=True,
                column_config={"Amount (EUR)": st.column_config.NumberColumn(format="%.2f")},
            )
        st.download_button(
            "Download for Internal Audit (CSV)",
            deviations.to_csv(index=False).encode("utf-8"),
            file_name="process_deviations.csv",
            mime="text/csv",
        )

# --- Business case -----------------------------------------------------------

with case_tab:
    case = get_business_case()
    base_case = case["base"]
    scenario_table = case["scenarios"].set_index("scenario")
    st.markdown(f'<div class="headline">{case["headline"]}</div>', unsafe_allow_html=True)
    st.caption(
        "Company-wide, 3 years from go-live (the sidebar filters don't apply here). Benefits are the measured "
        "leakage each fix removes. The headline counts hard benefits only; estimated savings are shown separately."
    )

    col1, col2, col3, col4 = st.columns(4)
    with col1, st.container(border=True):
        st.metric("One-off investment", f"€{base_case['investment_eur']:,.0f}",
                  delta=f"plus €{base_case['annual_run_cost_eur']:,.0f} a year to run", delta_color="off",
                  delta_arrow="off",
                  help=f"IT days at €{IT_DAY_RATE_EUR:,.0f} and business days at €{INTERNAL_DAY_RATE_EUR:,.0f}, "
                  "per lever (table below).")
    with col2, st.container(border=True):
        st.metric("Hard benefit a year", f"€{base_case['annual_hard_benefit_eur']:,.0f}",
                  delta=f"plus €{case['measured']['paid_duplicates'] * base_case['params']['duplicate_recovery_rate']:,.0f} "
                        "recovered once", delta_color="off", delta_arrow="off",
                  help="Leakage the fixes remove each year, from the root-cause Pareto; plus the one-off "
                  "claim-back of duplicates already paid.")
    with col3, st.container(border=True):
        st.metric("3-year NPV", f"€{base_case['hard']['npv_eur']:,.0f}",
                  delta=f"ROI {base_case['hard']['roi_pct']:.0f}%", delta_color="off", delta_arrow="off",
                  help=f"Discounted at the {base_case['params']['cost_of_capital_pct']:g}% cost of capital. "
                  "ROI = 3-year net return minus the investment, over the investment.")
    with col4, st.container(border=True):
        st.metric("Payback", f"{base_case['hard']['payback_months']:.0f} months",
                  delta=f"worst case {scenario_table.loc['Worst', 'payback_hard_months']:.0f} months",
                  delta_color="off", delta_arrow="off",
                  help="Months until the running total of net cash flow turns positive.")

    flow_col, scen_col = st.columns(2)
    with flow_col, st.container(border=True):
        st.subheader("Cash flow, base case")
        st.caption("Hard benefits only. Year 1 includes the claim-back of duplicates already paid and a "
                   f"{base_case['params']['ramp_up_year_1']:.0%} ramp-up after go-live.")
        st.altair_chart(cash_flow_chart(base_case["hard"]["flows"]), width="stretch")
    with scen_col, st.container(border=True):
        st.subheader("Worst, base and best case")
        scen = case["scenarios"].set_index("scenario").T
        scen.index = ["Investment (€)", "Hard benefit a year (€)", "NPV (€)", "ROI (%)",
                      "Payback (months)", "NPV without claim-back (€)", "NPV with estimated savings (€)"]
        st.dataframe(
            scen.map(lambda v: "—" if pd.isna(v) else f"{v:,.0f}".replace("-", "−")),
            width="stretch",
        )
        without = scenario_table["npv_hard_without_recovery_eur"]
        st.caption(
            "The claim-back of duplicates already paid needs no investment, so the recurring fixes are also "
            f"shown without it: NPV {eur(without['Base'])} in the base case"
            + (f", but {eur(without['Worst'])} in the worst case." if without["Worst"] < 0 else ".")
            + " Estimated savings (PO premium, working capital) rest on assumptions and are never in the headline."
        )

    with st.container(border=True):
        st.subheader("Which assumption matters most")
        st.caption(
            "Each bar moves one assumption to its worst (red) and best (blue) value, with all others at base. "
            "The longest bars are the ones to confirm before the board decides. Assumptions that only move the "
            "estimated savings are left out. "
            f"Break-even: costs could run to **{base_case['break_even_cost_multiplier']:.2f} times** the estimate "
            "before the NPV reaches zero."
        )
        moving = case["tornado"][case["tornado"]["swing_eur"] > 0]
        st.altair_chart(tornado_chart(moving), width="stretch")

    with st.container(border=True):
        st.subheader("The fixes: what each costs and returns (base case)")
        levers = base_case["levers"].assign(
            effectiveness=lambda d: (d["effectiveness"] * 100).round(0)
        )[["lever", "annual_benefit_eur", "one_off_cost_eur", "annual_run_cost_eur", "benefit_type",
           "eur_addressed", "effectiveness", "addresses", "owner", "action"]].rename(columns={
            "lever": "Fix", "benefit_type": "Benefit type", "addresses": "Addresses",
            "eur_addressed": "€ a year at stake", "effectiveness": "% removed",
            "annual_benefit_eur": "€ benefit a year", "one_off_cost_eur": "One-off cost (EUR)",
            "annual_run_cost_eur": "Running cost a year (EUR)", "owner": "Owner", "action": "What changes",
        })
        st.dataframe(
            levers,
            width="stretch",
            hide_index=True,
            column_config={
                c: st.column_config.NumberColumn(format="%.0f")
                for c in ["€ a year at stake", "% removed", "€ benefit a year", "One-off cost (EUR)",
                          "Running cost a year (EUR)"]
            },
        )
        st.caption(
            "AP time saved by less rework is not counted as a benefit (no hourly handling cost has been agreed), "
            "while staff time is counted as a cost: the case is deliberately conservative. Spend above budget "
            "is not a saving and is left out."
        )
        with st.expander("Assumptions: worst, base and best values, and where each comes from"):
            data_based = case["data_based"]
            rows = []
            for name, a in ASSUMPTIONS.items():
                base_value = data_based[name] if a["base"] is None else a["base"]
                rows.append({"Assumption": a["label"], "Worst": a["worst"], "Base": round(base_value, 3),
                             "Best": a["best"], "Source": a["source"]})
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

# --- Data quality ------------------------------------------------------------

with quality_tab:
    quality = get_data_quality()
    st.markdown(
        f'<div class="headline">{data_quality_headline(quality["issues"], quality["summary"], quality["coverage"])}'
        "</div>",
        unsafe_allow_html=True,
    )
    st.caption("Company-wide, extract of 31 August 2026 (the sidebar filters don't apply here).")

    with st.container(border=True):
        st.subheader("What each figure leaves out")
        st.caption(
            "Invoices are never deleted. A figure that needs a field an invoice lacks leaves that invoice out, "
            "and says so here. Open invoices are not errors, but they have no payment yet."
        )
        st.dataframe(
            quality["coverage"].drop(columns="population").rename(columns={
                "figure": "Figure", "invoices": "Invoices", "included": "Included", "excluded": "Left out",
                "excluded_because": "Why left out",
            }),
            width="stretch",
            hide_index=True,
            column_config={"Why left out": st.column_config.TextColumn(width="large")},
        )

    with st.container(border=True):
        st.subheader("Invoices failing a check")
        st.caption(
            "Checks on the cleaned data. Checks that find nothing are listed too: they run on every extract. "
            "Which figures each failure affects is shown in the table above."
        )
        st.dataframe(
            quality["summary"][["check", "invoices", "amount_eur", "owner", "fix_at_source"]].rename(columns={
                "check": "Check", "invoices": "Invoices", "amount_eur": "Amount (EUR)",
                "fix_at_source": "Fix at the source", "owner": "Owner",
            }),
            width="stretch",
            hide_index=True,
            column_config={"Amount (EUR)": st.column_config.NumberColumn(format="%.0f")},
        )
        issues = quality["issues"].assign(invoice_date=quality["issues"]["invoice_date"].dt.date).rename(columns={
            "check": "Check", "invoice_id": "Invoice", "vendor_id": "Supplier ID", "vendor_name": "Supplier",
            "department": "Department", "amount": "Amount (EUR)", "invoice_date": "Invoice date", "status": "Status",
        })[["Check", "Invoice", "Supplier ID", "Supplier", "Department", "Amount (EUR)", "Invoice date", "Status"]]
        with st.expander(f"The {len(issues)} invoices, one row per failed check"):
            st.dataframe(
                issues,
                width="stretch",
                hide_index=True,
                column_config={"Amount (EUR)": st.column_config.NumberColumn(format="%.2f")},
            )
        st.download_button(
            "Download the list for AP (CSV)",
            issues.to_csv(index=False).encode("utf-8"),
            file_name="data_quality_issues.csv",
            mime="text/csv",
        )

    with st.container(border=True):
        st.subheader("Repaired during cleaning: fix at the source")
        st.caption(
            "These no longer affect any figure, because the cleaning step repairs them. They come back with "
            "every extract until the entry screen or the supplier master stops them."
        )
        st.dataframe(
            quality["repairs"][["field", "issue", "rows", "owner", "fix_at_source", "examples"]].rename(
                columns={
                    "field": "Field", "issue": "Problem", "rows": "Rows", "owner": "Owner",
                    "fix_at_source": "Fix at the source", "examples": "Examples as typed",
                }
            ),
            width="stretch",
            hide_index=True,
        )

# --- Ask the AI --------------------------------------------------------------

with chat_tab:
    st.caption(
        "Ask in plain English. Your question picks the relevant precomputed facts; Gemini narrates only those. "
        "Open **Facts Gemini was given** under any answer to check every number."
    )

    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None

    suggestion_cols = st.columns(len(SUGGESTED_QUESTIONS) + 1)
    for col, suggestion in zip(suggestion_cols, SUGGESTED_QUESTIONS):
        if col.button(suggestion, width="stretch"):
            st.session_state.pending_question = suggestion
    if st.session_state.messages and suggestion_cols[-1].button("Clear chat", width="stretch"):
        st.session_state.messages = []
        st.rerun()

    # Messages render into this container, which sits above the input box, so
    # the conversation reads top-to-bottom with the input always last.
    conversation = st.container()
    question = st.chat_input("e.g. Which department went most over budget?")
    if not question and st.session_state.pending_question:
        question = st.session_state.pending_question
        st.session_state.pending_question = None

    with conversation:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if msg.get("source_caption"):
                    st.caption(msg["source_caption"])
                if msg.get("facts") is not None:
                    with st.expander("Facts Gemini was given"):
                        st.json(msg["facts"])

        if question:
            st.session_state.messages.append({"role": "user", "content": question})
            with st.chat_message("user"):
                st.markdown(question)

            facts, caption = None, None
            with st.chat_message("assistant"):
                try:
                    facts = retrieve(question, invoices, budgets)
                    with st.spinner("Asking Gemini..."):
                        result = answer(facts)
                    reply, caption = result["text"], source_caption(result)
                except Exception as e:
                    reply = f"Couldn't generate an answer: {e}"
                st.markdown(reply)
                if caption:
                    st.caption(caption)
                if facts is not None:
                    with st.expander("Facts Gemini was given"):
                        st.json(facts)

            st.session_state.messages.append(
                {"role": "assistant", "content": reply, "source_caption": caption, "facts": facts}
            )

# --- How it works ------------------------------------------------------------

with how_tab:
    step_cols = st.columns(3)
    steps = [
        ("Compute", "KPIs and anomaly rules run in plain pandas — deterministic and unit-tested. No AI involved."),
        ("Retrieve", "Your question selects only the relevant precomputed facts. Raw invoice rows never leave this step."),
        ("Narrate", "Gemini turns those facts into plain English, under instructions that forbid calculating anything."),
    ]
    for i, (col, (title, body)) in enumerate(zip(step_cols, steps), start=1):
        with col, st.container(border=True):
            st.markdown(
                f'<span class="step-num">{i}</span><span class="step-title">{title}</span>'
                f'<div class="step-body">{body}</div>',
                unsafe_allow_html=True,
            )

    st.subheader("Pipeline")
    st.graphviz_chart(
        """
        digraph {
            rankdir=LR; bgcolor="transparent";
            node [shape=box, style="rounded,filled", fillcolor="#eef4fc", color="#2a78d6",
                  fontname="sans-serif", fontsize=11, margin="0.15,0.08"];
            edge [color="#8a8980", arrowsize=0.7];
            gen   [label="1. Generate\\nsynthetic invoices\\n+ planted anomalies"];
            clean [label="2. Clean\\npandas notebook"];
            calc  [label="3. Compute\\nKPIs + anomaly rules"];
            ret   [label="4. Retrieve\\nonly relevant facts"];
            llm   [label="5. Narrate\\nGemini", fillcolor="#fdf0e9", color="#eb6834"];
            ui    [label="6. Display\\nthis app"];
            gen -> clean -> calc -> ret -> llm -> ui;
            calc -> ui [style=dashed, label=" charts", fontsize=10, fontcolor="#52514e"];
        }
        """,
        width="stretch",
    )
    st.caption("Data flows one way. Nothing after step 3 ever touches a raw invoice row.")

    guard_col, score_col = st.columns(2)
    with guard_col, st.container(border=True):
        st.subheader("The AI guardrail")
        st.markdown(
            "- **Structural, not just a prompt.** Gemini's request contains only a small JSON of "
            "precomputed facts — there are no raw rows in it to misread.\n"
            "- **No arithmetic.** The system instruction forbids calculating, estimating or inventing "
            "figures; every number must be copied from the facts.\n"
            "- **Auditable.** Every answer shows the exact facts it was given, so anyone can check it.\n"
            "- **Graceful degradation.** Tries "
            + " → ".join(f"`{m}`" for m in GEMINI_MODELS)
            + " live (30-second budget). If all are busy, suggested questions fall back to answers "
            "pre-generated for the exact same facts — always labelled as such."
        )
    with score_col, st.container(border=True):
        st.subheader("Detection accuracy")
        scorecard = get_scorecard()
        st.dataframe(
            pd.DataFrame(
                {
                    "Anomaly": scorecard["anomaly_type"].map(ANOMALY_LABELS),
                    "Planted": scorecard["planted"],
                    "Flagged": scorecard["flagged"],
                    "Recall": scorecard["recall"].map("{:.0%}".format),
                    "Precision": scorecard["precision"].map("{:.0%}".format),
                }
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Scored live against the data generator's answer key, which the detection code never reads. "
            "Recall = share of planted anomalies caught; precision = share of flags that were real."
        )

    with st.container(border=True):
        st.subheader("Honest limitations")
        st.markdown(
            "- Synthetic data: realistic patterns, but not real transactions.\n"
            "- Thresholds were tuned on this synthetic answer key; in production they'd be set with finance stakeholders.\n"
            "- Retrieval is keyword-based (no vector database) — right-sized for a few structured tables, "
            "but it won't understand every phrasing.\n"
            "- Gemini free tier is often overloaded: typed questions may ask you to retry, while the "
            "briefing and suggested questions fall back to clearly labelled pre-generated answers."
        )
