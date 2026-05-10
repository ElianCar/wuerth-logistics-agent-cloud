-- Row count for every table
SELECT 'region' AS table_name, COUNT(*) AS row_count FROM region
UNION ALL
SELECT 'nation' AS table_name, COUNT(*) AS row_count FROM nation
UNION ALL
SELECT 'supplier' AS table_name, COUNT(*) AS row_count FROM supplier
UNION ALL
SELECT 'customer' AS table_name, COUNT(*) AS row_count FROM customer
UNION ALL
SELECT 'part' AS table_name, COUNT(*) AS row_count FROM part
UNION ALL
SELECT 'partsupp' AS table_name, COUNT(*) AS row_count FROM partsupp
UNION ALL
SELECT 'orders' AS table_name, COUNT(*) AS row_count FROM orders
UNION ALL
SELECT 'lineitem' AS table_name, COUNT(*) AS row_count FROM lineitem
ORDER BY table_name;

-- Total revenue
SELECT
    SUM(l_extendedprice * (1 - l_discount)) AS total_revenue
FROM lineitem;

-- Total revenue by nation
SELECT
    n.n_name AS nation,
    SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
JOIN lineitem l ON o.o_orderkey = l.l_orderkey
JOIN nation n ON c.c_nationkey = n.n_nationkey
GROUP BY n.n_name
ORDER BY revenue DESC;

-- Top 10 customers by revenue
SELECT
    c.c_custkey AS customer_key,
    c.c_name AS customer_name,
    n.n_name AS nation,
    SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
JOIN lineitem l ON o.o_orderkey = l.l_orderkey
JOIN nation n ON c.c_nationkey = n.n_nationkey
GROUP BY c.c_custkey, c.c_name, n.n_name
ORDER BY revenue DESC
LIMIT 10;

-- Number of orders by order status
SELECT
    o_orderstatus AS order_status,
    COUNT(*) AS order_count
FROM orders
GROUP BY o_orderstatus
ORDER BY order_count DESC;

-- Revenue by supplier
SELECT
    s.s_suppkey AS supplier_key,
    s.s_name AS supplier_name,
    n.n_name AS nation,
    SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM supplier s
JOIN lineitem l ON s.s_suppkey = l.l_suppkey
JOIN nation n ON s.s_nationkey = n.n_nationkey
GROUP BY s.s_suppkey, s.s_name, n.n_name
ORDER BY revenue DESC;

-- Monthly order volume
SELECT
    DATE_TRUNC('month', o_orderdate)::date AS order_month,
    COUNT(*) AS order_count,
    SUM(o_totalprice) AS total_order_value
FROM orders
GROUP BY order_month
ORDER BY order_month;

-- Top 10 parts by revenue
SELECT
    p.p_partkey AS part_key,
    p.p_name AS part_name,
    p.p_brand AS brand,
    p.p_type AS part_type,
    SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM part p
JOIN lineitem l ON p.p_partkey = l.l_partkey
GROUP BY p.p_partkey, p.p_name, p.p_brand, p.p_type
ORDER BY revenue DESC
LIMIT 10;

-- Average discount by order priority
SELECT
    o.o_orderpriority AS order_priority,
    AVG(l.l_discount) AS average_discount,
    COUNT(*) AS lineitem_count
FROM orders o
JOIN lineitem l ON o.o_orderkey = l.l_orderkey
GROUP BY o.o_orderpriority
ORDER BY average_discount DESC;
