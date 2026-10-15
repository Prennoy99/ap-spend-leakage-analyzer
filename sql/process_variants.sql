-- Every distinct path through invoice-to-pay, most frequent first: process
-- mining's variant list, built in the warehouse by joining each invoice's
-- activities in time order.
-- pandas/pm4py: process_mining.variants
WITH paths AS (
    SELECT invoice_id,
           STRING_AGG(activity, ' → ' ORDER BY timestamp) AS path,
           COUNT(*)                                     AS steps
    FROM invoice_events
    GROUP BY invoice_id
),
variants AS (
    SELECT path, steps, COUNT(*) AS invoices
    FROM paths
    GROUP BY path, steps
)
SELECT printf('V%02d', ROW_NUMBER() OVER (ORDER BY invoices DESC, path)) AS variant,
       path,
       steps,
       invoices,
       ROUND(invoices * 100.0 / SUM(invoices) OVER (), 1) AS share_pct,
       ROUND(SUM(invoices) OVER (ORDER BY invoices DESC, path ROWS UNBOUNDED PRECEDING) * 100.0
             / SUM(invoices) OVER (), 1)                  AS cumulative_pct
FROM variants
ORDER BY invoices DESC, path;
