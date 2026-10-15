# As-is process model: invoice-to-pay at Rheinwerk HQ

> **Portfolio note.** Rheinwerk Komponenten GmbH is a fictional client and all data is synthetic.

This is the invoice-to-pay process **as the people who run it describe it**, modelled in BPMN 2.0. It is
more detailed than the [SIPOC](02_sipoc.md). It shows who does each step, where invoices wait and where
money leaks. In Analyze (task 4.1), process mining compares this model with the process **as it actually
runs** in the data. The differences between the two are findings in themselves.

**Source file:** [`bpmn/as_is_invoice_to_pay.bpmn`](bpmn/as_is_invoice_to_pay.bpmn) (BPMN 2.0 XML). Open it in
[Camunda Modeler](https://camunda.com/download/modeler/) or in the browser at [demo.bpmn.io](https://demo.bpmn.io)
(drag the file onto the page).

## The model

```mermaid
flowchart LR
    SUP(["Supplier"]) -. invoice .-> S
    subgraph CLK["AP clerk"]
        S(("Invoice<br/>received")) --> T1["Open and sort<br/>AP inbox (daily)"]
        T1 --> T2["Enter invoice<br/>in ERP by hand"]
        T2 --> G1{"PO<br/>exists?"}
        G1 -- Yes --> T3["Match invoice<br/>to PO"]
        G1 -- No --> T4
        T3 --> T4["Submit for<br/>approval"]
        T6["Correct invoice or<br/>query supplier"] --> T4
        W(("Weekly<br/>payment run")) --> T7["Create payment proposal<br/>(all approved invoices)"]
        T10["Post payment and<br/>clear invoice"] --> E(("Invoice<br/>closed"))
    end
    subgraph BO["Budget owner"]
        T5["Review and<br/>approve invoice"] --> G2{"Approved?"}
    end
    subgraph MGR["AP Manager"]
        T8["Release payment<br/>proposal"]
    end
    subgraph TRE["Treasury"]
        T9["Execute bank<br/>transfer"]
    end
    T4 --> T5
    G2 -- No --> T6
    G2 -- Yes --> W
    T7 --> T8 --> T9 --> T10
    T9 -. payment .-> SUP

    classDef leak fill:#fde8e8,stroke:#e34948,color:#000
    class T1,T2,G1,T5,T6,T7 leak
```

*Red: a leakage point (see the table below). This is a simplified preview: the BPMN file is the reference
model, with message events, the timer and the leakage annotations. Not shown here: Controlling's
separate month-end flow (month-end close → budget vs actual report → overruns reported).*

## Steps, timestamps and leakage points

| # | Step | Lane | Timestamp in the data | Leakage point | Hypothesis |
|---|---|---|---|---|---|
| 1 | Invoice received (message from the supplier) | AP clerk | `invoice_date` | | |
| 2 | Open and sort AP inbox, daily | AP clerk | | Invoices wait unopened while the discount window runs | B2 |
| 3 | Enter invoice in ERP by hand | AP clerk | | **No duplicate check**: a re-sent invoice is entered as new | A1 |
| 4 | PO exists? Yes → match invoice to PO. No → skip | AP clerk | | No PO: maverick spend, and no check against an agreed price | C2, A2 |
| 5 | Submit for approval | AP clerk | `submitted_date` (missing for 24 invoices) | | |
| 6 | Review and approve | Budget owner | `approved_date` | Approver **cannot see the remaining budget**; the longest wait | C1, D2 |
| 7 | Not approved → correct invoice or query supplier → resubmit | AP clerk | None yet (Phase 2.3 adds these events) | Rework loop | D1 |
| 8 | Wait for the weekly payment run | (timer) | | | |
| 9 | Create payment proposal: **every approved invoice**, whatever its terms | AP clerk | | Paid late (fees), too late for the discount, or too early | B1, B2, B3 |
| 10 | Release payment proposal | AP Manager | | | |
| 11 | Execute bank transfer (message to the supplier) | Treasury | `paid_date` | | |
| 12 | Post payment and clear invoice | AP clerk | | | |
| — | Month-end close → budget vs actual report | Controlling | (monthly) | Overruns found only after close, too late to stop | C1 |

## Where the time goes

Elapsed days between the timestamps, all 12 months (preliminary, from the current extract):

| Stage | Steps | Median | Mean | 90th percentile | Max |
|---|---|---|---|---|---|
| Receive → submit | 1–5 | 3 | 2.5 | 5 | 5 |
| **Submit → approve** | 5–7 | **4** | **5.4** | **10** | 40 |
| Approve → pay | 8–11 | 3 | 4.6 | 8 | 66 |
| **Invoice → pay (total)** | 1–11 | 10 | 12.5 | 18 | 95 |

Receive → submit and submit → approve exclude the 24 invoices with no submission date.

- **Approval is the longest stage.** It takes 43% of the average time from invoice to payment, and it has the
  widest spread. This supports hypothesis D2 and is where Analyze looks first.
- **Approve → pay has a median of 3 days**, which fits a weekly payment run (an average wait of 3.5 days).
  The run adds waiting time to every invoice, and it pays without looking at due or discount dates.
- **The rework loop cannot be measured yet.** A rejected invoice is resubmitted, but the data keeps only the
  final dates, so its rework time is hidden inside "submit → approve". Phase 2.3 adds the reject and resubmit events.

## What the model tells us

1. **Leakage happens at hand-offs and checks no one owns.** Steps 3, 6 and 9 are where the four control
   tasks without an Accountable owner (see the [process RACI](04_stakeholders_and_raci.md#4-process-raci-invoice-to-pay-today))
   should happen.
2. **The payment run ignores payment terms.** One rule for all invoices means some are paid too late, some
   miss the discount and some are paid too early. This one step drives all three timing hypotheses (B1–B3).
3. **Budget information arrives after the decision.** The approver decides in step 6. Controlling reports on
   budgets only after month-end close. The to-be process needs the remaining budget visible at the point
   of approval.
4. **Two steps leave no trace in the data:** the duplicate check (it does not exist) and the rework loop.
   What the process does not record cannot be monitored, so both are in the Phase 2 data extension and the
   control plan.

## Modelling conventions

- BPMN 2.0, with one pool for Rheinwerk HQ and one collapsed pool for the supplier. Message flows show
  the invoice and the payment.
- **Lanes are roles, never named people**, in line with the works-council decision in the
  [stakeholder map](04_stakeholders_and_raci.md).
- Text annotations mark each leakage point with its issue-tree hypothesis ID.
- User tasks are done by a person in the ERP. "Execute bank transfer" is a plain task: Treasury sends the
  payment file and the bank interface does the rest.
- The as-is model shows what people *say* happens. It is validated against the event log in Analyze (4.1,
  4.2): a discovered process map, its variants, and a conformance check (paid without approval, paid before approval).
