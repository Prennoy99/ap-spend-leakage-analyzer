# Project charter: AP Spend Leakage (DMAIC)

> **Portfolio note.** Rheinwerk Komponenten GmbH is a fictional client and all data is synthetic.
> The charter is written as it would be for a real engagement.

| | |
|---|---|
| **Client** | Rheinwerk Komponenten GmbH: precision machined components for machine builders. HQ in Germany, plants in Germany, Poland and Czechia. About €180M revenue and 900 staff. |
| **Project** | AP Spend Leakage: find, size and stop avoidable losses in the invoice-to-pay process |
| **Method** | Lean Six Sigma DMAIC (Define, Measure, Analyze, Improve, Control) |
| **Sponsor** | CFO |
| **Process owner** | AP Manager (Shared Finance Services, HQ) |
| **Project lead** | External consultant / business analyst |
| **Period** | 12 weeks, 19 Oct 2026 – 8 Jan 2027 |
| **Status** | Define: approved for Measure |

## 1. Background

During the FY2025/26 audit, the external auditors found several supplier invoices that had been paid twice.
Suppliers repaid them, but only because the suppliers noticed the duplicates. AP has no systematic duplicate check.
Budget owners also say they learn about overspending weeks after month-end, when it can no longer be prevented.

The CFO wants to know how much money the invoice-to-pay process is losing, where the losses come from,
and what it would take to stop them, before deciding whether to invest in AP automation.

## 2. Problem statement

In the 12 months to 31 August 2026, HQ paid **2,550 indirect-spend invoices worth €3.70M** to 40 suppliers.
A first review of the data found:

- **50 suspected duplicate payments** (same supplier, same amount, within 5 days), worth **€60k**.
- **50 of 432 department-category-months more than 15% over budget**, with **€337k** spent above budget in those months.
- Invoice processing (submission to payment) **averages 10.0 days**. The median is 8 days and
  10% of invoices take more than 15 days, up to 90 days.
- 24 invoices have no submission date, so their processing time cannot be measured.

None of these is monitored today, so the total cost to the business is unknown.

*Preliminary figures from the initial data extract. Measure (Phase 3) will confirm them and replace them.*

## 3. Goal statement

By **31 March 2027**, measured over the three months after go-live:

1. **No paid duplicate invoices.** Suspected duplicates are stopped before payment, and the €60k
   already paid twice has been claimed back from suppliers.
2. **Invoice processing time halved:** median from 8 to 4 days, and 90th percentile from 15 to 8 days.
3. **No unapproved overruns:** every department-category-month above 115% of budget has written budget-owner
   approval before month-end close.
4. **A € leakage baseline and a monthly control report** that the AP Manager owns and runs without the consultant.

Targets 2 and 3 are provisional. They will be confirmed with the process owner once Measure has set the baseline.

## 4. Scope

| In scope | Out of scope |
|---|---|
| Indirect spend at HQ: consulting, professional services, software and IT, facilities, office supplies, travel | Direct materials and production spend at the plants |
| Six HQ departments: Finance, HR, IT, Legal, Marketing, Operations | Payroll, intercompany invoices, tax payments |
| Invoice-to-pay: invoice received → submitted → approved → paid | Procure-to-order (sourcing, contracts, supplier selection) |
| Supplier master data needed for the analysis (payment terms, purchase orders) | Replacing or reconfiguring the ERP system |
| Recommendations, business case and control plan | Building the to-be automation (designed and costed only) |

The HQ indirect-spend pilot was chosen because it has the least purchase-order discipline and the
most manual approvals. If it succeeds, the same approach is rolled out to the plants.

## 5. Critical-to-quality metrics

