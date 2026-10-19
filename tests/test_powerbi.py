"""The Power BI kit in bi/powerbi/ (task 6.3) can't be run here: Power BI
Desktop is Windows-only. These tests check what can be checked without it:

- the Power Query scripts are the ones the exporter generates today;
- every table, column and measure the DAX refers to exists;
- the DAX definitions, mirrored in pandas on the same CSVs Power BI loads,
  give the Python headline figures and the control report's monthly values.
  The mirror follows the DAX line by line (filters, the paid-date
  relationship, rounding), so a definition that drifts from Python fails here
  before anyone builds the report;
- the expected values the build guide quotes are the right ones.
"""

import importlib.util
import json
import re
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
POWERBI = ROOT / "bi" / "powerbi"
DATA = ROOT / "bi" / "data"


@pytest.fixture(scope="module")
def exporter():
    spec = importlib.util.spec_from_file_location("export_bi_data", ROOT / "scripts" / "export_bi_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def queries(exporter):
    return exporter.powerbi_queries(exporter.build_exports())


# --- Power Query scripts ----------------------------------------------------------------

def test_committed_queries_are_up_to_date(exporter, queries):
    on_disk = {p.name: p.read_text(encoding="utf-8") for p in exporter.POWERBI_QUERY_DIR.glob("*.pq")}
    assert set(on_disk) == set(queries)
    for name, text in queries.items():
        assert on_disk[name] == text, f"bi/powerbi/queries/{name} is stale: rerun scripts/export_bi_data.py"


def test_every_csv_column_is_typed_with_the_en_us_culture(queries):
    for csv in DATA.glob("*.csv"):
        header = pd.read_csv(csv, nrows=0).columns.tolist()
        script = queries[f"{''.join(p.capitalize() for p in csv.stem.split('_'))}.pq"]
        typed = re.findall(r'\{"([^"]+)", (?:type \w+|Int64\.Type)\}', script)
        assert typed == header, csv.name
        assert '"en-US")' in script


def test_flags_that_can_be_blank_are_logical(queries):
    script = queries["Invoices.pq"]
    for column in ["has_po", "is_paid", "paid_on_time", "discount_taken"]:
        assert f'{{"{column}", type logical}}' in script
    assert '{"amount", type number}' in script
    assert '{"po_number", type text}' in script  # an ID, not a number


# --- DAX: every reference resolves ------------------------------------------------------

def strip_comments_and_strings(dax: str) -> str:
    dax = re.sub(r'"[^"]*"', '""', dax)
    return re.sub(r"//[^\n]*", "", dax)


def model_columns(queries) -> dict[str, set[str]]:
    columns = {
        name.removesuffix(".pq"): set(re.findall(r'\{"([^"]+)", (?:type \w+|Int64\.Type)\}', text))
        for name, text in queries.items()
    }
    columns["Date"] = {"Date", "Month", "Month start", "Month label"}
    return columns


def defined_measures(dax: str) -> set[str]:
    return set(re.findall(r"MEASURE '_Measures'\[([^\]]+)\]", dax))


def test_dax_refers_only_to_existing_tables_columns_and_measures(queries):
    columns = model_columns(queries)
    measures_dax = (POWERBI / "measures.dax").read_text(encoding="utf-8")
    measures = defined_measures(measures_dax)
    assert len(measures) > 30
    for path in [POWERBI / "measures.dax", POWERBI / "date_table.dax"]:
        code = strip_comments_and_strings(path.read_text(encoding="utf-8"))
        for quoted, bare, name in re.findall(r"(?:'([^']+)'|\b([A-Za-z_]\w*))\[([^\]]+)\]", code):
            table = quoted or bare
            if table == "_Measures":
                continue
            assert table in columns, f"{path.name}: unknown table {table}"
            assert name in columns[table], f"{path.name}: unknown column {table}[{name}]"
        if path.name == "measures.dax":
            for name in re.findall(r"(?<![\w'\]])\[([^\]]+)\]", code):
                assert name in measures, f"measures.dax: unknown measure [{name}]"


def test_check_table_covers_every_headline_figure():
    dax = (POWERBI / "measures.dax").read_text(encoding="utf-8")
    switch = dax.split("MEASURE '_Measures'[Power BI value]")[1].split("MEASURE")[0]
    checked = set(re.findall(r'"(\w+)", ', switch))
    figures = set(pd.read_csv(DATA / "headline_figures.csv")["figure"])
    # Passed through from Python (an assumption times a count), so there is nothing to recompute.
    assert figures - checked == {"expected_duplicate_recovery_eur"}
    assert checked <= figures


def test_theme_is_valid_json_in_the_app_colours():
    theme = json.loads((POWERBI / "theme.json").read_text(encoding="utf-8"))
    assert theme["dataColors"][:3] == ["#2a78d6", "#eb6834", "#1baf7a"]


# --- The DAX definitions, mirrored in pandas ---------------------------------------------

@pytest.fixture(scope="module")
def model():
    """The CSVs as the Power Query scripts type them."""
    invoices = pd.read_csv(DATA / "invoices.csv", parse_dates=["invoice_date", "paid_date"],
                           dtype={"po_number": str})
    for flag in ["paid_on_time", "discount_taken"]:
        invoices[flag] = invoices[flag].map({True: True, False: False, "True": True, "False": False})
    return {
        "invoices": invoices,
        "vendors": pd.read_csv(DATA / "vendors.csv"),
        "leakage_by_invoice": pd.read_csv(DATA / "leakage_by_invoice.csv"),
        "leakage_by_driver": pd.read_csv(DATA / "leakage_by_driver.csv"),
        "events": pd.read_csv(DATA / "invoice_events.csv"),
        "scenarios": pd.read_csv(DATA / "business_case_scenarios.csv").set_index("scenario"),
    }


def paid(invoices):
    return invoices[invoices["is_paid"]]


def dax_dpo(invoices):
    p = paid(invoices)
    return ((p["paid_date"] - p["invoice_date"]).dt.days * p["amount"]).sum() / p["amount"].sum()


def dax_agreed_days(invoices, vendors):
    p = paid(invoices).merge(vendors[["vendor_id", "net_days"]], on="vendor_id")
    return (p["net_days"] * p["amount"]).sum() / p["amount"].sum()


def dax_on_time(invoices):
    return (paid(invoices)["paid_on_time"] == True).sum() / len(paid(invoices))  # noqa: E712


def dax_discount_capture(invoices):
    p = paid(invoices)
    return (p["discount_taken"] == True).sum() / p["discount_taken"].notna().sum()  # noqa: E712


def dax_po_compliance(invoices):
    return invoices.loc[invoices["has_po"], "amount"].sum() / invoices["amount"].sum()


def dax_rework(invoices):
    return (invoices["rework_loops"] > 0).sum() / len(invoices)


def dax_rework_of_paid(invoices):
    return (paid(invoices)["rework_loops"] > 0).sum() / len(paid(invoices))


def dax_median_processing(invoices):
    days = paid(invoices)["processing_days"]
    return days[days >= 0].median()


def power_bi_values(m) -> dict[str, float]:
    """[Power BI value] for each figure: the measure, in Python's units and rounding."""
    inv, base = m["invoices"], m["scenarios"].loc["Base"]
    drivers = m["leakage_by_driver"]
    hard = m["leakage_by_invoice"]["impact_eur"].sum()
    return {
        "total_spend_eur": round(inv["amount"].sum(), 2),
        "invoices": len(inv),
        "hard_leakage_eur": round(hard, 2),
        "hard_leakage_pct_of_spend": round(hard / inv["amount"].sum() * 100, 2),
        "spend_at_risk_eur": round(drivers.loc[drivers["tier"] == "Controllable spend at risk", "impact_eur"].sum(), 2),
        "dpo_days": round(dax_dpo(inv), 1),
        "agreed_payment_days": round(dax_agreed_days(inv, m["vendors"]), 1),
        "on_time_payment_pct": round(dax_on_time(inv) * 100, 1),
        "discount_capture_pct": round(dax_discount_capture(inv) * 100, 1),
        "po_compliance_pct": round(dax_po_compliance(inv) * 100, 1),
        "rework_pct": round(dax_rework(inv) * 100, 1),
        "investment_eur": base["investment_eur"],
        "annual_hard_benefit_eur": base["annual_hard_benefit_eur"],
        "npv_hard_eur": base["npv_hard_eur"],
        "roi_hard_pct": base["roi_hard_pct"],
        "payback_hard_months": base["payback_hard_months"],
        "npv_with_estimated_eur": base["npv_with_estimated_eur"],
    }


def test_measures_reproduce_every_headline_figure_to_the_cent(model):
    """The Checks page shows ALL OK if the DAX does what the mirror does."""
    python = pd.read_csv(DATA / "headline_figures.csv").set_index("figure")["value"]
    for figure, value in power_bi_values(model).items():
        assert abs(value - python[figure]) < 0.001, figure


def test_hard_leakage_per_invoice_adds_up_to_the_driver_table(model):
    drivers = model["leakage_by_driver"]
    hard_tier = drivers.loc[drivers["tier"] == "Hard leakage", "impact_eur"].sum()
    assert model["leakage_by_invoice"]["impact_eur"].sum() == pytest.approx(hard_tier, abs=0.01)


# Payment measures use the paid-date relationship; PO compliance the invoice date.
MONTHLY = [
    ("On-time payment rate", "paid_month", lambda inv: dax_on_time(inv) * 100),
    ("Early-payment discount capture", "paid_month", lambda inv: dax_discount_capture(inv) * 100),
    ("Days payable outstanding", "paid_month", dax_dpo),
    ("Rework rate", "paid_month", lambda inv: dax_rework_of_paid(inv) * 100),
    ("PO compliance", "invoice_month", lambda inv: dax_po_compliance(inv) * 100),
]


@pytest.mark.parametrize("ctq, month_column, measure", MONTHLY, ids=[m[0] for m in MONTHLY])
def test_monthly_measures_match_the_control_report(model, ctq, month_column, measure):
    report = pd.read_csv(DATA / "control_report.csv")
    rows = report[report["ctq"] == ctq].dropna(subset=["this_month"])
    assert len(rows) == 12
    inv = model["invoices"]
    for _, row in rows.iterrows():
        month_slice = inv[inv[month_column] == row["month"]]
        assert round(measure(month_slice), 1) == pytest.approx(row["this_month"], abs=0.051), row["month"]


def test_monthly_median_processing_time_matches_the_control_report(model):
    report = pd.read_csv(DATA / "control_report.csv")
    rows = report[report["measure"] == "Median, submission to payment"]
    inv = model["invoices"]
    for _, row in rows.iterrows():
        assert dax_median_processing(inv[inv["paid_month"] == row["month"]]) == row["this_month"], row["month"]


def test_rejections_by_reason_add_up(model):
    events = model["events"]
    rejected = events[events["activity"] == "Reject invoice"]
    assert rejected["reject_reason"].notna().all()
    # Every rejected invoice carries the rework flag the Rework % measure counts.
    flagged = set(model["invoices"].loc[model["invoices"]["rework_loops"] > 0, "invoice_id"])
    assert set(rejected["invoice_id"]) == flagged


# --- The build guide quotes the right numbers ----------------------------------------------

def eur(value: float) -> str:
    return f"€{value:,.0f}"


def test_guide_quotes_todays_figures(model):
    guide = (POWERBI / "README.md").read_text(encoding="utf-8")
    inv, leak = model["invoices"], model["leakage_by_invoice"]
    by_invoice = leak.merge(inv[["invoice_id", "department"]], on="invoice_id")
    top_department = by_invoice.groupby("department")["impact_eur"].sum().sort_values().index[-1]
    top_department_eur = by_invoice.groupby("department")["impact_eur"].sum().max()
    po_by_department = inv.assign(with_po=inv["amount"].where(inv["has_po"], 0)).groupby("department")[
        ["with_po", "amount"]].sum()
    lowest_po = (po_by_department["with_po"] / po_by_department["amount"]).sort_values()
    scenarios = model["scenarios"]
    expected = [
        eur(inv["amount"].sum()),
        eur(leak["impact_eur"].sum()),
        f"{top_department} ({eur(top_department_eur)})",
        f"{lowest_po.index[0]} ({lowest_po.iloc[0] * 100:.1f}%)",
        eur(scenarios.loc["Base", "npv_hard_eur"]),
        eur(scenarios.loc["Worst", "npv_hard_eur"]),
        f"{dax_dpo(inv):.1f} days",
    ]
    for text in expected:
        assert text in guide, f"guide should quote {text}"
