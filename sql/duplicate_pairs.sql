-- Suspected duplicate payments: the same supplier and amount invoiced again
-- within $window_days days. Each invoice is compared with the previous one for
-- that supplier and amount; the later one is taken as the copy (on a same-day
-- tie, the higher document number, since it was entered last).
-- pandas: anomalies.find_duplicate_pairs
WITH ordered AS (
    SELECT vendor_id,
           ROUND(amount, 2) AS amount,
           invoice_id,
           invoice_date,
           LAG(invoice_id)   OVER w AS previous_invoice_id,
           LAG(invoice_date) OVER w AS previous_invoice_date
    FROM invoices
    WINDOW w AS (PARTITION BY vendor_id, ROUND(amount, 2) ORDER BY invoice_date, invoice_id)
)
SELECT vendor_id, amount,
       previous_invoice_id                                    AS first_invoice_id,
       invoice_id                                             AS second_invoice_id,
       date_diff('day', previous_invoice_date, invoice_date)  AS days_apart
FROM ordered
WHERE date_diff('day', previous_invoice_date, invoice_date) <= $window_days
ORDER BY vendor_id, amount, invoice_date, invoice_id;
