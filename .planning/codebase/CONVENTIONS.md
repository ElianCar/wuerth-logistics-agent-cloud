# Coding Conventions

**Analysis Date:** 2026-06-21

## Naming Patterns

**Files:**
- Use lower_snake_case for Python modules in `src/`, `app/`, `scripts/`, and `evaluation/`: `src/agent/visualization_spec.py`, `src/agent/golden_test_runner.py`, `scripts/validate_wuerth_local_setup.py`.
- Use package directories for bounded areas: `src/agent/`, `src/backends/`, `src/config/`, `src/llm/`, `app/`.
- Use `test_*.py` for discoverable test files under `evaluation/`: `evaluation/test_orchestrator.py`, `evaluation/test_visualization_spec.py`, `evaluation/test_backend_config_and_validation.py`.
- Use scenario-scoped fixture directories for golden data: `evaluation/demo/`, `evaluation/databricks/`, `evaluation/wuerth_local/`.
- Keep binary and branded assets under `assets/templates/`; the copied PowerPoint master template is `assets/templates/PPT_Vorlage_Wuerth.pptx`.

**Functions:**
- Use snake_case verbs that describe the action: `build_reporting_result()` in `src/agent/reporting_agent.py`, `validate_generated_sql()` in `src/agent/sql_validator.py`, `load_databricks_config()` in `src/backends/config.py`.
- Prefix private helper functions with `_`: `_safe_databricks_error()` in `src/backends/databricks/databricks_adapter.py`, `_chart_spec()` in `src/agent/visualization_spec.py`, `_write_yaml()` in `src/agent/memory_store.py`.
- Use `build_`, `load_`, `validate_`, `run_`, `render_`, `log_`, `get_`, and `parse_` prefixes consistently for public helpers in `src/agent/`, `src/config/`, and `streamlit_app.py`.
- Use `test_*` method names inside `unittest.TestCase` classes in `evaluation/test_*.py`.

**Variables:**
- Use snake_case for locals and parameters: `router_context`, `query_result`, `source_tables`, `validation_success` in `src/agent/orchestrator.py`.
- Use UPPER_SNAKE_CASE for constants and environment-key collections: `SUPPORTED_BACKENDS` in `src/backends/config.py`, `CHART_DISPLAY_ROW_LIMIT` in `src/agent/visualization_spec.py`, `QUERY_LOG_FIELDS` in `src/agent/logging_utils.py`.
- Use lowercase stable IDs for scenarios and providers: `"demo"`, `"wuerth_local"`, `"databricks"` in `src/config/scenarios.py`; `"gemini"`, `"anthropic"`, `"ollama"` in `src/llm/model_adapter.py`.
- Keep graph and result dictionary keys lower_snake_case to match `TypedDict` fields: `SQLAgentState` in `src/agent/langgraph_sql_agent.py`, `OrchestratorState` in `src/agent/orchestrator.py`.

**Types:**
- Use PascalCase for classes, dataclasses, protocols, and errors: `SQLAgentConfig` in `src/agent/langgraph_sql_agent.py`, `ScenarioConfig` in `src/config/scenarios.py`, `SQLBackend` in `src/backends/base.py`, `BackendConfigError` in `src/backends/config.py`.
- Use frozen dataclasses for immutable configuration and result records: `DatabricksBackendConfig` and `BackendSettings` in `src/backends/config.py`, `ModelResponse` in `src/llm/model_adapter.py`.
- Use `TypedDict` for mutable LangGraph state payloads: `RouterState` in `src/agent/router.py`, `SQLAgentState` in `src/agent/langgraph_sql_agent.py`.

## Code Style

