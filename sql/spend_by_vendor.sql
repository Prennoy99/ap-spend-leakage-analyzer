-- The $top_n suppliers by spend.
-- pandas: kpis.spend_by_vendor
SELECT vendor_id,
       vendor_name,
       ROUND(SUM(amount), 2) AS total_spend,
       COUNT(invoice_id)     AS invoice_count
FROM invoices
GROUP BY vendor_id, vendor_name
ORDER BY total_spend DESC
LIMIT $top_n;
