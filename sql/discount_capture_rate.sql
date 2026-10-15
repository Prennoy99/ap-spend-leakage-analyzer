-- % of paid invoices with early-payment discount terms that were paid inside
-- the discount window.
-- pandas: kpis.discount_capture_rate
SELECT ROUND(AVG(CASE WHEN paid_date <= discount_date THEN 1 ELSE 0 END) * 100, 1) AS discount_capture_pct
FROM invoices
WHERE paid_date IS NOT NULL
  AND discount_date IS NOT NULL;
