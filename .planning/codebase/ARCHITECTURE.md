<!-- refreshed: 2026-06-21 -->
# Architecture

**Analysis Date:** 2026-06-21

## System Overview

```text
+-----------------------------------------------------------------------+
|                       User-facing application                          |
|                                                                       |
|  Streamlit UI                              Golden test CLI             |
|  `streamlit_app.py`                        `evaluation/run_evaluation.py` |
+------------+--------------------+---------------------+----------------+
             |                    |                     |
             v                    v                     v
+-----------------------------------------------------------------------+
|                         Orchestration layer                            |
|                                                                       |
|  Router LangGraph          SQL Agent LangGraph        Reporting layer  |
|  `src/agent/router.py`     `src/agent/langgraph_sql_agent.py`          |
|  `src/agent/orchestrator.py`                         `src/agent/reporting_agent.py` |
+------------+--------------------+---------------------+----------------+
             |                    |                     |
             v                    v                     v
+-----------------------------------------------------------------------+
|                         Domain and safety layer                         |
|                                                                       |
|  Scenario config       SQL validation       Memory/template store       |
|  `src/config/scenarios.py` `src/agent/sql_validator.py` `src/agent/memory_store.py` |
+------------+--------------------+---------------------+----------------+
             |                    |                     |
             v                    v                     v
+-----------------------------------------------------------------------+
|                         Backend and data layer                          |
|                                                                       |
|  Backend protocol/factory      PostgreSQL adapter       Databricks adapter |
|  `src/backends/base.py`        `src/backends/demo/postgres_adapter.py`     |
|  `src/backends/factory.py`     `src/backends/databricks/databricks_adapter.py` |
|                                                                       |
|  Semantic YAML          Memory YAML/CSV logs       Presentation assets  |
|  `semantic_layer/`      `memory/`, `logs/`         `assets/templates/PPT_Vorlage_Wuerth.pptx` |
+-----------------------------------------------------------------------+
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

**Overall:** Layered LangGraph agent with deterministic safety, scenario-aware backend adapters, and a Streamlit operator UI.

**Key Characteristics:**
- Run user questions through `src/agent/orchestrator.py` before calling SQL generation.
- Keep generated SQL read-only and scenario-bounded through `src/agent/sql_validator.py` and `src/config/scenarios.py`.
- Keep database-specific details behind `src/backends/base.py`, `src/backends/factory.py`, and `src/agent/db.py`.
- Build summaries, charts, tables, and export-ready result metadata after SQL execution in `src/agent/reporting_agent.py`.
- Store reusable knowledge in scenario-specific YAML under `memory/`, with approval and audit workflow exposed in `streamlit_app.py`.
- Treat `assets/templates/PPT_Vorlage_Wuerth.pptx` as a static rendering asset. Add PowerPoint generation as a backend/reporting capability, not as SQL-agent logic.

## Layers

**UI and Entrypoints:**
- Purpose: Accept user questions, show configuration, render results, collect feedback, run memory review, and launch golden tests.
- Location: `streamlit_app.py`, `evaluation/run_evaluation.py`
- Contains: Streamlit pages, result displays, export buttons for CSV/XLSX, and test execution controls.
- Depends on: `src/agent/orchestrator.py`, `src/agent/golden_test_runner.py`, `src/agent/memory_store.py`, `src/config/scenarios.py`, `src/llm/model_adapter.py`
- Used by: Local users through Streamlit and CLI commands.

**Orchestration:**
- Purpose: Coordinate routing, model choice, SQL agent execution, reporting result creation, fallback runs, and router logging.
- Location: `src/agent/orchestrator.py`
- Contains: `OrchestratorState`, `build_orchestrator_graph`, `run_orchestrator`, tiered model selection, forced fallback path, and router log writing.
- Depends on: `src/agent/router.py`, `src/agent/langgraph_sql_agent.py`, `src/agent/reporting_agent.py`, `src/llm/model_adapter.py`
- Used by: `streamlit_app.py`, `src/agent/golden_test_runner.py`

**Router and Intent Classification:**
- Purpose: Classify user intent before SQL work and stop unsafe or under-specified requests.
- Location: `src/agent/router.py`, `semantic_layer/router_excerpt.yaml`
- Contains: deterministic block regexes, router prompt construction, JSON parsing, fallback state, clarification gate, and LangGraph router graph.
- Depends on: `src.llm.model_adapter.invoke_model`, `src.agent.router_template_retriever.find_similar_templates_for_router`
- Used by: `src/agent/orchestrator.py`

**SQL Agent Workflow:**
- Purpose: Convert an approved data question into a validated and executed read-only SQL query with repair and fallback attempts.
- Location: `src/agent/langgraph_sql_agent.py`
- Contains: `SQLAgentConfig`, `SQLAgentState`, prompt construction, scenario SQL rules, approved template context, `build_sql_agent_graph`, and `run_sql_agent`.
- Depends on: `src/agent/db.py`, `src/agent/sql_validator.py`, `src/agent/memory_retriever.py`, `src/agent/logging_utils.py`, `src/llm/model_adapter.py`
- Used by: `src/agent/orchestrator.py`, `src/agent/golden_test_runner.py`, `evaluation/run_langgraph_smoke_tests.py`

**Validation and Safety:**
- Purpose: Enforce read-only SQL and scenario-bounded table/column usage before execution.
- Location: `src/agent/sql_validator.py`, `src/agent/memory_validation.py`
- Contains: destructive keyword blocks, table extraction, CTE handling, allowed table mapping from schema context, broad-query limit validation, known-column validation, and template validation.
- Depends on: Schema text from `src/agent/db.py` and active scenario state from `src/config/scenarios.py`.
- Used by: `src/agent/langgraph_sql_agent.py`, `src/agent/golden_test_runner.py`, `src/agent/memory_validation.py`

**Backend Abstraction:**
- Purpose: Hide data-source details behind a stable SQL backend contract.
- Location: `src/agent/db.py`, `src/backends/base.py`, `src/backends/factory.py`, `src/backends/config.py`, `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`
- Contains: backend protocol, scenario-driven adapter selection, Databricks config validation, PostgreSQL schema introspection, Databricks information schema loading, and SQL execution.
- Depends on: `src/config/scenarios.py`, `app/db.py`, `app/schema.py`, Databricks connector packages.
- Used by: SQL agent, validation scripts, golden tests, Streamlit sidebar metadata.

**Scenario and Semantic Layer:**
- Purpose: Define the active dataset, backend, dialect, allowed tables, semantic context, memory location, and evaluation location.
- Location: `src/config/scenarios.py`, `semantic_layer/demo/tpch_semantic_layer.yaml`, `semantic_layer/wuerth_local/wuerth_semantic_layer.yaml`
- Contains: `ScenarioConfig`, context-local active scenario override, supported scenario constants, and semantic YAML loading.
- Depends on: YAML files under `semantic_layer/`.
- Used by: Backend adapters, Streamlit sidebar, SQL prompt rules, memory store, golden tests, validation scripts.

**Memory and Template Review:**
- Purpose: Let successful runs become human-reviewed reusable solution templates.
- Location: `src/agent/memory_store.py`, `src/agent/memory_retriever.py`, `src/agent/memory_validation.py`, `memory/demo/`, `memory/wuerth_local/`
- Contains: YAML initialization, candidate creation, editing, approval, rejection, template disable/reactivation, audit CSV writing, and approved template retrieval.
- Depends on: `src/config/scenarios.py`, `src/agent/logging_utils.py`, `src/agent/sql_validator.py`
- Used by: `streamlit_app.py`, `src/agent/langgraph_sql_agent.py`, `src/agent/router.py`

**Reporting and Visualization:**
- Purpose: Convert query results into deterministic summaries, chart plans, KPI cards, and audit metadata.
- Location: `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, `streamlit_app.py`
- Contains: result-to-DataFrame conversion, metric/grouping detection, chart eligibility, German summary generation, table plan, chart rendering in Streamlit, and reporting audit output.
- Depends on: Pandas, Altair in `streamlit_app.py`, already executed `query_result`.
- Used by: `src/agent/orchestrator.py`, `streamlit_app.py`

