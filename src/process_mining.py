"""Process mining on the invoice event log: how invoice-to-pay actually runs.

The invoice timestamps (submitted, approved, paid) only show how long each stage
took. The event log also shows the path each invoice took: rework loops, skipped
approvals, payments made before the approval. Process mining compares those
paths with the process as the AP team describes it (docs/06_as_is_process.md).
The differences between the two are findings in themselves.

pm4py does the process-mining part: it discovers the directly-follows graph
and the variants, and it checks conformance with alignments. Durations and €
are plain pandas aggregations over the same log, like the rest of the KPIs.

The log is at role level only (AP clerk, Budget owner, Treasury), never a
person, so nothing here can be used to monitor individual employees
(works council, § 87(1) no. 6 BetrVG; see the Decisions log).

Like kpis.py this reads only data/processed/. Nothing here reads the answer key.
"""

import pandas as pd
import pm4py
from pm4py.util import constants as pm4py_constants

# pm4py draws tqdm progress bars by default; they clutter the app and test output.
pm4py_constants.SHOW_PROGRESS_BAR = False

RECEIVE = "Receive invoice"
SUBMIT = "Submit for approval"
REJECT = "Reject invoice"
CORRECT = "Correct and resubmit"
APPROVE = "Approve invoice"
PAY = "Pay invoice"

# Activities in process order, for drawing the map left to right.
ACTIVITY_ORDER = [RECEIVE, SUBMIT, REJECT, CORRECT, APPROVE, PAY]

# The approved process: receive, submit, any number of reject-and-correct
# loops, approve, pay. This is the as-is BPMN model's main flow. A rework loop
# is allowed (costly, but within policy); paying before or without an
# approval is not. pm4py process-tree notation: -> is a sequence, *(do, redo)
# a loop, tau a silent step.
NORMATIVE_PROCESS = (
    f"->( '{RECEIVE}', '{SUBMIT}', *( tau, ->( '{REJECT}', '{CORRECT}' ) ), '{APPROVE}', '{PAY}' )"
)

# The steps that may directly follow each other in NORMATIVE_PROCESS. The
# process map draws every other transition as a deviation. A test checks this
# set against what the conforming invoices actually do.
NORMATIVE_TRANSITIONS = {
    (RECEIVE, SUBMIT), (SUBMIT, APPROVE), (SUBMIT, REJECT), (REJECT, CORRECT),
    (CORRECT, APPROVE), (CORRECT, REJECT), (APPROVE, PAY),
}

# Path types, in the order they are checked: the first that applies wins. A
# control breach outranks a missing submission because it is the bigger risk.
OPEN = "Open at extract"
BREACH = "Control breach"
NO_SUBMISSION = "Submission not recorded"
REWORK = "Rework"
STRAIGHT_THROUGH = "Straight through"
PATH_TYPES = [STRAIGHT_THROUGH, REWORK, NO_SUBMISSION, BREACH, OPEN]

PAID_BEFORE_APPROVAL = "Paid before approval"
PAID_WITHOUT_APPROVAL = "Paid without approval"

SECONDS_PER_DAY = 86_400


def _pm4py_keys() -> dict:
    """Column names of our log, so pm4py reads it without renaming."""
    return {"case_id_key": "invoice_id", "activity_key": "activity", "timestamp_key": "timestamp"}


def _in_time_order(events: pd.DataFrame) -> pd.DataFrame:
    """pm4py keeps the row order within a case instead of sorting by time, so
    every log is sorted before it reaches pm4py.
    """
    return events.sort_values(["invoice_id", "timestamp"], kind="stable")


def traces(events: pd.DataFrame) -> pd.Series:
    """Each invoice's activities in time order, as a tuple, indexed by invoice_id."""
    return _in_time_order(events).groupby("invoice_id")["activity"].agg(tuple)


def path_type(trace: tuple) -> str:
    """Business label for one invoice's path; see PATH_TYPES for the order."""
    if PAY not in trace:
        return OPEN
    if control_breach(trace) is not None:
        return BREACH
    if SUBMIT not in trace:
        return NO_SUBMISSION
    if REJECT in trace:
        return REWORK
    return STRAIGHT_THROUGH


def control_breach(trace: tuple) -> str | None:
    """Which approval control a paid invoice broke, if any."""
    if PAY not in trace:
        return None
    if APPROVE not in trace:
        return PAID_WITHOUT_APPROVAL
    if trace.index(PAY) < trace.index(APPROVE):
        return PAID_BEFORE_APPROVAL
    return None


