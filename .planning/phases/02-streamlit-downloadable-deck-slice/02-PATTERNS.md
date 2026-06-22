# Phase 02: Streamlit Downloadable Deck Slice - Pattern Map

**Mapped:** 2026-06-21
**Files analyzed:** 3 likely new/modified files
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `streamlit_app.py` | component/view | event-driven, request-response, file download | `streamlit_app.py` result export row and session-state helpers | exact |
| `evaluation/test_streamlit_presentation_export.py` | test | transform, event-driven helper, source boundary check | `evaluation/test_presentation_export.py` plus `evaluation/test_visualization_spec.py` | role-match |
| `evaluation/test_presentation_export.py` | test | file-I/O, transform | Existing PowerPoint export tests in same file | exact if planner colocates tests |

## Read-Only Pattern Sources

`src/agent/presentation_export.py` is a backend boundary and pattern source for this phase. Do not move PPTX rendering into Streamlit and do not add Streamlit imports there. Phase 2 should call:

```python
build_presentation_export(record=record, include_closing=False)
can_export_presentation(record)
PPTX_MIME_TYPE
```

## Pattern Assignments

### `streamlit_app.py` (component/view, event-driven request-response)

**Primary analog:** `streamlit_app.py`

**Backend boundary analog:** `src/agent/presentation_export.py`

**Imports pattern** (`streamlit_app.py` lines 1-31):

```python
import io
import uuid

import altair as alt
import pandas as pd
import streamlit as st
import yaml

from src.agent.db import get_active_backend_metadata
from src.agent.golden_test_runner import load_golden_questions, run_golden_tests
from src.agent.langgraph_sql_agent import SQLAgentConfig
from src.agent.orchestrator import run_orchestrator
from src.agent.logging_utils import log_feedback
```

Add the PPT import near the existing `src.agent` imports. Keep this allowlist only:

```python
from src.agent.presentation_export import (
    PPTX_MIME_TYPE,
    build_presentation_export,
    can_export_presentation,
)
```

Do not import `pptx`, `Presentation`, `SlideDeckSpec`, `SlideSpec`, `validate_template`, or renderer internals in `streamlit_app.py`.

**Session-state pattern** (`streamlit_app.py` lines 265-282):

```python
def initialize_state() -> None:
    if "data_scenario" in st.session_state:
        set_active_scenario_id(st.session_state.data_scenario)
    if "chats" not in st.session_state:
        first_id = _new_chat_id()
        st.session_state.chats = {first_id: _make_chat()}
        st.session_state.active_chat_id = first_id
    if st.session_state.get("active_chat_id") not in st.session_state.get("chats", {}):
        st.session_state.active_chat_id = next(iter(st.session_state.chats))
    st.session_state.setdefault("editing_chat_id", None)
    st.session_state.setdefault("confirm_delete_chat_id", None)
    st.session_state.setdefault("last_golden_run_id", "")
    st.session_state.setdefault("last_selected_question_ids", [])
    st.session_state.setdefault("last_failed_question_ids", [])
    st.session_state.setdefault("last_errored_question_ids", [])
    st.session_state.setdefault("last_golden_result_summary", {})
    st.session_state.setdefault("last_golden_results", [])
    initialize_memory_files()
```

Copy the `setdefault` pattern for deck storage:

```python
st.session_state.setdefault("presentation_exports", {})
```

Use a deterministic helper local to `streamlit_app.py`:

```python
def presentation_export_key(record: dict, index: int) -> str:
    active_chat_id = st.session_state.get("active_chat_id", "chat")
    record_id = record.get("run_id") or index
    return f"ppt_export_{active_chat_id}_{record_id}"
```

**Existing result export row pattern** (`streamlit_app.py` lines 1357-1398):

```python
def render_record(record: dict, index: int, config: SQLAgentConfig) -> None:
    ...
        query_result = record.get("query_result", {})
        rows = query_result.get("rows", [])
        columns = query_result.get("columns", [])
        if rows and columns:
            st.subheader("Ergebnisvorschau")
            df = result_to_dataframe(record)
            st.dataframe(df, use_container_width=True)
            render_chart_from_spec(record, df)

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

Change only the export row shape:

```python
col_csv, col_xlsx, col_ppt = st.columns(3)
```

Place PPT controls in `col_ppt` beside CSV and Excel. Keep them under the dataframe and optional chart, before `SQL-Anweisung`.

**Create/download backend call pattern** (`src/agent/presentation_export.py` lines 163-230):

```python
def build_presentation_export(
    *,
    record: dict[str, Any],
    include_closing: bool = False,
    template_path: Path | str = DEFAULT_TEMPLATE_PATH,
) -> PresentationExport:
    """Build deterministic PPTX bytes from an already validated agent result.

    This function does not generate SQL, execute SQL, call a database, call an
    LLM, or import Streamlit. It only inspects an existing orchestrator record
    and renders a validated local slide spec through the Wuerth template.
    """

    eligibility = can_export_presentation(record)
    if not eligibility.can_export:
        return _unavailable_export(eligibility.reason)
    ...
    return PresentationExport(
        available=True,
        content=content,
        filename=_filename_for(record),
        mime_type=PPTX_MIME_TYPE,
        slide_count=len(reopened.slides),
        warnings=_unique(warnings),
        unavailable_reason="",
        template_audit=audit,
        deck_spec=deck_spec,
    )


