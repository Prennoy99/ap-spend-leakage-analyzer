-- Agreed net payment terms in days, weighted by amount, over the same paid
-- invoices as DPO.
-- pandas: kpis.agreed_payment_days
SELECT ROUND(SUM(net_days * amount) / SUM(amount), 1) AS agreed_payment_days
FROM invoices
WHERE paid_date IS NOT NULL;