**Data Ingestion and Fixtures:**
- Purpose: Prepare demo TPC-H data and local Wuerth PostgreSQL data.
- Location: `database/`, `docker/postgres/init/`, `scripts/ingest_wuerth_csv_to_postgres.py`, `scripts/validate_wuerth_local_setup.py`
- Contains: DuckDB TPC-H generation/export helpers, PostgreSQL schema/load SQL, Docker init SQL, CSV ingestion, setup validation, and demo CSV exports.
- Depends on: DuckDB, Psycopg, PostgreSQL, CSV files under `database/exports/`.
- Used by: Local Docker workflow, manual setup, tests, and backend schema loading.

**Presentation Output Asset:**
- Purpose: Provide a Wuerth-branded PowerPoint master for future export of agent result data.
- Location: `assets/templates/PPT_Vorlage_Wuerth.pptx`
- Contains: Static `.pptx` template only.
- Depends on: Not detected.
- Used by: Not detected. Future export code should consume reporting output from `src/agent/reporting_agent.py` and place PPTX rendering behind a new module such as `src/agent/presentation_export.py`, then expose only a download action in `streamlit_app.py`.

## Data Flow

### Primary Streamlit Request Path

1. User submits a chat prompt through `st.chat_input` in `streamlit_app.py:1480`.
2. Streamlit builds optional prior chat context with `_build_chat_context` in `streamlit_app.py:111`.
3. Streamlit calls `run_orchestrator(question, config=config, chat_context=chat_context, step_callback=_on_step)` in `streamlit_app.py:1513`.
4. `run_orchestrator` creates a run id and initial state in `src/agent/orchestrator.py:702`.
5. `build_orchestrator_graph` runs `run_router` first in `src/agent/orchestrator.py:474`.
6. `run_router_node` invokes the compiled router graph in `src/agent/orchestrator.py:267`.
7. `build_router_graph` classifies intent and applies clarification/safety gates in `src/agent/router.py:339`.
8. `select_model` maps router complexity tier to provider-specific primary and fallback model names in `src/agent/orchestrator.py:309`.
9. `_run_sql_agent_node_impl` calls `run_sql_agent` in `src/agent/orchestrator.py:346`.
10. `run_sql_agent` compiles and invokes the SQL LangGraph workflow in `src/agent/langgraph_sql_agent.py:562`.
11. The SQL graph loads schema context through `src/agent/db.py:7`, validates SQL through `src/agent/sql_validator.py:295`, and executes SQL through `src/agent/db.py:11`.
12. The orchestrator builds a deterministic reporting result with `build_reporting_result` in `src/agent/reporting_agent.py:22`.
13. Streamlit renders answer, table, chart, SQL, source tables, feedback, and memory candidate controls in `streamlit_app.py:1357`.

