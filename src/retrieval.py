"""RAG-lite retrieval layer.

Real RAG: embed a question, run vector similarity search over a document
store, hand the top-k chunks to an LLM. There's no vector DB here on
purpose — the "documents" are a handful of already-computed KPI tables and
anomaly records (data/processed/), not unstructured text, and the topics a
user can ask about are a small enumerable set. So retrieval here is
keyword/topic matching over those precomputed facts, doing the same job
(narrow the context before it reaches an LLM) without the machinery.

This module never calls Gemini and never passes raw invoice rows on — it only
narrows down which *already-computed* facts are relevant. Facts are aggregates
(totals, rates, per-group tables) plus at most MAX_ROWS anomaly flags, each
with its rule; tests/test_retrieval.py checks the request payload for this.
See src/insights.py for the LLM call that narrates whatever this returns.
"""

import pandas as pd

from src.anomalies import detect_all
from src.impact import compute_all_impact
from src.kpis import (
    agreed_payment_days,
    avg_processing_days,
    budget_vs_actual,
    days_payable_outstanding,
    discount_capture_rate,
    discount_deadlines,
    load_budgets,
    load_invoices,
    load_vendors,
    no_po_spend_by_preferred,
    on_time_payment_rate,
    po_compliance,
    spend_by_category,
    spend_by_department,
    spend_by_vendor,
    stage_durations,
    total_spend,
    vendor_pareto,
    vendors_for_spend_share,
)
from src.recommendations import rank_recommendations

TOPIC_KEYWORDS = {
    "duplicate_payment": ["duplicate", "double pay", "double-pay", "paid twice"],
    "processing_time_outlier": ["processing time", "delay", "slow", "late", "stuck", "bottleneck", "turnaround"],
    "budget_overrun": ["budget", "overrun", "over budget", "overspend", "variance"],
    "vendor": ["vendor", "supplier", "concentrat", "consolidat", "pareto", "80/20"],
    "spend": ["spend", "spending", "cost", "expense", "how much"],
    "leakage": ["leak", "losing", "lost", "lose", "impact", "money", "saving", "recover", "business case",
                "fix", "recommend", "priorit", "what should"],
    "payment_timing": ["dpo", "days payable", "on time", "on-time", "early", "late pay", "payment terms",
                       "terms", "discount", "working capital", "cash"],
    "purchase_order": ["purchase order", "maverick", "po compliance", "no po", "without a po",
                       "without po", "preferred", "off-contract"],
}
ANOMALY_TOPICS = {"duplicate_payment", "processing_time_outlier", "budget_overrun"}
MAX_ROWS = 15


def _detect_topics(question: str) -> set:
    q = question.lower()
    matched = {topic for topic, keywords in TOPIC_KEYWORDS.items() if any(kw in q for kw in keywords)}
    return matched or {"overview"}


def _detect_entity(question: str, values) -> str | None:
    q = question.lower()
    for value in sorted(set(values), key=len, reverse=True):
        if value.lower() in q:
            return value
    return None


def enrich_anomalies_with_dims(anomalies_df: pd.DataFrame, invoices: pd.DataFrame) -> pd.DataFrame:
    lookup = invoices.set_index("invoice_id")[["department", "category"]]
    enriched = anomalies_df.copy()
    has_invoice = enriched["invoice_id"].notna()
    enriched.loc[has_invoice, ["department", "category"]] = lookup.reindex(
        enriched.loc[has_invoice, "invoice_id"]
    ).values
    return enriched


