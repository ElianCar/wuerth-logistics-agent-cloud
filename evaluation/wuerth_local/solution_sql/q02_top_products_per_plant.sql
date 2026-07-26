WITH lieferpositionen AS (
  SELECT plant, customer_material AS product, COUNT(*) AS lieferpositionen,
    ROW_NUMBER() OVER (PARTITION BY plant ORDER BY COUNT(*) DESC) AS rn
  FROM wuerth.shipments
  GROUP BY plant, customer_material
),
umsatz AS (
  SELECT s.plant, i.product, SUM(i.turnover_inv) AS revenue,
    ROW_NUMBER() OVER (PARTITION BY s.plant ORDER BY SUM(i.turnover_inv) DESC) AS rn
  FROM wuerth.invoices i
  JOIN (SELECT DISTINCT order_number, plant FROM wuerth.shipments) s
    ON i.order_number = s.order_number
  GROUP BY s.plant, i.product
)
SELECT
  l.plant AS plant,
  'Lieferpositionen' AS metric,
  l.product AS product,
  CAST(l.lieferpositionen AS DOUBLE PRECISION) AS metric_value,
  l.rn AS rank
FROM lieferpositionen l
WHERE l.rn <= 3
UNION ALL
SELECT
  u.plant AS plant,
  'Umsatz' AS metric,
  u.product AS product,
  CAST(u.revenue AS DOUBLE PRECISION) AS metric_value,
  u.rn AS rank
FROM umsatz u
WHERE u.rn <= 3
ORDER BY plant, metric, rank
LIMIT 50