### SQL Agent Graph Path

1. `build_sql_agent_graph` defines nodes in `src/agent/langgraph_sql_agent.py:289`.
2. `load_schema` reads backend schema plus semantic context in `src/agent/langgraph_sql_agent.py:302`.
3. `generate_sql` builds a scenario-aware SQL prompt and calls the selected LLM in `src/agent/langgraph_sql_agent.py:324`.
4. `validate_sql` normalizes and validates generated SQL in `src/agent/langgraph_sql_agent.py:374`.
5. `execute_sql` executes only validated SQL and logs the attempt in `src/agent/langgraph_sql_agent.py:417`.
6. `repair_sql` loops back to generation when validation or execution fails and primary attempts remain in `src/agent/langgraph_sql_agent.py:455`.
7. `switch_model` swaps to fallback model when primary attempts are exhausted in `src/agent/langgraph_sql_agent.py:465`.
8. `generate_final_answer` creates the user-facing final answer from execution status and row count in `src/agent/langgraph_sql_agent.py:478`.
9. `run_sql_agent` writes final query log metadata when logging is enabled in `src/agent/langgraph_sql_agent.py:664`.

### Backend Schema and Execution Path

1. Agent code calls `load_schema_context` or `execute_read_only_sql` in `src/agent/db.py`.
2. The facade calls `get_backend()` in `src/backends/factory.py:15`.
3. `load_backend_settings()` reads the active scenario backend from `src/backends/config.py:163`.
4. PostgreSQL scenarios use `PostgresAdapter` from `src/backends/demo/postgres_adapter.py:10`.
5. Databricks scenarios use `DatabricksAdapter` from `src/backends/databricks/databricks_adapter.py:12`.
6. PostgreSQL schema context combines live `information_schema` columns from `app/schema.py:18` with semantic YAML from `src/config/scenarios.py:154`.
7. PostgreSQL execution starts a read-only transaction, runs `EXPLAIN`, then executes the query in `src/backends/demo/postgres_adapter.py:24`.
8. Databricks schema and execution use configured allowed tables and connector-safe errors in `src/backends/databricks/databricks_adapter.py:75` and `src/backends/databricks/databricks_adapter.py:130`.

