SELECT i.calendar_yearmonth, SUM(i.turnover_inv) AS revenue
FROM wuerth.invoices i
WHERE i.calendar_day >= TIMESTAMP '2025-12-01 00:00:00'
  AND i.calendar_day < TIMESTAMP '2026-01-01 00:00:00'
  AND i.order_number IN (
    SELECT order_number
    FROM wuerth.shipments
    WHERE plant = '9981'
  )
GROUP BY i.calendar_yearmonth
ORDER BY i.calendar_yearmonth
