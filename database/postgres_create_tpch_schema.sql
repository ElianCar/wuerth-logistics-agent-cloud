DROP TABLE IF EXISTS lineitem;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS partsupp;
DROP TABLE IF EXISTS customer;
DROP TABLE IF EXISTS supplier;
DROP TABLE IF EXISTS part;
DROP TABLE IF EXISTS nation;
DROP TABLE IF EXISTS region;

CREATE TABLE region (
    r_regionkey INTEGER PRIMARY KEY,
    r_name VARCHAR(25) NOT NULL,
    r_comment TEXT
);

CREATE TABLE nation (
    n_nationkey INTEGER PRIMARY KEY,
    n_name VARCHAR(25) NOT NULL,
    n_regionkey INTEGER NOT NULL,
    n_comment TEXT,
    CONSTRAINT fk_nation_region
        FOREIGN KEY (n_regionkey) REFERENCES region (r_regionkey)
);

CREATE TABLE supplier (
    s_suppkey INTEGER PRIMARY KEY,
    s_name VARCHAR(25) NOT NULL,
    s_address VARCHAR(40) NOT NULL,
    s_nationkey INTEGER NOT NULL,
    s_phone VARCHAR(15) NOT NULL,
    s_acctbal NUMERIC(15, 2) NOT NULL,
    s_comment TEXT,
    CONSTRAINT fk_supplier_nation
        FOREIGN KEY (s_nationkey) REFERENCES nation (n_nationkey)
);

CREATE TABLE customer (
    c_custkey INTEGER PRIMARY KEY,
    c_name VARCHAR(25) NOT NULL,
    c_address VARCHAR(40) NOT NULL,
    c_nationkey INTEGER NOT NULL,
    c_phone VARCHAR(15) NOT NULL,
    c_acctbal NUMERIC(15, 2) NOT NULL,
    c_mktsegment VARCHAR(10) NOT NULL,
    c_comment TEXT,
    CONSTRAINT fk_customer_nation
        FOREIGN KEY (c_nationkey) REFERENCES nation (n_nationkey)
);

CREATE TABLE part (
    p_partkey INTEGER PRIMARY KEY,
    p_name VARCHAR(55) NOT NULL,
    p_mfgr VARCHAR(25) NOT NULL,
    p_brand VARCHAR(10) NOT NULL,
    p_type VARCHAR(25) NOT NULL,
    p_size INTEGER NOT NULL,
    p_container VARCHAR(10) NOT NULL,
    p_retailprice NUMERIC(15, 2) NOT NULL,
    p_comment TEXT
);

CREATE TABLE partsupp (
    ps_partkey INTEGER NOT NULL,
    ps_suppkey INTEGER NOT NULL,
    ps_availqty INTEGER NOT NULL,
    ps_supplycost NUMERIC(15, 2) NOT NULL,
    ps_comment TEXT,
    PRIMARY KEY (ps_partkey, ps_suppkey),
    CONSTRAINT fk_partsupp_part
        FOREIGN KEY (ps_partkey) REFERENCES part (p_partkey),
    CONSTRAINT fk_partsupp_supplier
        FOREIGN KEY (ps_suppkey) REFERENCES supplier (s_suppkey)
);

CREATE TABLE orders (
    o_orderkey INTEGER PRIMARY KEY,
    o_custkey INTEGER NOT NULL,
    o_orderstatus VARCHAR(1) NOT NULL,
    o_totalprice NUMERIC(15, 2) NOT NULL,
    o_orderdate DATE NOT NULL,
    o_orderpriority VARCHAR(15) NOT NULL,
    o_clerk VARCHAR(15) NOT NULL,
    o_shippriority INTEGER NOT NULL,
    o_comment TEXT,
    CONSTRAINT fk_orders_customer
        FOREIGN KEY (o_custkey) REFERENCES customer (c_custkey)
);

CREATE TABLE lineitem (
    l_orderkey INTEGER NOT NULL,
    l_partkey INTEGER NOT NULL,
    l_suppkey INTEGER NOT NULL,
    l_linenumber INTEGER NOT NULL,
    l_quantity NUMERIC(15, 2) NOT NULL,
    l_extendedprice NUMERIC(15, 2) NOT NULL,
    l_discount NUMERIC(15, 2) NOT NULL,
    l_tax NUMERIC(15, 2) NOT NULL,
    l_returnflag VARCHAR(1) NOT NULL,
    l_linestatus VARCHAR(1) NOT NULL,
    l_shipdate DATE NOT NULL,
    l_commitdate DATE NOT NULL,
    l_receiptdate DATE NOT NULL,
    l_shipinstruct VARCHAR(25) NOT NULL,
    l_shipmode VARCHAR(10) NOT NULL,
    l_comment TEXT,
    PRIMARY KEY (l_orderkey, l_linenumber),
    CONSTRAINT fk_lineitem_orders
        FOREIGN KEY (l_orderkey) REFERENCES orders (o_orderkey),
    CONSTRAINT fk_lineitem_part
        FOREIGN KEY (l_partkey) REFERENCES part (p_partkey),
    CONSTRAINT fk_lineitem_supplier
        FOREIGN KEY (l_suppkey) REFERENCES supplier (s_suppkey),
    CONSTRAINT fk_lineitem_partsupp
        FOREIGN KEY (l_partkey, l_suppkey) REFERENCES partsupp (ps_partkey, ps_suppkey)
);