### Memory Candidate Flow

1. Streamlit shows candidate creation for successful records in `streamlit_app.py:575`.
2. `create_candidate_from_run` stores a pending solution-template candidate in `src/agent/memory_store.py:307`.
3. Streamlit memory review loads and filters candidates in `streamlit_app.py:724`.
4. Edited YAML is validated through `validate_proposed_template` in `src/agent/memory_validation.py:68`.
5. Approval writes an approved template and updates the candidate atomically in `src/agent/memory_store.py:430`.
6. Future SQL prompts include approved templates via `format_approved_template_context` in `src/agent/langgraph_sql_agent.py:119`.

### Golden Test Flow

1. Streamlit Golden Test mode calls `run_golden_tests` in `streamlit_app.py:1039`, or the CLI calls it through `evaluation/run_evaluation.py:30`.
2. `run_golden_tests` loads active scenario questions from `src/agent/golden_test_runner.py:642`.
3. Each question reads reference SQL under `evaluation/*/solution_sql/` via `read_solution_sql` in `src/agent/golden_test_runner.py:89`.
4. Reference SQL and agent SQL are validated with `validate_generated_sql` in `src/agent/sql_validator.py:295`.
5. Result comparison uses `compare_query_results` in `src/agent/golden_test_runner.py:342`.
6. Results append to active scenario `golden_results.jsonl` through `append_golden_result` in `src/agent/golden_test_runner.py:620`.

### Presentation Export Path

1. No active code path writes PowerPoint output.
2. Use `assets/templates/PPT_Vorlage_Wuerth.pptx` as the template input.
3. Build export data from `reporting_result`, `query_result`, `final_sql`, and `source_tables` returned by `src/agent/orchestrator.py`.
4. Add deterministic PPTX rendering in a backend/reporting module such as `src/agent/presentation_export.py`.
5. Add only the UI trigger and download response to `streamlit_app.py`.
6. Add tests under `evaluation/test_presentation_export.py`.

**State Management:**
- Streamlit session state stores chats, selected scenario, page filters, golden-test state, and memory editor state in `streamlit_app.py`.
- Active data scenario is held in a `ContextVar` named `_active_scenario_id` in `src/config/scenarios.py:30`.
- The orchestrator caches a compiled router graph in module global `_compiled_router` in `src/agent/orchestrator.py:114`.
- Logs are append-only CSV files under `logs/` through `src/agent/logging_utils.py`.
- Memory/template state is YAML plus audit CSV under scenario-specific directories in `memory/`.

