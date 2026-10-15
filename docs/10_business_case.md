# Business case: what the fixes cost and return

> **Portfolio note.** Rheinwerk Komponenten GmbH is a fictional client and all data is synthetic.
> The cost estimates are a consultant's first estimates, to be replaced by IT quotes.

## The answer first

**The fixes cost €60k once and return €66k a year in hard benefits: a 3-year NPV of €119k, paid back in
8 months.** Even the worst case stays positive (NPV €21k, payback 24 months), before any estimated savings.

- **One lever carries the case.** Blocking duplicates at invoice entry returns €57.7k a year, 87% of the hard
  benefit, for €9.2k of the investment. It is the decision to take first.
- **The biggest uncertainty is cost, not benefit.** In the sensitivity analysis the cost estimate moves the
  NPV most (€78k to €127k). Costs could run to **2.45 times** the estimate before the NPV reaches zero.
- **The one-off claim-back flatters the case.** Recovering duplicates already paid (€48.2k) needs no
  investment. Without it the base NPV is still €74k, but the worst case turns negative (−€12k). Read the
  worst case as "the fixes pay back only if the claims are made too", which they will be.
- **Estimated savings are reported separately.** With the purchase-order premium and working capital the NPV
  is €193k, but those rest on assumptions (a 5% premium, an 8% cost of capital) and are not in the headline.

The figures are computed by [`src/business_case.py`](../src/business_case.py) and shown on the app's
**Business case** tab. The NPV, ROI and payback formulas are checked against a hand-worked example in
[`tests/test_business_case.py`](../tests/test_business_case.py).

## 1. The fixes

