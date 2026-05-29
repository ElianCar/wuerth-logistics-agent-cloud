WITH shipment_keys AS (
    SELECT
        order_number,
        shiptoparty,
        customer_material,
        COUNT(*) AS shipment_rows
    FROM wuerth.shipments
    GROUP BY order_number, shiptoparty, customer_material
),
invoice_keys AS (
    SELECT
        order_number,
        customer,
        material_price,
        COUNT(*) AS invoice_rows
    FROM wuerth.invoices
    GROUP BY order_number, customer, material_price
)
SELECT
    s.order_number,
    s.shiptoparty,
    s.customer_material,
    s.shipment_rows
FROM shipment_keys AS s
LEFT JOIN invoice_keys AS i
    ON s.order_number = i.order_number
   AND s.shiptoparty = i.customer
   AND s.customer_material = i.material_price
WHERE i.order_number IS NULL
ORDER BY s.order_number, s.shiptoparty, s.customer_material
LIMIT 50
