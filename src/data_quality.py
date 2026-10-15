"""Data quality: what the extract got wrong, and what each figure leaves out (US-08).

Three views, for the AP Manager who has to trust the baseline and get the gaps
fixed where they start:

1. **Repaired in cleaning.** The notebook fixes typing and format problems and
   logs each kind of repair (data/processed/cleaning_log.parquet). The data is
   usable, but next month's extract will have the same problems until the entry
   screen or the supplier master is fixed.
2. **Open issues.** Checks on the cleaned data. An invoice that fails one is kept
   (its amount still counts towards spend) but left out of the figures that need
   the missing or inconsistent field.
3. **Coverage per figure.** For each headline figure, how many invoices it uses
   and why the rest are left out, so no invoice is dropped silently.

Like kpis.py this reads only data/processed/.
"""

import pandas as pd

from src.kpis import PROCESSED_DIR

AP_MANAGER = "AP Manager"
PROCUREMENT = "Procurement lead"
CONTROLLING = "Controlling"
IT = "IT (ERP team)"

# How each kind of cleaning repair is stopped at its source, and who owns that.
SOURCE_FIXES = {
    ("invoices", "department"): ("Pick-list instead of free text at invoice entry", IT),
    ("invoices", "category"): ("Pick-list instead of free text at invoice entry", IT),
    ("invoices", "status"): ("Status set by the workflow, not typed", IT),
    ("invoices", "invoice_date"): ("Date field with one fixed format in the entry screen", IT),
    ("invoices", "po_number"): ("PO field checked against open POs; 'no PO' as an explicit choice", IT),
    ("vendors", "vendor_name"): ("Name check when a supplier is created", PROCUREMENT),
    ("vendors", "payment_terms"): ("Terms chosen from a list of standard terms; yearly review", PROCUREMENT),
}


def load_cleaning_log() -> pd.DataFrame:
    return pd.read_parquet(PROCESSED_DIR / "cleaning_log.parquet")


def cleaning_repairs(cleaning_log: pd.DataFrame) -> pd.DataFrame:
    """The notebook's repairs, each with the fix at the source and its owner.
    A field without a known fix raises a KeyError, so a new repair in the
    notebook can't reach the app without an owner.
    """
    fixes = [SOURCE_FIXES[(table, field)] for table, field in zip(cleaning_log["table"], cleaning_log["field"])]
    return cleaning_log.assign(
        fix_at_source=[fix for fix, _ in fixes],
        owner=[owner for _, owner in fixes],
    )


# --- Open issues ------------------------------------------------------------------

def _first_budget_month(budgets: pd.DataFrame) -> str:
    return budgets["month"].min()


def _checks(invoices: pd.DataFrame, budgets: pd.DataFrame, vendors: pd.DataFrame) -> list[tuple]:
    """(check, failing rows, what it affects, fix at the source, owner) for every check.
    Checks that pass today stay in the list: a check that finds nothing is
    evidence too, and it catches the problem if a later extract has it.
    """
    paid = invoices["paid_date"].notna()
    month = invoices["invoice_date"].dt.strftime("%Y-%m")
    return [
        ("No submission date", invoices["missing_submitted_date"],
         "Processing time; submit → approve and submit → pay stages; processing-delay check",
         "Submission date set automatically when the invoice is submitted", AP_MANAGER),
        ("Paid without an approval date", paid & invoices["approved_date"].isna(),
         "Approve → pay stage. Also a control breach (Measure baseline)",
         "Payment run releases approved invoices only", AP_MANAGER),
        ("Paid before the approval date", paid & (invoices["paid_date"] < invoices["approved_date"]),
         "Approve → pay stage. Also a control breach (Measure baseline)",
         "Payment run releases approved invoices only", AP_MANAGER),
        ("Invoice dated before the first budget month", month < _first_budget_month(budgets),
         "Budget vs actual and the budget-overrun check: not compared with any budget",
         "Budget file covers every month in the extract", CONTROLLING),
        ("Submitted before the invoice date", invoices["submitted_date"] < invoices["invoice_date"],
         "Processing time", "Entry screen rejects a submission date before the invoice date", IT),
        ("Approved before submission", invoices["approved_date"] < invoices["submitted_date"],
         "Submit → approve stage", "Workflow sets the approval date", IT),
        ("Supplier missing from the supplier master", ~invoices["vendor_id"].isin(vendors["vendor_id"]),
         "Payment terms, due dates and every supplier figure", "Invoice entry only for existing suppliers",
         PROCUREMENT),
        ("Amount zero or negative", invoices["amount"] <= 0,
         "Spend and every € figure", "Credit notes booked as their own document type", IT),
    ]


