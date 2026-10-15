-- % of invoice spend covered by a purchase order (by spend, not invoice
-- count: one large no-PO invoice matters more than many small ones).
-- pandas: kpis.po_compliance
SELECT ROUND(SUM(CASE WHEN has_po THEN amount ELSE 0 END) / SUM(amount) * 100, 1) AS po_compliance_pct
FROM invoices;
