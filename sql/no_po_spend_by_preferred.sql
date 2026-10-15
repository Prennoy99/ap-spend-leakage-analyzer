-- Spend without a PO, split by whether the supplier is on the preferred list.
-- No-PO spend with a non-preferred supplier is the clearest maverick case:
-- no order and no negotiated terms (hypothesis C2).
-- pandas: kpis.no_po_spend_by_preferred
SELECT v.preferred_vendor,
       ROUND(SUM(i.amount), 2) AS no_po_spend,
       COUNT(i.invoice_id)     AS invoice_count
FROM invoices i
JOIN vendors v USING (vendor_id)
WHERE NOT i.has_po
GROUP BY v.preferred_vendor
ORDER BY v.preferred_vendor;
