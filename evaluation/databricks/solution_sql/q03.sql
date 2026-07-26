SELECT i.calendar_yearmonth, SUM(i.turnover_inv) AS revenue
FROM workspace.default.datenabzug_projekt_tum_invoices i
WHERE i.calendar_day >= '2025-12-01'
  AND i.calendar_day <= '2025-12-31'
  AND i.order_number IN (
    SELECT order_number
    FROM workspace.default.datenabzug_projekt_tum_shipments
    WHERE plant = '9981'
  )
GROUP BY i.calendar_yearmonth
ORDER BY i.calendar_yearmonth
