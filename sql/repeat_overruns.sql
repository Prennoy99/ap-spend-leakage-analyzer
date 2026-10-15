-- Months over budget per department and category, and the longest run of
-- consecutive months over. A long run points at a wrong budget; a single
-- month at a one-off overspend. $threshold is the detector's tolerance
-- (actual / budget), passed in from anomalies.BUDGET_OVERRUN_THRESHOLD.
-- Consecutive months are found with the gaps-and-islands pattern: month
-- number minus row number is constant within a run.
-- pandas: kpis.repeat_overruns(anomalies.detect_budget_overruns(...))
WITH actual AS (
    SELECT department, category,
           strftime(invoice_date, '%Y-%m') AS month,
           SUM(amount)                     AS actual_amount
    FROM invoices
    GROUP BY department, category, month
),
over_budget AS (
    SELECT b.department, b.category, b.month,
           year(strptime(b.month, '%Y-%m')) * 12 + month(strptime(b.month, '%Y-%m')) AS month_number
    FROM budgets b
    LEFT JOIN actual a USING (department, category, month)
    WHERE COALESCE(a.actual_amount, 0) / b.budget_amount > $threshold
),
islands AS (
    SELECT *,
           month_number - ROW_NUMBER() OVER (PARTITION BY department, category ORDER BY month_number) AS run_id
    FROM over_budget
),
runs AS (
    SELECT department, category, run_id,
           COUNT(*)                               AS run_length,
           MIN(month)                             AS first_month,
           string_agg(month, ', ' ORDER BY month) AS run_months
    FROM islands
    GROUP BY department, category, run_id
)
SELECT department, category,
       SUM(run_length)::BIGINT                            AS months_over,
       MAX(run_length)                                    AS longest_run,
       string_agg(run_months, ', ' ORDER BY first_month) AS months
FROM runs
GROUP BY department, category
ORDER BY longest_run DESC, months_over DESC, department, category;
