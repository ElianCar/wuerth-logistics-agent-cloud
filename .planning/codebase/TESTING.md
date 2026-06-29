# Testing Patterns

**Analysis Date:** 2026-06-21

## Test Framework

**Runner:**
- `unittest` from the Python standard library. Tests are discoverable because files are named `evaluation/test_*.py` and classes inherit `unittest.TestCase`.
- Config: Not detected. There is no `pytest.ini`, `pyproject.toml`, `tox.ini`, or dedicated test runner config.

**Assertion Library:**
- `unittest.TestCase` assertions in `evaluation/test_orchestrator.py`, `evaluation/test_reporting_agent.py`, `evaluation/test_backend_config_and_validation.py`, and `evaluation/test_visualization_spec.py`.
- Plain `assert` in script-style smoke tests such as `evaluation/run_langgraph_smoke_tests.py`.
- `pandas.testing.assert_frame_equal()` for DataFrame mutation checks in `evaluation/test_reporting_agent.py`.

**Run Commands:**
```bash
python -m compileall app src scripts streamlit_app.py evaluation
python -m unittest discover -s evaluation -p "test_*.py"
python evaluation/run_langgraph_smoke_tests.py
python scripts/validate_wuerth_local_setup.py --skip-db
DATA_SCENARIO=wuerth_local python evaluation/run_evaluation.py W01 W02 W03 W04 W05
```

## Test File Organization

**Location:**
- Unit and focused integration tests live under `evaluation/`: `evaluation/test_router.py`, `evaluation/test_orchestrator.py`, `evaluation/test_visualization_spec.py`, `evaluation/test_backend_config_and_validation.py`.
- Golden question data for the current local scenarios lives under `evaluation/demo/golden_questions.yaml` and `evaluation/wuerth_local/golden_questions.yaml`. Databricks golden fixtures were removed from the current local hand-in/demo scope.
- Golden SQL fixtures live under scenario solution folders: `evaluation/demo/solution_sql/`, `evaluation/wuerth_local/solution_sql/`.
- CLI smoke and evaluation entry points also live under `evaluation/`: `evaluation/run_langgraph_smoke_tests.py`, `evaluation/run_evaluation.py`.

**Naming:**
- Use `test_*.py` for files that should be picked up by `python -m unittest discover -s evaluation -p "test_*.py"`.
- Use `*Tests` for `unittest.TestCase` classes: `OrchestratorTests`, `VisualizationSpecTests`, `BackendConfigAndValidationTests`.
- Use behavior-focused method names starting with `test_`, such as `test_reporting_failure_preserves_successful_sql_result()` in `evaluation/test_orchestrator.py`.

**Structure:**
```text
evaluation/
├── test_*.py                    # unittest-discovered tests
├── run_langgraph_smoke_tests.py  # script smoke test with plain assert
├── run_evaluation.py            # golden question runner
├── demo/
│   ├── golden_questions.yaml
│   └── solution_sql/
└── wuerth_local/
    ├── golden_questions.yaml
    └── solution_sql/
```

## Test Structure

**Suite Organization:**
```python
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from src.agent.langgraph_sql_agent import SQLAgentConfig


def test_config() -> SQLAgentConfig:
    return SQLAgentConfig(
        primary_model="hard-primary",
        fallback_model="fallback-model",
        max_primary_attempts=3,
        llm_provider="gemini",
        ollama_host="http://localhost:11434",
    )


class OrchestratorTests(unittest.TestCase):
    def test_needs_clarification_stops_before_sql_execution(self) -> None:
        ...


if __name__ == "__main__":
    unittest.main()
```

**Patterns:**
- Put small factory helpers above the test class: `router_state()` and `sql_result()` in `evaluation/test_orchestrator.py`, `query_result()` in `evaluation/test_visualization_spec.py`, `build_report()` in `evaluation/test_reporting_agent.py`.
- Use fake classes for simple protocols: `FakeRouter` in `evaluation/test_orchestrator.py`, `FakeConnection` and `FakeCursor` in `evaluation/test_backend_config_and_validation.py`.
- Reset global/context state with `setUp()` and `tearDown()` when tests touch scenarios, as in `evaluation/test_wuerth_local_scenario.py` and `evaluation/test_backend_config_and_validation.py`.
- Use `self.subTest(...)` for table-driven variants, as in `test_validator_allows_approved_databricks_table_forms()` in `evaluation/test_backend_config_and_validation.py`.
- Assert public contracts rather than implementation details: public result fields in `evaluation/test_orchestrator.py`, chart spec fields in `evaluation/test_visualization_spec.py`, audit fields in `evaluation/test_reporting_agent.py`.

## Mocking

**Framework:** `unittest.mock`

**Patterns:**
```python
sql_mock = Mock(return_value=sql_result())
with patch("src.agent.orchestrator._get_compiled_router", return_value=FakeRouter(router_state())), patch(
    "src.agent.orchestrator.run_sql_agent",
    sql_mock,
):
    result = orchestrator.run_orchestrator(
        "Wie viele Bestellungen gibt es?",
        config=test_config(),
        log_to_query_log=False,
    )
```