## Key Abstractions

**`ScenarioConfig`:**
- Purpose: One object defines data scenario, backend, SQL dialect, semantic layer, memory path, evaluation path, dataset id, and allowed tables.
- Examples: `src/config/scenarios.py`
- Pattern: Frozen dataclass plus central `SCENARIOS` registry.

**`SQLBackend`:**
- Purpose: Stable contract for database adapters used by the agent.
- Examples: `src/backends/base.py`, `src/backends/demo/postgres_adapter.py`, `src/backends/databricks/databricks_adapter.py`
- Pattern: Python `Protocol` with factory dispatch in `src/backends/factory.py`.

**`SQLAgentConfig`:**
- Purpose: Provider, primary model, fallback model, attempt count, and Ollama host for each run.
- Examples: `src/agent/langgraph_sql_agent.py`, `streamlit_app.py`
- Pattern: Frozen dataclass with `from_env` and `from_provider` constructors.

**`RouterState`, `SQLAgentState`, `OrchestratorState`:**
- Purpose: TypedDict state objects passed through LangGraph nodes.
- Examples: `src/agent/router.py`, `src/agent/langgraph_sql_agent.py`, `src/agent/orchestrator.py`
- Pattern: Explicit state keys with node functions returning partial updates.

**`SQLValidationResult`:**
- Purpose: Normalized SQL, validity flag, error message, and used tables.
- Examples: `src/agent/sql_validator.py`
- Pattern: Frozen dataclass returned by pure validation helpers.

**`reporting_result`:**
- Purpose: Transport object for summary, interpretation, caveats, chart plan, table plan, KPI cards, notes, and audit metadata.
- Examples: `src/agent/reporting_agent.py`, `streamlit_app.py`
- Pattern: Deterministic dictionary built after SQL execution.

**Memory template records:**
- Purpose: Human-approved reusable SQL guidance scoped by scenario and dataset.
- Examples: `memory/demo/solution_templates.yaml`, `src/agent/memory_store.py`, `src/agent/memory_retriever.py`
- Pattern: YAML records with status, active flag, source run, trigger phrases, required tables, metric definitions, join logic, SQL skeleton, and quality metadata.

## Entry Points

**Streamlit application:**
- Location: `streamlit_app.py`
- Triggers: `streamlit run streamlit_app.py`, Docker `CMD` in `Dockerfile`
- Responsibilities: UI, chat state, scenario selection, model selection, result rendering, downloads, feedback, memory review, templates, and golden tests.

**Golden test CLI:**
- Location: `evaluation/run_evaluation.py`
- Triggers: `python evaluation/run_evaluation.py [question_ids]`
- Responsibilities: Run scenario golden questions and summarize pass/fail counts.

**LangGraph smoke test:**
- Location: `evaluation/run_langgraph_smoke_tests.py`
- Triggers: `python evaluation/run_langgraph_smoke_tests.py`
- Responsibilities: Exercise SQL agent fallback, validation, placeholder API key handling, correction prompts, and logging behavior with fakes.

**Wuerth CSV ingestion:**
- Location: `scripts/ingest_wuerth_csv_to_postgres.py`
- Triggers: `python scripts/ingest_wuerth_csv_to_postgres.py`
- Responsibilities: Detect Wuerth CSVs, normalize columns, create `wuerth` schema tables, load rows, and create join indexes.

**Wuerth setup validation:**
- Location: `scripts/validate_wuerth_local_setup.py`
- Triggers: `python scripts/validate_wuerth_local_setup.py [--skip-db]`
- Responsibilities: Validate local Wuerth CSV files, semantic layer, scenarios, and PostgreSQL table/schema context.

**TPC-H database helpers:**
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

**What happens:** Resolved in cleanup. The older direct `app/` SQL path was removed, so user-facing question flows should remain on the orchestrator path.

