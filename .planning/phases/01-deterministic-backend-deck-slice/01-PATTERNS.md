# Phase 01: Deterministic Backend Deck Slice - Pattern Map

**Mapped:** 2026-06-21
**Files analyzed:** 3 Phase 1 file targets plus 1 future consumer context
**Analogs found:** 3 / 3 direct file targets

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/agent/presentation_export.py` | service, utility | request-response, transform, file-I/O | `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py` | role-match |
| `evaluation/test_presentation_export.py` | test | request-response, file-I/O | `evaluation/test_orchestrator.py`, `evaluation/test_reporting_agent.py`, `evaluation/test_visualization_spec.py` | role-match |
| `requirements.txt` | config | dependency config | `requirements.txt` | exact |

**Future consumer context only:** `streamlit_app.py` should not be modified in Phase 1. Use the existing CSV/XLSX download pattern later.

## Pattern Assignments

### `src/agent/presentation_export.py` (service, utility, request-response + transform + file-I/O)

**Primary analog:** `src/agent/reporting_agent.py`

**Supporting analogs:**
- `src/agent/visualization_spec.py` for fail-closed spec construction.
- `src/config/scenarios.py` for repo-relative constants and frozen dataclass registries.
- `src/backends/config.py` for domain-specific config errors.
- `src/agent/orchestrator.py` for the successful record contract.
- `.planning/PPT_TEMPLATE_GUIDE.md` for Wuerth template layout names and dynamic deck rules.

**Imports pattern** from `src/agent/reporting_agent.py` (lines 1-9):

```python
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

import pandas as pd

