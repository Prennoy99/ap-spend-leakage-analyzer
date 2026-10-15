-- Median and 90th-percentile days per process stage, over invoices that have
-- completed it. Invoices left out are counted, not hidden: a missing start
-- (no submission date, or paid without approval) and an end before the start
-- (paid before approval) are reported separately.
-- pandas: kpis.stage_durations
WITH stages AS (
    SELECT 1 AS stage_order, 'Submit → approve' AS stage, submitted_date AS start_ts, approved_date AS end_ts FROM invoices
    UNION ALL
    SELECT 2, 'Approve → pay', approved_date, paid_date FROM invoices
    UNION ALL
    SELECT 3, 'Submit → pay', submitted_date, paid_date FROM invoices
),
completed AS (
    SELECT stage_order, stage, start_ts, date_diff('day', start_ts, end_ts) AS days
    FROM stages
    WHERE end_ts IS NOT NULL
)
SELECT stage,
       -- quantile_cont interpolates between values, like pandas' default.
       quantile_cont(days, 0.5) FILTER (WHERE days >= 0)           AS median_days,
       ROUND(quantile_cont(days, 0.9) FILTER (WHERE days >= 0), 1) AS p90_days,
       COUNT(*) FILTER (WHERE days >= 0)                           AS invoices_measured,
       COUNT(*) FILTER (WHERE start_ts IS NULL)                    AS excluded_missing_start,
       COUNT(*) FILTER (WHERE days < 0)                            AS excluded_out_of_order
FROM completed
GROUP BY stage_order, stage
ORDER BY stage_order;