**Why it's wrong:** New UI or product flows that use this path skip router classification, scenario-specific SQL rules, LangGraph repair/fallback, reporting output, memory handling, and router logs.

**Do this instead:** Use `run_orchestrator` from `src/agent/orchestrator.py` for user-facing question flows.

### Treating Router Template Retrieval As Active Retrieval

**What happens:** `src/agent/router_template_retriever.py` is a placeholder that always returns `[]` and documents that it must not mutate memory, call an LLM, call a database, generate SQL, approve templates, or bypass validation.

**Why it's wrong:** Building orchestration decisions on router candidates assumes a retrieval signal that does not exist.

**Do this instead:** Use approved template guidance in `src/agent/memory_retriever.py` and `src/agent/langgraph_sql_agent.py`. Implement real router retrieval behind `src/agent/router_template_retriever.py` only after preserving its metadata-only contract.

### Putting Export Logic Directly In Streamlit

**What happens:** `streamlit_app.py` already owns CSV and XLSX download buttons in `render_record`, and no PowerPoint generation module exists.

**Why it's wrong:** Adding PPTX construction directly to `streamlit_app.py` would couple rendering, template parsing, file generation, and UI state in the largest file in the repo.

**Do this instead:** Put PPTX generation in a new deterministic module such as `src/agent/presentation_export.py`, read `assets/templates/PPT_Vorlage_Wuerth.pptx` there, test it under `evaluation/test_presentation_export.py`, and keep `streamlit_app.py` limited to triggering and downloading the generated file.

## Error Handling

**Strategy:** Fail closed around SQL safety and backend configuration, return user-facing status metadata for agent failures, and avoid crashing UI flows where possible.

**Patterns:**
- Use deterministic blocked/clarification states in `src/agent/router.py`.
- Convert model/provider failures into SQL agent error state in `src/agent/langgraph_sql_agent.py`.
- Retry primary model attempts, then switch to fallback model in `src/agent/langgraph_sql_agent.py`.
- Raise `BackendConfigError` for unsupported or missing backend configuration in `src/backends/config.py`.
- Wrap Databricks connector errors in sanitized messages without credential values in `src/backends/databricks/databricks_adapter.py`.
- Let Streamlit catch backend metadata, memory, and golden question loading errors and render `st.error` in `streamlit_app.py`.
- Log query attempts, final runs, router decisions, and feedback to CSV through `src/agent/logging_utils.py`.

## Cross-Cutting Concerns

**Logging:** Use CSV append helpers in `src/agent/logging_utils.py`. Query attempts and final runs go to `logs/query_log.csv`; feedback goes to `logs/feedback.csv`; router decisions go to `logs/router_log.csv`; memory audits go to scenario-specific `memory/*/memory_audit_log.csv`.

**Validation:** Use `src/agent/sql_validator.py` for active agent SQL and `src/agent/memory_validation.py` for template YAML.

**Authentication:** LLM providers use environment variables in `src/llm/model_adapter.py`; Databricks uses environment variables validated by `src/backends/config.py`; PostgreSQL uses environment variables read by `app/config.py`.

**Configuration:** Runtime scenario is selected by `DATA_SCENARIO` or `set_active_scenario_id` in `src/config/scenarios.py`. LLM provider/model config is loaded through `SQLAgentConfig` in `src/agent/langgraph_sql_agent.py`.

**Persistence:** Logs persist under `logs/`; approved templates and candidate state persist under `memory/`; golden test results persist under `evaluation/*/golden_results.jsonl`; local demo data CSV exports persist under `database/exports/`; Wuerth CSV input directories are ignored by `.gitignore`.

**Presentation assets:** Keep Wuerth-branded assets under `assets/templates/`. Use `assets/templates/PPT_Vorlage_Wuerth.pptx` as the canonical template for any PPTX export feature.

---

*Architecture analysis: 2026-06-21*