| Metric | Definition | Baseline | Target |
|---|---|---|---|
| Duplicate payments | Invoice pairs, same supplier and amount, ≤ 5 days apart | 50 pairs / €60k | 0 paid |
| Processing time | Days from submission to payment | Median 8, P90 15 | Median 4, P90 8 |
| Unapproved budget overruns | Department-category-months > 115% of budget | 50 of 432 | 0 without approval |
| Missing process timestamps | Invoices with no submission date | 24 | 0 |
| PO compliance | % of invoice spend with a purchase order | Set in Measure | Set in Measure |
| Early-payment discount capture | % of available discounts taken | Set in Measure | Set in Measure |
| On-time payment rate | % of invoices paid by the due date | Set in Measure | Set in Measure |
| Days payable outstanding (DPO) | Average days from invoice to payment | Set in Measure | Set in Measure |

PO compliance, discounts, on-time payment and DPO need payment terms and purchase-order data,
which is being added to the extract (Phase 2).

## 6. Business case (initial)

- **Direct losses:** money paid twice, early-payment discounts not taken, and late-payment costs.
  Under German law (§ 288 BGB), suppliers can charge late business-to-business payments interest at
  9 percentage points above the base rate, plus a €40 flat fee per invoice.
- **Control:** overspending found after month-end cannot be stopped, only explained.
- **Working capital:** paying too early gives away cash, and paying too late costs penalties and supplier goodwill.
  Both show up in DPO.
- **Automation decision:** a quantified baseline lets the CFO compare an AP automation investment against hard numbers.
  Return on investment, net present value and payback are calculated in Improve (Phase 5).

## 7. Deliverables and timeline

| Weeks | Phase | Key deliverables |
|---|---|---|
| 1–2 | **Define** | This charter, SIPOC, issue tree and driver tree, stakeholder map and RACI, requirements, as-is process model (BPMN) |
| 3–5 | **Measure** | € impact per leakage driver, AP KPI baseline, executive summary dashboard, SQL query layer |
| 6–8 | **Analyze** | Process mining (variants, bottlenecks, conformance), Pareto of leakage causes, control chart, root-cause analysis |
| 9–10 | **Improve** | What-if scenarios, business case (ROI, NPV, payback, sensitivity), to-be process model, prioritised recommendations |
| 11–12 | **Control** | Control plan, monitoring view, Power BI and Excel hand-over, executive memo and steering-committee deck |

**Tollgate reviews** with the sponsor take place at the end of each phase.

## 8. Team and governance

| Role | Who | Involvement |
|---|---|---|
| Sponsor | CFO | Approves the charter and each tollgate, removes blockers |
| Process owner | AP Manager | Owns targets and the control plan after hand-over |
| Project lead | Consultant / business analyst | Analysis, deliverables, facilitation |
| Core team | AP clerk (×2), Procurement lead, Controlling (budget) analyst | Process knowledge, data validation, ~2 h/week |
| Subject-matter experts | IT (ERP data extracts), budget owners for the six departments | On request |

Full stakeholder map and RACI: see the Define deliverables (task 1.5).

## 9. Assumptions, constraints and risks

**Assumptions**
- The ERP extract is complete for the 12 months. Every invoice has a supplier, amount and invoice date.
- Same supplier + same amount + ≤ 5 days apart is a reliable enough duplicate signal to start a supplier claim.

**Constraints**
- No ERP changes during the engagement. Recommendations must work with the current system or a bolt-on.
- Core-team time is limited to about 2 hours per week each.

**Risks and mitigations**

| Risk | Impact | Mitigation |
|---|---|---|
| Some "duplicates" are legitimate repeat charges (e.g. fixed monthly fees) | Overstated recovery | AP confirms each pair with the supplier before claiming. Report gross and confirmed figures separately. |
| Missing or unreliable timestamps | Distorted processing-time baseline | Exclude and count them, and make complete timestamps a control-plan metric |
| Budget owners see overrun reporting as blame | Low adoption | Position it as early warning before month-end, agreed with Controlling |
| Thresholds (115%, 5 days) are judgement calls | Too many or too few flags | Set them with the process owner. Show the sensitivity in the what-if analysis. |

## 10. Sign-off

| Role | Name | Date |
|---|---|---|
| Sponsor (CFO) | | |
| Process owner (AP Manager) | | |
| Project lead | | |
