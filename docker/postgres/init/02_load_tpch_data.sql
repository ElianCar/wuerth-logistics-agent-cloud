COPY region
FROM '/docker-entrypoint-initdb.d/exports/region.csv'
WITH CSV HEADER;

COPY nation
FROM '/docker-entrypoint-initdb.d/exports/nation.csv'
WITH CSV HEADER;

COPY supplier
FROM '/docker-entrypoint-initdb.d/exports/supplier.csv'
WITH CSV HEADER;

COPY customer
FROM '/docker-entrypoint-initdb.d/exports/customer.csv'
WITH CSV HEADER;

COPY part
FROM '/docker-entrypoint-initdb.d/exports/part.csv'
WITH CSV HEADER;

COPY partsupp
FROM '/docker-entrypoint-initdb.d/exports/partsupp.csv'
WITH CSV HEADER;

COPY orders
FROM '/docker-entrypoint-initdb.d/exports/orders.csv'
WITH CSV HEADER;

COPY lineitem
FROM '/docker-entrypoint-initdb.d/exports/lineitem.csv'
WITH CSV HEADER;
