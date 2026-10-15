-- Spend and invoice count per invoice month.
-- pandas: kpis.spend_by_month
SELECT strftime(invoice_date, '%Y-%m') AS month,
       ROUND(SUM(amount), 2)          AS total_spend,
       COUNT(invoice_id)              AS invoice_count
FROM invoices
GROUP BY month
ORDER BY month;
