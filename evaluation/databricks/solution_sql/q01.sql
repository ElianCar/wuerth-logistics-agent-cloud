SELECT COUNT(*) AS lieferpositionen
FROM workspace.default.datenabzug_projekt_tum_shipments
WHERE plant = '8240'
  AND shipment_date >= '2025-12-01'
  AND shipment_date <= '2025-12-31'
