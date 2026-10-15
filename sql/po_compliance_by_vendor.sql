-- PO compliance and no-PO spend per supplier, least compliant first.
-- pandas: kpis.po_compliance(by=["vendor_id", "vendor_name"])
SELECT vendor_id,
       vendor_name,
       ROUND(SUM(amount), 2)                                               AS total_spend,
       ROUND(SUM(CASE WHEN has_po THEN 0 ELSE amount END), 2)              AS no_po_spend,
       ROUND(SUM(CASE WHEN has_po THEN amount ELSE 0 END) / SUM(amount) * 100, 1) AS po_compliance_pct
FROM invoices
GROUP BY vendor_id, vendor_name
ORDER BY po_compliance_pct, vendor_id;
