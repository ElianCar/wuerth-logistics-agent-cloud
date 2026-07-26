WITH order_plants AS (
  SELECT order_number, COUNT(DISTINCT plant) AS plant_count
  FROM wuerth.shipments s
  WHERE s.shipment_date >= TIMESTAMP '2025-07-01 00:00:00'
    AND s.shipment_date < TIMESTAMP '2026-01-01 00:00:00'
  GROUP BY order_number
)
SELECT
  COUNT(CASE WHEN plant_count > 1 THEN 1 END) AS orders_multi_plant,
  COUNT(*) AS total_orders,
  COUNT(CASE WHEN plant_count > 1 THEN 1 END) * 1.0 / COUNT(*) AS share_multi_plant
FROM order_plants