**Formatting:**
- No formatter config is detected. Follow the existing PEP 8 style used in `src/agent/visualization_spec.py`, `src/backends/config.py`, and `evaluation/test_orchestrator.py`: 4-space indentation, blank lines between import groups, and readable wrapped calls.
- Use modern type hints such as `list[str]`, `dict[str, Any]`, `str | None`, and `tuple[str, ...]` as in `src/agent/reporting_agent.py` and `src/config/scenarios.py`.
- Add `from __future__ import annotations` to new modern modules under `src/`, `scripts/`, and `evaluation/`; existing examples include `src/agent/orchestrator.py`, `src/backends/base.py`, and `evaluation/test_visualization_spec.py`.
- Prefer `pathlib.Path` for filesystem paths in new code, matching `src/config/scenarios.py`, `src/agent/golden_test_runner.py`, and `scripts/validate_wuerth_local_setup.py`.
- Use keyword-only parameters for complex builder APIs, matching `build_reporting_result()` in `src/agent/reporting_agent.py` and `build_visualization_spec()` in `src/agent/visualization_spec.py`.

**Linting:**
- Not detected. There is no `pyproject.toml`, `.flake8`, `ruff.toml`, or lint command in `requirements.txt`.
- Use the repository's general syntax check from `README.md`: `python -m compileall app src scripts streamlit_app.py evaluation`.
- Treat deterministic validators as the local style guardrail: SQL safety lives in `src/agent/sql_validator.py`, scenario validation lives in `scripts/validate_wuerth_local_setup.py`, and output comparison lives in `src/agent/golden_test_runner.py`.

## Import Organization

**Order:**
1. `from __future__ import annotations` first where used, as in `src/agent/langgraph_sql_agent.py`.
2. Standard library imports next: `os`, `re`, `csv`, `Path`, `dataclass`, `typing` in `src/backends/config.py` and `src/agent/logging_utils.py`.
3. Third-party imports after a blank line: `yaml`, `pandas`, `streamlit`, `langgraph`, `dotenv` in `src/agent/langgraph_sql_agent.py` and `streamlit_app.py`.
4. Local imports last, using absolute package paths: `from src.agent...` and `from app...` in `src/agent/orchestrator.py`, `src/backends/demo/postgres_adapter.py`, and `main.py`.

**Path Aliases:**
- No configured path aliases are detected. Use absolute imports from repo-root packages: `from src.config.scenarios import get_active_scenario` in `src/backends/config.py`, `from app.db import get_connection` in `src/backends/demo/postgres_adapter.py`.
- CLI scripts that are run directly add `PROJECT_ROOT` to `sys.path` before local imports: `evaluation/run_evaluation.py`, `scripts/validate_wuerth_local_setup.py`, `scripts/databricks/test_databricks_connection.py`.
- Avoid adding logic to package markers. Existing `__init__.py` files are empty in `src/__init__.py`, `src/agent/__init__.py`, `src/backends/__init__.py`, and `app/__init__.py`.

## Error Handling

**Patterns:**
- Define domain-specific errors close to the domain: `BackendConfigError` in `src/backends/config.py`, `ScenarioConfigError` in `src/config/scenarios.py`, `ModelAdapterError` in `src/llm/model_adapter.py`, `MemoryStoreError` in `src/agent/memory_store.py`.
- Raise configuration errors with missing key names, not secret values. `load_databricks_config()` in `src/backends/config.py` reports missing env var names and tests assert that sensitive placeholders are absent in `evaluation/test_backend_config_and_validation.py`.
- Sanitize external connector exceptions before returning them to callers. `_safe_databricks_error()` in `src/backends/databricks/databricks_adapter.py` reports the connector error type while omitting host, path, and token values.
- Return structured validation objects for expected invalid input rather than raising exceptions. `validate_generated_sql()` returns `SQLValidationResult` in `src/agent/sql_validator.py`; the legacy `app/sql_validator.py` returns `ValidationResult`.
- Keep terminal and UI flows resilient. `main.py` catches startup, LLM, explain, and execution failures and prints short messages; `streamlit_app.py` catches `MemoryStoreError` around memory review actions.
- Preserve exception chaining for dependency and configuration failures with `raise ... from error`, as in `src/llm/model_adapter.py`, `src/backends/databricks/databricks_adapter.py`, and `scripts/validate_wuerth_local_setup.py`.
- Logging failures are intentionally non-fatal: `append_csv_row()` in `src/agent/logging_utils.py` catches exceptions and prints `Logging failed for ...`.