def retrieve(question: str, invoices: pd.DataFrame = None, budgets: pd.DataFrame = None) -> dict:
    """Return only the precomputed facts relevant to a free-text question."""
    if invoices is None:
        invoices = load_invoices()
    if budgets is None:
        budgets = load_budgets()

    topics = _detect_topics(question)
    department = _detect_entity(question, invoices["department"])
    category = _detect_entity(question, invoices["category"])

    scoped = invoices
    if department:
        scoped = scoped[scoped["department"] == department]
    if category:
        scoped = scoped[scoped["category"] == category]

    facts = {
        "question": question,
        "topics": sorted(topics),
        "filters": {"department": department, "category": category},
        "total_spend": total_spend(scoped),
        "avg_processing_days": avg_processing_days(scoped),
    }

    if "spend" in topics or "overview" in topics:
        facts["spend_by_department"] = spend_by_department(scoped).to_dict("records")
        facts["spend_by_category"] = spend_by_category(scoped).to_dict("records")

    if "vendor" in topics:
        facts["top_vendors"] = spend_by_vendor(scoped).to_dict("records")
        pareto = vendor_pareto(scoped)
        facts["supplier_concentration"] = {
            "suppliers_with_spend": len(pareto),
            "suppliers_making_up_80pct_of_spend": vendors_for_spend_share(pareto, 80.0),
        }

    if "leakage" in topics or "overview" in topics:
        scoped_budgets = budgets
        if department:
            scoped_budgets = scoped_budgets[scoped_budgets["department"] == department]
        if category:
            scoped_budgets = scoped_budgets[scoped_budgets["category"] == category]
        impact = compute_all_impact(scoped, scoped_budgets)
        facts["leakage"] = {
            "period": "12 months to the extract date, 2026-08-31",
            "hard_leakage_eur": impact["hard_leakage_eur"],
            "hard_leakage_pct_of_spend": impact["hard_leakage_pct_of_spend"],
            "controllable_spend_at_risk_eur": impact["spend_at_risk_eur"],
            "expected_duplicate_recovery_eur": impact["expected_duplicate_recovery_eur"],
            "by_driver": impact["summary"].drop(columns="base_eur").to_dict("records"),
            "assumptions": impact["assumptions"],
        }
        facts["recommendations"] = (
            rank_recommendations(impact["summary"])
            .drop(columns="drivers")
            .to_dict("records")
        )

    if "payment_timing" in topics:
        deadlines = discount_deadlines(scoped)
        facts["payment_timing"] = {
            "dpo_days_amount_weighted": days_payable_outstanding(scoped),
            "agreed_net_terms_days_amount_weighted": agreed_payment_days(scoped),
            "on_time_payment_pct": on_time_payment_rate(scoped),
            "discount_capture_pct": discount_capture_rate(scoped),
            "open_invoices_with_discount_still_claimable": len(deadlines),
            "discount_still_claimable_eur": round(float(deadlines["discount_eur"].sum()), 2),
        }

    if "purchase_order" in topics:
        facts["purchase_orders"] = {
            "po_compliance_pct_of_spend": po_compliance(scoped),
            "po_compliance_by_department": po_compliance(scoped, by="department").to_dict("records"),
            "no_po_spend_by_preferred_supplier": no_po_spend_by_preferred(scoped, load_vendors()).to_dict("records"),
        }

    if "processing_time_outlier" in topics:
        facts["stage_durations_days"] = stage_durations(scoped).to_dict("records")

    if "budget_overrun" in topics or "overview" in topics:
        bva = budget_vs_actual(invoices, budgets)
        if department:
            bva = bva[bva["department"] == department]
        if category:
            bva = bva[bva["category"] == category]
        facts["budget_vs_actual"] = bva.sort_values("variance_pct", ascending=False).head(MAX_ROWS).to_dict("records")

    anomalies_df = enrich_anomalies_with_dims(detect_all(invoices, budgets), invoices)
    if department:
        anomalies_df = anomalies_df[anomalies_df["department"] == department]
    if category:
        anomalies_df = anomalies_df[anomalies_df["category"] == category]

    anomaly_types_wanted = topics & ANOMALY_TOPICS
    if anomaly_types_wanted:
        anomalies_df = anomalies_df[anomalies_df["anomaly_type"].isin(anomaly_types_wanted)]

    facts["anomaly_counts"] = anomalies_df["anomaly_type"].value_counts().to_dict()
    # Individual flags only when the question is about anomalies (or is open):
    # a PO or payment-timing question gains nothing from 15 duplicate flags.
    if anomaly_types_wanted or "overview" in topics:
        facts["anomalies"] = anomalies_df.head(MAX_ROWS).to_dict("records")

    return facts


if __name__ == "__main__":
    import json

    for q in [
        "What duplicate payments were found in Marketing?",
        "How much did we spend on Consulting?",
        "Any budget overruns?",
        "How much money is AP leaking?",
        "Are we paying suppliers on time?",
        "What's the average processing time?",
    ]:
        print(f"Q: {q}")
        result = retrieve(q)
        print(json.dumps({k: v for k, v in result.items() if k != "anomalies"}, indent=2, default=str))
        print(f"anomalies returned: {len(result.get('anomalies', []))}")
        print()