def can_export_presentation(record: dict[str, Any]) -> PresentationEligibility:
    """Return whether a record is eligible for deterministic PPTX export."""

    reason = _record_unavailable_reason(record)
    return PresentationEligibility(can_export=not reason, reason=reason)
```

Use this call shape in Streamlit:

```python
eligibility = can_export_presentation(record)
export = build_presentation_export(record=record, include_closing=False)
```

Do not pass `template_path` from Streamlit.

**Download button pattern** (`streamlit_app.py` lines 1380-1398 plus `presentation_export.py` lines 106-115):

```python
@dataclass(frozen=True)
class PresentationExport:
    available: bool
    content: bytes
    filename: str
    mime_type: str
    slide_count: int
    warnings: list[str]
    unavailable_reason: str = ""
    template_audit: TemplateAudit | None = None
    deck_spec: SlideDeckSpec | None = None
```

Render downloads from backend fields:

```python
col_ppt.download_button(
    "Download PPT",
    data=export.content,
    file_name=export.filename,
    mime=PPTX_MIME_TYPE,
    key=f"download_{export_key}",
    use_container_width=True,
)
```

Use `PresentationExport.filename` exactly. Do not build a Streamlit-specific PPT filename.

**Error and warning display pattern** (`streamlit_app.py` lines 293-300, 254-262):

```python
def render_flash() -> None:
    flash = st.session_state.pop("memory_flash", None)
    if not flash:
        return
    level, message = flash
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    else:
        st.info(message)
```

```python
def render_reporting_audit(record: dict) -> None:
    ...
    with st.expander("Reporting-Audit", expanded=False):
        st.json(audit, expanded=False)
```

Apply the same style for PPT:

```python
st.caption("PPT ready.")
st.warning("PPT created with warnings.")
with st.expander("PPT warnings", expanded=False):
    for warning in export.warnings:
        st.write(warning)
st.error(f"PPT export failed: {reason}. Fix the template or rerun a valid analysis, then create the deck again.")
```

**Spinner pattern** (`streamlit_app.py` line 1038):

```python
with st.spinner("Golden Tests are running..."):
    results = run_golden_tests(...)
```

Use the same block shape with the approved copy:

```python
with st.spinner("Creating PPT..."):
    export = build_presentation_export(record=record, include_closing=False)
```

**Eligibility reason source** (`src/agent/presentation_export.py` lines 654-681):

```python
def _record_unavailable_reason(record: dict[str, Any]) -> str:
    if not isinstance(record, dict):
        return "record_missing"
    if record.get("blocked_or_unsafe"):
        return "blocked_request"
    if record.get("needs_clarification"):
        return "clarification_needed"
    if not record.get("execution_success"):
        return "sql_execution_failed"
    if record.get("validation_success") is not True:
        return "sql_validation_failed"
    if record.get("sql_valid") is not True:
        return "sql_validation_failed"

    query = record.get("query_result")
    if not isinstance(query, dict):
        return "missing_query_result"
    columns = query.get("columns") or []
    rows = query.get("rows") or []
    if not columns:
        return "missing_query_columns"
    if not rows:
        return "missing_query_rows"
    effective_row_count = _effective_row_count(record, query, rows)
    if effective_row_count == 0:
        return "zero_row_count"
    return ""
```

Streamlit may translate these reason strings to UI copy, but it must not duplicate the eligibility decision.

---

### `evaluation/test_streamlit_presentation_export.py` (test, transform and boundary)

**Primary analog:** `evaluation/test_presentation_export.py`

**Secondary analog:** `evaluation/test_visualization_spec.py`

Prefer a new focused test module if adding helper functions in `streamlit_app.py`. This keeps backend export tests focused on PPTX rendering.

**Test import pattern** (`evaluation/test_presentation_export.py` lines 1-27):

```python
from __future__ import annotations

from io import BytesIO
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from pptx import Presentation

from src.agent.presentation_export import (
    DEFAULT_TEMPLATE_PATH,
    PPTX_MIME_TYPE,
    SlideDeckSpec,
    SlideSpec,
    FIXED_PPTX_TIMESTAMP,
    build_presentation_export,
    build_slide_deck_spec,
    validate_slide_deck_spec,
    validate_template,
)
```

For a Streamlit helper test, keep imports narrower. If the test reads `streamlit_app.py` as text, it does not need to import Streamlit:

```python
from __future__ import annotations

