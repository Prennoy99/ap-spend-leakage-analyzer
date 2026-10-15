-- DPO, on-time % and average days paid relative to the due date per invoice
-- month (negative = paid before the due date).
-- pandas: kpis.payment_timing(by="month")
SELECT strftime(invoice_date, '%Y-%m')                                        AS month,
       COUNT(invoice_id)                                                      AS paid_invoices,
       ROUND(SUM(amount), 2)                                                  AS paid_amount,
       ROUND(AVG(CASE WHEN paid_date <= due_date THEN 1 ELSE 0 END) * 100, 1) AS on_time_pct,
       ROUND(AVG(date_diff('day', due_date, paid_date)), 1)                   AS avg_days_vs_due,
       ROUND(SUM(date_diff('day', invoice_date, paid_date) * amount) / SUM(amount), 1) AS dpo_days
FROM invoices
WHERE paid_date IS NOT NULL
GROUP BY month
ORDER BY month;
