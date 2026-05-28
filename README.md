# Agentic AI Chat with your Data Prototype

This project starts with a local TPC-H database and a simple CLI backend that asks an LLM to generate PostgreSQL SQL. Gemini is the default LLM provider, with Ollama still available for local runs.

DuckDB is used to generate the local TPC-H sample data. PostgreSQL is used as the target database for the first backend prototype.

## First CLI prototype

This assumes the local PostgreSQL database `agentic_ai` already exists and contains the TPC-H tables. The database setup commands are documented in `database/README.md`.

Install Python dependencies:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Replace the placeholder `GEMINI_API_KEY` value in `.env` with a real Gemini API key before making Gemini calls.

Run the prototype:

```bash
python main.py
```

Optional local configuration:

```bash
cp .env.example .env
```

Example questions:

```text
What is the total revenue?
What are the top 10 customers by revenue?
What is the revenue by nation?
How many orders are there by order status?
What is the monthly order volume?
```

The CLI LLM path only generates SQL. The backend validates that the SQL is a single `SELECT` statement against the allowed TPC-H tables. PostgreSQL then validates the query with `EXPLAIN`. Only after validation and `EXPLAIN` pass is the SQL executed.

## Run Streamlit frontend

This reuses the same backend modules as the CLI. PostgreSQL should already be running with the TPC-H data loaded. Gemini is used by default.

Install dependencies:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Replace the placeholder `GEMINI_API_KEY` value in `.env` with a real Gemini API key.

Run the Streamlit app:

```bash
streamlit run streamlit_app.py
```

Example questions:

```text
What is the total revenue?
What are the top 10 customers by revenue?
What is the revenue by nation?
How many orders are there by order status?
What is the monthly order volume?
```

The Streamlit frontend shows the user question, deterministic answer summary, result table, generated SQL, used tables, selected model, attempt count, fallback status, graph trace steps, and feedback buttons. Feedback is stored locally in `logs/feedback.csv`.

## Run LangGraph SQL agent workflow

The Streamlit frontend runs a LangGraph SQL workflow with explicit nodes for loading schema context, SQL generation, validation, execution, SQL repair, fallback model switching, and final answer generation.

The app first uses Gemini Flash Lite Preview:

```text
LLM_PROVIDER=gemini
GEMINI_PRIMARY_MODEL=gemini-3.1-flash-lite-preview
```

If the primary API call fails, returns invalid SQL, fails SQL validation, or fails PostgreSQL execution, the graph tries the primary model up to two times by default. If a different fallback model is configured, it then retries with Gemini Flash:

```text
GEMINI_BACKUP_MODEL=gemini-2.5-flash
```

To use local Ollama instead, enable `Lokales Ollama verwenden` in the Streamlit sidebar. The Streamlit app keeps the model choices fixed: Gemini uses the configured Gemini primary/fallback models, and Ollama uses `llama3.2:3b` for both primary and fallback.

Run the app:

```bash
streamlit run streamlit_app.py
```

Useful local environment variables:

```text
GEMINI_API_KEY=<your-gemini-api-key>
LLM_PROVIDER=gemini
GEMINI_PRIMARY_MODEL=gemini-3.1-flash-lite-preview
GEMINI_BACKUP_MODEL=gemini-2.5-flash
MAX_PRIMARY_ATTEMPTS=2
OLLAMA_HOST=http://localhost:11434
PRIMARY_MODEL=llama3.2:3b
FALLBACK_MODEL=llama3.2:3b
LLM_TEMPERATURE=0
LLM_MAX_OUTPUT_TOKENS=1024
```

Every SQL generation attempt is logged to `logs/query_log.csv`. Streamlit feedback is logged to `logs/feedback.csv`.

The feedback controls support correction-driven reruns:

- `Good answer` and `Bad answer` save feedback only.
- `Retry with comment` sends the original question, previous SQL, previous answer, and your correction comment back through the LangGraph workflow.
- `Use fallback model` reruns the question with `FALLBACK_MODEL` immediately, optionally using your correction comment.

## Routing control layer

Streamlit now calls `run_orchestrator`, which runs a router before the existing LangGraph SQL agent. The router is a control layer only: it classifies intent, SQL need, clarification need, obvious unsafe requests, complexity tier, output mode, language, and a memory intent key. It does not generate SQL, validate SQL, execute SQL, or approve memory templates.

Router decisions can stop the workflow before SQL generation when a request is blocked, too vague, or does not require SQL. For SQL questions, the orchestrator uses the router complexity tier for model selection and then calls the public `run_sql_agent` wrapper so the existing SQL validation, execution, repair, fallback, normalization, and query logging behavior is preserved.

The router also exposes `template_candidates` through `src/agent/router_template_retriever.py`. This is currently a placeholder that always returns an empty list and has no side effects. It is designed to be replaced later by a vector-space or embedding-based cosine-similarity retriever. Retrieved templates are not implemented yet and cannot influence SQL generation, SQL validation, or SQL execution.

Golden tests keep the direct SQL-agent path by default. Use `python evaluation/run_evaluation.py --use-orchestrator Q01` to exercise the opt-in router-plus-SQL path during evaluation.

## Evaluation and logging

Run evaluation:

```bash
python evaluation/run_evaluation.py
```

View query logs:

```bash
cat logs/query_log.csv
```

View feedback logs:

```bash
cat logs/feedback.csv
```

`evaluation/golden_questions.yaml` contains predefined benchmark questions for the TPC-H dataset. `evaluation/run_evaluation.py` tests whether the prototype generates reasonable SQL by checking expected tables, expected SQL keywords, SQL validation, PostgreSQL `EXPLAIN`, and query execution.

