# External Integrations

**Analysis Date:** 2026-06-21

## APIs & External Services

**LLM Providers:**
- Google Gemini - default hosted LLM provider for SQL generation, router classification, and fallback flows.
  - SDK/Client: `langchain_google_genai.ChatGoogleGenerativeAI` in `src/llm/model_adapter.py`; packages listed in `requirements.txt`.
  - Auth: `GEMINI_API_KEY` or `GOOGLE_API_KEY` read in `src/llm/model_adapter.py`.
  - Model config: `GEMINI_PRIMARY_MODEL`, `GEMINI_BACKUP_MODEL`, `GEMINI_EASY_MODEL`, `GEMINI_MEDIUM_MODEL`, `GEMINI_HARD_MODEL`, `GEMINI_FALLBACK_MODEL`, and `GEMINI_ROUTER_MODEL` read in `src/llm/model_adapter.py`, `src/agent/router.py`, and `src/agent/orchestrator.py`.
- Anthropic Claude - alternate hosted LLM provider for SQL generation, router classification, and tiered model selection.
  - SDK/Client: `langchain_anthropic.ChatAnthropic` in `src/llm/model_adapter.py`; package listed in `requirements.txt`.
  - Auth: `ANTHROPIC_API_KEY` read in `src/llm/model_adapter.py`.
  - Model config: `ANTHROPIC_PRIMARY_MODEL`, `ANTHROPIC_FALLBACK_MODEL`, `ANTHROPIC_EASY_MODEL`, `ANTHROPIC_MEDIUM_MODEL`, `ANTHROPIC_HARD_MODEL`, and `ANTHROPIC_ROUTER_MODEL` read in `src/llm/model_adapter.py`, `src/agent/router.py`, and `src/agent/orchestrator.py`.
- Ollama - optional local LLM provider selected through the Streamlit sidebar or `LLM_PROVIDER=ollama`.
  - SDK/Client: `langchain_ollama.ChatOllama` in `src/llm/model_adapter.py` and `src/agent/ollama_client.py`; packages listed in `requirements.txt`.
  - Auth: none detected.
  - Endpoint config: `OLLAMA_HOST`, `OLLAMA_MODEL`, `PRIMARY_MODEL`, `FALLBACK_MODEL`, `OLLAMA_EASY_MODEL`, `OLLAMA_MEDIUM_MODEL`, `OLLAMA_HARD_MODEL`, `OLLAMA_FALLBACK_MODEL`, and `OLLAMA_ROUTER_MODEL` read in `app/config.py`, `src/llm/model_adapter.py`, `src/agent/router.py`, and `src/agent/orchestrator.py`.

**Data Warehouses:**
- Databricks SQL Warehouse - optional/legacy backend for the `databricks` scenario.
  - SDK/Client: `databricks.sql.connect` and `databricks.sdk.core.oauth_service_principal` in `src/backends/databricks/databricks_adapter.py`; packages listed in `requirements.txt`.
  - Auth: `DATABRICKS_AUTH_TYPE` controls `oauth_u2m`, `oauth_m2m`, or `pat` in `src/backends/config.py`.
  - Required config: `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA` read in `src/backends/config.py`.
  - PAT auth config: `DATABRICKS_ACCESS_TOKEN` or `DATABRICKS_TOKEN` read in `src/backends/config.py`.
  - OAuth M2M config: `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET` read in `src/backends/config.py`.
  - Table allowlist: `DATABRICKS_ALLOWED_TABLES` normalized and checked against scenario allowlists in `src/backends/config.py` and `src/config/scenarios.py`.

**Not detected:**
- No Stripe, Supabase, AWS, S3, Firebase, Slack, Sentry, Redis, Celery, Kafka, RabbitMQ, Flask, FastAPI, `requests`, or `httpx` integration was detected in `requirements.txt`, `README.md`, `app/`, `src/`, `scripts/`, or `evaluation/`.

## Data Storage

