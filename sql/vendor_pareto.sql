-- Every supplier ranked by spend with its cumulative share of total spend
-- (the 80/20 view). Ties on spend are broken by supplier ID so the ranking
-- is stable.
-- pandas: kpis.vendor_pareto
WITH by_vendor AS (
    SELECT vendor_id, vendor_name,
           SUM(amount)       AS total_spend,
           COUNT(invoice_id) AS invoice_count
    FROM invoices
    GROUP BY vendor_id, vendor_name
)
SELECT vendor_id, vendor_name,
       ROUND(total_spend, 2) AS total_spend,
       invoice_count,
       ROW_NUMBER() OVER w   AS rank,
       -- Cumulate the unrounded spend, round at the end.
       ROUND(SUM(total_spend) OVER (w ROWS UNBOUNDED PRECEDING) / SUM(total_spend) OVER () * 100, 2) AS cumulative_pct
FROM by_vendor
WINDOW w AS (ORDER BY total_spend DESC, vendor_id)
ORDER BY rank;