`logs/query_log.csv` stores every processed question from Streamlit. `logs/feedback.csv` stores user feedback from the thumbs up/down buttons. These logs support traceability and manual validation while the prototype is still simple and local.

## Database backends

The SQL agent now selects its database backend through `DB_BACKEND`.

```text
DB_BACKEND=postgres
```

PostgreSQL demo mode is the default when `DB_BACKEND` is unset. It preserves the existing local TPC-H demo behavior and uses the existing PostgreSQL settings:

```text
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=agentic_ai
POSTGRES_USER=postgres
POSTGRES_PASSWORD=
```

The backend structure is:

```text
src/backends/base.py
src/backends/config.py
src/backends/factory.py
src/backends/demo/postgres_adapter.py
src/backends/databricks/databricks_adapter.py
```

`src/backends/demo` wraps the existing PostgreSQL demo logic. `src/backends/databricks` contains the optional Databricks SQL Warehouse integration. The LangGraph workflow still uses the same load-schema, generate-SQL, validate, execute, repair, fallback, and final-answer nodes.

## Databricks mode

Databricks mode is optional and selected with:

```text
DB_BACKEND=databricks
```

Required safe configuration names are listed in `.env.example`. Do not commit real credentials or workspace details. The app must never expose tokens, client secrets, server hostnames, HTTP paths, OAuth values, or full connection strings in logs or UI.

For local testing in this organization, use OAuth user-to-machine because personal access tokens are disabled:

```text
DATABRICKS_AUTH_TYPE=oauth_u2m
DATABRICKS_SERVER_HOSTNAME=<your-databricks-server-hostname>
DATABRICKS_HTTP_PATH=<your-sql-warehouse-http-path>
DATABRICKS_CATALOG=workspace
DATABRICKS_SCHEMA=default
DATABRICKS_ALLOWED_TABLES=workspace.default.datenabzug_projekt_tum_shipments,workspace.default.datenabzug_projekt_tum_invoices
```

PAT mode is available only as an isolated optional path:

```text
DATABRICKS_AUTH_TYPE=pat
DATABRICKS_ACCESS_TOKEN=<optional-token>
```

For AWS or Wuerth-hosted deployment, OAuth machine-to-machine with a service principal is the preferred direction:

```text
DATABRICKS_AUTH_TYPE=oauth_m2m
DATABRICKS_HOST=<your-databricks-workspace-url>
DATABRICKS_CLIENT_ID=<service-principal-client-id>
DATABRICKS_CLIENT_SECRET=<service-principal-client-secret>
```

Only the configured allowed tables are exposed to the agent schema context. The intended allowed tables are:

```text
workspace.default.datenabzug_projekt_tum_shipments
workspace.default.datenabzug_projekt_tum_invoices
```

### Databricks TLS certificates

Local Databricks OAuth and SQL Warehouse connections require the Python environment to trust the TLS certificate chain presented by the network. In corporate environments with TLS inspection, this usually means installing the company proxy/root CA certificate into the local trust store or pointing Python at a CA bundle that includes it.

If the smoke test fails with `SSLCertVerificationError` or `self-signed certificate in certificate chain`, create or use a PEM bundle that contains:

```text
certifi root certificates
corporate TLS inspection/root CA certificate
any endpoint protection proxy CA certificate used on the machine
```

For this local machine, the successful smoke test used a temporary bundle made from the virtualenv `certifi` CA file plus the local endpoint-protection CA bundle. Use environment variables to point Python and requests-compatible libraries at the bundle:

```bash
SSL_CERT_FILE=/path/to/company-ca-bundle.pem \
REQUESTS_CA_BUNDLE=/path/to/company-ca-bundle.pem \
python scripts/test_databricks_connection.py
```

Do not disable TLS verification. Do not commit certificate bundles if they are internal company assets. Prefer installing the corporate root CA through managed device policy or a documented local certificate setup.

Live Databricks tests are intentionally not run during implementation because starting or querying the SQL Warehouse is a manual step and the warehouse auto-stops after a short idle period. When you are ready for live testing, manually start the SQL Warehouse first, then run:

```bash
python scripts/test_databricks_connection.py
```

That script opens the Databricks connection, runs `SELECT 1`, and samples five rows from each allowed table. It prints only safe success messages and row counts.

## Run with Docker Compose

The Docker setup runs Streamlit and PostgreSQL in Docker Compose. The app service reads `.env` through `env_file`, so replace the placeholder Gemini API key before asking questions.

Make sure TPC-H CSV exports exist:

```bash
source .venv/bin/activate
python database/export_tpch_to_csv.py
```

If you set `LLM_PROVIDER=ollama`, Ollama still runs on the host machine and the Dockerized app connects through `http://host.docker.internal:11434`.

Start Docker Compose:

```bash
docker compose up --build
```

If your Docker install only has the legacy Compose binary, use the same command with `docker-compose`:

```bash
docker-compose up --build
```

Open Streamlit:

```text
http://localhost:8501
```

Stop containers:

```bash
docker compose down
```

Reset the database completely:

```bash
docker compose down -v
```

Then start again:

```bash
docker compose up --build
```

Dockerized PostgreSQL is exposed on host port `5433`, mapped to container port `5432`. Inside Docker, the Streamlit app connects to PostgreSQL at `postgres:5432`.

Database initialization only runs when the `postgres_data` Docker volume is empty. If the CSV files in `database/exports/` change, reset the database with `docker compose down -v` before restarting so PostgreSQL reruns the initialization scripts.

Test the Dockerized PostgreSQL database from your host:

```bash
psql -h localhost -p 5433 -U postgres -d agentic_ai -c "SELECT COUNT(*) FROM lineitem;"
```

Password:

```text
postgres
```
