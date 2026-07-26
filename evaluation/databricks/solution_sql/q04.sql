WITH order_plants AS (
  SELECT order_number, COUNT(DISTINCT plant) AS plant_count
  FROM workspace.default.datenabzug_projekt_tum_shipments s
  WHERE s.shipment_date >= '2025-07-01' AND s.shipment_date <= '2025-12-31'
  GROUP BY order_number
)
SELECT
  COUNT(CASE WHEN plant_count > 1 THEN 1 END) AS orders_multi_plant,
  COUNT(*) AS total_orders,
  COUNT(CASE WHEN plant_count > 1 THEN 1 END) * 1.0 / COUNT(*) AS share_multi_plant
FROM order_plants
