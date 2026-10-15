-- % of paid invoices paid on or before the due date.
-- pandas: kpis.on_time_payment_rate
SELECT ROUND(AVG(CASE WHEN paid_date <= due_date THEN 1 ELSE 0 END) * 100, 1) AS on_time_payment_pct
FROM invoices
WHERE paid_date IS NOT NULL;