def process_map(events: pd.DataFrame) -> pd.DataFrame:
    """Directly-follows graph: one row per pair of activities that follow each
    other, with how often and the median wait between them. The waits show the
    bottlenecks: where invoices sit, not who is slow.
    """
    events = _in_time_order(events)
    frequency, _, _ = pm4py.discover_dfg(events, **_pm4py_keys())
    performance, _, _ = pm4py.discover_performance_dfg(events, **_pm4py_keys())
    edges = pd.DataFrame(
        [
            {
                "source": source,
                "target": target,
                "transitions": count,
                "median_wait_days": round(performance[(source, target)]["median"] / SECONDS_PER_DAY, 1),
            }
            for (source, target), count in frequency.items()
        ]
    )
    edges["allowed"] = [(s, t) in NORMATIVE_TRANSITIONS for s, t in zip(edges["source"], edges["target"])]
    edges["share_of_source_pct"] = (
        edges["transitions"] / edges.groupby("source")["transitions"].transform("sum") * 100
    ).round(1)
    return edges.sort_values(["transitions", "source", "target"], ascending=[False, True, True]).reset_index(drop=True)


def activity_counts(events: pd.DataFrame) -> pd.DataFrame:
    """Events and invoices per activity, in process order (the map's nodes)."""
    counts = (
        events.groupby("activity")
        .agg(events=("invoice_id", "size"), invoices=("invoice_id", "nunique"))
        .reindex(ACTIVITY_ORDER)
        .dropna()
        .astype(int)
        .reset_index()
    )
    return counts


def case_table(events: pd.DataFrame, invoices: pd.DataFrame) -> pd.DataFrame:
    """One row per invoice: its path, path type, rework loops and, once paid,
    its throughput time from receipt to payment (event timestamps, so part days).
    """
    paths = traces(events)
    first_receive = events[events["activity"] == RECEIVE].groupby("invoice_id")["timestamp"].min()
    paid_at = events[events["activity"] == PAY].groupby("invoice_id")["timestamp"].max()
    cases = pd.DataFrame({"path": paths})
    cases["path_type"] = cases["path"].map(path_type)
    cases["rework_loops"] = cases["path"].map(lambda p: p.count(REJECT))
    cases["throughput_days"] = (paid_at - first_receive).dt.total_seconds() / SECONDS_PER_DAY
    cases = cases.join(invoices.set_index("invoice_id")[["amount", "department", "vendor_id"]])
    return cases.reset_index()


def variants(events: pd.DataFrame, invoices: pd.DataFrame) -> pd.DataFrame:
    """Every distinct path through the process, most frequent first, with its
    share of invoices and spend and its throughput time (paid invoices only).
    """
    pm4py_variants = pm4py.get_variants(_in_time_order(events), **_pm4py_keys())
    cases = case_table(events, invoices)
    stats = (
        cases.groupby("path")
        .agg(
            spend=("amount", "sum"),
            median_days=("throughput_days", "median"),
            p90_days=("throughput_days", lambda d: d.quantile(0.9)),
            path_type=("path_type", "first"),
        )
    )
    table = pd.DataFrame(
        {"path": list(pm4py_variants), "invoices": list(pm4py_variants.values())}
    ).join(stats, on="path")
    table["steps"] = table["path"].map(len)
    table["path"] = table["path"].map(" → ".join)
    # Ties in frequency are broken by the path text, as in sql/process_variants.sql.
    table = table.sort_values(["invoices", "path"], ascending=[False, True]).reset_index(drop=True)
    table.insert(0, "variant", [f"V{n:02d}" for n in range(1, len(table) + 1)])
    table["share_pct"] = (table["invoices"] / table["invoices"].sum() * 100).round(1)
    table["cumulative_pct"] = (table["invoices"].cumsum() / table["invoices"].sum() * 100).round(1)
    table["spend"] = table["spend"].round(2)
    table["median_days"] = table["median_days"].round(1)
    table["p90_days"] = table["p90_days"].round(1)
    return table[["variant", "path", "path_type", "steps", "invoices", "share_pct", "cumulative_pct",
                  "spend", "median_days", "p90_days"]]


def throughput_by_path_type(events: pd.DataFrame, invoices: pd.DataFrame) -> pd.DataFrame:
    """Invoices, spend and receipt-to-payment days per path type. The rework
    rows answer "what does a rejection cost in time"; open invoices have no
    throughput yet and show their count only.
    """
    cases = case_table(events, invoices)
    table = (
        cases.groupby("path_type")
        .agg(
            invoices=("invoice_id", "count"),
            spend=("amount", "sum"),
            median_days=("throughput_days", "median"),
            p90_days=("throughput_days", lambda d: d.quantile(0.9)),
        )
        .reindex(PATH_TYPES)
        .dropna(subset=["invoices"])
        .reset_index()
    )
    table["invoices"] = table["invoices"].astype(int)
    table["share_pct"] = (table["invoices"] / table["invoices"].sum() * 100).round(1)
    table["spend"] = table["spend"].round(2)
    table["median_days"] = table["median_days"].round(1)
    table["p90_days"] = table["p90_days"].round(1)
    return table