## Logging

**Framework:** console, CSV helpers, and Python logging

**Patterns:**
- Use `src/agent/logging_utils.py` for query, feedback, router, and memory audit CSV output. It owns CSV schemas such as `QUERY_LOG_FIELDS` and `FEEDBACK_LOG_FIELDS`.
- Use `app/logging_utils.py` only for the legacy CLI path under `app/` and `main.py`.
- Use Python's `logging` module for operational scripts, as in `scripts/ingest_wuerth_csv_to_postgres.py`.
- Use `print()` for short CLI status in `main.py`, `evaluation/run_evaluation.py`, and `scripts/validate_wuerth_local_setup.py`.
- Never log raw credentials or connector secrets. Follow the safe-error pattern in `src/backends/databricks/databricks_adapter.py` and the assertions in `evaluation/test_backend_config_and_validation.py`.

## Comments

**When to Comment:**
- Prefer clear function names and structured return values over inline commentary. Most helper modules under `src/agent/` are self-documenting through typed signatures and constants.
- Add a docstring when a public builder has important side-effect boundaries. Examples: `build_reporting_result()` in `src/agent/reporting_agent.py` states that it does not generate SQL, modify SQL, call a database, or call an LLM; `build_visualization_spec()` in `src/agent/visualization_spec.py` states that it only inspects existing result data.
- Use comments sparingly around non-obvious compatibility or migration logic. CSV schema migration is centralized in `ensure_csv_columns()` in `src/agent/logging_utils.py`.

**JSDoc/TSDoc:**
- Not applicable. This is a Python repository with no TypeScript source.
- Use Python docstrings for public protocols and boundary methods, as in `SQLBackend` in `src/backends/base.py`.

## Function Design

**Size:** Keep new domain logic as small pure helpers under `src/agent/`, `src/backends/`, or `src/config/`. Large orchestration and UI modules already exist in `src/agent/orchestrator.py`, `src/agent/langgraph_sql_agent.py`, and `streamlit_app.py`; add helpers instead of growing those files when practical.

**Parameters:** Use explicit dependency injection for external effects. `run_sql_agent()` accepts `schema_loader`, `sql_generator`, `sql_executor`, and `attempt_logger` in `src/agent/langgraph_sql_agent.py`; `DatabricksAdapter` accepts `connect_func` in `src/backends/databricks/databricks_adapter.py`.

**Return Values:** Return JSON-serializable dictionaries for agent state, chart specs, reporting results, and logs, matching `src/agent/orchestrator.py`, `src/agent/visualization_spec.py`, and `src/agent/reporting_agent.py`. Use frozen dataclasses for config/value records in `src/backends/config.py`, `src/config/scenarios.py`, and `src/llm/model_adapter.py`.

## Module Design

**Exports:** Import concrete functions/classes directly from their modules. There is no `__all__` pattern and no active barrel export pattern in `src/__init__.py`, `src/agent/__init__.py`, or `src/backends/__init__.py`.

**Barrel Files:** Keep package `__init__.py` files empty unless there is a concrete import compatibility need. Do not introduce cross-package side effects there.

**State and globals:**
- Keep scenario state behind the context variable helpers in `src/config/scenarios.py`: use `set_active_scenario_id()` and `reset_active_scenario_id()` in tests and UI flows.
- Keep Streamlit session state inside `streamlit_app.py`. New non-UI behavior should live in `src/agent/` or `src/config/` so it can be tested without Streamlit.
- Keep lazy graph caching private to the module, following `_compiled_router` and `_get_compiled_router()` in `src/agent/orchestrator.py`.

**Asset handling:**
- Resolve repository assets with `Path` rather than absolute local paths. Future PowerPoint export code should reference `assets/templates/PPT_Vorlage_Wuerth.pptx` through a module-level `Path` constant near the export implementation.
- Keep binary template handling out of Streamlit callbacks where practical. Expose a pure export function under `src/agent/` or a new focused module so `evaluation/test_*.py` can test the PowerPoint output path.

---

*Convention analysis: 2026-06-21*
