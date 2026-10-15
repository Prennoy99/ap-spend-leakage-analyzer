-- PO compliance and no-PO spend per department, least compliant first.
-- pandas: kpis.po_compliance(by="department")
SELECT department,
       ROUND(SUM(amount), 2)                                               AS total_spend,
       ROUND(SUM(CASE WHEN has_po THEN 0 ELSE amount END), 2)              AS no_po_spend,
       ROUND(SUM(CASE WHEN has_po THEN amount ELSE 0 END) / SUM(amount) * 100, 1) AS po_compliance_pct
FROM invoices
GROUP BY department
ORDER BY po_compliance_pct, department;
