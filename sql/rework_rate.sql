-- % of invoices rejected at least once by the budget owner and sent back to AP.
-- pandas: kpis.rework_rate
SELECT ROUND(
           (SELECT COUNT(DISTINCT invoice_id) FROM invoice_events WHERE activity = 'Reject invoice')
           / (SELECT COUNT(*) FROM invoices) * 100, 1) AS rework_pct;
