-- Average days from submission to payment. Invoices with no submission date
-- are left out (no start, so no duration); open invoices have no processing
-- time yet and AVG skips their NULLs.
-- pandas: kpis.avg_processing_days
SELECT ROUND(AVG(processing_days), 1) AS avg_processing_days
FROM invoices
WHERE NOT missing_submitted_date;
