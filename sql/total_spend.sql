-- Total invoice spend in the extract (EUR).
-- pandas: kpis.total_spend
SELECT ROUND(SUM(amount), 2) AS total_spend
FROM invoices;