from src.agent.visualization_spec import build_visualization_spec
```

Copy this import organization:
- `from __future__ import annotations`
- standard library imports first
- third-party imports next, such as `from pptx import Presentation`
- repo imports last
- no Streamlit import in the backend module

**Public builder boundary** from `src/agent/reporting_agent.py` (lines 22-40):

```python
def build_reporting_result(
    *,
    user_question: str,
    router_state: dict[str, Any] | None = None,
    sql: str = "",
    query_result: dict[str, Any] | None = None,
    result_dataframe: pd.DataFrame | None = None,
    row_count: int | None = None,
    source_tables: list[str] | None = None,
    execution_success: bool = False,
    validation_success: bool = False,
    language: str = "de",
    chart_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic post-SQL reporting output.

    The reporting layer does not generate SQL, modify SQL, call a database, or
    call an LLM. It only inspects the already returned SQL result and metadata.
    """
```

Apply this shape to a public export function, for example `build_presentation_export(...)` or `export_presentation(...)`:
- use keyword-only parameters for complex inputs
- accept an orchestrator record or normalized record fields
- return a structured object instead of throwing for expected ineligible records
- docstring must state the boundary: no SQL generation, no database calls, no LLM calls, no Streamlit dependency

**Deterministic return object pattern** from `src/agent/reporting_agent.py` (lines 87-101):

```python
return {
    "summary": summary_parts["summary"],
    "interpretation": summary_parts["interpretation"],
    "caveats": caveats,
    "chart_plan": chart_plan,
    "table_plan": {
        "render_allowed": bool(not df.empty),
        "row_count": effective_row_count,
        "columns": [str(column) for column in df.columns],
        "preserve_sql_order": True,
    },
    "kpi_cards": _build_kpi_cards(df, metadata),
    "display_notes": display_notes,
    "audit": audit,
}
```

Use the same structured-output style for the exporter. Suggested fields:
- `available: bool`
- `content: bytes`
- `filename: str`
- `mime_type: str`
- `slide_count: int`
- `warnings: list[str]`
- `unavailable_reason: str`
- `template_audit: dict[str, Any]`

**Fail-closed eligibility pattern** from `src/agent/visualization_spec.py` (lines 55-72):

```python
if not _chart_requested(router_context, output_mode):
    return _no_chart("No explicit chart request was made.")

if not execution_success:
    return _no_chart("SQL execution did not succeed.")
if not validation_success:
    return _no_chart("SQL validation did not succeed.")

columns = [str(column) for column in query_result.get("columns", [])]
rows = list(query_result.get("rows", []) or [])
effective_row_count = int(row_count if row_count is not None else query_result.get("row_count", len(rows)) or 0)

if not columns:
    return _no_chart("The SQL result has no columns.")
if not rows or effective_row_count == 0:
    return _no_chart("The SQL result is empty.")
```

Adapt this directly for `can_export_presentation(record)`:
- reject `blocked_or_unsafe`
- reject `needs_clarification`
- reject `not execution_success`
- reject `not validation_success` and `not sql_valid`
- reject empty or missing `query_result.columns`
- reject empty or missing `query_result.rows`
- reject missing template before rendering, but only after record eligibility is known

**Structured unavailable-result pattern** from `src/agent/visualization_spec.py` (lines 206-229):

```python
def _no_chart(reason: str, warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "chart_type": "none",
        "x_axis": None,
        "y_axis": None,
        "series": None,
        "title": "",
        "x_label": "",
        "y_label": "",
        "unit": "",
        "reason": reason,
        "confidence": 0.0,
        "render_allowed": False,
        "warnings": warnings or [],
        "orientation": "vertical",
        "category_order": [],
        "x_type": "",
        "y_type": "",
        "value_axis_starts_at_zero": False,
        "display_row_limit": CHART_DISPLAY_ROW_LIMIT,
        "truncated": False,
        "note": "",
        "sort": {"mode": "none", "explicit": False},
    }
```

Create the exporter equivalent, for example `_unavailable_export(reason, warnings=None)`, with all public fields present and `content=b""`.

**Frozen result and validation-object pattern** from `src/agent/sql_validator.py` (lines 84-90):

```python
@dataclass(frozen=True)
class SQLValidationResult:
    sql: str
    is_valid: bool
    error: str
    used_tables: list[str]
```

Use frozen dataclasses for `PresentationExport`, `SlideDeckSpec`, `SlideSpec`, `TemplateManifest`, and `TemplateAudit` unless the planner chooses a plain dict contract for consistency with reporting output. If dataclasses are used, keep them immutable.

**Repo-relative path and manifest pattern** from `src/config/scenarios.py` (lines 10, 40-68):

```python
PROJECT_ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class ScenarioConfig:
    scenario_id: str
    label: str
    backend_name: str
    backend_display_name: str
    sql_dialect: str
    semantic_layer_path: Path
    memory_dir: Path
    evaluation_dir: Path
    dataset_id: str
    allowed_tables: tuple[str, ...]

    @property
    def semantic_layer_filename(self) -> str:
        return self.semantic_layer_path.name

    @property
    def safe_metadata(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "scenario_label": self.label,
            "backend_name": self.backend_name,
            "backend_display_name": self.backend_display_name,
            "sql_dialect": self.sql_dialect,
            "semantic_layer": self.semantic_layer_filename,
            "dataset_id": self.dataset_id,
            "allowed_tables": list(self.allowed_tables),
        }
```

Put the template manifest/constants inside `src/agent/presentation_export.py` for Phase 1. Do not create a separate manifest file unless planning finds a strong reason. Use:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "assets" / "templates" / "PPT_Vorlage_Wuerth.pptx"
PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
```

**Domain error pattern** from `src/backends/config.py` (lines 24-35):

```python
class BackendConfigError(ValueError):
    """Raised when backend configuration is missing or unsupported."""


@dataclass(frozen=True)
class DatabricksBackendConfig:
    auth_type: str
    server_hostname: str = field(repr=False)
    http_path: str = field(repr=False)
    catalog: str
    schema: str
    allowed_tables: tuple[str, ...]
```

Use a local `PresentationExportError` only for exceptional renderer failures. Expected ineligibility should return a structured unavailable export.

**Record fields to consume** from `src/agent/orchestrator.py` (lines 49-98):

```python
class OrchestratorState(TypedDict, total=False):
    run_id: str
    user_question: str
    chat_context: str
    llm_provider: str
    ollama_host: str

    intent: str
    needs_sql: bool
    needs_clarification: bool
    blocked_or_unsafe: bool
    output_mode: str
    language: str
    memory_intent_key: str
    complexity_tier: str
    complexity_reason: str
    constraints: dict[str, Any]
    execution_plan: list[str]
    clarification_question: str
    template_candidates: list[dict[str, Any]]

    selected_model: str
    model_used: str
    primary_model: str
    fallback_model: str
    max_primary_attempts: int

    schema_context: str
    generated_sql: str
    final_sql: str
    sql_valid: bool
    sql_error: str
    query_result: dict[str, Any]
    execution_success: bool
    validation_success: bool
    fallback_used: bool
    source_tables: list[str]
    row_count: int
    total_attempts: int
    result_status: str
    error_type: str
    error_message: str
    latency_seconds: float
    trace_steps: list[str]
    final_answer: str
    answer: str
    schema_load_failed: bool
    chart_spec: dict[str, Any]
    reporting_result: dict[str, Any]
```

The exporter should depend on this public record shape. It should not call the router, SQL agent, database facade, or reporting agent unless the implementation explicitly supports missing `reporting_result` as a fallback.

**Terminal failure record pattern** from `src/agent/orchestrator.py` (lines 423-451):

```python
terminal_result = {
    "final_answer": answer,
    "answer": answer,
    "execution_success": False,
    "validation_success": False,
    "fallback_used": False,
    "generated_sql": "",
    "final_sql": "",
    "sql_valid": False,
    "sql_error": "",
    "query_result": {},
    "source_tables": [],
    "row_count": 0,
    "total_attempts": 0,
    "result_status": status,
    "error_type": error_type,
    "error_message": "",
}
router_context = _build_router_context(state)
reporting_result = _build_reporting_result(
    user_question=state.get("user_question", ""),
    router_context=router_context,
    result=terminal_result,
)
return {
    **terminal_result,
    "chart_spec": reporting_result["chart_plan"],
    "reporting_result": reporting_result,
}
```

Copy the idea: even failed or blocked records still have predictable fields. The exporter should return predictable fields too.

**Template layout contract** from `.planning/PPT_TEMPLATE_GUIDE.md` (lines 40-68):

```markdown
1. `Agent 01 Cover`
2. `Agent 02 Executive Summary`
3. `Agent 03 KPI Overview`
4. `Agent 04 Chart Evidence`
5. `Agent 05 Table Evidence`
6. `Agent 06 Comparison`
7. `Agent 07 Caveats And Sources`
8. `Agent 08 Appendix Metadata`
9. `Agent 09 Closing`
```

Dynamic deck rules to encode in the manifest:
- Always include `Agent 01 Cover`.
- Include `Agent 02 Executive Summary` only when summary or takeaway exists.
- Include `Agent 03 KPI Overview` only when useful KPI cards exist.
- Repeat `Agent 04 Chart Evidence` and `Agent 05 Table Evidence` as needed.
- Include `Agent 09 Closing` only when the deck contract enables it.

**Important template warning:** `01-CONTEXT.md` has stale names for layouts 7 and 8 in one place. Use the current names from `.planning/PPT_TEMPLATE_GUIDE.md` and `01-RESEARCH.md`: `Agent 07 Caveats And Sources` and `Agent 08 Appendix Metadata`.

**No exact codebase analog:** The repo has no PPTX rendering code. Use `01-RESEARCH.md` for `python-pptx` examples. Keep `zipfile` package scans limited to template safety checks:
- warn on the known two think-cell OLE objects
- block macros such as `vbaProject.bin`
- block external relationships
- do not fail only because the known OLE objects exist

### `evaluation/test_presentation_export.py` (test, request-response + file-I/O)

**Primary analog:** `evaluation/test_orchestrator.py`

**Supporting analogs:**
- `evaluation/test_reporting_agent.py` for inline factories and pure post-processing assertions.
- `evaluation/test_visualization_spec.py` for fail-closed and serialization assertions.

**Imports and helper factory pattern** from `evaluation/test_reporting_agent.py` (lines 1-38):

```python
from __future__ import annotations

from decimal import Decimal
import unittest

import pandas as pd

from src.agent.reporting_agent import build_reporting_result


def requested_router(**overrides: object) -> dict[str, object]:
    router = {"output_mode": "chart_plus_table", "language": "de"}
    router.update(overrides)
    return router


def query_result(columns: list[str], rows: list[tuple[object, ...]]) -> dict[str, object]:
    return {"columns": columns, "rows": rows, "row_count": len(rows)}
```

For PPT tests, create small local helpers above the test class:
- `query_result(columns, rows)`
- `reporting_result(...)`
- `orchestrator_record(**overrides)`
- optionally `valid_record()` and `ineligible_record(...)`

**Fake orchestrator record pattern** from `evaluation/test_orchestrator.py` (lines 23-63):

```python
def router_state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "intent": "aggregation",
        "needs_sql": True,
        "needs_clarification": False,
        "blocked_or_unsafe": False,
        "output_mode": "table",
        "language": "de",
        "memory_intent_key": "aggregation",
        "complexity_tier": "hard",
        "complexity_reason": "requires SQL",
        "constraints": {"time_window": None, "grouping_level": []},
        "execution_plan": ["retrieve_templates", "run_sql_agent"],
        "clarification_question": "",
        "template_candidates": [],
    }
    state.update(overrides)
    return state


def sql_result(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "generated_sql": "SELECT 1",
        "final_sql": "SELECT 1",
        "query_result": {"columns": ["one"], "rows": [(1,)], "row_count": 1},
        "row_count": 1,
        "validation_success": True,
        "execution_success": True,
        "result_status": "im ersten Versuch erfolgreich",
        "final_answer": "Die Antwort ist 1.",
        "answer": "Die Antwort ist 1.",
        "source_tables": ["orders"],
        "total_attempts": 1,
        "fallback_used": False,
        "model_used": "hard-primary",
        "selected_model": "hard-primary",
        "trace_steps": ["SQL agent ran"],
        "error_type": "",
    }
    result.update(overrides)
    return result
```

Copy this approach for exporter inputs. The tests should not call the live orchestrator or database.

**Eligibility-blocking tests** from `evaluation/test_orchestrator.py` (lines 161-187):

```python
def test_needs_clarification_stops_before_sql_execution(self) -> None:
    result, sql_mock = self.run_with_fake_router(
        router_state(
            needs_sql=False,
            needs_clarification=True,
            clarification_question="Welche Kennzahl meinst du?",
        )
    )

    sql_mock.assert_not_called()
    self.assertEqual(result["result_status"], "clarification_needed")
    self.assertEqual(result["final_answer"], "Welche Kennzahl meinst du?")

def test_blocked_or_unsafe_stops_before_sql_execution(self) -> None:
    result, sql_mock = self.run_with_fake_router(
        router_state(
            intent="blocked",
            needs_sql=False,
            blocked_or_unsafe=True,
            clarification_question="Diese Anfrage kann aus Sicherheitsgruenden nicht verarbeitet werden.",
        )
    )

    sql_mock.assert_not_called()
    self.assertEqual(result["result_status"], "blocked")
    self.assertEqual(result["error_type"], "blocked_request")
```

Create table-style test cases for export ineligibility:
- failed execution
- failed validation
- `sql_valid=False`
- `needs_clarification=True`
- `blocked_or_unsafe=True`
- empty `query_result`
- missing rows or columns
- missing template path

**Temporary filesystem pattern** from `evaluation/test_orchestrator.py` (lines 352-373):

```python
def test_router_logging_handles_empty_template_candidate_fields(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        sql_mock = Mock(return_value=sql_result())
        with patch("src.agent.orchestrator.get_log_dir", return_value=Path(temp_dir)), patch(
            "src.agent.orchestrator._get_compiled_router",
            return_value=FakeRouter(router_state()),
        ), patch("src.agent.orchestrator.run_sql_agent", sql_mock):
            result = orchestrator.run_orchestrator(
                "Wie viele Bestellungen gibt es?",
                config=test_config(),
                log_to_query_log=True,
            )

        log_path = Path(temp_dir) / "router_log.csv"
        with log_path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
```

Use `tempfile.TemporaryDirectory()` and `Path` for missing-template and generated-byte tests. Do not require Microsoft PowerPoint.

**Fail-closed assertion pattern** from `evaluation/test_visualization_spec.py` (lines 45-75):

```python
class VisualizationSpecTests(unittest.TestCase):
    def test_empty_result_returns_no_chart(self) -> None:
        spec = build_spec(query_result(["region", "total_revenue"], []))

        self.assertFalse(spec["render_allowed"])
        self.assertEqual(spec["chart_type"], "none")
        self.assertIn("empty", str(spec["reason"]).lower())

    def test_failed_sql_returns_no_chart(self) -> None:
        spec = build_spec(
            query_result(["region", "total_revenue"], [("EUROPE", 10)]),
            execution_success=False,
        )

        self.assertFalse(spec["render_allowed"])
        self.assertIn("execution", str(spec["reason"]).lower())

    def test_failed_validation_returns_no_chart(self) -> None:
        spec = build_spec(
            query_result(["region", "total_revenue"], [("EUROPE", 10)]),
            validation_success=False,
        )

        self.assertFalse(spec["render_allowed"])
        self.assertIn("validation", str(spec["reason"]).lower())
```

Use the same assertion style for `PresentationExport.available` and `PresentationExport.unavailable_reason`.

**Serialization/openability pattern** from `evaluation/test_visualization_spec.py` (lines 221-224):

```python
def test_chart_spec_is_json_serializable(self) -> None:
    spec = build_spec(query_result(["region", "total_revenue"], [("EUROPE", Decimal("10.5"))]))

    json.dumps(spec)
```

For PPTX output, replace JSON serialization with:
- assert `content` is non-empty bytes
- reopen bytes with `python-pptx`
- optionally inspect the ZIP package with `zipfile`
- assert generated slide count matches the dynamic deck spec

### `requirements.txt` (config, dependency config)

**Analog:** `requirements.txt`

**Existing dependency style** (lines 1-19):

```text
altair
duckdb
databricks-sdk
databricks-sql-connector
google-genai
langchain
langchain-anthropic
langchain-community
langchain-google-genai
langchain-ollama
langgraph
ollama
pandas
psycopg[binary]
python-dotenv
PyYAML
tabulate
streamlit
sqlalchemy
```

Pattern:
- one package per line
- currently no version pins
- no lockfile is present

Planner should add `python-pptx` unless it intentionally pins `python-pptx==1.0.2` after the package verification checkpoint from `01-RESEARCH.md`.

## Shared Patterns

### Deterministic Post-SQL Boundary

**Source:** `src/agent/reporting_agent.py` lines 36-40 and `src/agent/visualization_spec.py` lines 43-47

Apply to `src/agent/presentation_export.py`:
- no LLM calls
- no SQL generation
- no database access
- no Streamlit import
- inspect existing orchestrator/reporting output only

### Export Eligibility

**Source:** `src/agent/visualization_spec.py` lines 55-72 and `src/agent/orchestrator.py` lines 423-451

Apply before template loading:
- failed SQL returns unavailable export
- failed validation returns unavailable export
- blocked or clarification records return unavailable export
- empty result data returns unavailable export
- missing template returns unavailable export after record eligibility passes

### Structured Warnings

**Source:** `src/agent/reporting_agent.py` lines 83-85 and `src/agent/visualization_spec.py` lines 206-229

Apply to:
- known think-cell OLE entries
- chart/table truncation
- template hash drift if the implementation records a hash

### Template Manifest

**Source:** `.planning/PPT_TEMPLATE_GUIDE.md` lines 40-68 and `src/config/scenarios.py` lines 40-68

Apply in backend code:
- store layout names in a frozen dataclass or constant mapping
- store placeholder indexes by layout where implementation discovers them
- keep dynamic deck behavior in spec construction, not in Streamlit

### Error Handling

**Source:** `src/backends/config.py` lines 24-35 and `src/agent/memory_validation.py` lines 68-109

Apply to:
- expected validation failures return `list[str]` or structured unavailable results
- unexpected renderer failures may raise `PresentationExportError` or return an unavailable export with `error_type`
- do not expose local absolute paths beyond safe repo-relative template descriptions

### Future Streamlit Handoff

**Source:** `streamlit_app.py` lines 1378-1396

```python
col_csv, col_xlsx = st.columns(2)
csv_data = df.to_csv(index=False).encode("utf-8")
col_csv.download_button(
    "Als CSV exportieren",
    data=csv_data,
    file_name=f"ergebnis_{record.get('run_id', index)}.csv",
    mime="text/csv",
    key=f"export_csv_{index}",
    use_container_width=True,
)
xlsx_buffer = io.BytesIO()
df.to_excel(xlsx_buffer, index=False)
col_xlsx.download_button(
    "Als Excel exportieren",
    data=xlsx_buffer.getvalue(),
    file_name=f"ergebnis_{record.get('run_id', index)}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    key=f"export_xlsx_{index}",
    use_container_width=True,
)
```

Phase 2 should call the backend exporter and pass returned bytes to `st.download_button`. Phase 1 should not modify this file.

## No Analog Found

| File / Capability | Role | Data Flow | Reason |
|-------------------|------|-----------|--------|
| `src/agent/presentation_export.py` PPTX rendering internals | service | file-I/O | No current source imports `python-pptx` or writes PPTX files. Use `01-RESEARCH.md` examples plus this repo's validation/output patterns. |
| Template ZIP safety scan | utility | file-I/O, validation | No existing OOXML package scanner exists. Use standard-library `zipfile` and the fail-closed validation style from `memory_validation.py` and `sql_validator.py`. |
| Native PowerPoint chart/table rendering | service | transform, file-I/O | Current charts are Streamlit/Altair UI only. Phase 1 may render chart evidence as text/table fallback if the slide contract leaves room for later chart work. |

## Metadata

**Analog search scope:** `src/agent/`, `src/config/`, `src/backends/`, `evaluation/`, `requirements.txt`, `streamlit_app.py`, `.planning/PPT_TEMPLATE_GUIDE.md`
**Files scanned:** 117 via `rg --files`
**Pattern extraction date:** 2026-06-21
**Project skills:** No repo-local `.codex/skills/` or `.agents/skills/` directories found
