# Agentic AI SQL Agent Prototype

This repository contains the Würth Agentic AI / LangGraph SQL Agent prototype. The app supports two isolated data scenarios:

- **Würth Databricks**: default and primary scenario, backed by Databricks SQL Warehouse.
- **Demo data**: optional TPC-H demo scenario, backed by the old PostgreSQL demo database.

The Streamlit UI, LangGraph flow, feedback, logging, repair, fallback, and memory review flows are shared, but scenario-owned data files are separated so demo TPC-H context does not influence Würth SQL generation.

## Scenarios

The active scenario is selected in the Streamlit sidebar under **Data scenario**. Initial selection comes from:

```text
DATA_SCENARIO=databricks
```

Allowed values:

```text
databricks
demo
```

If `DATA_SCENARIO` is unset, the app defaults to `databricks`.

## Würth Databricks Scenario

The Würth scenario exposes only these tables:

```text
workspace.default.datenabzug_projekt_tum_invoices
workspace.default.datenabzug_projekt_tum_shipments
```

The active semantic layer is:

```text
semantic_layer/databricks/wuerth_semantic_layer.yaml
```

Required Databricks environment variables:

```text
DATA_SCENARIO=databricks
SQL_BACKEND=databricks
DATABRICKS_AUTH_TYPE=oauth
DATABRICKS_SERVER_HOSTNAME=<your-databricks-server-hostname>
DATABRICKS_HTTP_PATH=<your-sql-warehouse-http-path>
DATABRICKS_CATALOG=workspace
DATABRICKS_SCHEMA=default
DATABRICKS_ALLOWED_TABLES=workspace.default.datenabzug_projekt_tum_invoices,workspace.default.datenabzug_projekt_tum_shipments
```

In this organization, personal access tokens are disabled. Use OAuth user-to-machine locally:

```text
DATABRICKS_AUTH_TYPE=oauth
```

OAuth machine-to-machine with a service principal is the recommended direction for AWS or Würth-hosted deployment:

```text
DATABRICKS_AUTH_TYPE=oauth_m2m
DATABRICKS_HOST=<your-databricks-workspace-url>
DATABRICKS_CLIENT_ID=<service-principal-client-id>
DATABRICKS_CLIENT_SECRET=<service-principal-client-secret>
```

Credentials, hostnames, HTTP paths, tokens, client IDs, and client secrets must never be committed or shown in logs/UI.

## Unsupported Würth KPIs

The current Würth semantic layer explicitly treats these KPIs as unsupported unless additional columns and confirmed business rules are provided:

- S24 compliance
- on-time delivery rate
- delivery delay
- gross profit / Rohertrag

The SQL prompt also warns against raw invoice-to-shipment joins that can multiply measures. Combined invoice and shipment measures must be pre-aggregated first, then joined on `order_number` and `customer = soldtoparty`.

## Demo Data Scenario

The old TPC-H demo is available only by selecting **Demo data** in the sidebar or setting:

```text
DATA_SCENARIO=demo
```

Demo PostgreSQL variables:

```text
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=agentic_ai
POSTGRES_USER=postgres
POSTGRES_PASSWORD=
```

The demo semantic layer and memory files live under:

```text
semantic_layer/demo/
memory/demo/
evaluation/demo/
```

## Folder Layout

Scenario-specific files are organized under scenario folders:

```text
semantic_layer/
  databricks/wuerth_semantic_layer.yaml
  demo/tpch_semantic_layer.yaml

memory/
  databricks/
  demo/

evaluation/
  databricks/
  demo/

scripts/
  databricks/test_databricks_connection.py

src/backends/
  databricks/
  demo/
```

## Run Locally

Install dependencies:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Copy and fill local environment values:

```bash
cp .env.example .env
```

Run Streamlit:

```bash
streamlit run streamlit_app.py
```

## Run with Docker

Default Docker behavior starts only the Streamlit app with Würth Databricks as the selected scenario:

```bash
docker compose build
docker compose up
```

Open:

```text
http://localhost:8501
```

The default `docker compose up` does not start PostgreSQL. To use the old demo data in Docker, start the demo profile:

```bash
docker compose --profile demo up --build
```

If the demo database needs fresh CSV exports:

```bash
source .venv/bin/activate
python database/export_tpch_to_csv.py
```

## Databricks Smoke Test

Start the Databricks SQL Warehouse manually first. Then run:

```bash
python scripts/databricks/test_databricks_connection.py
```

The script opens a Databricks connection, runs `SELECT 1`, and runs table reachability checks for the two allowed Würth tables. It prints only safe status messages and row counts.

Live Databricks tests are intentionally not run during normal implementation because the SQL Warehouse is manually started and auto-stops after a short idle period.

## TLS Certificates

Databricks public endpoints normally chain to public certificate authorities. If local or Docker Databricks connections fail with `SSLCertVerificationError` or `self-signed certificate in certificate chain`, the missing trust is usually the Würth/company TLS inspection root CA or endpoint-protection proxy CA, not a Databricks CA.

Install the required corporate root/intermediate CA through the managed OS trust store, or point Python at a PEM bundle that includes:

```text
certifi root certificates
Würth/company TLS inspection root CA
endpoint-protection proxy CA if used on the machine
```

Example:

```bash
SSL_CERT_FILE=/path/to/company-ca-bundle.pem \
REQUESTS_CA_BUNDLE=/path/to/company-ca-bundle.pem \
python scripts/databricks/test_databricks_connection.py
```

Do not disable TLS verification. Do not commit internal certificate bundles.

## Verification

Offline checks:

```bash
python -m compileall .
python -m unittest discover -s evaluation -p "test_*.py"
```

Databricks live check, only after manually starting the warehouse:

```bash
python scripts/databricks/test_databricks_connection.py
```
