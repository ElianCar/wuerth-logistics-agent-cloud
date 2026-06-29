<!-- GSD:project-start source:PROJECT.md -->
## Project

**Wuerth Logistics Agent Presentation Export**

This project continues the existing Wuerth logistics agent prototype and makes its output presentation-ready. The agent already answers logistics questions through the Streamlit UI, routes requests, generates safe SQL, executes against supported scenarios, builds summaries, renders simple charts, and exports result tables. The next increment turns successful agent output into Wuerth-branded PowerPoint slides using `assets/templates/PPT_Vorlage_Wuerth.pptx`, while closing the remaining presentation-readiness gaps around memory governance, documentation, and richer visuals.

**Core Value:** Users can turn a validated logistics analysis result into a clear Wuerth-branded PowerPoint output with minimal manual cleanup.

### Constraints

- **Base branch**: Build from `origin/dev` behavior on local branch `codex/remaining-github-issues`.
- **Tech stack**: Python 3.11, Streamlit, LangGraph, pandas, Altair, PostgreSQL, optional Databricks.
- **Template asset**: Use `assets/templates/PPT_Vorlage_Wuerth.pptx`; do not hardcode Leon's local project path.
- **Output safety**: Generate PowerPoint only from successful, validated query results.
- **Architecture boundary**: Keep PPT generation behind a pure backend/export module, then expose a thin Streamlit download button.
- **Testing**: Use existing `unittest` style under `evaluation/test_*.py`; PPT export tests should not require local PowerPoint installation.
- **Documentation**: Final docs must explain implemented versus conceptual parts and known source-data limitations.
- **Security**: Existing app lacks broad app-level auth; avoid presenting lightweight template RBAC as full production security.
- **Data limits**: Local Wuerth CSV source data lacks several business columns; unsupported KPI answers should remain explicit limitations.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.11 - application code, LangGraph agents, Streamlit UI, backend adapters, data loaders, and evaluation scripts. Runtime image is declared in `Dockerfile`.
- SQL - PostgreSQL schema/load/test SQL and query fixtures live in `database/postgres_create_tpch_schema.sql`, `database/postgres_load_tpch_csv.sql`, `database/postgres_test_queries.sql`, `docker/postgres/init/01_create_tpch_schema.sql`, `docker/postgres/init/02_load_tpch_data.sql`, and `evaluation/**/solution_sql/*.sql`.
- YAML - semantic layers, router context, golden questions, and memory files live in `semantic_layer/router_excerpt.yaml`, `semantic_layer/demo/tpch_semantic_layer.yaml`, `semantic_layer/wuerth_local/wuerth_semantic_layer.yaml`, `evaluation/**/golden_questions.yaml`, and `memory/**.yaml`.
- CSV - committed demo TPC-H exports live in `database/exports/*.csv`; local Wuerth CSV inputs are expected under ignored paths `database/exports/wuerth/` or `database/exports/Wuerth/`.
- Dockerfile and Docker Compose - local container runtime is defined in `Dockerfile`, `docker-compose.yml`, and `.dockerignore`.
## Runtime
- Python 3.11 in containers via `python:3.11-slim` in `Dockerfile`.
- Streamlit serves the primary app on port `8501` via `streamlit run streamlit_app.py` in `Dockerfile`.
- Docker Compose starts `postgres`, `wuerth_ingest`, and `app` services in `docker-compose.yml`; PostgreSQL uses image `postgres:16`.
- The old direct CLI entry point was removed; `streamlit_app.py` is the normal UI path.
- pip with `requirements.txt`.
- Lockfile: missing. No `requirements.lock`, `pyproject.toml`, `poetry.lock`, `Pipfile.lock`, or equivalent was detected.
- Dependency versions: unpinned in `requirements.txt`; installs resolve latest compatible versions at install time.
## Frameworks
- Streamlit, unpinned - interactive web UI in `streamlit_app.py`.
- LangGraph, unpinned - router and SQL-agent workflow graphs in `src/agent/router.py`, `src/agent/orchestrator.py`, and `src/agent/langgraph_sql_agent.py`.
- LangChain provider integrations, unpinned - LLM client adapter in `src/llm/model_adapter.py`.
- psycopg binary, unpinned - PostgreSQL access in `app/db.py`, `src/backends/demo/postgres_adapter.py`, and `scripts/ingest_wuerth_csv_to_postgres.py`.
- Databricks SQL connector and Databricks SDK, unpinned - optional Databricks backend in `src/backends/databricks/databricks_adapter.py`.
- pandas and Altair, unpinned - reporting and charts in `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, and `streamlit_app.py`.
- PyYAML, unpinned - semantic layers, memory files, and golden questions in `src/config/scenarios.py`, `src/agent/memory_store.py`, and `src/agent/golden_test_runner.py`.
- unittest from the Python standard library - test modules in `evaluation/test_*.py`.
- compileall from the Python standard library - README validation command checks `app`, `src`, `scripts`, `streamlit_app.py`, and `evaluation`.
- No pytest, coverage, or test-runner config file was detected in `requirements.txt` or repository root.
- Docker and Docker Compose - local stack in `Dockerfile` and `docker-compose.yml`.
- python-dotenv, unpinned - environment loading in `app/config.py`, `src/llm/model_adapter.py`, `src/agent/router.py`, `src/agent/orchestrator.py`, and `src/agent/langgraph_sql_agent.py`.
- DuckDB, unpinned - local TPC-H database generation/export tools in `database/create_tpch_database.py`, `database/export_tpch_to_csv.py`, and `database/inspect_schema.py`.
- No formatter or linter config file was detected, such as `.prettierrc`, `.eslintrc`, `ruff.toml`, or `pyproject.toml`.
## Key Dependencies
- `streamlit` - renders the interactive app and workflow pages in `streamlit_app.py`.
- `langgraph` - composes router and SQL agent state machines in `src/agent/router.py`, `src/agent/orchestrator.py`, and `src/agent/langgraph_sql_agent.py`.
- `langchain-google-genai` and `google-genai` - Gemini provider support in `src/llm/model_adapter.py`.
- `langchain-anthropic` - Anthropic provider support in `src/llm/model_adapter.py`.
- `langchain-ollama` and `ollama` - local Ollama provider support in `src/llm/model_adapter.py`.
- `psycopg[binary]` - PostgreSQL connectivity in `app/db.py` and Wuerth CSV ingestion in `scripts/ingest_wuerth_csv_to_postgres.py`.
- `databricks-sql-connector` and `databricks-sdk` - optional Databricks SQL Warehouse connectivity and OAuth M2M support in `src/backends/databricks/databricks_adapter.py`.
- `pandas` and `altair` - dataframe conversion, report summaries, KPI cards, and chart rendering in `src/agent/reporting_agent.py` and `streamlit_app.py`.
- `PyYAML` - semantic layer and memory parsing in `src/config/scenarios.py`, `src/agent/memory_store.py`, and `src/agent/memory_retriever.py`.
- `python-dotenv` - loads `.env` values in `app/config.py`, `src/llm/model_adapter.py`, `src/agent/router.py`, `src/agent/orchestrator.py`, and `src/agent/langgraph_sql_agent.py`.
- `duckdb` - creates and inspects local TPC-H development data in `database/create_tpch_database.py` and `database/inspect_schema.py`.
- `tabulate` - listed in `requirements.txt`; no active runtime import was detected after removing the old direct CLI stack.
- `sqlalchemy` - listed in `requirements.txt`; no direct import was detected in current Python files.
- PowerPoint generation dependencies - not detected. `assets/templates/PPT_Vorlage_Wuerth.pptx` exists as a master template asset, but no package such as `python-pptx` is listed in `requirements.txt` and no source code currently references the template.
## Configuration
- Environment files: `.env.example` is present, `.env` is gitignored in `.gitignore`, and `.env` is excluded from Docker build context in `.dockerignore`. Contents were not read.
- PostgreSQL config names are read in `app/config.py` and `scripts/ingest_wuerth_csv_to_postgres.py`: `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.
- Scenario selection is read in `src/config/scenarios.py`: `DATA_SCENARIO`, with supported scenario IDs `demo`, `wuerth_local`, and `databricks`.
- LLM provider config is read in `src/llm/model_adapter.py` and `src/agent/langgraph_sql_agent.py`: `LLM_PROVIDER`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `OLLAMA_HOST`, `PRIMARY_MODEL`, `FALLBACK_MODEL`, `OLLAMA_MODEL`, `GEMINI_PRIMARY_MODEL`, `GEMINI_BACKUP_MODEL`, `ANTHROPIC_PRIMARY_MODEL`, `ANTHROPIC_FALLBACK_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_OUTPUT_TOKENS`, and `MAX_PRIMARY_ATTEMPTS`.
- Router/orchestrator model tier config is read in `src/agent/router.py` and `src/agent/orchestrator.py`: `ROUTER_EXCERPT_PATH`, `ANTHROPIC_ROUTER_MODEL`, `GEMINI_ROUTER_MODEL`, `OLLAMA_ROUTER_MODEL`, `ANTHROPIC_EASY_MODEL`, `ANTHROPIC_MEDIUM_MODEL`, `ANTHROPIC_HARD_MODEL`, `GEMINI_EASY_MODEL`, `GEMINI_MEDIUM_MODEL`, `GEMINI_HARD_MODEL`, `GEMINI_FALLBACK_MODEL`, `OLLAMA_EASY_MODEL`, `OLLAMA_MEDIUM_MODEL`, `OLLAMA_HARD_MODEL`, and `OLLAMA_FALLBACK_MODEL`.
- Databricks config is read in `src/backends/config.py`: `DATABRICKS_AUTH_TYPE`, `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA`, `DATABRICKS_ALLOWED_TABLES`, `DATABRICKS_ACCESS_TOKEN`, `DATABRICKS_TOKEN`, `DATABRICKS_HOST`, `DATABRICKS_CLIENT_ID`, and `DATABRICKS_CLIENT_SECRET`.
- Logging location is read in `src/agent/logging_utils.py`: `LOG_DIR`.
- Container image build is defined in `Dockerfile`.
- Multi-service local runtime is defined in `docker-compose.yml`.
- Docker exclusions are defined in `.dockerignore`.
- PostgreSQL bootstrap SQL is mounted from `docker/postgres/init/`.
- No application build config beyond Docker and `requirements.txt` was detected.
## Platform Requirements
- Python 3.11 and pip are required by `Dockerfile` and `requirements.txt`.
- Docker Compose is the normal local workflow via `docker-compose.yml`.
- PostgreSQL 16 is provisioned by Docker Compose through image `postgres:16` in `docker-compose.yml`.
- Optional local LLM use requires Ollama reachable through `OLLAMA_HOST`, with provider selection handled in `streamlit_app.py` and `src/llm/model_adapter.py`.
- Optional Gemini or Anthropic use requires API keys exposed through environment variables consumed by `src/llm/model_adapter.py`.
- Optional Databricks use requires explicit `DATA_SCENARIO=databricks` and Databricks env vars consumed by `src/backends/config.py`.
- Wuerth CSV local data is expected under ignored paths `database/exports/wuerth/` or `database/exports/Wuerth/` and ingested by `scripts/ingest_wuerth_csv_to_postgres.py`.
- No managed production deployment config was detected. The repository currently exposes a local/containerized Streamlit app through `Dockerfile` and `docker-compose.yml`.
- No CI/CD pipeline config was detected under `.github/`, `.gitlab-ci.yml`, `azure-pipelines.yml`, `Jenkinsfile`, or similar root deployment files.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Use lower_snake_case for Python modules in `src/`, `app/`, `scripts/`, and `evaluation/`: `src/agent/visualization_spec.py`, `src/agent/golden_test_runner.py`, `scripts/validate_wuerth_local_setup.py`.
- Use package directories for bounded areas: `src/agent/`, `src/backends/`, `src/config/`, `src/llm/`, `app/`.
- Use `test_*.py` for discoverable test files under `evaluation/`: `evaluation/test_orchestrator.py`, `evaluation/test_visualization_spec.py`, `evaluation/test_backend_config_and_validation.py`.
- Use scenario-scoped fixture directories for current golden data: `evaluation/demo/` and `evaluation/wuerth_local/`. Databricks fixtures were removed from the current local hand-in/demo scope.
- Keep binary and branded assets under `assets/templates/`; the copied PowerPoint master template is `assets/templates/PPT_Vorlage_Wuerth.pptx`.
- Use snake_case verbs that describe the action: `build_reporting_result()` in `src/agent/reporting_agent.py`, `validate_generated_sql()` in `src/agent/sql_validator.py`, `load_databricks_config()` in `src/backends/config.py`.
- Prefix private helper functions with `_`: `_safe_databricks_error()` in `src/backends/databricks/databricks_adapter.py`, `_chart_spec()` in `src/agent/visualization_spec.py`, `_write_yaml()` in `src/agent/memory_store.py`.
- Use `build_`, `load_`, `validate_`, `run_`, `render_`, `log_`, `get_`, and `parse_` prefixes consistently for public helpers in `src/agent/`, `src/config/`, and `streamlit_app.py`.
- Use `test_*` method names inside `unittest.TestCase` classes in `evaluation/test_*.py`.
- Use snake_case for locals and parameters: `router_context`, `query_result`, `source_tables`, `validation_success` in `src/agent/orchestrator.py`.
- Use UPPER_SNAKE_CASE for constants and environment-key collections: `SUPPORTED_BACKENDS` in `src/backends/config.py`, `CHART_DISPLAY_ROW_LIMIT` in `src/agent/visualization_spec.py`, `QUERY_LOG_FIELDS` in `src/agent/logging_utils.py`.
- Use lowercase stable IDs for scenarios and providers: `"demo"`, `"wuerth_local"`, `"databricks"` in `src/config/scenarios.py`; `"gemini"`, `"anthropic"`, `"ollama"` in `src/llm/model_adapter.py`.
- Keep graph and result dictionary keys lower_snake_case to match `TypedDict` fields: `SQLAgentState` in `src/agent/langgraph_sql_agent.py`, `OrchestratorState` in `src/agent/orchestrator.py`.
- Use PascalCase for classes, dataclasses, protocols, and errors: `SQLAgentConfig` in `src/agent/langgraph_sql_agent.py`, `ScenarioConfig` in `src/config/scenarios.py`, `SQLBackend` in `src/backends/base.py`, `BackendConfigError` in `src/backends/config.py`.
- Use frozen dataclasses for immutable configuration and result records: `DatabricksBackendConfig` and `BackendSettings` in `src/backends/config.py`, `ModelResponse` in `src/llm/model_adapter.py`.
- Use `TypedDict` for mutable LangGraph state payloads: `RouterState` in `src/agent/router.py`, `SQLAgentState` in `src/agent/langgraph_sql_agent.py`.
## Code Style
- No formatter config is detected. Follow the existing PEP 8 style used in `src/agent/visualization_spec.py`, `src/backends/config.py`, and `evaluation/test_orchestrator.py`: 4-space indentation, blank lines between import groups, and readable wrapped calls.
- Use modern type hints such as `list[str]`, `dict[str, Any]`, `str | None`, and `tuple[str, ...]` as in `src/agent/reporting_agent.py` and `src/config/scenarios.py`.
- Add `from __future__ import annotations` to new modern modules under `src/`, `scripts/`, and `evaluation/`; existing examples include `src/agent/orchestrator.py`, `src/backends/base.py`, and `evaluation/test_visualization_spec.py`.
- Prefer `pathlib.Path` for filesystem paths in new code, matching `src/config/scenarios.py`, `src/agent/golden_test_runner.py`, and `scripts/validate_wuerth_local_setup.py`.
- Use keyword-only parameters for complex builder APIs, matching `build_reporting_result()` in `src/agent/reporting_agent.py` and `build_visualization_spec()` in `src/agent/visualization_spec.py`.
- Not detected. There is no `pyproject.toml`, `.flake8`, `ruff.toml`, or lint command in `requirements.txt`.
- Use the repository's general syntax check from `README.md`: `python -m compileall app src scripts streamlit_app.py evaluation`.
- Treat deterministic validators as the local style guardrail: SQL safety lives in `src/agent/sql_validator.py`, scenario validation lives in `scripts/validate_wuerth_local_setup.py`, and output comparison lives in `src/agent/golden_test_runner.py`.
## Import Organization
- No configured path aliases are detected. Use absolute imports from repo-root packages: `from src.config.scenarios import get_active_scenario` in `src/backends/config.py`, `from app.db import get_connection` in `src/backends/demo/postgres_adapter.py`.
- CLI scripts that are run directly add `PROJECT_ROOT` to `sys.path` before local imports: `evaluation/run_evaluation.py` and `scripts/validate_wuerth_local_setup.py`.
- Avoid adding logic to package markers. Existing `__init__.py` files are empty in `src/__init__.py`, `src/agent/__init__.py`, `src/backends/__init__.py`, and `app/__init__.py`.
## Error Handling
- Define domain-specific errors close to the domain: `BackendConfigError` in `src/backends/config.py`, `ScenarioConfigError` in `src/config/scenarios.py`, `ModelAdapterError` in `src/llm/model_adapter.py`, `MemoryStoreError` in `src/agent/memory_store.py`.
- Raise configuration errors with missing key names, not secret values. `load_databricks_config()` in `src/backends/config.py` reports missing env var names and tests assert that sensitive placeholders are absent in `evaluation/test_backend_config_and_validation.py`.
- Sanitize external connector exceptions before returning them to callers. `_safe_databricks_error()` in `src/backends/databricks/databricks_adapter.py` reports the connector error type while omitting host, path, and token values.
- Return structured validation objects for expected invalid input rather than raising exceptions. `validate_generated_sql()` returns `SQLValidationResult` in `src/agent/sql_validator.py`.
- Keep terminal and UI flows resilient. `streamlit_app.py` catches `MemoryStoreError` around memory review actions.
- Preserve exception chaining for dependency and configuration failures with `raise ... from error`, as in `src/llm/model_adapter.py`, `src/backends/databricks/databricks_adapter.py`, and `scripts/validate_wuerth_local_setup.py`.
- Logging failures are intentionally non-fatal: `append_csv_row()` in `src/agent/logging_utils.py` catches exceptions and prints `Logging failed for ...`.
## Logging
- Use `src/agent/logging_utils.py` for query, feedback, router, and memory audit CSV output. It owns CSV schemas such as `QUERY_LOG_FIELDS` and `FEEDBACK_LOG_FIELDS`.
- Use Python's `logging` module for operational scripts, as in `scripts/ingest_wuerth_csv_to_postgres.py`.
- Use `print()` for short CLI status in `evaluation/run_evaluation.py` and `scripts/validate_wuerth_local_setup.py`.
- Never log raw credentials or connector secrets. Follow the safe-error pattern in `src/backends/databricks/databricks_adapter.py` and the assertions in `evaluation/test_backend_config_and_validation.py`.
## Comments
- Prefer clear function names and structured return values over inline commentary. Most helper modules under `src/agent/` are self-documenting through typed signatures and constants.
- Add a docstring when a public builder has important side-effect boundaries. Examples: `build_reporting_result()` in `src/agent/reporting_agent.py` states that it does not generate SQL, modify SQL, call a database, or call an LLM; `build_visualization_spec()` in `src/agent/visualization_spec.py` states that it only inspects existing result data.
- Use comments sparingly around non-obvious compatibility or migration logic. CSV schema migration is centralized in `ensure_csv_columns()` in `src/agent/logging_utils.py`.
- Not applicable. This is a Python repository with no TypeScript source.
- Use Python docstrings for public protocols and boundary methods, as in `SQLBackend` in `src/backends/base.py`.
## Function Design
## Module Design
- Keep scenario state behind the context variable helpers in `src/config/scenarios.py`: use `set_active_scenario_id()` and `reset_active_scenario_id()` in tests and UI flows.
- Keep Streamlit session state inside `streamlit_app.py`. New non-UI behavior should live in `src/agent/` or `src/config/` so it can be tested without Streamlit.
- Keep lazy graph caching private to the module, following `_compiled_router` and `_get_compiled_router()` in `src/agent/orchestrator.py`.
- Resolve repository assets with `Path` rather than absolute local paths. Future PowerPoint export code should reference `assets/templates/PPT_Vorlage_Wuerth.pptx` through a module-level `Path` constant near the export implementation.
- Keep binary template handling out of Streamlit callbacks where practical. Expose a pure export function under `src/agent/` or a new focused module so `evaluation/test_*.py` can test the PowerPoint output path.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## System Overview
```text
|                       User-facing application                          |
|                                                                       |
|  Streamlit UI                              Golden test CLI             |
|  `streamlit_app.py`                        `evaluation/run_evaluation.py` |
|                         Orchestration layer                            |
|                                                                       |
|  Router LangGraph          SQL Agent LangGraph        Reporting layer  |
|  `src/agent/router.py`     `src/agent/langgraph_sql_agent.py`          |
|  `src/agent/orchestrator.py`                         `src/agent/reporting_agent.py` |
|                         Domain and safety layer                         |
|                                                                       |
|  Scenario config       SQL validation       Memory/template store       |
|  `src/config/scenarios.py` `src/agent/sql_validator.py` `src/agent/memory_store.py` |
|                         Backend and data layer                          |
|                                                                       |
|  Backend protocol/factory      PostgreSQL adapter       Databricks adapter |
|  `src/backends/base.py`        `src/backends/demo/postgres_adapter.py`     |
|  `src/backends/factory.py`     `src/backends/databricks/databricks_adapter.py` |
|                                                                       |
|  Semantic YAML          Memory YAML/CSV logs       Presentation assets  |
|  `semantic_layer/`      `memory/`, `logs/`         `assets/templates/PPT_Vorlage_Wuerth.pptx` |
```
## Component Responsibilities
| Component | Responsibility | File |
|-----------|----------------|------|
| Streamlit application | Owns chat UI, scenario selection, model toggles, result rendering, feedback, memory review, template review, and golden test controls. Keep UI state in `st.session_state` and call orchestration functions for business work. | `streamlit_app.py` |
| Orchestrator | Runs router first, selects a tiered model, calls the SQL agent only when needed, builds reporting output, and writes router logs. | `src/agent/orchestrator.py` |
| Router | Classifies intent, SQL need, clarification need, safety blocks, complexity tier, output mode, language, constraints, and metadata-only template candidates. | `src/agent/router.py` |
| SQL agent | LangGraph workflow for schema loading, SQL generation, local validation, execution, repair, fallback switching, final answer creation, and query logging. | `src/agent/langgraph_sql_agent.py` |
| SQL validation | Enforces read-only SQL, single statements, allowed tables, broad-query `LIMIT 50`, and known-column checks from schema context. | `src/agent/sql_validator.py` |
| Reporting layer | Builds deterministic management summaries, KPI cards, table plans, chart plans, display notes, and audit metadata from already executed result data. | `src/agent/reporting_agent.py` |
| Visualization spec | Selects safe deterministic `bar`, `line`, or `none` chart specs from result shape and router context without calling an LLM or database. | `src/agent/visualization_spec.py` |
| Backend boundary | Exposes `load_schema_context`, `execute_read_only_sql`, and safe backend metadata through a single facade. New agent code should import this facade rather than adapter classes directly. | `src/agent/db.py` |
| Backend factory | Chooses PostgreSQL or Databricks from the active scenario and backend settings. | `src/backends/factory.py` |
| Backend protocol | Defines the adapter contract for SQL execution, schema loading, connection checks, backend name, and dialect. | `src/backends/base.py` |
| PostgreSQL adapter | Loads PostgreSQL schema plus semantic layer and executes read-only SQL after `EXPLAIN`. Uses `app.db` and `app.schema` for shared PostgreSQL helpers. | `src/backends/demo/postgres_adapter.py` |
| Databricks adapter | Loads allowed Databricks schema metadata and executes Databricks SQL with OAuth or PAT configuration. | `src/backends/databricks/databricks_adapter.py` |
| Scenario config | Defines supported scenarios, active scenario context, semantic-layer paths, memory directories, evaluation directories, SQL dialects, and allowed tables. | `src/config/scenarios.py` |
| Model adapter | Normalizes Gemini, Anthropic, and Ollama configuration behind `invoke_model` and `get_llm`. | `src/llm/model_adapter.py` |
| Memory store | Creates, edits, validates, approves, disables, and audits reusable solution template candidates per scenario. | `src/agent/memory_store.py` |
| Memory retrieval | Loads approved templates matching question tokens and the active scenario/dataset. | `src/agent/memory_retriever.py` |
| Router template retrieval | Metadata-only placeholder that returns no candidates and has no side effects. Do not treat it as semantic search. | `src/agent/router_template_retriever.py` |
| Golden test runner | Compares agent SQL output with reference SQL for active scenario golden questions and writes JSONL results. | `src/agent/golden_test_runner.py` |
| Wuerth CSV ingestion | Loads local Wuerth CSV exports into PostgreSQL `wuerth.invoices` and `wuerth.shipments`. | `scripts/ingest_wuerth_csv_to_postgres.py` |
| Wuerth setup validation | Checks CSV presence, scenario config, semantic layer, table data, and schema-context isolation. | `scripts/validate_wuerth_local_setup.py` |
| Presentation template asset | Provides the Wuerth PowerPoint master template for future generated PowerPoint output. No current code imports or writes PPTX files. | `assets/templates/PPT_Vorlage_Wuerth.pptx` |
## Pattern Overview
- Run user questions through `src/agent/orchestrator.py` before calling SQL generation.
- Keep generated SQL read-only and scenario-bounded through `src/agent/sql_validator.py` and `src/config/scenarios.py`.
- Keep database-specific details behind `src/backends/base.py`, `src/backends/factory.py`, and `src/agent/db.py`.
- Build summaries, charts, tables, and export-ready result metadata after SQL execution in `src/agent/reporting_agent.py`.
- Store reusable knowledge in scenario-specific YAML under `memory/`, with approval and audit workflow exposed in `streamlit_app.py`.
- Treat `assets/templates/PPT_Vorlage_Wuerth.pptx` as a static rendering asset. Add PowerPoint generation as a backend/reporting capability, not as SQL-agent logic.
## Layers
- Purpose: Accept user questions, show configuration, render results, collect feedback, run memory review, and launch golden tests.
- Location: `streamlit_app.py`, `evaluation/run_evaluation.py`
- Contains: Streamlit pages, result displays, export buttons for CSV/XLSX, and test execution controls.
- Depends on: `src/agent/orchestrator.py`, `src/agent/golden_test_runner.py`, `src/agent/memory_store.py`, `src/config/scenarios.py`, `src/llm/model_adapter.py`
- Used by: Local users through Streamlit and CLI commands.
- Purpose: Coordinate routing, model choice, SQL agent execution, reporting result creation, fallback runs, and router logging.
- Location: `src/agent/orchestrator.py`
- Contains: `OrchestratorState`, `build_orchestrator_graph`, `run_orchestrator`, tiered model selection, forced fallback path, and router log writing.
- Depends on: `src/agent/router.py`, `src/agent/langgraph_sql_agent.py`, `src/agent/reporting_agent.py`, `src/llm/model_adapter.py`
- Used by: `streamlit_app.py`, `src/agent/golden_test_runner.py`
- Purpose: Classify user intent before SQL work and stop unsafe or under-specified requests.
- Location: `src/agent/router.py`, `semantic_layer/router_excerpt.yaml`
- Contains: deterministic block regexes, router prompt construction, JSON parsing, fallback state, clarification gate, and LangGraph router graph.
- Depends on: `src.llm.model_adapter.invoke_model`, `src.agent.router_template_retriever.find_similar_templates_for_router`
- Used by: `src/agent/orchestrator.py`
- Purpose: Convert an approved data question into a validated and executed read-only SQL query with repair and fallback attempts.
- Location: `src/agent/langgraph_sql_agent.py`
- Contains: `SQLAgentConfig`, `SQLAgentState`, prompt construction, scenario SQL rules, approved template context, `build_sql_agent_graph`, and `run_sql_agent`.
- Depends on: `src/agent/db.py`, `src/agent/sql_validator.py`, `src/agent/memory_retriever.py`, `src/agent/logging_utils.py`, `src/llm/model_adapter.py`
- Used by: `src/agent/orchestrator.py`, `src/agent/golden_test_runner.py`, `evaluation/run_langgraph_smoke_tests.py`
- Purpose: Enforce read-only SQL and scenario-bounded table/column usage before execution.
- Location: `src/agent/sql_validator.py`, `src/agent/memory_validation.py`
- Contains: destructive keyword blocks, table extraction, CTE handling, allowed table mapping from schema context, broad-query limit validation, known-column validation, and template validation.
- Depends on: Schema text from `src/agent/db.py` and active scenario state from `src/config/scenarios.py`.
- Used by: `src/agent/langgraph_sql_agent.py`, `src/agent/golden_test_runner.py`, `src/agent/memory_validation.py`
- Purpose: Hide data-source details behind a stable SQL backend contract.
- Location: `src/agent/db.py`, `src/backends/base.py`, `src/backends/factory.py`, `src/backends/config.py`, `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`
- Contains: backend protocol, scenario-driven adapter selection, Databricks config validation, PostgreSQL schema introspection, Databricks information schema loading, and SQL execution.
- Depends on: `src/config/scenarios.py`, `app/db.py`, `app/schema.py`, Databricks connector packages.
- Used by: SQL agent, validation scripts, golden tests, Streamlit sidebar metadata.
- Purpose: Define the active dataset, backend, dialect, allowed tables, semantic context, memory location, and evaluation location.
- Location: `src/config/scenarios.py`, `semantic_layer/demo/tpch_semantic_layer.yaml`, `semantic_layer/wuerth_local/wuerth_semantic_layer.yaml`
- Contains: `ScenarioConfig`, context-local active scenario override, supported scenario constants, and semantic YAML loading.
- Depends on: YAML files under `semantic_layer/`.
- Used by: Backend adapters, Streamlit sidebar, SQL prompt rules, memory store, golden tests, validation scripts.
- Purpose: Let successful runs become human-reviewed reusable solution templates.
- Location: `src/agent/memory_store.py`, `src/agent/memory_retriever.py`, `src/agent/memory_validation.py`, `memory/demo/`, `memory/wuerth_local/`
- Contains: YAML initialization, candidate creation, editing, approval, rejection, template disable/reactivation, audit CSV writing, and approved template retrieval.
- Depends on: `src/config/scenarios.py`, `src/agent/logging_utils.py`, `src/agent/sql_validator.py`
- Used by: `streamlit_app.py`, `src/agent/langgraph_sql_agent.py`, `src/agent/router.py`
- Purpose: Convert query results into deterministic summaries, chart plans, KPI cards, and audit metadata.
- Location: `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, `streamlit_app.py`
- Contains: result-to-DataFrame conversion, metric/grouping detection, chart eligibility, German summary generation, table plan, chart rendering in Streamlit, and reporting audit output.
- Depends on: Pandas, Altair in `streamlit_app.py`, already executed `query_result`.
- Used by: `src/agent/orchestrator.py`, `streamlit_app.py`
- Purpose: Prepare demo TPC-H data and local Wuerth PostgreSQL data.
- Location: `database/`, `docker/postgres/init/`, `scripts/ingest_wuerth_csv_to_postgres.py`, `scripts/validate_wuerth_local_setup.py`
- Contains: DuckDB TPC-H generation/export helpers, PostgreSQL schema/load SQL, Docker init SQL, CSV ingestion, setup validation, and demo CSV exports.
- Depends on: DuckDB, Psycopg, PostgreSQL, CSV files under `database/exports/`.
- Used by: Local Docker workflow, manual setup, tests, and backend schema loading.
- Purpose: Provide a Wuerth-branded PowerPoint master for future export of agent result data.
- Location: `assets/templates/PPT_Vorlage_Wuerth.pptx`
- Contains: Static `.pptx` template only.
- Depends on: Not detected.
- Used by: Not detected. Future export code should consume reporting output from `src/agent/reporting_agent.py` and place PPTX rendering behind a new module such as `src/agent/presentation_export.py`, then expose only a download action in `streamlit_app.py`.
## Data Flow
### Primary Streamlit Request Path
### SQL Agent Graph Path
### Backend Schema and Execution Path
### Memory Candidate Flow
### Golden Test Flow
### Presentation Export Path
- Streamlit session state stores chats, selected scenario, page filters, golden-test state, and memory editor state in `streamlit_app.py`.
- Active data scenario is held in a `ContextVar` named `_active_scenario_id` in `src/config/scenarios.py:30`.
- The orchestrator caches a compiled router graph in module global `_compiled_router` in `src/agent/orchestrator.py:114`.
- Logs are append-only CSV files under `logs/` through `src/agent/logging_utils.py`.
- Memory/template state is YAML plus audit CSV under scenario-specific directories in `memory/`.
## Key Abstractions
- Purpose: One object defines data scenario, backend, SQL dialect, semantic layer, memory path, evaluation path, dataset id, and allowed tables.
- Examples: `src/config/scenarios.py`
- Pattern: Frozen dataclass plus central `SCENARIOS` registry.
- Purpose: Stable contract for database adapters used by the agent.
- Examples: `src/backends/base.py`, `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`
- Pattern: Python `Protocol` with factory dispatch in `src/backends/factory.py`.
- Purpose: Provider, primary model, fallback model, attempt count, and Ollama host for each run.
- Examples: `src/agent/langgraph_sql_agent.py`, `streamlit_app.py`
- Pattern: Frozen dataclass with `from_env` and `from_provider` constructors.
- Purpose: TypedDict state objects passed through LangGraph nodes.
- Examples: `src/agent/router.py`, `src/agent/langgraph_sql_agent.py`, `src/agent/orchestrator.py`
- Pattern: Explicit state keys with node functions returning partial updates.
- Purpose: Normalized SQL, validity flag, error message, and used tables.
- Examples: `src/agent/sql_validator.py`
- Pattern: Frozen dataclass returned by pure validation helpers.
- Purpose: Transport object for summary, interpretation, caveats, chart plan, table plan, KPI cards, notes, and audit metadata.
- Examples: `src/agent/reporting_agent.py`, `streamlit_app.py`
- Pattern: Deterministic dictionary built after SQL execution.
- Purpose: Human-approved reusable SQL guidance scoped by scenario and dataset.
- Examples: `memory/demo/solution_templates.yaml`, `src/agent/memory_store.py`, `src/agent/memory_retriever.py`
- Pattern: YAML records with status, active flag, source run, trigger phrases, required tables, metric definitions, join logic, SQL skeleton, and quality metadata.
## Entry Points
- Location: `streamlit_app.py`
- Triggers: `streamlit run streamlit_app.py`, Docker `CMD` in `Dockerfile`
- Responsibilities: UI, chat state, scenario selection, model selection, result rendering, downloads, feedback, memory review, templates, and golden tests.
- Location: `evaluation/run_evaluation.py`
- Triggers: `python evaluation/run_evaluation.py [question_ids]`
- Responsibilities: Run scenario golden questions and summarize pass/fail counts.
- Location: `evaluation/run_langgraph_smoke_tests.py`
- Triggers: `python evaluation/run_langgraph_smoke_tests.py`
- Responsibilities: Exercise SQL agent fallback, validation, placeholder API key handling, correction prompts, and logging behavior with fakes.
- Location: `scripts/ingest_wuerth_csv_to_postgres.py`
- Triggers: `python scripts/ingest_wuerth_csv_to_postgres.py`
- Responsibilities: Detect Wuerth CSVs, normalize columns, create `wuerth` schema tables, load rows, and create join indexes.
- Location: `scripts/validate_wuerth_local_setup.py`
- Triggers: `python scripts/validate_wuerth_local_setup.py [--skip-db]`
- Responsibilities: Validate local Wuerth CSV files, semantic layer, scenarios, and PostgreSQL table/schema context.
- Location: `database/create_tpch_database.py`, `database/export_tpch_to_csv.py`, `database/inspect_schema.py`
- Triggers: Direct Python scripts.
- Responsibilities: Generate, export, and inspect local demo TPC-H data.
## Architectural Constraints
- **Threading:** The app uses synchronous Streamlit request handling and synchronous LangGraph invocations. No worker queue, async service layer, or background job runner is detected.
- **Global state:** `src/agent/orchestrator.py` uses `_compiled_router`; `src/config/scenarios.py` uses `_active_scenario_id`; `streamlit_app.py` uses `st.session_state`; config modules call `load_dotenv()` at import time in `src/agent/orchestrator.py`, `src/agent/router.py`, `src/agent/langgraph_sql_agent.py`, and `src/llm/model_adapter.py`.
- **Backend boundary:** New agent code should call `src/agent/db.py`, not direct adapter constructors. Direct adapter use belongs in `src/backends/` and tests.
- **Scenario isolation:** All SQL generation, validation, memory, and evaluation must use the active scenario from `src/config/scenarios.py`. Do not hard-code Wuerth, TPC-H, or Databricks tables outside scenario-aware configuration, validation tests, or scenario-specific prompt rules.
- **SQL safety:** SQL generation must produce one read-only `SELECT` or `WITH ... SELECT`; destructive keywords, multiple statements, comments/prose, unknown tables, unknown qualified columns, and broad row-level queries without `LIMIT 50` are rejected in `src/agent/sql_validator.py`.
- **External secrets:** Runtime secrets live in environment variables. `.env` and `.env.*` files must not be read or committed; `.env.example` exists only as configuration documentation.
- **PowerPoint output:** The template exists at `assets/templates/PPT_Vorlage_Wuerth.pptx`, but no generation path exists. Add PPTX code as deterministic post-reporting output, not inside the router or SQL generator.
- **Circular imports:** No circular import chain is detected by inspection. There is a cross-package dependency where `src/backends/demo/postgres_adapter.py` imports `app.db` and `app.schema`.
- **Project skills:** No repo-local `.codex/skills/` or `.agents/skills/` directories are detected.
## Anti-Patterns
### Bypassing The Orchestrator For New UI Work
### Treating Router Template Retrieval As Active Retrieval
### Putting Export Logic Directly In Streamlit
## Error Handling
- Use deterministic blocked/clarification states in `src/agent/router.py`.
- Convert model/provider failures into SQL agent error state in `src/agent/langgraph_sql_agent.py`.
- Retry primary model attempts, then switch to fallback model in `src/agent/langgraph_sql_agent.py`.
- Raise `BackendConfigError` for unsupported or missing backend configuration in `src/backends/config.py`.
- Wrap Databricks connector errors in sanitized messages without credential values in `src/backends/databricks/databricks_adapter.py`.
- Let Streamlit catch backend metadata, memory, and golden question loading errors and render `st.error` in `streamlit_app.py`.
- Log query attempts, final runs, router decisions, and feedback to CSV through `src/agent/logging_utils.py`.
## Cross-Cutting Concerns
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
