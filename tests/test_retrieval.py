"""Retrieval: the right facts for each question, the same figures as the
analysis modules, and a request payload that holds aggregates only (NFR-02).
"""

import json
import re

import pytest

from src import impact, insights, kpis, retrieval
from src.answers import BRIEFING_QUESTION, SUGGESTED_QUESTIONS

QUESTIONS = [
    BRIEFING_QUESTION,
    *SUGGESTED_QUESTIONS,
    "How much did we spend on Consulting?",
    "Any budget overruns in Marketing?",
    "What's our PO compliance?",
    "Which suppliers could we consolidate?",
    "What is our DPO compared with the payment terms?",
    "How much is IT leaking, and what should we fix first?",
    "Hello",
]


@pytest.fixture(scope="module")
def invoices():
    return kpis.load_invoices()


@pytest.fixture(scope="module")
def budgets():
    return kpis.load_budgets()


def payload_facts(question: str, invoices, budgets) -> tuple[dict, str]:
    """The facts exactly as they appear in the request body sent to Gemini."""
    body = insights.build_request_body(retrieval.retrieve(question, invoices, budgets))
    text = body["contents"][0]["parts"][0]["text"]
    return json.loads(text.split("Precomputed facts (JSON):\n", 1)[1]), text


def all_keys(value) -> set:
    if isinstance(value, dict):
        return set(value) | set().union(*(all_keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(all_keys(v) for v in value))
    return set()


def all_lists(value) -> list:
    if isinstance(value, dict):
        return [lst for v in value.values() for lst in all_lists(v)]
    if isinstance(value, list):
        return [value] + [lst for v in value for lst in all_lists(v)]
    return []


# --- NFR-02: the payload holds aggregates only --------------------------------

@pytest.mark.parametrize("question", QUESTIONS)
def test_payload_has_no_invoice_level_fields(question, invoices, budgets):
    # Identifiers and dimensions may appear (in anomaly flags and group tables);
    # dates, amounts, terms, PO numbers and statuses of single invoices may not.
    row_level_fields = set(invoices.columns) - {"invoice_id", "vendor_id", "vendor_name", "department", "category"}
    facts, _ = payload_facts(question, invoices, budgets)
    assert not all_keys(facts) & row_level_fields


@pytest.mark.parametrize("question", QUESTIONS)
def test_payload_is_bounded_whatever_the_question(question, invoices, budgets):
    facts, text = payload_facts(question, invoices, budgets)
    assert all(len(lst) <= retrieval.MAX_ROWS for lst in all_lists(facts))
    # Each flag names its own invoice and at most one it matches.
    assert len(set(re.findall(r"INV\d{5}", text))) <= 2 * retrieval.MAX_ROWS
    assert len(text) < 20_000


# --- The right facts for the question --------------------------------------------

@pytest.mark.parametrize("question, expected_key", [
    ("How much money is AP leaking?", "leakage"),
    ("What should we fix first?", "recommendations"),
    ("Are we paying suppliers on time?", "payment_timing"),
    ("How many discounts do we miss?", "payment_timing"),
    ("What's our PO compliance?", "purchase_orders"),
    ("How much maverick spend is there?", "purchase_orders"),
    ("Which suppliers could we consolidate?", "supplier_concentration"),
    ("Where are invoices getting delayed?", "stage_durations_days"),
    ("Hello", "leakage"),
])
def test_question_retrieves_the_matching_facts(question, expected_key, invoices, budgets):
    assert expected_key in retrieval.retrieve(question, invoices, budgets)


def test_briefing_leads_with_leakage_and_recommendations(invoices, budgets):
    facts = retrieval.retrieve(BRIEFING_QUESTION, invoices, budgets)
    assert {"leakage", "recommendations", "budget_vs_actual", "anomalies"} <= set(facts)


def test_non_anomaly_question_gets_counts_but_no_individual_flags(invoices, budgets):
    facts = retrieval.retrieve("What's our PO compliance?", invoices, budgets)
    assert "anomaly_counts" in facts
    assert "anomalies" not in facts


# --- One version of the truth -------------------------------------------------------

def test_leakage_facts_equal_the_impact_module(invoices, budgets):
    leakage = retrieval.retrieve("How much money is AP leaking?", invoices, budgets)["leakage"]
    expected = impact.compute_all_impact(invoices, budgets)
    assert leakage["hard_leakage_eur"] == expected["hard_leakage_eur"]
    assert leakage["controllable_spend_at_risk_eur"] == expected["spend_at_risk_eur"]
    assert leakage["expected_duplicate_recovery_eur"] == expected["expected_duplicate_recovery_eur"]


def test_payment_timing_facts_equal_the_kpis(invoices, budgets):
    timing = retrieval.retrieve("What is our DPO?", invoices, budgets)["payment_timing"]
    assert timing["dpo_days_amount_weighted"] == kpis.days_payable_outstanding(invoices)
    assert timing["on_time_payment_pct"] == kpis.on_time_payment_rate(invoices)
    assert timing["discount_capture_pct"] == kpis.discount_capture_rate(invoices)
    assert timing["open_invoices_with_discount_still_claimable"] == len(kpis.discount_deadlines(invoices))


def test_department_question_scopes_the_leakage(invoices, budgets):
    company = retrieval.retrieve("How much money is AP leaking?", invoices, budgets)["leakage"]
    it_only = retrieval.retrieve("How much is IT leaking?", invoices, budgets)
    expected = impact.compute_all_impact(invoices[invoices["department"] == "IT"],
                                         budgets[budgets["department"] == "IT"])
    assert it_only["filters"]["department"] == "IT"
    assert it_only["leakage"]["hard_leakage_eur"] == expected["hard_leakage_eur"]
    assert it_only["leakage"]["hard_leakage_eur"] < company["hard_leakage_eur"]
