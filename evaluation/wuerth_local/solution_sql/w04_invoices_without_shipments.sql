WITH invoice_keys AS (
    SELECT
        order_number,
        customer,
        material_price,
        COUNT(*) AS invoice_rows
    FROM wuerth.invoices
    GROUP BY order_number, customer, material_price
),
shipment_keys AS (
    SELECT
        order_number,
        shiptoparty,
        customer_material,
        COUNT(*) AS shipment_rows
    FROM wuerth.shipments
    GROUP BY order_number, shiptoparty, customer_material
)
SELECT
    i.order_number,
    i.customer,
    i.material_price,
    i.invoice_rows
FROM invoice_keys AS i
LEFT JOIN shipment_keys AS s
    ON i.order_number = s.order_number
   AND i.customer = s.shiptoparty
   AND i.material_price = s.customer_material
WHERE s.order_number IS NULL
ORDER BY i.order_number, i.customer, i.material_price
LIMIT 50
