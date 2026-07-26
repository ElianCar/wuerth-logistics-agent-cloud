SELECT COUNT(*) AS lieferpositionen
FROM wuerth.shipments
WHERE plant = '8240'
  AND shipment_date >= TIMESTAMP '2025-12-01 00:00:00'
  AND shipment_date < TIMESTAMP '2026-01-01 00:00:00'
