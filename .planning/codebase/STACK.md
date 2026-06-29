# Technology Stack

**Analysis Date:** 2026-06-21

## Languages

**Primary:**
- Python 3.11 - application code, LangGraph agents, Streamlit UI, backend adapters, data loaders, and evaluation scripts. Runtime image is declared in `Dockerfile`.

**Secondary:**
- SQL - PostgreSQL schema/load/test SQL and query fixtures live in `database/postgres_create_tpch_schema.sql`, `database/postgres_load_tpch_csv.sql`, `database/postgres_test_queries.sql`, `docker/postgres/init/01_create_tpch_schema.sql`, `docker/postgres/init/02_load_tpch_data.sql`, and `evaluation/**/solution_sql/*.sql`.
- YAML - semantic layers, router context, golden questions, and memory files live in `semantic_layer/router_excerpt.yaml`, `semantic_layer/demo/tpch_semantic_layer.yaml`, `semantic_layer/wuerth_local/wuerth_semantic_layer.yaml`, `evaluation/**/golden_questions.yaml`, and `memory/**.yaml`.
- CSV - committed demo TPC-H exports live in `database/exports/*.csv`; local Wuerth CSV inputs are expected under ignored paths `database/exports/wuerth/` or `database/exports/Wuerth/`.
- Dockerfile and Docker Compose - local container runtime is defined in `Dockerfile`, `docker-compose.yml`, and `.dockerignore`.

## Runtime

**Environment:**
- Python 3.11 in containers via `python:3.11-slim` in `Dockerfile`.
- Streamlit serves the primary app on port `8501` via `streamlit run streamlit_app.py` in `Dockerfile`.
- Docker Compose starts `postgres`, `wuerth_ingest`, and `app` services in `docker-compose.yml`; PostgreSQL uses image `postgres:16`.
- The old direct CLI entry point was removed; `streamlit_app.py` is the normal UI path.

**Package Manager:**
- pip with `requirements.txt`.
- Lockfile: missing. No `requirements.lock`, `pyproject.toml`, `poetry.lock`, `Pipfile.lock`, or equivalent was detected.
- Dependency versions: unpinned in `requirements.txt`; installs resolve latest compatible versions at install time.

## Frameworks

