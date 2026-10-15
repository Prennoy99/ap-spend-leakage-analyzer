-- Paid invoices that broke the approval control: paid before the approval was
-- recorded, or never approved at all. One row per invoice, from the event log.
-- pandas/pm4py: process_mining.conformance (the two breach categories)
WITH steps AS (
    SELECT invoice_id,
           MAX(timestamp) FILTER (WHERE activity = 'Pay invoice')     AS paid_at,
           MIN(timestamp) FILTER (WHERE activity = 'Approve invoice') AS approved_at
    FROM invoice_events
    GROUP BY invoice_id
)
SELECT s.invoice_id,
       CASE WHEN s.approved_at IS NULL THEN 'Paid without approval'
            ELSE 'Paid before approval' END AS category,
       i.amount
FROM steps s
JOIN invoices i USING (invoice_id)
WHERE s.paid_at IS NOT NULL
  AND (s.approved_at IS NULL OR s.paid_at < s.approved_at)
ORDER BY category, s.invoice_id;
