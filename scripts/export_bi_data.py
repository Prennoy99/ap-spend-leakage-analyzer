"""Exports the analysis to plain CSV files in bi/data/ for Excel (Power Query),
Power BI and Tableau (Control, tasks 6.2–6.4).

Every figure is computed by the same Python code as the app, so the BI tools
only aggregate and display; they never re-derive a rule. headline_figures.csv
holds the numbers every view must show, and tests/test_bi_exports.py checks
the committed files are up to date with the code.

Files are UTF-8 with \\n line endings and dates as ISO text (YYYY-MM-DD), so
they import the same way on Windows and Linux.

Run: python scripts/export_bi_data.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import business_case, control, impact, kpis, recommendations, root_cause  # noqa: E402
from src.process_mining import case_table  # noqa: E402

BI_DATA_DIR = Path(__file__).resolve().parent.parent / "bi" / "data"


def invoices_table(invoices: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """One row per invoice with the flags the dashboards slice by."""
    paid = invoices["paid_date"].notna()
    cases = case_table(events, invoices).set_index("invoice_id")
    table = invoices[[
        "invoice_id", "vendor_id", "vendor_name", "department", "category", "po_number", "has_po",
        "invoice_date", "submitted_date", "approved_date", "paid_date", "due_date", "discount_date",
        "amount", "status", "payment_terms", "processing_days",
    ]].copy()
    table["invoice_month"] = table["invoice_date"].dt.strftime("%Y-%m")
    table["paid_month"] = table["paid_date"].dt.strftime("%Y-%m")
    table["is_paid"] = paid
    table["paid_on_time"] = (table["paid_date"] <= table["due_date"]).where(paid)
    has_discount = table["discount_date"].notna()
    table["discount_taken"] = (table["paid_date"] <= table["discount_date"]).where(paid & has_discount)
    table["path_type"] = table["invoice_id"].map(cases["path_type"])
    table["rework_loops"] = table["invoice_id"].map(cases["rework_loops"])
    return table


def headline_figures(invoices: pd.DataFrame, budgets: pd.DataFrame, events: pd.DataFrame,
                     case: dict) -> pd.DataFrame:
    """The figures every BI view must show, with where they come from (task 6.5)."""
    impact_result = impact.compute_all_impact(invoices, budgets)
    base = case["base"]
    rows = [
        ("total_spend_eur", kpis.total_spend(invoices), "kpis.total_spend"),
        ("invoices", len(invoices), "count of invoices"),
        ("hard_leakage_eur", impact_result["hard_leakage_eur"], "impact.compute_all_impact"),
        ("hard_leakage_pct_of_spend", impact_result["hard_leakage_pct_of_spend"], "impact.compute_all_impact"),
        ("spend_at_risk_eur", impact_result["spend_at_risk_eur"], "impact.compute_all_impact"),
        ("expected_duplicate_recovery_eur", impact_result["expected_duplicate_recovery_eur"], "impact.compute_all_impact"),
        ("dpo_days", kpis.days_payable_outstanding(invoices), "kpis.days_payable_outstanding"),
        ("agreed_payment_days", kpis.agreed_payment_days(invoices), "kpis.agreed_payment_days"),
        ("on_time_payment_pct", kpis.on_time_payment_rate(invoices), "kpis.on_time_payment_rate"),
        ("discount_capture_pct", kpis.discount_capture_rate(invoices), "kpis.discount_capture_rate"),
        ("po_compliance_pct", kpis.po_compliance(invoices), "kpis.po_compliance"),
        ("rework_pct", kpis.rework_rate(invoices, events), "kpis.rework_rate"),
        ("investment_eur", base["investment_eur"], "business_case (base)"),
        ("annual_hard_benefit_eur", base["annual_hard_benefit_eur"], "business_case (base)"),
        ("npv_hard_eur", base["hard"]["npv_eur"], "business_case (base)"),
        ("roi_hard_pct", base["hard"]["roi_pct"], "business_case (base)"),
        ("payback_hard_months", base["hard"]["payback_months"], "business_case (base)"),
        ("npv_with_estimated_eur", base["with_estimated"]["npv_eur"], "business_case (base)"),
    ]
    return pd.DataFrame(rows, columns=["figure", "value", "source"])


def control_report_all_months(invoices: pd.DataFrame, budgets: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    frames = [control.control_report(invoices, budgets, events, m).assign(month=m) for m in control.months(invoices)]
    report = pd.concat(frames, ignore_index=True)
    return report[["month"] + [c for c in report.columns if c != "month"]]


def build_exports() -> dict[str, pd.DataFrame]:
    invoices, budgets, events, vendors = kpis.load_invoices(), kpis.load_budgets(), kpis.load_events(), kpis.load_vendors()
    case = business_case.compute_business_case(invoices, budgets, events)
    return {
        "invoices": invoices_table(invoices, events),
        "vendors": vendors,
        "budgets": budgets,
        "invoice_events": events,
        "leakage_by_driver": impact.leakage_summary(invoices, budgets),
        "leakage_by_cause": root_cause.leakage_pareto(invoices, events),
        "leakage_by_invoice": root_cause.leakage_by_invoice(invoices, events),
        "business_case_levers": case["base"]["levers"],
        "business_case_scenarios": case["scenarios"],
        "business_case_tornado": case["tornado"],
        "impact_effort_matrix": recommendations.impact_effort_matrix(case["base"]["levers"]),
        "ctq_baseline": pd.read_csv(control.baseline.CTQ_BASELINE_FILE),
        "control_report": control_report_all_months(invoices, budgets, events),
        "headline_figures": headline_figures(invoices, budgets, events, case),
    }


def to_csv_text(frame: pd.DataFrame) -> str:
    # Dates as ISO text, so the files are identical on every run and every OS.
    out = frame.copy()
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].dt.strftime("%Y-%m-%d")
    return out.to_csv(index=False, lineterminator="\n")


def write_exports(exports: dict[str, pd.DataFrame], directory: Path = BI_DATA_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, frame in exports.items():
        (directory / f"{name}.csv").write_text(to_csv_text(frame), encoding="utf-8")


if __name__ == "__main__":
    write_exports(build_exports())
    print(f"wrote {len(list(BI_DATA_DIR.glob('*.csv')))} files to {BI_DATA_DIR}")