**What to Mock:**
- Mock LLM/model calls and router graph calls with `patch()` to keep tests deterministic: `evaluation/test_router.py`, `evaluation/test_orchestrator.py`.
- Mock environment variables with `patch.dict(os.environ, ..., clear=True)` for backend and provider config: `evaluation/test_backend_config_and_validation.py`, `evaluation/test_orchestrator.py`.
- Mock SQL connections with injected callables or fake connection classes: `DatabricksAdapter(connect_func=...)` in `evaluation/test_backend_config_and_validation.py`.
- Mock log directories with `tempfile.TemporaryDirectory()` and `patch("src.agent.orchestrator.get_log_dir", ...)` as in `evaluation/test_orchestrator.py`.
- Inject fake loaders, generators, executors, and loggers into `run_sql_agent()` for smoke coverage: `evaluation/run_langgraph_smoke_tests.py`.

**What NOT to Mock:**
- Do not mock deterministic validators and comparison helpers when small input data is enough: `src/agent/sql_validator.py`, `src/agent/visualization_spec.py`, `src/agent/reporting_agent.py`, `src/agent/golden_test_runner.py`.
- Do not mock the copied PowerPoint master template once PPT export exists. Tests should open or copy `assets/templates/PPT_Vorlage_Wuerth.pptx` so missing, corrupt, or accidentally moved template assets fail fast.
- Do not mock input mutation checks. Use real small lists/DataFrames as in `evaluation/test_visualization_spec.py` and `evaluation/test_reporting_agent.py`.

## Fixtures and Factories

**Test Data:**
```python
def query_result(columns: list[str], rows: list[tuple[object, ...]]) -> dict[str, object]:
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "executed_sql": "SELECT ...",
    }
```

**Location:**
- Inline test factories live in the test file that owns them: `evaluation/test_visualization_spec.py`, `evaluation/test_reporting_agent.py`, `evaluation/test_orchestrator.py`.
- Golden question fixtures live in `evaluation/<scenario>/golden_questions.yaml`.
- Golden solution SQL files live in `evaluation/demo/solution_sql/` and `evaluation/wuerth_local/solution_sql/`.
- Transient filesystem fixtures use `tempfile.TemporaryDirectory()` in `evaluation/test_orchestrator.py` and `evaluation/run_langgraph_smoke_tests.py`.
- Future PPT export fixtures should use `assets/templates/PPT_Vorlage_Wuerth.pptx` as the real master input and write generated presentations to a temporary directory.

## Coverage

**Requirements:** None enforced. No coverage package or coverage command is present in `requirements.txt` or repository config.

**View Coverage:**
```bash
python -m unittest discover -s evaluation -p "test_*.py"
```

Coverage is currently inferred from behavior-specific tests, not measured with a percentage target.

## Test Types

**Unit Tests:**
- Use focused `unittest` files for deterministic pure logic: `evaluation/test_visualization_spec.py` for chart specs, `evaluation/test_reporting_agent.py` for reporting output, `evaluation/test_golden_result_comparison.py` for golden result comparison, `evaluation/test_router.py` for router behavior.
- Use small dict/list inputs and assert complete public output fields, warnings, audit data, and non-mutation behavior.

**Integration Tests:**
- `evaluation/test_backend_config_and_validation.py` covers backend configuration, SQL validation, safe Databricks errors, and mocked adapter execution.
- `evaluation/test_wuerth_local_scenario.py` covers scenario selection, semantic layer loading, local table allowlists, and CSV-header compatibility checks when local CSV exports are present.
- `evaluation/run_langgraph_smoke_tests.py` covers the SQL agent fallback path, placeholder API key protection, query logging, silent golden-test mode, and correction prompts.
- `evaluation/run_evaluation.py` executes scenario golden questions from `evaluation/<scenario>/golden_questions.yaml` against `src/agent/golden_test_runner.py`.

**E2E Tests:**
- Browser/UI E2E tests are not used. `streamlit_app.py` has no direct Streamlit UI test suite.
- CLI-style end-to-end checks are represented by `evaluation/run_langgraph_smoke_tests.py`, `evaluation/run_evaluation.py`, and `scripts/validate_wuerth_local_setup.py`.

**PPT Export Tests:**
- PPT export code is not detected. The template asset is present at `assets/templates/PPT_Vorlage_Wuerth.pptx`.
- When PPT export is added, add `evaluation/test_ppt_export.py` or an equivalent `evaluation/test_*.py` file with tests for template path resolution, output file creation in a temporary directory, non-empty slides, expected brand template usage, and safe behavior when the template path is missing.
- Add a golden or smoke command for PPT export only if it can run without a local PowerPoint installation. If a renderer/converter is optional, skip that visual check when unavailable and keep deterministic file-level assertions mandatory.

## Common Patterns

**Async Testing:**
```python
# Not used. Current tests are synchronous unittest tests.
```

**Error Testing:**
```python
with self.assertRaises(RuntimeError) as context:
    adapter.execute_sql("SELECT 1")

message = str(context.exception)
self.assertIn("Databricks SQL execution failed", message)
self.assertNotIn("sensitive-token", message)
```

**Mutation Testing:**
```python
original = df.copy(deep=True)
build_reporting_result(...)
pd.testing.assert_frame_equal(df, original)
```

**Serialization Testing:**
```python
spec = build_spec(query_result(["region", "total_revenue"], [("EUROPE", Decimal("10.5"))]))
json.dumps(spec)
```

---

*Testing analysis: 2026-06-21*
