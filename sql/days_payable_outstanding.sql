-- Transactional DPO: days from invoice date to payment, weighted by amount,
-- over paid invoices. Read it next to agreed_payment_days.sql: DPO well below
-- the agreed terms means cash leaves earlier than suppliers require.
-- pandas: kpis.days_payable_outstanding
SELECT ROUND(SUM(date_diff('day', invoice_date, paid_date) * amount) / SUM(amount), 1) AS dpo_days
FROM invoices
WHERE paid_date IS NOT NULL;