**Core:**
- Streamlit, unpinned - interactive web UI in `streamlit_app.py`.
- LangGraph, unpinned - router and SQL-agent workflow graphs in `src/agent/router.py`, `src/agent/orchestrator.py`, and `src/agent/langgraph_sql_agent.py`.
- LangChain provider integrations, unpinned - LLM client adapter in `src/llm/model_adapter.py`.
- psycopg binary, unpinned - PostgreSQL access in `app/db.py`, `src/backends/demo/postgres_adapter.py`, and `scripts/ingest_wuerth_csv_to_postgres.py`.
- Databricks SQL connector and Databricks SDK, unpinned - optional Databricks backend in `src/backends/databricks/databricks_adapter.py`.
- pandas and Altair, unpinned - reporting and charts in `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, and `streamlit_app.py`.
- PyYAML, unpinned - semantic layers, memory files, and golden questions in `src/config/scenarios.py`, `src/agent/memory_store.py`, and `src/agent/golden_test_runner.py`.

**Testing:**
- unittest from the Python standard library - test modules in `evaluation/test_*.py`.
- compileall from the Python standard library - README validation command checks `app`, `src`, `scripts`, `streamlit_app.py`, and `evaluation`.
- No pytest, coverage, or test-runner config file was detected in `requirements.txt` or repository root.

**Build/Dev:**
- Docker and Docker Compose - local stack in `Dockerfile` and `docker-compose.yml`.
- python-dotenv, unpinned - environment loading in `app/config.py`, `src/llm/model_adapter.py`, `src/agent/router.py`, `src/agent/orchestrator.py`, and `src/agent/langgraph_sql_agent.py`.
- DuckDB, unpinned - local TPC-H database generation/export tools in `database/create_tpch_database.py`, `database/export_tpch_to_csv.py`, and `database/inspect_schema.py`.
- No formatter or linter config file was detected, such as `.prettierrc`, `.eslintrc`, `ruff.toml`, or `pyproject.toml`.

## Key Dependencies

**Critical:**
- `streamlit` - renders the interactive app and workflow pages in `streamlit_app.py`.
- `langgraph` - composes router and SQL agent state machines in `src/agent/router.py`, `src/agent/orchestrator.py`, and `src/agent/langgraph_sql_agent.py`.
- `langchain-google-genai` and `google-genai` - Gemini provider support in `src/llm/model_adapter.py`.
- `langchain-anthropic` - Anthropic provider support in `src/llm/model_adapter.py`.
- `langchain-ollama` and `ollama` - local Ollama provider support in `src/llm/model_adapter.py`.
- `psycopg[binary]` - PostgreSQL connectivity in `app/db.py` and Wuerth CSV ingestion in `scripts/ingest_wuerth_csv_to_postgres.py`.
- `databricks-sql-connector` and `databricks-sdk` - optional Databricks SQL Warehouse connectivity and OAuth M2M support in `src/backends/databricks/databricks_adapter.py`.
- `pandas` and `altair` - dataframe conversion, report summaries, KPI cards, and chart rendering in `src/agent/reporting_agent.py` and `streamlit_app.py`.
- `PyYAML` - semantic layer and memory parsing in `src/config/scenarios.py`, `src/agent/memory_store.py`, and `src/agent/memory_retriever.py`.

**Infrastructure:**
- `python-dotenv` - loads `.env` values in `app/config.py`, `src/llm/model_adapter.py`, `src/agent/router.py`, `src/agent/orchestrator.py`, and `src/agent/langgraph_sql_agent.py`.
- `duckdb` - creates and inspects local TPC-H development data in `database/create_tpch_database.py` and `database/inspect_schema.py`.
- `tabulate` - listed in `requirements.txt`; no active runtime import was detected after removing the old direct CLI stack.
- `sqlalchemy` - listed in `requirements.txt`; no direct import was detected in current Python files.
- PowerPoint generation dependencies - not detected. `assets/templates/PPT_Vorlage_Wuerth.pptx` exists as a master template asset, but no package such as `python-pptx` is listed in `requirements.txt` and no source code currently references the template.

## Configuration

**Environment:**
- Environment files: `.env.example` is present, `.env` is gitignored in `.gitignore`, and `.env` is excluded from Docker build context in `.dockerignore`. Contents were not read.
- PostgreSQL config names are read in `app/config.py` and `scripts/ingest_wuerth_csv_to_postgres.py`: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.
- Scenario selection is read in `src/config/scenarios.py`: `DATA_SCENARIO`, with supported scenario IDs `demo`, `wuerth_local`, and `databricks`.
- LLM provider config is read in `src/llm/model_adapter.py` and `src/agent/langgraph_sql_agent.py`: `LLM_PROVIDER`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_HOST`, `PRIMARY_MODEL`, `FALLBACK_MODEL`, `OLLAMA_MODEL`, `GEMINI_PRIMARY_MODEL`, `GEMINI_BACKUP_MODEL`, `ANTHROPIC_PRIMARY_MODEL`, `ANTHROPIC_FALLBACK_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_OUTPUT_TOKENS`, and `MAX_PRIMARY_ATTEMPTS`.
- Router/orchestrator model tier config is read in `src/agent/router.py` and `src/agent/orchestrator.py`: `ROUTER_EXCERPT_PATH`, `ANTHROPIC_ROUTER_MODEL`, `GEMINI_ROUTER_MODEL`, `OLLAMA_ROUTER_MODEL`, `ANTHROPIC_EASY_MODEL`, `ANTHROPIC_MEDIUM_MODEL`, `ANTHROPIC_HARD_MODEL`, `GEMINI_EASY_MODEL`, `GEMINI_MEDIUM_MODEL`, `GEMINI_HARD_MODEL`, `GEMINI_FALLBACK_MODEL`, `OLLAMA_EASY_MODEL`, `OLLAMA_MEDIUM_MODEL`, `OLLAMA_HARD_MODEL`, and `OLLAMA_FALLBACK_MODEL`.
- Databricks config is read in `src/backends/config.py`: `DATABRICKS_AUTH_TYPE`, `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA`, `DATABRICKS_ALLOWED_TABLES`, `DATABRICKS_ACCESS_TOKEN`, `DATABRICKS_TOKEN`, `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET`.
- Logging location is read in `src/agent/logging_utils.py`: `LOG_DIR`.

**Build:**
- Container image build is defined in `Dockerfile`.
- Multi-service local runtime is defined in `docker-compose.yml`.
- Docker exclusions are defined in `.dockerignore`.
- PostgreSQL bootstrap SQL is mounted from `docker/postgres/init/`.
- No application build config beyond Docker and `requirements.txt` was detected.

## Platform Requirements

**Development:**
- Python 3.11 and pip are required by `Dockerfile` and `requirements.txt`.
- Docker Compose is the normal local workflow via `docker-compose.yml`.
- PostgreSQL 16 is provisioned by Docker Compose through image `postgres:16` in `docker-compose.yml`.
- Optional local LLM use requires Ollama reachable through `OLLAMA_HOST`, with provider selection handled in `streamlit_app.py` and `src/llm/model_adapter.py`.
- Optional Gemini or Anthropic use requires API keys exposed through environment variables consumed by `src/llm/model_adapter.py`.
- Optional Databricks use requires explicit `DATA_SCENARIO=databricks` and Databricks env vars consumed by `src/backends/config.py`.
- Wuerth CSV local data is expected under ignored paths `database/exports/wuerth/` or `database/exports/Wuerth/` and ingested by `scripts/ingest_wuerth_csv_to_postgres.py`.

**Production:**
- No managed production deployment config was detected. The repository currently exposes a local/containerized Streamlit app through `Dockerfile` and `docker-compose.yml`.
- No CI/CD pipeline config was detected under `.github/`, `.gitlab-ci.yml`, `azure-pipelines.yml`, `Jenkinsfile`, or similar root deployment files.

---

*Stack analysis: 2026-06-21*
