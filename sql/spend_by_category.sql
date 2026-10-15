-- Spend and invoice count per spend category, largest first.
-- pandas: kpis.spend_by_category
SELECT category,
       ROUND(SUM(amount), 2) AS total_spend,
       COUNT(invoice_id)     AS invoice_count
FROM invoices
GROUP BY category
ORDER BY total_spend DESC;
