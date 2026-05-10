-- 1. Total revenue
SELECT
    SUM(l_extendedprice * (1 - l_discount)) AS total_revenue
FROM lineitem;

-- 2. Total revenue by nation
SELECT
    n.n_name AS nation,
    SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
JOIN lineitem l ON o.o_orderkey = l.l_orderkey
JOIN nation n ON c.c_nationkey = n.n_nationkey
GROUP BY n.n_name
ORDER BY revenue DESC;

-- 3. Top 10 customers by revenue
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

-- 4. Number of orders by order status
SELECT
    o_orderstatus AS order_status,
    COUNT(*) AS order_count
FROM orders
GROUP BY o_orderstatus
ORDER BY order_count DESC;

-- 5. Revenue by supplier
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

-- 6. Monthly order volume
SELECT
    DATE_TRUNC('month', o_orderdate) AS order_month,
    COUNT(*) AS order_count,
    SUM(o_totalprice) AS total_order_value
FROM orders
GROUP BY order_month
ORDER BY order_month;

-- 7. Top 10 parts by revenue
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

-- 8. Average discount by order priority
SELECT
    o.o_orderpriority AS order_priority,
    AVG(l.l_discount) AS average_discount,
    COUNT(*) AS lineitem_count
FROM orders o
JOIN lineitem l ON o.o_orderkey = l.l_orderkey
GROUP BY o.o_orderpriority
ORDER BY average_discount DESC;
