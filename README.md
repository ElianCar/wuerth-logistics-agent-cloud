# Agentic AI SQL Agent Prototype

This repository contains the Würth Agentic AI / LangGraph SQL Agent prototype.

The normal local prototype uses PostgreSQL for both supported local data scenarios:

- **Demo data**: TPC-H tables in the PostgreSQL `public` schema.
- **Würth local CSV data**: Würth invoice and shipment CSV exports imported into PostgreSQL schema `wuerth`.

Databricks code is kept as optional/legacy integration code, but Databricks is not required for the normal local Docker workflow.

## Local Data Scenarios

The active scenario is selected in the Streamlit sidebar under **Data scenario**. Initial selection comes from:

```text
DATA_SCENARIO=demo
```

Supported local values:

```text
demo
wuerth_local
```

The local Docker Compose workflow starts PostgreSQL by default. `SQL_BACKEND=postgres` is the expected backend for local prototype use.

## Routing Control Layer

Streamlit calls `run_orchestrator(...)`, not the SQL agent directly. The orchestrator runs the router first, then calls the public SQL agent path when SQL is needed.

Flow:

```text
User question
-> Streamlit
-> run_orchestrator(...)
-> Router LangGraph
-> SQL Agent LangGraph when SQL is needed
-> Streamlit result rendering
```

The router classifies intent, SQL need, clarification need, obvious unsafe requests, complexity tier, output mode, language, constraints, execution plan, and memory intent key. It does not generate SQL, validate SQL, execute SQL, create templates, approve templates, or bypass SQL validation.

`src/agent/router_template_retriever.py` is currently a future-compatible placeholder. It returns an empty list and has no side effects. Template creation remains human gated through the successful-run/manual-review memory flow.

## Demo PostgreSQL Scenario

Demo mode uses the existing TPC-H tables:

```text
region
nation
supplier
customer
part
partsupp
orders
lineitem
```

The active demo semantic layer is:

```text
semantic_layer/demo/tpch_semantic_layer.yaml
```

## Würth Local PostgreSQL Scenario

Place the Würth CSV files under:

```text
database/exports/Wuerth
```

The loader also accepts the lowercase path:

```text
database/exports/wuerth
```

Expected files:

```text
Wuerth_invoices.csv
Wuerth_shipments.csv
```

Docker runs the ingestion script before Streamlit starts:

```text
scripts/ingest_wuerth_csv_to_postgres.py
```

The script creates:

```text
wuerth.invoices
wuerth.shipments
```

The active Würth semantic layer is:

```text
semantic_layer/databricks/wuerth_semantic_layer.yaml
```

The current local CSV files expose these join-key candidates:

```text
Order Number: invoices.order_number = shipments.order_number
Customer to Ship to Party: invoices.customer = shipments.shiptoparty
Material key candidate: invoices.material_price = shipments.customer_material
```

The material-key mapping is based on the current CSV column names and still needs business confirmation because neither file contains a column literally named `material_number`.

Important process warning: invoices and shipments may not match one to one because invoicing and shipping can happen with time delays. For combined invoice/shipment analysis, aggregate invoices first, aggregate shipments first, and then join the aggregates. Do not sum measures after a raw many-to-many join.

Current source-data limitation: the local CSV files currently do not contain a revenue/turnover column in invoices or a packing-cost column in shipments. The semantic layer marks those KPIs as unsupported until the columns are provided. Freight cost is available as `wuerth.shipments.freight_costs`.

## Run With Docker

Copy environment defaults:

```bash
cp .env.example .env
```

Start the local stack:

```bash
docker compose up --build
```

Open:

```text
http://localhost:8501
```

Select **Demo data** or **Würth local CSV data** in the sidebar.

To start directly in Würth local mode:

```bash
DATA_SCENARIO=wuerth_local docker compose up --build
```

## PowerPoint Export

The normal PPT path uses the Wuerth template and a local deterministic renderer. In Docker, PPT creation also uses a bounded Sonnet JSON planning step by default:

```text
PRESENTATION_EXPORT_MODE=deterministic
PRESENTATION_PLANNING_MODE=llm
PRESENTATION_PLANNING_MODEL=claude-sonnet-4-6
PRESENTATION_PLANNING_MAX_TOKENS=2048
PRESENTATION_PLANNING_TIMEOUT_SECONDS=30
```

The Sonnet planner only decides the German presentation plan: title, executive bullets, chart choice, table pages, and caveats. The PPTX file is still rendered locally with editable PowerPoint charts where possible. Set `PRESENTATION_PLANNING_MODE=deterministic` to avoid the extra API call.

Planner debug records are appended to `logs/presentation_planner_debug.jsonl` by default, or to `$LOG_DIR/presentation_planner_debug.jsonl` when `LOG_DIR` is set. Each record contains the Sonnet planning prompt and response text, so treat it as analysis data and do not commit it.

`PRESENTATION_EXPORT_MODE=claude` is a separate experimental path that asks Claude's PowerPoint Skill to create the file. It is intentionally not the default because it can be much more expensive and less predictable.

## Manual Ingestion

When PostgreSQL is running locally, the Würth import can be run manually:

```bash
python scripts/ingest_wuerth_csv_to_postgres.py
```

Docker container values are:

```text
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=agentic_ai
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
```

Local host defaults are in `.env.example`.

## Validation

Validate CSV files, scenario config, semantic layer wiring, and database tables:

```bash
python scripts/validate_wuerth_local_setup.py
```

Validate only file/config/semantic-layer checks without a database:

```bash
python scripts/validate_wuerth_local_setup.py --skip-db
```

General checks:

```bash
python -m compileall app src scripts streamlit_app.py evaluation
python -m unittest discover -s evaluation -p "test_*.py"
```

Run the existing LangGraph smoke test:

```bash
python evaluation/run_langgraph_smoke_tests.py
```

Run Würth local golden questions after CSV ingestion:

```bash
DATA_SCENARIO=wuerth_local python evaluation/run_evaluation.py W01 W02 W03 W04 W05
```

## Optional Databricks

Databricks remains available only when explicitly configured:

```text
DATA_SCENARIO=databricks
SQL_BACKEND=databricks
DATABRICKS_AUTH_TYPE=oauth
DATABRICKS_SERVER_HOSTNAME=<your-databricks-server-hostname>
DATABRICKS_HTTP_PATH=<your-sql-warehouse-http-path>
DATABRICKS_CATALOG=workspace
DATABRICKS_SCHEMA=default
```

Do not commit credentials, hostnames, HTTP paths, tokens, client IDs, client secrets, or internal certificates.
