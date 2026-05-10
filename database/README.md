# Local TPC-H DuckDB Database

This folder contains a small local TPC-H database for testing SQL queries before connecting an LLM agent.

DuckDB is used to generate the local sample data. Optional PostgreSQL scripts are included so the same data can be loaded into a local PostgreSQL database. There is no Docker, frontend, LangGraph, or agent code in this setup.

## Files

```text
database/
  create_tpch_database.py
  export_tpch_to_csv.py
  exports/
  inspect_schema.py
  postgres_create_tpch_schema.sql
  postgres_load_tpch_csv.sql
  postgres_test_queries.sql
  test_queries.sql
  README.md
  tpch.duckdb
requirements.txt
```

`tpch.duckdb` is created by running `create_tpch_database.py`.

## Install Requirements

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Create The Database

From the project root:

```bash
python database/create_tpch_database.py
```

The script creates a fresh database file at:

```text
database/tpch.duckdb
```

It installs and loads DuckDB's TPC-H extension, then generates the standard TPC-H tables using scale factor `0.01` when available. If that scale factor is not supported by the installed DuckDB version, the script tries the next smallest configured scale factor.

The script is idempotent. If `database/tpch.duckdb` already exists, it is deleted and recreated.

## Inspect The Schema

From the project root:

```bash
python database/inspect_schema.py
```

This prints:

- all table names
- all column names
- column types
- row count per table

## Run Test Queries

You can run the test queries with the DuckDB CLI if it is installed:

```bash
duckdb database/tpch.duckdb < database/test_queries.sql
```

If the DuckDB CLI is not installed, run the full SQL file through Python:

```bash
python - <<'PY'
from pathlib import Path
import duckdb

con = duckdb.connect("database/tpch.duckdb", read_only=True)
con.execute(Path("database/test_queries.sql").read_text())
print("test_queries.sql executed successfully")
con.close()
PY
```

You can also run individual queries from Python:

```bash
python - <<'PY'
import duckdb

con = duckdb.connect("database/tpch.duckdb", read_only=True)
result = con.execute("""
    SELECT
        SUM(l_extendedprice * (1 - l_discount)) AS total_revenue
    FROM lineitem
""").fetchdf()
print(result)
con.close()
PY
```

## Test Query Examples

`test_queries.sql` includes:

- total revenue
- total revenue by nation
- top 10 customers by revenue
- number of orders by order status
- revenue by supplier
- monthly order volume
- top 10 parts by revenue
- average discount by order priority

## TPC-H Tables

- `region`: high-level geographic regions.
- `nation`: countries, each linked to a region.
- `supplier`: suppliers that provide parts.
- `customer`: customers that place orders.
- `part`: parts or products available for purchase.
- `partsupp`: relationship between parts and suppliers, including supply cost and available quantity.
- `orders`: customer orders, including order date, status, priority, and total price.
- `lineitem`: individual order line items, including part, supplier, quantity, price, discount, tax, and shipping details.

## Move TPC-H from DuckDB to PostgreSQL

DuckDB is used to generate the local TPC-H sample data. PostgreSQL is the later target database because it is closer to the final agent setup. Docker will be added later, not now.

Install PostgreSQL on macOS if needed:

```bash
brew install postgresql@16
brew services start postgresql@16
```

Create a local PostgreSQL database:

```bash
createdb agentic_ai
```

Export the DuckDB TPC-H tables to CSV:

```bash
source .venv/bin/activate
python database/export_tpch_to_csv.py
```

This creates:

```text
database/exports/region.csv
database/exports/nation.csv
database/exports/supplier.csv
database/exports/customer.csv
database/exports/part.csv
database/exports/partsupp.csv
database/exports/orders.csv
database/exports/lineitem.csv
```

Create the PostgreSQL schema:

```bash
psql -d agentic_ai -f database/postgres_create_tpch_schema.sql
```

Load CSV data into PostgreSQL:

```bash
psql -d agentic_ai -f database/postgres_load_tpch_csv.sql
```

Run PostgreSQL test queries:

```bash
psql -d agentic_ai -f database/postgres_test_queries.sql
```

Quick row count checks:

```bash
psql -d agentic_ai -c "SELECT COUNT(*) FROM orders;"
psql -d agentic_ai -c "SELECT COUNT(*) FROM lineitem;"
```
