# Codebase Structure

**Analysis Date:** 2026-06-21

## Directory Layout

```text
wuerth-logistics-agent/
├── app/                         # Legacy/compatibility PostgreSQL CLI helpers
├── assets/
│   └── templates/               # Static output templates, including Wuerth PowerPoint master
├── database/                    # Demo TPC-H data generation, CSV exports, and PostgreSQL SQL scripts
├── docker/
│   └── postgres/init/           # PostgreSQL initialization SQL and Docker init export placeholder
├── evaluation/                  # Unit tests, smoke tests, golden tests, reference SQL, and fixtures
├── logs/                        # Runtime CSV/log output, ignored except directory presence
├── memory/                      # Scenario-specific memory/template YAML and audit data
├── scripts/                     # Operational setup, ingestion, validation, and Databricks checks
├── semantic_layer/              # Router excerpt plus scenario semantic YAML files
├── src/
│   ├── agent/                   # Active LangGraph agent, router, reporting, validation, memory, logging
│   ├── backends/                # SQL backend protocol, factory, config, PostgreSQL and Databricks adapters
│   ├── config/                  # Scenario registry and active scenario state
│   └── llm/                     # Provider adapter for Gemini, Anthropic, and Ollama
├── .dockerignore                # Docker build exclusions
├── .env.example                 # Environment variable example, contents not mapped because `.env.*` is secret-patterned
├── .gitignore                   # Ignored runtime files, local data, logs, and secrets
├── Dockerfile                   # Python 3.11 Streamlit container entry point
├── docker-compose.yml           # Local compose stack, contents not inspected because compose files can contain inline secrets
├── main.py                      # Legacy CLI prototype
├── README.md                    # Local setup, scenarios, validation, and workflow notes
├── requirements.txt             # Python runtime dependencies
└── streamlit_app.py             # Primary Streamlit application
```

## Directory Purposes

