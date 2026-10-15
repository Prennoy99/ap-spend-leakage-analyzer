-- Open invoices whose early-payment discount can still be taken at the
-- extract date, most urgent first: the AP clerk's work list.
-- pandas: kpis.discount_deadlines
SELECT invoice_id, vendor_id, vendor_name, status, amount, discount_date,
       date_diff('day', extract_date, discount_date) AS days_left,
       ROUND(amount * discount_pct / 100, 2)         AS discount_eur
FROM invoices
WHERE paid_date IS NULL
  AND discount_date IS NOT NULL
  AND discount_date >= extract_date
ORDER BY discount_date, discount_eur DESC;