One fix per root cause from the [root-cause analysis](09_root_cause_analysis.md#9-what-this-means-for-improve),
plus two that have no € benefit but are part of the programme.

| Fix | Addresses | € a year at stake | Removed (base) | € benefit a year | One-off cost | Running cost a year | Owner |
|---|---|---|---|---|---|---|---|
| Block duplicates at invoice entry | No duplicate check at entry | €60,265 | 96% | €57,731 | €9,200 | €1,600 | AP Manager, IT |
| Pay to terms | Payment run ignores terms | €6,278 | 80% | €5,023 | €6,200 | — | AP Manager |
| Approval deadline for discount invoices | Slow approval | €4,018 | 50% | €2,009 | €12,000 | €800 | Budget owners, AP Manager |
| Validate cost centre and PO at entry | Rework delays approval | €2,991 | 55% | €1,650 | €13,200 | — | IT, AP clerks |
| **Hard benefit** | | **€73,553** | | **€66,413** | | | |
| No PO, no pay | Purchase-order premium (estimated) | €39,889 | 54% | €21,422 | €11,000 | €6,000 | Procurement lead |
| Pay to terms: working capital | Working capital (estimated) | €12,532 | 80% | €10,025 | (same change) | — | AP Manager |
| **Estimated saving** | | | | **€31,447** | | | |
| Payment block without approval | Control breaches | — | — | — | €2,400 | — | AP Manager, Internal Audit |
| Programme management and training | All | — | — | — | €6,000 | — | AP Manager |
| **Total** | | | | | **€60,000** | **€8,400** | |

**How costs are built.** IT days × €1,000 (an external SAP consultant) plus business days × €400 (internal
staff at about €50 an hour, fully loaded). For example, blocking duplicates is 8 IT days and 3 business
days (testing, training the clerks), plus 4 business days a year to clear the review list. Every rate and
day count is a named constant in the code.

**Deliberately conservative.** Staff time is counted as a cost, but the AP time saved by fewer rejections is
not counted as a benefit, because no hourly handling cost has been agreed. Spend above budget (€337k) is left
out completely: it is spend to review, not a saving.

## 2. Where "removed" comes from

| Assumption | Worst | Base | Best | Source |
|---|---|---|---|---|
| Duplicates prevented | 80% | **95.8%** | 100% | Data: the € share of duplicates that reused a PO, which the entry block stops |
| Pay-to-terms effectiveness | 60% | 80% | 100% | Consultant estimate: every invoice here was approved with a day to spare, but a weekly run can still miss some |
| Late approvals avoided | 25% | 50% | 75% | Consultant estimate, to confirm with budget owners |
| Rework prevented at entry | 30% | **55.2%** | 70% | Data: rejections for a wrong cost centre or a missing PO, which an entry check catches |
| No-PO spend brought under PO | 25% | **53.7%** | 75% | Data: the share of the gap closed by reaching the 90% PO-compliance target from 78.4% |
| Paid duplicates recovered | 60% | 80% | 95% | Measure assumption; open question Q1 (CFO, AP Manager) |
| Premium paid without a PO | 2% | 5% | 8% | Measure assumption; confirm with Procurement |
| Implementation and running cost | ×1.5 | ×1.0 | ×0.9 | IT projects overrun more often than they underrun |
| Cost of capital (discount rate) | 10% | 8% | 6% | Measure assumption; open question Q3 (CFO) |
| Year-1 benefit realised | 50% | 75% | 90% | Go-live in the first quarter (charter goal date 31 March 2027) |

Bold base values come from the data, not from judgement.

## 3. Cash flow and headline figures (base case, hard benefits)

| | Year 0 | Year 1 | Year 2 | Year 3 |
|---|---|---|---|---|
| Benefit | | €49,810 (75% ramp-up) | €66,413 | €66,413 |
| Duplicates recovered (one-off) | | €48,212 | | |
| Cost | −€60,000 | −€8,400 | −€8,400 | −€8,400 |
| **Net cash flow** | **−€60,000** | **€89,622** | **€58,013** | **€58,013** |
| Running total | −€60,000 | €29,622 | €87,635 | €145,648 |

- **NPV (3 years, 8%): €118,772.** Each year's net flow divided by 1.08 to the power of the year.
- **ROI: 243%.** The 3-year net return minus the investment, divided by the investment.
- **Payback: 8 months.** The running total turns positive during year 1 (net flows assumed even within a year).

## 4. Worst, base and best case

Every assumption at its worst, base or best value together.

| | Worst | Base | Best |
|---|---|---|---|
| Investment | €90,000 | €60,000 | €54,000 |
| Hard benefit a year | €53,881 | €66,413 | €71,651 |
| **NPV, hard benefits** | **€21,040** | **€118,772** | **€164,567** |
| ROI | 48% | 243% | 349% |
| Payback | 24 months | 8 months | 6 months |
| NPV without the one-off claim-back | −€11,832 | €74,132 | €110,556 |
| NPV including estimated savings | €48,248 | €192,535 | €312,235 |

## 5. Sensitivity: which assumption matters most

Each assumption moved alone to its worst and best value, with the others at base (the tornado chart on the
Business case tab).

| Assumption | NPV at worst value | NPV at best value | Swing |
|---|---|---|---|
| Implementation and running cost | €77,949 | €126,937 | €48,989 |
| Duplicates prevented | €96,444 | €124,715 | €28,272 |
| Year-1 benefit realised | €103,399 | €127,996 | €24,597 |
| Paid duplicates recovered | €107,612 | €127,142 | €19,530 |
| Cost of capital | €113,005 | €124,889 | €11,884 |
| Pay-to-terms effectiveness | €115,827 | €121,718 | €5,891 |
| Late approvals avoided | €116,416 | €121,129 | €4,713 |
| Rework prevented at entry | €117,007 | €119,814 | €2,807 |

No single assumption takes the NPV below €77k. The two PO assumptions move only the estimated savings, so
they don't appear here.

**What to confirm before the board decides**, in this order:

1. **IT quotes** for the four ERP changes: the largest swing, and the only one that could move the decision.
2. **Whether invoices really carry their PO numbers** after go-live: the duplicate block depends on it.
3. **The go-live date**: each month of delay costs about €5.5k of hard benefit.

## 6. What the what-if tab adds

The **What-if** tab ([`src/what_if.py`](../src/what_if.py)) re-runs the real calculations with one lever moved:

- **Faster approval alone doesn't reach the targets.** Cutting approval by 4 days brings the median from
  submission to payment to 4 days (the charter goal) and discount capture to 76.9%. Even 7 days faster only
  reaches 84.4% capture and 97.2% on-time payment, short of the 90% and 98% targets. The payment run has to
  pick discount invoices first as well, which is why pay-to-terms is the second fix.
- **The 115% overrun threshold is about right.** It catches every planted overrun with 8 extra flags; at 120%
  recall already falls to 88%. Controlling should set it from how many reviews it can handle (open question Q2).
- **Supplier consolidation is a separate, estimated lever.** Spend is spread evenly, so moving the five
  smallest non-preferred suppliers shifts €317k, worth about €16k a year at a 5% volume saving. It is not
  in the business case: it rests on a negotiated discount, and Procurement owns the decision.

## 7. Recommendation

Approve the programme, starting with the duplicate block and the pay-to-terms change. Together they cost
€15.4k and return €62.8k a year, so they pay back in about three months of operation on their own. The
approval deadline and the entry validation follow: they return less in cash (€3.7k a year together) but cut
processing time and rework, which the [baseline](08_measure_baseline.md) targets. The impact/effort matrix
(task 5.4) puts this order into one picture, and the to-be process (task 5.3) shows where each change sits.
