-- Average days from submission to payment per department, slowest first.
-- pandas: kpis.avg_processing_days(by="department")
SELECT department,
       ROUND(AVG(processing_days), 1) AS avg_processing_days
FROM invoices
WHERE NOT missing_submitted_date
GROUP BY department
ORDER BY avg_processing_days DESC, department;
