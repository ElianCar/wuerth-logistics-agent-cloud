SELECT
    SUM(freight_costs) AS total_freight_costs,
    'Packing costs are unsupported because no packing cost column is present in the local Würth shipment CSV.' AS packing_costs_limitation
FROM wuerth.shipments