def invoice_issues(invoices: pd.DataFrame, budgets: pd.DataFrame, vendors: pd.DataFrame) -> pd.DataFrame:
    """One row per invoice and failed check: the list AP works through."""
    columns = ["invoice_id", "vendor_id", "vendor_name", "department", "amount", "invoice_date", "status"]
    frames = [
        invoices.loc[failing, columns].assign(check=check)
        for check, failing, *_ in _checks(invoices, budgets, vendors)
        if failing.any()
    ]
    if not frames:
        return pd.DataFrame(columns=columns + ["check"])
    return pd.concat(frames, ignore_index=True).sort_values(["check", "invoice_id"]).reset_index(drop=True)


def issue_summary(invoices: pd.DataFrame, budgets: pd.DataFrame, vendors: pd.DataFrame) -> pd.DataFrame:
    """One row per check: invoices and € failing it, what it affects, and the fix."""
    return pd.DataFrame([
        {
            "check": check,
            "invoices": int(failing.sum()),
            "amount_eur": round(float(invoices.loc[failing, "amount"].sum()), 2),
            "affects": affects,
            "fix_at_source": fix,
            "owner": owner,
        }
        for check, failing, affects, fix, owner in _checks(invoices, budgets, vendors)
    ])


# --- Coverage per figure -------------------------------------------------------------

def kpi_coverage(invoices: pd.DataFrame, budgets: pd.DataFrame) -> pd.DataFrame:
    """For each headline figure: the invoices it could use, how many it does
    use, and the count for each reason the rest are left out. Open invoices are
    not an error, but they are still left out of every payment figure, so they
    are counted like any other exclusion.
    """
    paid = invoices["paid_date"].notna()
    approved = invoices["approved_date"].notna()
    no_submission = invoices["missing_submitted_date"]
    paid_without_approval = paid & ~approved
    paid_before_approval = paid & (invoices["paid_date"] < invoices["approved_date"])
    before_budget = invoices["invoice_date"].dt.strftime("%Y-%m") < _first_budget_month(budgets)
    has_discount = invoices["discount_date"].notna()
    everything = pd.Series(True, index=invoices.index)

    figures = [
        ("Total spend, PO compliance, duplicate check", "All invoices", everything, []),
        ("Budget vs actual, budget-overrun check", "All invoices", everything,
         [("dated before the first budget month", before_budget)]),
        ("Processing time (submission to payment)", "All invoices", everything,
         [("not paid yet", ~paid), ("no submission date", paid & no_submission)]),
        ("Submit → approve", "All invoices", everything,
         [("not approved yet", ~approved & ~paid), ("paid without approval", paid_without_approval),
          ("no submission date", approved & no_submission)]),
        ("Approve → pay", "All invoices", everything,
         [("not paid yet", ~paid), ("paid without approval", paid_without_approval),
          ("paid before approval", paid_before_approval)]),
        ("Days payable outstanding, on-time payment rate", "All invoices", everything,
         [("not paid yet", ~paid)]),
        ("Early-payment discount capture (invoices with discount terms)", "Invoices with discount terms", has_discount,
         [("not paid yet", has_discount & ~paid)]),
    ]
    rows = []
    for figure, population_label, population, reasons in figures:
        excluded = pd.Series(False, index=invoices.index)
        notes = []
        for reason, mask in reasons:
            mask = mask & population
            # A reason only counts invoices no earlier reason has taken, so the counts add up.
            new = mask & ~excluded
            if new.any():
                notes.append(f"{int(new.sum()):,} {reason}")
            excluded |= new
        rows.append({
            "figure": figure,
            "population": population_label,
            "invoices": int(population.sum()),
            "included": int((population & ~excluded).sum()),
            "excluded": int(excluded.sum()),
            "excluded_because": " · ".join(notes) if notes else "nothing left out",
        })
    return pd.DataFrame(rows)


def headline(issues: pd.DataFrame, summary: pd.DataFrame, coverage: pd.DataFrame) -> str:
    """One answer-first sentence for the top of the data-quality view. Invoices
    are counted once even when they fail more than one check.
    """
    affected = issues.drop_duplicates("invoice_id")
    return (
        f"{int((summary['invoices'] > 0).sum())} of {len(summary)} checks find issues in "
        f"{len(affected):,} invoices (€{affected['amount'].sum():,.0f}). No invoice is deleted: "
        f"{int((coverage['excluded'] > 0).sum())} of {len(coverage)} figures leave some out, and say how many and why."
    )