def throughput_by_rework_loops(events: pd.DataFrame, invoices: pd.DataFrame) -> pd.DataFrame:
    """Receipt-to-payment days by number of rework loops, paid invoices that
    followed the approved process only, so breaches and data gaps don't blur it.
    """
    cases = case_table(events, invoices)
    conforming = cases[cases["path_type"].isin([STRAIGHT_THROUGH, REWORK])]
    table = (
        conforming.groupby("rework_loops")
        .agg(
            invoices=("invoice_id", "count"),
            median_days=("throughput_days", "median"),
            p90_days=("throughput_days", lambda d: d.quantile(0.9)),
        )
        .reset_index()
    )
    table["median_days"] = table["median_days"].round(1)
    table["p90_days"] = table["p90_days"].round(1)
    return table


# --- Conformance (Analyze 4.2) ------------------------------------------------

def _normative_net():
    tree = pm4py.parse_process_tree(NORMATIVE_PROCESS)
    return pm4py.convert_to_petri_net(tree)


def _describe_alignment(alignment: list) -> str:
    """Turn alignment moves into plain words. A log move (activity, '>>') is a
    step the approved process doesn't allow at that point; a model move
    ('>>', activity) is a step it requires that never happened. A step that is
    both happened, but at the wrong point.
    """
    extra = [log for log, model in alignment if model == ">>"]
    missing = [model for log, model in alignment if log == ">>" and model is not None]
    out_of_order = [a for a in extra if a in missing]
    parts = [f"{a} out of order" for a in out_of_order]
    parts += [f"{a} not allowed at this point" for a in extra if a not in out_of_order]
    parts += [f"{a} missing" for a in missing if a not in out_of_order]
    return "; ".join(parts)


def conformance(events: pd.DataFrame, invoices: pd.DataFrame) -> pd.DataFrame:
    """Every paid invoice that deviates from the approved process, with the
    deviation pm4py's alignments found and the business category.

    Only paid invoices are checked: an open invoice hasn't finished, so a
    missing approval or payment is not yet a deviation.
    """
    paid_ids = events.loc[events["activity"] == PAY, "invoice_id"].unique()
    paid_events = _in_time_order(events[events["invoice_id"].isin(paid_ids)])
    net, initial, final = _normative_net()
    alignments = pm4py.conformance_diagnostics_alignments(paid_events, net, initial, final, **_pm4py_keys())
    # pm4py returns one alignment per case, in the order the cases appear in the log.
    case_ids = paid_events.drop_duplicates("invoice_id")["invoice_id"].tolist()
    paths = traces(paid_events)
    rows = []
    for invoice_id, result in zip(case_ids, alignments):
        if result["fitness"] == 1.0:
            continue
        path = paths[invoice_id]
        rows.append({
            "invoice_id": invoice_id,
            "category": control_breach(path) or NO_SUBMISSION,
            "deviation": _describe_alignment(result["alignment"]),
            "fitness": round(result["fitness"], 3),
            "path": " → ".join(path),
        })
    deviations = pd.DataFrame(rows, columns=["invoice_id", "category", "deviation", "fitness", "path"])
    details = invoices.set_index("invoice_id")[
        ["vendor_name", "department", "amount", "approved_date", "paid_date"]
    ]
    deviations = deviations.join(details, on="invoice_id")
    return deviations.sort_values(["category", "invoice_id"]).reset_index(drop=True)


def conformance_summary(events: pd.DataFrame, invoices: pd.DataFrame) -> dict:
    """Headline conformance figures for paid invoices: how many followed the
    approved process, and the deviations by category with their spend.
    """
    deviations = conformance(events, invoices)
    paid = events.loc[events["activity"] == PAY, "invoice_id"].nunique()
    by_category = (
        deviations.groupby("category")
        .agg(invoices=("invoice_id", "count"), spend=("amount", "sum"))
        .reindex([PAID_BEFORE_APPROVAL, PAID_WITHOUT_APPROVAL, NO_SUBMISSION], fill_value=0)
    )
    by_category["spend"] = by_category["spend"].round(2)
    return {
        "paid_invoices": int(paid),
        "conforming_invoices": int(paid - len(deviations)),
        "conformance_pct": round((paid - len(deviations)) / paid * 100, 1),
        "by_category": by_category.reset_index(),
    }