**Databases:**
- PostgreSQL - normal local runtime database for `demo` and `wuerth_local` scenarios.
  - Connection: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` read in `app/config.py` and `scripts/ingest_wuerth_csv_to_postgres.py`.
  - Client: `psycopg` in `app/db.py`, `src/backends/demo/postgres_adapter.py`, and `scripts/ingest_wuerth_csv_to_postgres.py`.
  - Docker runtime: service `postgres` uses image `postgres:16` in `docker-compose.yml`.
  - Bootstrap schema/data: `docker/postgres/init/01_create_tpch_schema.sql`, `docker/postgres/init/02_load_tpch_data.sql`, `database/postgres_create_tpch_schema.sql`, and `database/postgres_load_tpch_csv.sql`.
  - Allowed tables: `region`, `nation`, `supplier`, `customer`, `part`, `partsupp`, `orders`, `lineitem`, `wuerth.invoices`, and `wuerth.shipments` declared in `src/config/scenarios.py`.
- DuckDB - local development and export source for TPC-H data, not the normal app backend.
  - Connection: file `database/tpch.duckdb` is generated locally and ignored by `.gitignore`; no env var config detected.
  - Client: `duckdb` in `database/create_tpch_database.py`, `database/export_tpch_to_csv.py`, and `database/inspect_schema.py`.
- Databricks SQL Warehouse - optional external backend for the `databricks` scenario.
  - Connection: Databricks env vars read in `src/backends/config.py`.
  - Client: `DatabricksAdapter` in `src/backends/databricks/databricks_adapter.py`.

**File Storage:**
- Local filesystem only - no cloud file storage integration detected.
- Committed demo CSV exports: `database/exports/customer.csv`, `database/exports/lineitem.csv`, `database/exports/nation.csv`, `database/exports/orders.csv`, `database/exports/part.csv`, `database/exports/partsupp.csv`, `database/exports/region.csv`, and `database/exports/supplier.csv`.
- Ignored Wuerth CSV import locations: `database/exports/wuerth/` and `database/exports/Wuerth/`, referenced in `README.md`, `.gitignore`, `.dockerignore`, and `scripts/ingest_wuerth_csv_to_postgres.py`.
- Semantic layer files: `semantic_layer/router_excerpt.yaml`, `semantic_layer/demo/tpch_semantic_layer.yaml`, and `semantic_layer/databricks/wuerth_semantic_layer.yaml`.
- Memory files: `memory/demo/solution_templates.yaml`, `memory/demo/memory_candidates.yaml`, `memory/demo/error_memory.yaml`, `memory/databricks/solution_templates.yaml`, `memory/databricks/memory_candidates.yaml`, and `memory/databricks/error_memory.yaml`.
- Logs and audits: `logs/feedback.csv` is present; runtime CSV logs use `LOG_DIR` from `src/agent/logging_utils.py`; memory audit logs are written by `src/agent/memory_store.py`.
- PowerPoint master template: `assets/templates/PPT_Vorlage_Wuerth.pptx` exists as a local template asset for future PowerPoint output generation. No current source file references it and no PowerPoint generation dependency is listed in `requirements.txt`.

**Caching:**
- No Redis, Memcached, disk cache, or external cache service detected.
- In-process cached router graph: `_compiled_router` module-level variable in `src/agent/orchestrator.py`.
- Scenario override uses a `ContextVar` in `src/config/scenarios.py`, not an external cache.

## Authentication & Identity

**Auth Provider:**
- End-user authentication: Not detected. Streamlit UI in `streamlit_app.py` has no login provider, session identity provider, or role system.
  - Implementation: local UI state through `st.session_state` in `streamlit_app.py`.
- Service authentication: provider API keys and database credentials are read from environment variables in `src/llm/model_adapter.py`, `app/config.py`, and `src/backends/config.py`.
- Databricks authentication: supports `oauth_u2m`, `oauth_m2m`, and `pat` through `src/backends/config.py` and `src/backends/databricks/databricks_adapter.py`.

## Monitoring & Observability

**Error Tracking:**
- None detected. No Sentry, OpenTelemetry, Datadog, Honeycomb, or similar package or config was found in `requirements.txt`, `app/`, `src/`, or root config files.

**Logs:**
- Query logs, feedback logs, router logs, and memory audit logs are local CSV files written by `src/agent/logging_utils.py`, `src/agent/orchestrator.py`, and `src/agent/memory_store.py`.
- Runtime log directory defaults to `logs` and can be overridden with `LOG_DIR` in `src/agent/logging_utils.py`.
- Docker and ingestion script logging use standard process output and Python logging in `scripts/ingest_wuerth_csv_to_postgres.py`.

## CI/CD & Deployment

**Hosting:**
- Local/container hosting through Docker Compose in `docker-compose.yml`.
- App container command is `streamlit run streamlit_app.py --server.address=0.0.0.0 --server.port=8501` in `Dockerfile`.
- Streamlit UI is exposed on port `8501` in `Dockerfile` and `docker-compose.yml`.
- PostgreSQL is exposed from container port `5432` to host port `5433` in `docker-compose.yml`.
- No cloud hosting manifest was detected, such as `render.yaml`, `fly.toml`, `railway.json`, `Procfile`, or Kubernetes manifests.

**CI Pipeline:**
- None detected. No `.github/`, `.gitlab-ci.yml`, `azure-pipelines.yml`, or `Jenkinsfile` was detected.

## Environment Configuration

**Required env vars:**
- Local PostgreSQL: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` are consumed by `app/config.py` and `scripts/ingest_wuerth_csv_to_postgres.py`.
- Scenario selection: `DATA_SCENARIO` is consumed by `src/config/scenarios.py`.
- LLM provider selection: `LLM_PROVIDER` is consumed by `src/llm/model_adapter.py`.
- Gemini: `GEMINI_API_KEY` or `GOOGLE_API_KEY` is consumed by `src/llm/model_adapter.py`.
- Anthropic: `ANTHROPIC_API_KEY` is consumed by `src/llm/model_adapter.py`.
- Ollama: `OLLAMA_HOST` is consumed by `app/config.py`, `src/llm/model_adapter.py`, `src/agent/router.py`, `src/agent/orchestrator.py`, and `src/agent/langgraph_sql_agent.py`.
- Model overrides: `PRIMARY_MODEL`, `FALLBACK_MODEL`, `OLLAMA_MODEL`, `GEMINI_PRIMARY_MODEL`, `GEMINI_BACKUP_MODEL`, `ANTHROPIC_PRIMARY_MODEL`, `ANTHROPIC_FALLBACK_MODEL`, provider tier model vars, `LLM_TEMPERATURE`, `LLM_MAX_OUTPUT_TOKENS`, and `MAX_PRIMARY_ATTEMPTS` are consumed by `src/llm/model_adapter.py`, `src/agent/router.py`, `src/agent/orchestrator.py`, and `src/agent/langgraph_sql_agent.py`.
- Databricks optional backend: `DATABRICKS_AUTH_TYPE`, `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA`, `DATABRICKS_ALLOWED_TABLES`, `DATABRICKS_ACCESS_TOKEN`, `DATABRICKS_TOKEN`, `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET` are consumed by `src/backends/config.py`.
- Logs: `LOG_DIR` is consumed by `src/agent/logging_utils.py`.

**Secrets location:**
- `.env` is the expected local secrets/config file, is ignored by `.gitignore`, and is excluded by `.dockerignore`.
- `.env.example` is present as an environment template, but its contents were not read.
- Docker Compose also references environment configuration in `docker-compose.yml`; secret-like values must stay in `.env` or runtime environment, not in committed source.

## Webhooks & Callbacks

**Incoming:**
- None detected. The repository exposes a Streamlit HTTP UI through `streamlit_app.py`, `Dockerfile`, and `docker-compose.yml`, but no webhook route framework such as FastAPI or Flask was detected.

**Outgoing:**
- LLM calls to Gemini, Anthropic, or Ollama through `src/llm/model_adapter.py`.
- Optional Databricks SQL Warehouse calls through `src/backends/databricks/databricks_adapter.py`.
- PostgreSQL calls through `app/db.py`, `src/backends/demo/postgres_adapter.py`, and `scripts/ingest_wuerth_csv_to_postgres.py`.
- No webhook callback sender, Slack notifier, email provider, or HTTP callback client was detected.

---

*Integration audit: 2026-06-21*