**`src/agent/`:**
- Purpose: Active agent runtime and deterministic post-processing.
- Contains: LangGraph orchestration, router, SQL generation workflow, SQL validation, reporting, visualization spec, memory store/retrieval, golden runner, logging, ids, and Ollama compatibility helper.
- Key files: `src/agent/orchestrator.py`, `src/agent/router.py`, `src/agent/langgraph_sql_agent.py`, `src/agent/sql_validator.py`, `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, `src/agent/db.py`, `src/agent/memory_store.py`, `src/agent/golden_test_runner.py`

**`src/backends/`:**
- Purpose: Data-source boundary for SQL execution and schema context.
- Contains: Backend `Protocol`, factory, backend configuration, PostgreSQL adapter, Databricks adapter.
- Key files: `src/backends/base.py`, `src/backends/factory.py`, `src/backends/config.py`, `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`

**`src/config/`:**
- Purpose: Scenario registry and active scenario selection.
- Contains: `ScenarioConfig`, scenario constants, active scenario context variable, semantic-layer loader.
- Key files: `src/config/scenarios.py`

**`src/llm/`:**
- Purpose: Provider-agnostic LLM call wrapper.
- Contains: Environment-driven model lookup, API key checks, LangChain client construction, response text extraction, fallback invocation helper.
- Key files: `src/llm/model_adapter.py`

**`app/`:**
- Purpose: Legacy/compatibility package plus PostgreSQL helpers still reused by the active PostgreSQL adapter.
- Contains: Database config/connection, schema introspection, semantic-layer access, prompt builder, LLM client wrapper, query executor, SQL validator, result formatting, logging utility.
- Key files: `app/db.py`, `app/schema.py`, `app/config.py`, `app/sql_validator.py`, `app/prompt_builder.py`, `app/query_executor.py`, `app/semantic_layer.py`, `app/llm_client.py`, `app/answer_formatter.py`

**`semantic_layer/`:**
- Purpose: Business metadata for router prompts and SQL generation.
- Contains: `semantic_layer/router_excerpt.yaml`, demo TPC-H semantic layer, Wuerth semantic layer reused by Databricks and local Wuerth PostgreSQL scenarios.
- Key files: `semantic_layer/router_excerpt.yaml`, `semantic_layer/demo/tpch_semantic_layer.yaml`, `semantic_layer/databricks/wuerth_semantic_layer.yaml`

**`memory/`:**
- Purpose: Scenario-specific reusable solution templates, pending candidates, and error memory.
- Contains: `memory/demo/`, `memory/databricks/`, each with `solution_templates.yaml`, `memory_candidates.yaml`, and `error_memory.yaml`.
- Key files: `memory/demo/solution_templates.yaml`, `memory/demo/memory_candidates.yaml`, `memory/databricks/solution_templates.yaml`, `memory/databricks/memory_candidates.yaml`

**`evaluation/`:**
- Purpose: Test suite, golden-question fixtures, golden reference SQL, and CLI runners.
- Contains: `unittest` test modules, scenario golden question YAML, scenario reference SQL folders, smoke/evaluation scripts.
- Key files: `evaluation/test_orchestrator.py`, `evaluation/test_router.py`, `evaluation/test_reporting_agent.py`, `evaluation/test_visualization_spec.py`, `evaluation/test_wuerth_local_scenario.py`, `evaluation/test_backend_config_and_validation.py`, `evaluation/run_evaluation.py`, `evaluation/run_langgraph_smoke_tests.py`

**`evaluation/demo/`:**
- Purpose: Demo TPC-H golden fixtures.
- Contains: `evaluation/demo/golden_questions.yaml` and `evaluation/demo/solution_sql/*.sql`.
- Key files: `evaluation/demo/golden_questions.yaml`, `evaluation/demo/solution_sql/q01.sql`

**`evaluation/wuerth_local/`:**
- Purpose: Wuerth local scenario golden fixtures.
- Contains: `evaluation/wuerth_local/golden_questions.yaml` and reference SQL for W01 through W05.
- Key files: `evaluation/wuerth_local/golden_questions.yaml`, `evaluation/wuerth_local/solution_sql/w01_total_revenue_limitation.sql`, `evaluation/wuerth_local/solution_sql/w05_shipments_without_invoices.sql`

**`evaluation/databricks/`:**
- Purpose: Optional Databricks golden-question fixtures.
- Contains: `evaluation/databricks/golden_questions.yaml`.
- Key files: `evaluation/databricks/golden_questions.yaml`

**`database/`:**
- Purpose: Local demo data setup and PostgreSQL loading scripts.
- Contains: DuckDB TPC-H generation/export scripts, schema inspection, SQL scripts, committed TPC-H CSV exports under `database/exports/`.
- Key files: `database/create_tpch_database.py`, `database/export_tpch_to_csv.py`, `database/inspect_schema.py`, `database/postgres_create_tpch_schema.sql`, `database/postgres_load_tpch_csv.sql`, `database/exports/lineitem.csv`

**`docker/`:**
- Purpose: Database initialization assets for the local Docker workflow.
- Contains: PostgreSQL init SQL copied from database scripts and an `exports` placeholder directory.
- Key files: `docker/postgres/init/01_create_tpch_schema.sql`, `docker/postgres/init/02_load_tpch_data.sql`, `docker/postgres/init/exports/.gitkeep`

**`scripts/`:**
- Purpose: Manual and Docker-support operational scripts.
- Contains: Wuerth CSV ingestion, Wuerth setup validation, Databricks connection test.
- Key files: `scripts/ingest_wuerth_csv_to_postgres.py`, `scripts/validate_wuerth_local_setup.py`, `scripts/databricks/test_databricks_connection.py`

**`assets/templates/`:**
- Purpose: Static templates used by generated outputs.
- Contains: Wuerth PowerPoint master template.
- Key files: `assets/templates/PPT_Vorlage_Wuerth.pptx`

**`logs/`:**
- Purpose: Runtime output for query logs, router logs, feedback, retrieval errors, and migrated log backups.
- Contains: Ignored CSV/log files produced by `src/agent/logging_utils.py` and related helpers.
- Key files: `logs/query_log.csv`, `logs/router_log.csv`, `logs/feedback.csv` are runtime paths, not committed files.

**`.planning/codebase/`:**
- Purpose: GSD codebase maps consumed by planning and execution workflows.
- Contains: Architecture and structure documents written by this mapping task.
- Key files: `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/STRUCTURE.md`

## Key File Locations

**Entry Points:**
- `streamlit_app.py`: Primary Streamlit app with chat, scenario configuration, memory review, approved template view, golden test mode, result rendering, and CSV/XLSX downloads.
- `main.py`: Legacy interactive CLI for direct SQL generation and PostgreSQL execution through `app/`.
- `evaluation/run_evaluation.py`: CLI for running golden questions against the active scenario.
- `evaluation/run_langgraph_smoke_tests.py`: Script-level smoke test for SQL agent fallback, safety validation, correction, and logs.
- `scripts/ingest_wuerth_csv_to_postgres.py`: CLI for importing Wuerth CSV exports into local PostgreSQL.
- `scripts/validate_wuerth_local_setup.py`: CLI for validating Wuerth local CSV, semantic layer, scenarios, and database state.
- `scripts/databricks/test_databricks_connection.py`: CLI for optional Databricks adapter connectivity.

**Configuration:**
- `src/config/scenarios.py`: Active scenario registry and semantic layer path mapping.
- `src/backends/config.py`: Backend-specific settings and Databricks validation.
- `app/config.py`: PostgreSQL and Ollama environment defaults for shared PostgreSQL helpers.
- `src/agent/langgraph_sql_agent.py`: `SQLAgentConfig` and provider-specific default model selection.
- `src/llm/model_adapter.py`: LLM provider/model/API key configuration and invocation.
- `requirements.txt`: Python package dependencies.
- `Dockerfile`: Container runtime for Streamlit.
- `docker-compose.yml`: Local stack configuration, contents not mapped for secret safety.
- `.env.example`: Example environment file, contents not mapped for secret safety.

**Core Logic:**
- `src/agent/orchestrator.py`: Primary request coordinator and LangGraph wrapper around routing, SQL agent, and reporting.
- `src/agent/router.py`: Intent classification, safety blocks, clarification gate, and router graph.
- `src/agent/langgraph_sql_agent.py`: SQL prompt, SQL generation, validation, execution, repair, fallback, and final answer graph.
- `src/agent/sql_validator.py`: Active SQL safety and allowlist validator.
- `src/agent/reporting_agent.py`: Deterministic result summary, table plan, chart plan, KPI cards, and audit output.
- `src/agent/visualization_spec.py`: Deterministic chart eligibility and spec builder.
- `src/agent/db.py`: Facade for active backend schema loading and SQL execution.
- `src/backends/factory.py`: Active backend selection.
- `src/backends/demo/postgres_adapter.py`: PostgreSQL schema context and query execution adapter.
- `src/backends/databricks/databricks_adapter.py`: Optional Databricks schema context and query execution adapter.
- `src/agent/memory_store.py`: Candidate/template lifecycle and audit writes.
- `src/agent/memory_retriever.py`: Approved template retrieval for prompts.
- `src/agent/golden_test_runner.py`: Golden question loading, reference execution, agent execution, comparison, and JSONL result writing.

**Data And Semantics:**
- `semantic_layer/router_excerpt.yaml`: Router prompt domain excerpt.
- `semantic_layer/demo/tpch_semantic_layer.yaml`: Demo TPC-H business metadata.
- `semantic_layer/databricks/wuerth_semantic_layer.yaml`: Wuerth semantic metadata for Databricks and local Wuerth PostgreSQL.
- `database/exports/*.csv`: Committed demo TPC-H CSV exports.
- `database/postgres_create_tpch_schema.sql`: TPC-H PostgreSQL schema.
- `database/postgres_load_tpch_csv.sql`: TPC-H PostgreSQL data loading script.
- `docker/postgres/init/01_create_tpch_schema.sql`: Docker PostgreSQL schema init.
- `docker/postgres/init/02_load_tpch_data.sql`: Docker PostgreSQL data init.

**Templates And Output Assets:**
- `assets/templates/PPT_Vorlage_Wuerth.pptx`: Wuerth PowerPoint master template for future PPTX generation.
- `streamlit_app.py`: Current output surface for tables, Altair charts, CSV downloads, and XLSX downloads.
- `src/agent/reporting_agent.py`: Best source object for future PPTX export content because it already emits summary, caveats, table plan, chart plan, KPI cards, and audit metadata.

**Testing:**
- `evaluation/test_orchestrator.py`: Orchestrator branching, model selection, logging, fallback, reporting integration.
- `evaluation/test_router.py`: Router classification, deterministic blocks, template retrieval placeholder.
- `evaluation/test_reporting_agent.py`: Reporting summary, audit, table plan, chart integration.
- `evaluation/test_visualization_spec.py`: Chart spec selection and safety behavior.
- `evaluation/test_wuerth_local_scenario.py`: Wuerth scenario configuration and semantic expectations.
- `evaluation/test_backend_config_and_validation.py`: Backend config and SQL validator coverage.
- `evaluation/test_golden_result_comparison.py`: Golden result comparison semantics.

## Naming Conventions

**Files:**
- Use snake_case for Python modules: `src/agent/langgraph_sql_agent.py`, `src/agent/memory_store.py`, `scripts/validate_wuerth_local_setup.py`.
- Use `test_*.py` for `unittest` modules under `evaluation/`: `evaluation/test_orchestrator.py`.
- Use lowercase descriptive YAML names for semantic/memory files: `semantic_layer/router_excerpt.yaml`, `memory/demo/solution_templates.yaml`.
- Use question ids in reference SQL filenames for golden tests: `evaluation/demo/solution_sql/q01.sql`, `evaluation/wuerth_local/solution_sql/w05_shipments_without_invoices.sql`.
- Keep static branded assets under descriptive original filenames: `assets/templates/PPT_Vorlage_Wuerth.pptx`.

**Directories:**
- Use feature/domain directories under `src/`: `src/agent/`, `src/backends/`, `src/config/`, `src/llm/`.
- Use scenario directories where data or fixtures vary by scenario: `memory/demo/`, `memory/databricks/`, `evaluation/wuerth_local/`, `semantic_layer/demo/`.
- Use adapter directories under `src/backends/` for backend-specific implementations: `src/backends/demo/`, `src/backends/databricks/`.
- Use `solution_sql/` under each golden fixture directory for reference SQL files.

**Classes And Types:**
- Use PascalCase for dataclasses, protocols, TypedDicts, and custom errors: `SQLAgentConfig`, `SQLBackend`, `ScenarioConfig`, `BackendConfigError`, `MemoryStoreError`.
- Use suffix `State` for LangGraph state TypedDicts: `RouterState`, `SQLAgentState`, `OrchestratorState`.
- Use suffix `Config` for runtime configuration value objects: `ScenarioConfig`, `DatabricksBackendConfig`, `BackendSettings`, `SQLAgentConfig`.

**Functions:**
- Use snake_case with action-oriented names: `run_orchestrator`, `build_router_graph`, `validate_generated_sql`, `load_schema_context`, `execute_read_only_sql`.
- Use `build_*` for pure construction helpers: `build_sql_prompt`, `build_reporting_result`, `build_visualization_spec`.
- Use `load_*` for file/config readers: `load_semantic_layer_text`, `load_backend_settings`, `load_golden_questions`.
- Use `render_*` for Streamlit UI sections: `render_sidebar`, `render_record`, `render_memory_review_view`.

## Where to Add New Code

**New User-Facing Question Flow:**
- Primary code: `src/agent/orchestrator.py`
- SQL-agent behavior: `src/agent/langgraph_sql_agent.py`
- Router behavior: `src/agent/router.py` and `semantic_layer/router_excerpt.yaml`
- UI controls or display only: `streamlit_app.py`
- Tests: `evaluation/test_orchestrator.py`, `evaluation/test_router.py`, and scenario golden files under `evaluation/*/`

**New SQL Safety Rule:**
- Primary code: `src/agent/sql_validator.py`
- Template validation if relevant: `src/agent/memory_validation.py`
- Legacy CLI rule only if preserving `main.py` behavior: `app/sql_validator.py`
- Tests: `evaluation/test_backend_config_and_validation.py`

**New Backend:**
- Protocol contract: `src/backends/base.py`
- Implementation: `src/backends/<backend_name>/<backend_name>_adapter.py`
- Selection: `src/backends/factory.py`
- Config: `src/backends/config.py`
- Scenario mapping: `src/config/scenarios.py`
- Tests: `evaluation/test_backend_config_and_validation.py`

**New Data Scenario:**
- Scenario registry: `src/config/scenarios.py`
- Semantic layer: `semantic_layer/<scenario>/<scenario>_semantic_layer.yaml`
- Memory directory: `memory/<scenario>/`
- Golden fixtures: `evaluation/<scenario>/golden_questions.yaml` and `evaluation/<scenario>/solution_sql/`
- Sidebar support: `streamlit_app.py` only when labels or controls need UI changes.

**New Reporting Feature:**
- Primary code: `src/agent/reporting_agent.py`
- Chart-specific logic: `src/agent/visualization_spec.py`
- UI rendering: `streamlit_app.py`
- Tests: `evaluation/test_reporting_agent.py`, `evaluation/test_visualization_spec.py`

**New PowerPoint Export:**
- Primary code: create `src/agent/presentation_export.py`
- Template asset: read `assets/templates/PPT_Vorlage_Wuerth.pptx`
- Input data: use `reporting_result`, `query_result`, `final_sql`, and `source_tables` from orchestrator records.
- UI trigger/download: `streamlit_app.py`
- Tests: create `evaluation/test_presentation_export.py`
- Do not generate PPTX inside `src/agent/router.py`, `src/agent/langgraph_sql_agent.py`, or `src/backends/*`.

**New Memory/Template Capability:**
- Primary code: `src/agent/memory_store.py`
- Retrieval logic: `src/agent/memory_retriever.py`
- Validation: `src/agent/memory_validation.py`
- UI review controls: `streamlit_app.py`
- Tests: add or extend `evaluation/test_orchestrator.py` and targeted memory tests under `evaluation/`.

**New Golden Test:**
- Demo question: `evaluation/demo/golden_questions.yaml` and `evaluation/demo/solution_sql/qNN.sql`
- Wuerth local question: `evaluation/wuerth_local/golden_questions.yaml` and `evaluation/wuerth_local/solution_sql/wNN_*.sql`
- Runner: no new runner needed, use `evaluation/run_evaluation.py`

**New Operational Script:**
- Implementation: `scripts/<task_name>.py`
- Databricks-only scripts: `scripts/databricks/<task_name>.py`
- Import project code by inserting repo root into `sys.path`, matching `scripts/validate_wuerth_local_setup.py`.

**Utilities:**
- Agent-local helpers: `src/agent/`
- Backend helpers: `src/backends/`
- Shared scenario helpers: `src/config/scenarios.py`
- Avoid placing new active utilities in `app/` unless they are specifically for the legacy CLI or existing PostgreSQL helper reuse.

## Special Directories

**`assets/templates/`:**
- Purpose: Holds static templates for generated outputs.
- Generated: No
- Committed: Yes
- Notes: `assets/templates/PPT_Vorlage_Wuerth.pptx` is the canonical Wuerth PowerPoint master template.

**`database/exports/`:**
- Purpose: Committed demo TPC-H CSV exports used by PostgreSQL loading scripts.
- Generated: Yes, by `database/export_tpch_to_csv.py`
- Committed: Yes for demo TPC-H CSV files.
- Notes: Wuerth CSV export directories `database/exports/wuerth/` and `database/exports/Wuerth/` are ignored by `.gitignore`.

**`docker/postgres/init/`:**
- Purpose: PostgreSQL initialization files for Docker startup.
- Generated: No
- Committed: Yes
- Notes: Contains schema/data init SQL and an `exports/.gitkeep` placeholder.

**`logs/`:**
- Purpose: Runtime query, router, feedback, and error logs.
- Generated: Yes
- Committed: Directory only if present; runtime `*.csv`, `*.log`, and backups are ignored by `.gitignore`.
- Notes: Writers live in `src/agent/logging_utils.py`.

**`memory/`:**
- Purpose: Scenario-specific persistent solution memory.
- Generated: Mixed. Base demo/databricks YAML files are present; runtime audit files and Wuerth local memory are generated.
- Committed: `memory/demo/` and `memory/databricks/` YAML files are present; `memory/wuerth_local/`, audit CSVs, and backups are ignored by `.gitignore`.
- Notes: Memory initialization and writes are centralized in `src/agent/memory_store.py`.

**`evaluation/*/solution_sql/`:**
- Purpose: Reference SQL for golden tests.
- Generated: No
- Committed: Yes
- Notes: Golden runners compare agent output against these SQL files through `src/agent/golden_test_runner.py`.

**`.planning/codebase/`:**
- Purpose: Generated codebase maps for GSD planning and execution.
- Generated: Yes
- Committed: Managed by orchestrator workflow.
- Notes: This task writes only `.planning/codebase/ARCHITECTURE.md` and `.planning/codebase/STRUCTURE.md`.

**`__pycache__/`, `.pytest_cache/`, `.venv/`:**
- Purpose: Local Python caches and virtual environment.
- Generated: Yes
- Committed: No, ignored by `.gitignore`.

---

*Structure analysis: 2026-06-21*
