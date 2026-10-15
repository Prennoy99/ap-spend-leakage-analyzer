-- Spend and invoice count per department, largest first.
-- pandas: kpis.spend_by_department
SELECT department,
       ROUND(SUM(amount), 2) AS total_spend,
       COUNT(invoice_id)     AS invoice_count
FROM invoices
GROUP BY department
ORDER BY total_spend DESC;