from pathlib import Path
import unittest
```

If tests import helper functions from `streamlit_app.py`, patch Streamlit and backend calls at the `streamlit_app` import boundary.

**Fixture pattern** (`evaluation/test_presentation_export.py` lines 29-116):

```python
def query_result(columns: list[str], rows: list[tuple[object, ...]]) -> dict[str, object]:
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


def orchestrator_record(**overrides: object) -> dict[str, object]:
    result = query_result(
        ["region", "shipment_count"],
        [
            ("Sued", 90),
            ("Nord", 75),
        ],
    )
    record: dict[str, object] = {
        "run_id": "run-ppt-001",
        "user_question": "Zeige Lieferungen nach Region als Praesentation",
        "final_sql": "SELECT region, COUNT(*) AS shipment_count FROM wuerth.shipments GROUP BY region",
        "query_result": result,
        "row_count": result["row_count"],
        "execution_success": True,
        "validation_success": True,
        "sql_valid": True,
        "source_tables": ["wuerth.shipments"],
        "reporting_result": reporting_result(result),
        "result_status": "success",
        "error_type": "",
    }
    record.update(overrides)
    return record
```

Reuse this fixture shape for successful and ineligible records. Keep records aligned with `can_export_presentation`.

**Pure helper test style** (`evaluation/test_visualization_spec.py` lines 1-30):

```python
from __future__ import annotations

from decimal import Decimal
import json
import unittest

from src.agent.visualization_spec import build_visualization_spec


def requested_context(**overrides: object) -> dict[str, object]:
    context: dict[str, object] = {"output_mode": "chart_plus_table"}
    context.update(overrides)
    return context
```

Copy this style for small helpers such as:

```python
presentation_export_key(record, index)
presentation_exports_state()
format_presentation_unavailable_reason(reason)
```

**Success assertions pattern** (`evaluation/test_presentation_export.py` lines 118-130):

```python
class PresentationExportSuccessTests(unittest.TestCase):
    def test_successful_record_returns_dynamic_pptx_export(self) -> None:
        export = build_presentation_export(record=valid_record())

        self.assertTrue(export.available)
        self.assertIsInstance(export.content, bytes)
        self.assertGreater(len(export.content), 0)
        self.assertTrue(export.filename.endswith(".pptx"))
        self.assertEqual(export.mime_type, PPTX_MIME_TYPE)
        self.assertGreater(export.slide_count, 0)
        self.assertNotEqual(export.slide_count, 9)
```

For UI helper tests, assert stored export fields, filename pass-through, MIME type, and create/download state separately.

**Boundary test pattern** (`evaluation/test_presentation_export.py` lines 198-235):

```python
script = textwrap.dedent(
    """
    import sys

    from src.agent.presentation_export import build_slide_deck_spec
    ...
    unexpected = [name for name in ("streamlit", "streamlit_app") if name in sys.modules]
    if unexpected:
        raise SystemExit("unexpected imports: " + ", ".join(unexpected))
    """
)
completed = subprocess.run(
    [sys.executable, "-c", script],
    cwd=Path(__file__).resolve().parents[1],
    capture_output=True,
    text=True,
    check=False,
)

self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
```

Add the inverse Phase 2 boundary check as a source-text assertion:

```python
source = Path("streamlit_app.py").read_text(encoding="utf-8")
self.assertIn("build_presentation_export", source)
self.assertIn("can_export_presentation", source)
self.assertIn("PPTX_MIME_TYPE", source)
self.assertNotIn("from pptx import", source)
self.assertNotIn("SlideDeckSpec", source)
self.assertNotIn("SlideSpec", source)
self.assertNotIn("validate_template", source)
```

**Failure patch pattern** (`evaluation/test_presentation_export.py` lines 346-355):

```python
def test_render_failure_returns_structured_unavailable_export(self) -> None:
    with patch("src.agent.presentation_export._render_presentation", side_effect=RuntimeError("boom")):
        export = build_presentation_export(record=valid_record())

    self.assert_unavailable_export(export, "render")
    self.assertIsNotNone(export.template_audit)
    self.assertIsNotNone(export.deck_spec)
```

For Streamlit helper tests, patch at the Streamlit import site:

```python
with patch("streamlit_app.build_presentation_export", return_value=fake_export):
    ...
