-- Rejections and invoices affected per reason, most frequent first: which
-- checks at invoice entry would remove the most rework.
-- pandas: kpis.reject_reasons
SELECT reject_reason,
       COUNT(invoice_id)          AS rejections,
       COUNT(DISTINCT invoice_id) AS invoices
FROM invoice_events
WHERE activity = 'Reject invoice'
GROUP BY reject_reason
ORDER BY rejections DESC, reject_reason;
