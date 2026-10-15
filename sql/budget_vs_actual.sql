-- Actual spend against budget per department, category and month, most over
-- budget first. Starts from the budget table, so a month with no invoices
-- still shows up (actual 0, variance -100%). Invoices in a month with no
-- budget line are not shown (see the data-quality note in PLAN task 3.7).
-- pandas: kpis.budget_vs_actual
WITH actual AS (
    SELECT department, category,
           strftime(invoice_date, '%Y-%m') AS month,
           SUM(amount)                     AS actual_amount
    FROM invoices
    GROUP BY department, category, month
),
joined AS (
    SELECT b.department, b.category, b.month, b.budget_amount,
           ROUND(COALESCE(a.actual_amount, 0), 2) AS actual_amount
    FROM budgets b
    LEFT JOIN actual a USING (department, category, month)
)
SELECT department, category, month, budget_amount, actual_amount,
       ROUND(actual_amount - budget_amount, 2)            AS variance,
       -- Round after scaling to %, not before (same as the pandas version).
       ROUND((actual_amount / budget_amount - 1) * 100, 2) AS variance_pct
FROM joined
ORDER BY variance_pct DESC, department, category, month;