```

---

### `evaluation/test_presentation_export.py` (test, file-I/O transform, optional modification)

**Analog:** Existing file, exact match.

If the planner colocates Phase 2 tests here, use the existing classes and fixture helpers. Do not weaken the backend tests by importing Streamlit unless the local runtime has Streamlit installed and the test remains deterministic.

**Existing eligibility test pattern** (`evaluation/test_presentation_export.py` lines 259-321):

```python
class PresentationExportEligibilityTests(unittest.TestCase):
    def assert_unavailable_export(self, export: object, expected_reason_part: str) -> None:
        self.assertFalse(export.available)
        self.assertEqual(export.content, b"")
        self.assertTrue(export.unavailable_reason)
        self.assertIn(expected_reason_part, export.unavailable_reason.lower())

    def test_ineligible_records_return_unavailable_without_pptx_bytes(self) -> None:
        cases = [
            (
                "failed_execution",
                {"execution_success": False},
                "execution",
            ),
            ...
        ]

        for name, overrides, expected_reason_part in cases:
            with self.subTest(name=name):
                export = build_presentation_export(record=orchestrator_record(**overrides))

                self.assert_unavailable_export(export, expected_reason_part)
```

Use this pattern for reason translation tests:

```python
cases = [
    ("record_missing", "No analysis record was found."),
    ("blocked_request", "This request was blocked for safety."),
    ("unknown_reason", "The backend exporter marked this run as unavailable."),
]
for reason, expected in cases:
    with self.subTest(reason=reason):
        self.assertEqual(format_presentation_unavailable_reason(reason), expected)
```

## Shared Patterns

### Streamlit State

**Source:** `streamlit_app.py` lines 265-282

**Apply to:** `streamlit_app.py`

Use `st.session_state.setdefault(...)` for new stable state. Do not store generated PPTX bytes in local variables only, because button-triggered reruns will lose them.

### Export Button Layout

**Source:** `streamlit_app.py` lines 1374-1398

**Apply to:** `streamlit_app.py`

Keep the export row directly under the dataframe and chart. Change two equal columns to three equal columns. Preserve existing CSV and Excel buttons and keys.

### Backend Export Boundary

**Source:** `src/agent/presentation_export.py` lines 163-230

**Apply to:** `streamlit_app.py`, `evaluation/test_streamlit_presentation_export.py`

Streamlit calls the backend and displays the result. It does not render, validate templates, inspect slide specs, or choose slide content.

### Eligibility And Reason Handling

**Source:** `src/agent/presentation_export.py` lines 226-230 and 654-681

**Apply to:** `streamlit_app.py`

Use `can_export_presentation(record)` for the eligibility decision. UI code may map reason strings to short copy, but it should not repeat the backend's boolean rules.

### Warning And Audit Display

**Source:** `streamlit_app.py` lines 254-262 and 293-300

**Apply to:** `streamlit_app.py`

Use captions, `st.warning`, `st.error`, and collapsed expanders. Keep backend audit details optional and compact.

### Test Fixtures

**Source:** `evaluation/test_presentation_export.py` lines 29-116

**Apply to:** `evaluation/test_streamlit_presentation_export.py`, optional additions to `evaluation/test_presentation_export.py`

Build realistic orchestrator records with `query_result`, `reporting_result`, `run_id`, SQL flags, and `source_tables`. This keeps UI tests aligned with backend eligibility.

### Boundary Tests

**Source:** `evaluation/test_presentation_export.py` lines 198-235

**Apply to:** `evaluation/test_streamlit_presentation_export.py`

Use source-text or subprocess checks for architectural boundaries. A simple source scan is acceptable for verifying Streamlit does not import PPTX renderer internals.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `evaluation/test_streamlit_presentation_export.py` | test | event-driven helper | No existing Streamlit-specific test module exists. Use `evaluation/test_presentation_export.py` fixtures and `evaluation/test_visualization_spec.py` pure helper style. |
| `streamlit_app.py` PPT create/download helper | component helper | event-driven, file download | Existing CSV/XLSX downloads are the layout analog, but no current helper stores generated binary export state across reruns. Use the UI spec state-key contract. |

## Explicit Non-Targets

| File | Reason |
|------|--------|
| `src/agent/presentation_export.py` | Backend exporter already owns eligibility, rendering, filename, MIME type, warnings, and unavailable reasons. Phase 2 should consume it, not move UI logic into it. |
| `requirements.txt` | `python-pptx` and `streamlit` are already present. No new package is recommended. |
| `assets/templates/PPT_Vorlage_Wuerth.pptx` | Static template asset. Do not modify during Streamlit integration. |

## Metadata

**Analog search scope:** `streamlit_app.py`, `src/agent/*.py`, `evaluation/test_*.py`, `requirements.txt`, phase research files

**Files scanned:** 9 Python candidates from `src/agent`, `streamlit_app.py`, and `evaluation`

**Analogs read:** `streamlit_app.py`, `src/agent/presentation_export.py`, `evaluation/test_presentation_export.py`, `evaluation/test_visualization_spec.py`

**Project skills:** No repo-local `.codex/skills/` or `.agents/skills/` directory found

**Pattern extraction date:** 2026-06-21
