# Phase 03: Readable Evidence And Fallback Slice - Pattern Map

**Mapped:** 2026-06-22
**Files analyzed:** 6
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/agent/presentation_planner.py` | service, utility | transform, optional request-response | `src/agent/reporting_agent.py`; `src/agent/visualization_spec.py`; `src/llm/model_adapter.py` | role-match |
| `src/agent/presentation_export.py` | service, exporter | file-I/O, transform | `src/agent/presentation_export.py` | exact |
| `streamlit_app.py` | component | event-driven, request-response | `streamlit_app.py`; `evaluation/test_streamlit_presentation_export.py` | exact, conditional |
| `evaluation/test_presentation_export.py` | test | file-I/O, transform | `evaluation/test_presentation_export.py` | exact |
| `evaluation/test_streamlit_presentation_export.py` | test | event-driven, request-response | `evaluation/test_streamlit_presentation_export.py` | exact, conditional |
| `.env.example` | config | configuration | `.env.example`; `src/llm/model_adapter.py` | exact |

Notes:

- `requirements.txt` should normally not change. Existing dependencies already include `python-pptx`, `matplotlib`, `pandas`, `anthropic`, and `langchain-anthropic`.
- `streamlit_app.py` should only change if new backend warning or unavailable reason copy is needed. Do not add PPT rendering, slide spec inspection, chart selection, or planner controls there.

## Pattern Assignments

### `src/agent/presentation_planner.py` (service, transform)

**Analogs:** `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, `src/agent/presentation_export.py`, `src/llm/model_adapter.py`

**Use this file for:** deterministic presentation profiling, German presentation plan generation, table page planning, top-N chart decisions, rich text span data, fallback metadata, and optional schema-constrained LLM planning.

**Imports and pure post-SQL boundary pattern**  
Source: `src/agent/reporting_agent.py` lines 1-9 and 22-40

```python
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

import pandas as pd

from src.agent.visualization_spec import build_visualization_spec


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

Planner copy rule:

- New planner functions should accept only already returned record fields: `user_question`, `final_sql`, `query_result`, `reporting_result`, `row_count`, `source_tables`, and existing chart/table metadata.
- The deterministic path must not call Streamlit, SQL execution, Databricks, PowerPoint, or a live model.

**Structured return pattern**  
Source: `src/agent/reporting_agent.py` lines 87-101

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

Planner copy rule:

- Return one validated, JSON-serializable plan object or frozen dataclass with explicit fields for title, language, executive bullets, emphasis spans, charts, tables, caveats, warnings, and audit metadata.
- Preserve SQL result order in table plans. Add page ranges and visible truncation notes before rendering.

**Frozen dataclass pattern for plan objects**  
Source: `src/agent/presentation_export.py` lines 85-102

```python
@dataclass(frozen=True)
class SlideSpec:
    slide_type: str
    layout_name: str
    title: str
    body: list[str] = field(default_factory=list)
    table_columns: list[str] = field(default_factory=list)
    table_rows: list[list[str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SlideDeckSpec:
    title: str
    slides: list[SlideSpec]
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
```

Planner copy rule:

- Use frozen dataclasses for `PresentationPlan`, `ExecutiveBullet`, `TextSpan`, `EvidenceChartPlan`, `EvidenceTablePage`, and `PlanningAudit`, or keep dictionaries only if validation remains explicit.
- If rich text is needed in `presentation_export.py`, extend the internal spec with a stable field such as `rich_body` rather than encoding bold markers inside strings.

**Column profiling and chart decision pattern**  
Source: `src/agent/visualization_spec.py` lines 82-99 and 354-383

```python
profiles = [_profile_column(column, chart_rows, index) for index, column in enumerate(columns)]
numeric_measures = [profile for profile in profiles if profile["kind"] == "numeric_measure"]
time_dimensions = [profile for profile in profiles if profile["kind"] == "date_or_time_dimension"]
categorical_dimensions = [
    profile
    for profile in profiles
    if profile["kind"] == "categorical_dimension" and int(profile["distinct_count"]) <= MAX_CATEGORICAL_VALUES
]
unsupported_dimensions = [
    profile
    for profile in profiles
    if profile["kind"] == "categorical_dimension" and int(profile["distinct_count"]) > MAX_CATEGORICAL_VALUES
]

def _profile_column(column: str, rows: list[Any], index: int) -> dict[str, Any]:
    values = [_row_value(row, column, index) for row in rows]
    non_null_values = [value for value in values if value is not None]
    distinct_values = {str(value) for value in non_null_values}
    normalized_name = _normalize_name(column)
```

Planner copy rule:

- Copy the profiling shape, but do not reuse the v1 Streamlit chart limits blindly. Phase 3 PPT evidence can support multiple categorical dimensions by selecting separate top-N evidence charts.
- For W05-like outputs, prefer `customer_material`, `shiptoparty`, and duplicate `order_number` evidence when present.

**Chart fallback object pattern**  
Source: `src/agent/visualization_spec.py` lines 206-229

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

Planner copy rule:

- Unsupported PPT chart shapes must return a German fallback reason and either a table plan or a limitation slide plan.
- The deck should still be created when a chart is unsupported.

**Top value profiling pattern for W05-like evidence**  
Source: `src/agent/presentation_export.py` lines 1034-1052

```python
def _result_profile(columns: list[str], rows: list[dict[str, str]]) -> dict[str, Any]:
    profile: dict[str, Any] = {"column_count": len(columns), "row_count_in_payload": len(rows)}
    for preferred_column in ("order_number", "shiptoparty", "customer_material"):
        if preferred_column not in columns:
            continue
        values = [row.get(preferred_column, "") for row in rows if row.get(preferred_column, "")]
        profile[f"distinct_{preferred_column}"] = len(set(values))
        profile[f"top_{preferred_column}_values"] = _top_values(values, limit=8)
    return profile


def _top_values(values: list[str], *, limit: int) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return [
        {"value": value, "count": count}
        for value, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]
```

Planner copy rule:

- Generalize this into deterministic profiles: distinct order numbers, returned exception rows, sum of `shipment_rows` where present, duplicate order counts, top `customer_material`, and top `shiptoparty`.
- For top-N categories, aggregate remaining categories into `Sonstige` when they exceed the chart budget.

**Optional LLM invocation pattern**  
Source: `src/llm/model_adapter.py` lines 113-133 and 136-169

```python
def invoke_model(
    prompt: str,
    model_name: str | None = None,
    *,
    provider: str | None = None,
    ollama_host: str | None = None,
) -> ModelResponse:
    selected_provider = get_provider(provider)
    selected_model = model_name or get_primary_model(selected_provider)
    llm = get_llm(selected_model, provider=selected_provider, ollama_host=ollama_host)
    raw_response = llm.invoke(prompt)
    response_text = _extract_response_text(raw_response)

    if not response_text:
        raise ModelAdapterError(f"Model '{selected_model}' returned an empty response.")

    return ModelResponse(
        model_name=selected_model,
        raw_response=raw_response,
        response_text=response_text,
    )
```

```python
for model_name in attempts:
    try:
        response = invoke_model(
            prompt,
            model_name=model_name,
            provider=selected_provider,
            ollama_host=ollama_host,
        )
        _validate_response_text(response.response_text, validation_fn)
        return ModelResponse(
            model_name=response.model_name,
            raw_response=response.raw_response,
            response_text=response.response_text,
            fallback_triggered=model_name != primary_model,
        )
    except Exception as error:
        errors.append(f"{model_name}: {error}")

raise ModelAdapterError("Both LLM attempts failed. " + " | ".join(errors))
```

Planner copy rule:

- If optional LLM planning is implemented, use a capped prompt and parse JSON into the same local `PresentationPlan` schema.
- Any exception, invalid JSON, invalid schema, timeout, missing key, or refused output must fall back to deterministic planning and add a warning.
- Do not use the direct Claude PPTX Skill path for Phase 3 planning.

---

### `src/agent/presentation_export.py` (service, file-I/O + transform)

**Analog:** `src/agent/presentation_export.py`

**Use this file for:** converting a validated presentation plan into `SlideDeckSpec`, validating slide specs, rendering PPTX bytes, handling template audits, inserting images/tables, and returning `PresentationExport`.

**Imports, asset path, and constants pattern**  
Source: `src/agent/presentation_export.py` lines 1-21 and 38-43

```python
from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx import Presentation
from pptx.util import Inches, Pt

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "assets" / "templates" / "PPT_Vorlage_Wuerth.pptx"

MAX_TABLE_ROWS_PER_SLIDE = 10
MAX_TABLE_COLUMNS_PER_SLIDE = 5
MAX_BODY_ITEMS_PER_SLIDE = 8
MAX_BODY_TEXT_CHARS_PER_SLIDE = 700
FIXED_PPTX_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
```

Exporter copy rule:

- Keep the Wuerth template path resolved from `PROJECT_ROOT`. Do not hardcode local absolute paths.
- New chart and text budgets belong here or in the planner module, not in Streamlit.

**Export orchestration and structured error pattern**  
Source: `src/agent/presentation_export.py` lines 226-273

```python
def build_deterministic_presentation_export(
    *,
    record: dict[str, Any],
    include_closing: bool = False,
    template_path: Path | str = DEFAULT_TEMPLATE_PATH,
) -> PresentationExport:
    """Build deterministic PPTX bytes with the local python-pptx renderer."""

    eligibility = can_export_presentation(record)
    if not eligibility.can_export:
        return _unavailable_export(eligibility.reason)

    try:
        deck_spec = build_slide_deck_spec(record=record, include_closing=include_closing)
    except PresentationExportError as error:
        return _unavailable_export(str(error))

    spec_errors = validate_slide_deck_spec(deck_spec)
    if spec_errors:
        return _unavailable_export("slide_spec_invalid", warnings=spec_errors, deck_spec=deck_spec)

    audit = validate_template(template_path=template_path)
    if audit.errors:
        return _unavailable_export(
            "template_invalid",
            warnings=[*audit.warnings, *audit.errors],
            template_audit=audit,
            deck_spec=deck_spec,
        )

    try:
        content = _render_presentation(
            deck_spec=deck_spec,
            template_path=Path(template_path),
        )
        reopened = Presentation(BytesIO(content))
    except Exception as error:
        return _unavailable_export(
            "render_failed",
            warnings=[f"PPTX rendering failed: {type(error).__name__}."],
            template_audit=audit,
            deck_spec=deck_spec,
        )

    warnings = [*deck_spec.warnings, *audit.warnings]
    return PresentationExport(
        available=True,
        content=content,
```

Exporter copy rule:

- Insert presentation planning before `build_slide_deck_spec()` creates slides, or make `build_slide_deck_spec()` call the planner internally.
- Keep eligibility, spec validation, template validation, render, reopen, and warning collection in this order.

**Dynamic slide spec construction pattern**  
Source: `src/agent/presentation_export.py` lines 384-476 and 477-557

```python
def build_slide_deck_spec(
    *,
    record: dict[str, Any],
    include_closing: bool = False,
) -> SlideDeckSpec:
    """Build an ordered, dynamic slide spec from a successful record."""

    eligibility = can_export_presentation(record)
    if not eligibility.can_export:
        raise PresentationExportError(eligibility.reason)

    reporting = _dict_or_empty(record.get("reporting_result"))
    query = _dict_or_empty(record.get("query_result"))
    source_tables = _string_list(record.get("source_tables"))
    title = _deck_title(record)
    footer_source = title
    warnings: list[str] = []

    slides: list[SlideSpec] = [
        SlideSpec(
            slide_type="cover",
            layout_name=LAYOUT_COVER,
            title=title,
            body=[
                _cover_subtitle(record, reporting),
            ],
            metadata={
                "run_id": str(record.get("run_id", "")),
                "footer_author": "Logistics Agent",
                "footer_date": _display_date(record),
                "footer_source": footer_source,
            },
        )
    ]
```

```python
table_columns, table_rows, table_warnings = _table_content(query)
warnings.extend(table_warnings)
if table_columns and table_rows:
    evidence_rows = table_rows[:MAX_EVIDENCE_ROWS]
    slides.append(
        SlideSpec(
            slide_type="table_evidence",
            layout_name=LAYOUT_TABLE,
            title="Evidence Table",
            body=[
                "Compact sample from the validated SQL result.",
                f"Showing {len(evidence_rows)} of {_effective_row_count(record, query, list(query.get('rows', []) or []))} returned rows.",
            ],
            table_columns=table_columns,
            table_rows=evidence_rows,
            metadata={
                "section_label": "VALIDATED SQL SAMPLE",
                "footer_source": footer_source,
                "footer_date": _display_date(record),
            },
        )
    )
```

Exporter copy rule:

- Keep dynamic slide inclusion. Do not produce a fixed 9-slide deck.
- Replace raw reporting-driven titles/body with `PresentationPlan` fields.
- Germanize visible slide titles and labels, for example `Management-Zusammenfassung`, `Kennzahlen`, `Evidenz`, `Datenbasis und Grenzen`, `Anhang`.
- Move evidence tables later than management summary and chart/insight slides.

**Spec validation pattern**  
Source: `src/agent/presentation_export.py` lines 559-636

```python
def validate_slide_deck_spec(
    deck_spec: SlideDeckSpec,
    *,
    manifest: TemplateManifest = DEFAULT_TEMPLATE_MANIFEST,
) -> list[str]:
    errors: list[str] = []
    allowed_layouts = set(manifest.required_layouts) | set(manifest.optional_layouts)
    repeatable_layouts = {LAYOUT_CHART, LAYOUT_TABLE}

    if not deck_spec.slides:
        errors.append("Slide deck spec must contain at least one slide.")
        return errors

    if deck_spec.slides[0].layout_name != LAYOUT_COVER:
        errors.append("First slide must use Agent 01 Cover.")

    for index, slide in enumerate(deck_spec.slides, start=1):
        if len(slide.title) > 140:
            errors.append(f"Slide {index} title exceeds text budget.")
        body_text_size = sum(len(item) for item in slide.body)
        if body_text_size > MAX_BODY_TEXT_CHARS_PER_SLIDE:
            errors.append(f"Slide {index} body exceeds text budget.")
        if len(slide.table_rows) > MAX_TABLE_ROWS_PER_SLIDE:
            errors.append(f"Slide {index} table exceeds row limit.")
        if len(slide.table_columns) > MAX_TABLE_COLUMNS_PER_SLIDE:
            errors.append(f"Slide {index} table exceeds column limit.")
```

Exporter copy rule:

- Extend validation to check placeholder-specific budgets from the plan: cover title, subtitle, executive bullets, chart labels, table notes, appendix metadata.
- If rich text spans are added, validate that span text joins back to the displayed bullet and that no span exceeds the bullet text.

**Template safety pattern**  
Source: `src/agent/presentation_export.py` lines 638-714

```python
def validate_template(
    *,
    template_path: Path | str = DEFAULT_TEMPLATE_PATH,
    manifest: TemplateManifest = DEFAULT_TEMPLATE_MANIFEST,
) -> TemplateAudit:
    path = Path(template_path)
    safe_path = _safe_path(path)
    if not path.exists():
        return TemplateAudit(
            available=False,
            template_path=safe_path,
            errors=[f"Template file is missing: {safe_path}."],
        )

    warnings: list[str] = []
    errors: list[str] = []
    ole_entries: list[str] = []
    macro_entries: list[str] = []
    external_relationships: list[str] = []

    try:
        digest = sha256(path.read_bytes()).hexdigest().upper()
    except OSError as error:
        return TemplateAudit(
            available=False,
            template_path=safe_path,
            errors=[f"Template file is not readable: {type(error).__name__}."],
        )
```

Exporter copy rule:

- Reuse this unchanged for Phase 3 unless template placeholders changed.
- OLE warnings stay non-blocking. Macros, ActiveX, and external relationships stay blocking.

**Rendering dispatch and deterministic bytes pattern**  
Source: `src/agent/presentation_export.py` lines 1121-1163

```python
def _render_presentation(*, deck_spec: SlideDeckSpec, template_path: Path) -> bytes:
    presentation = Presentation(str(template_path))
    if not presentation.slides:
        cover_slide = presentation.slides.add_slide(_layout_by_name(presentation, LAYOUT_COVER))
    else:
        cover_slide = presentation.slides[0]

    _render_slide(cover_slide, deck_spec.slides[0], slide_number=1, deck_title=deck_spec.title)
    for slide_number, slide_spec in enumerate(deck_spec.slides[1:], start=2):
        slide = presentation.slides.add_slide(_layout_by_name(presentation, slide_spec.layout_name))
        _render_slide(slide, slide_spec, slide_number=slide_number, deck_title=deck_spec.title)

    output = BytesIO()
    presentation.save(output)
    return _normalize_pptx_package(output.getvalue())
```

Exporter copy rule:

- Preserve deterministic package normalization. Tests assert repeatable bytes and fixed timestamps.

**Content shape replacement pitfall**  
Source: `src/agent/presentation_export.py` lines 1194-1207

```python
def _render_content_slide(slide: Any, slide_spec: SlideSpec) -> None:
    _render_common_header(slide, slide_spec)
    content_shape = _shape_by_name(slide, "content") or _shape_by_name(slide, "body")
    if content_shape is None:
        return
    if slide_spec.slide_type == "chart_evidence":
        chart_image = _chart_image(slide_spec)
        if chart_image is not None:
            _replace_shape_with_picture(slide, content_shape, chart_image)
            return
    if slide_spec.table_rows:
        _replace_shape_with_table(slide, content_shape, slide_spec.table_columns, slide_spec.table_rows)
        return
    _set_shape_bullets(content_shape, slide_spec.body, font_size=18)
```

Exporter copy rule:

- This currently drops table body text when a table is rendered. Phase 3 must render visible table notes separately, for example a caption textbox or footer note, so `Zeilen 1-10 von 50` and `Weitere Spalten ausgeblendet` are inside the PPTX.

**Text helper and rich text change point**  
Source: `src/agent/presentation_export.py` lines 1334-1368

```python
def _set_shape_text(
    shape: Any,
    text: str,
    *,
    font_size: int,
    bold: bool = False,
    center: bool = False,
    color: RGBColor | None = None,
) -> None:
    if not getattr(shape, "has_text_frame", False):
        return
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.TOP
    paragraph = frame.paragraphs[0]
    paragraph.text = _trim_text(text, 350)
    paragraph.alignment = PP_ALIGN.CENTER if center else PP_ALIGN.LEFT
    for run in paragraph.runs:
        run.font.size = Pt(font_size)
        run.font.bold = bold
```

Exporter copy rule:

- For executive summary emphasis, add a separate rich text helper that clears the frame, creates paragraphs, then uses `paragraph.add_run()` per span and sets `run.font.bold` per span.
- Do not try to bold substrings after assigning `paragraph.text`; build the runs explicitly.

**Table and chart image patterns**  
Source: `src/agent/presentation_export.py` lines 1377-1467

```python
def _replace_shape_with_table(slide: Any, shape: Any, columns: list[str], rows: list[list[str]]) -> None:
    bounds = (shape.left, shape.top, shape.width, shape.height)
    _remove_shape(shape)
    _add_table(slide, bounds=bounds, columns=columns[:MAX_EVIDENCE_COLUMNS], rows=rows[:MAX_EVIDENCE_ROWS])


def _add_table(
    slide: Any,
    *,
    bounds: tuple[int, int, int, int],
    columns: list[str],
    rows: list[list[str]],
) -> None:
    if not columns or not rows:
        return
    left, top, width, height = bounds
    visible_rows = rows[:MAX_EVIDENCE_ROWS]
    shape = slide.shapes.add_table(len(visible_rows) + 1, len(columns), left, top, width, height)
```

```python
def _chart_image(slide_spec: SlideSpec) -> BytesIO | None:
    if not slide_spec.table_columns or not slide_spec.table_rows:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    fig, ax = plt.subplots(figsize=(10.5, 4.4), dpi=160)
    chart_type = slide_spec.metadata.get("chart_type", "bar")
    if chart_type == "line":
        ax.plot(x_values, y_values, color="#D00000", linewidth=2.5, marker="o")
    else:
        ax.bar(x_values, y_values, color="#D00000")
    fig.tight_layout()
    output = BytesIO()
    fig.savefig(output, format="png", transparent=False, bbox_inches="tight")
```

Exporter copy rule:

- Add horizontal bar support for PPT top-N charts, probably with `ax.barh(...)`, inverted y-axis, label truncation, and larger left margin.
- Keep chart rendering local and deterministic. If matplotlib is unavailable, add a warning and fall back to a table or limitation slide.

**Current pitfalls to fix in this file**

| Pitfall | Evidence | Phase 3 Pattern |
|---------|----------|-----------------|
| Cover title uses raw question | `_deck_title()` trims `user_question`, lines 1721-1725 | Derive short German title before rendering. |
| English slide labels | `Executive Summary`, `Result Snapshot`, `Evidence Table`, lines 425, 441, 485 | Use German labels from plan. |
| Table body is dropped | `_render_content_slide()` returns after table replacement, lines 1204-1206 | Render visible page and truncation notes outside the table shape. |
| Vertical bars only | `_chart_image()` uses `ax.bar(...)`, line 1454 | Use horizontal top-N bars for long categorical labels. |
| Direct Claude PPTX path exists | `PRESENTATION_EXPORT_MODE=claude`, lines 193-219 | Do not expand it for Phase 3. Optional LLM only returns validated planning JSON. |

---

### `streamlit_app.py` (component, event-driven request-response)

**Analog:** `streamlit_app.py`

**Use this file for:** thin create/download UX only. Surface `PresentationExport.warnings` and `unavailable_reason`. Do not inspect or mutate slide specs.

**Allowed imports pattern**  
Source: `streamlit_app.py` lines 30-34

```python
from src.agent.presentation_export import (
    PPTX_MIME_TYPE,
    build_presentation_export,
    can_export_presentation,
)
```

Streamlit copy rule:

- If `streamlit_app.py` changes, keep this import list limited to public export symbols.
- Do not import `pptx`, `Presentation`, `SlideSpec`, `SlideDeckSpec`, planner dataclasses, or render helpers.

**Session-state key pattern**  
Source: `streamlit_app.py` lines 120-150

```python
def presentation_export_key(
    record: dict,
    index: int,
    *,
    active_chat_id: str | None = None,
) -> str:
    chat_id = active_chat_id or st.session_state.get("active_chat_id", "chat")
    record_id = record.get("run_id") or index
    return f"ppt_export_{chat_id}_{record_id}"


def presentation_exports_state(session_state: dict | None = None) -> dict:
    state = session_state if session_state is not None else st.session_state
    exports = state.setdefault("presentation_exports", {})
    if not isinstance(exports, dict):
        exports = {}
        state["presentation_exports"] = exports
    return exports
```

**Warning and failure display pattern**  
Source: `streamlit_app.py` lines 340-431

```python
def render_presentation_export_feedback(export: object, container=st) -> None:
    warnings = _presentation_export_warnings(export)
    slide_count = int(getattr(export, "slide_count", 0) or 0)
    if warnings:
        container.warning("PPT created with warnings.")
        if slide_count:
            container.caption(f"Slides: {slide_count}")
        with container.expander("PPT warnings", expanded=False):
            for warning in warnings:
                st.write(warning)
        return
    container.caption("PPT ready.")
```

```python
if clicked:
    with st.spinner("Creating PPT..."):
        export = build_presentation_export(record=record, include_closing=False)
    exports[export_key] = export

if getattr(export, "available", False):
    control_slot.download_button(
        "Download PPT",
        data=export.content,
        file_name=export.filename,
        mime=export.mime_type or PPTX_MIME_TYPE,
        key=download_key,
        type="primary",
        use_container_width=True,
    )
```

Streamlit copy rule:

- Planner fallback and truncation warnings should flow through `export.warnings`.
- Do not add slide-builder controls. No chart type selector, slide order selector, or preview controls in Phase 3.

**Export placement pattern**  
Source: `streamlit_app.py` lines 1537-1582

```python
if rows and columns:
    st.subheader("Ergebnisvorschau")
    df = result_to_dataframe(record)
    st.dataframe(df, use_container_width=True)
    render_chart_from_spec(record, df)

    col_csv, col_xlsx, col_ppt = st.columns(3)
    csv_data = df.to_csv(index=False).encode("utf-8")
    col_csv.download_button(
        "Als CSV exportieren",
        data=csv_data,
        file_name=f"ergebnis_{record.get('run_id', index)}.csv",
        mime="text/csv",
        key=f"export_csv_{index}",
        use_container_width=True,
    )
    render_presentation_export_controls(record, index, col_ppt)
else:
    render_presentation_unavailable_compact(record)
```

Streamlit copy rule:

- Keep PPT controls next to CSV/XLSX exports.
- Keep one-click `Create PPT`, then `Download PPT`.

---

### `evaluation/test_presentation_export.py` (test, file-I/O + transform)

**Analog:** `evaluation/test_presentation_export.py`

**Use this file for:** deterministic planner tests, exporter rendering tests, PPTX reopenability, text/table/image inspection, warning propagation, and invalid spec validation.

**Fixture pattern**  
Source: `evaluation/test_presentation_export.py` lines 1-120

```python
from __future__ import annotations

from io import BytesIO
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
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
    build_deterministic_presentation_export,
    build_presentation_export,
    build_slide_deck_spec,
    validate_slide_deck_spec,
    validate_template,
)


def query_result(columns: list[str], rows: list[tuple[object, ...]]) -> dict[str, object]:
    return {"columns": columns, "rows": rows, "row_count": len(rows)}
```

Test copy rule:

- Add W05 fixture helpers next to these helpers. Include rows with `order_number`, `shiptoparty`, `customer_material`, and `shipment_rows`.
- Keep fake records as plain dictionaries matching backend eligibility.

**PPTX reopenability and deterministic bytes pattern**  
Source: `evaluation/test_presentation_export.py` lines 213-244

```python
def test_generated_pptx_bytes_reopen_without_powerpoint(self) -> None:
    export = build_deterministic_presentation_export(record=valid_record())

    presentation = Presentation(BytesIO(export.content))

    self.assertEqual(len(presentation.slides), export.slide_count)
    self.assertGreater(len(presentation.slides), 1)


def test_successful_record_produces_repeatable_pptx_bytes(self) -> None:
    first = build_deterministic_presentation_export(record=valid_record())
    second = build_deterministic_presentation_export(record=valid_record())

    self.assertTrue(first.available)
    self.assertTrue(second.available)
    self.assertEqual(first.content, second.content)
    with zipfile.ZipFile(BytesIO(first.content)) as package:
        self.assertEqual(package.namelist(), sorted(package.namelist()))
        self.assertTrue(
            all(info.date_time == FIXED_PPTX_TIMESTAMP for info in package.infolist())
        )
```

Test copy rule:

- Every rendering change should preserve reopenability and deterministic bytes unless a deliberate nondeterministic artifact is introduced. If chart images include metadata timestamps, normalize or test around them.

**Text, table, and boundary inspection pattern**  
Source: `evaluation/test_presentation_export.py` lines 246-275 and 320-363

```python
presentation = Presentation(BytesIO(export.content))
text_values: list[str] = []
has_table = False
for slide in presentation.slides:
    for shape in slide.shapes:
        if getattr(shape, "has_text_frame", False):
            text_values.append(shape.text)
        if getattr(shape, "has_table", False):
            has_table = True

rendered_text = "\n".join(text_values)
self.assertIn("Executive Summary", rendered_text)
self.assertTrue(has_table)
```

```python
completed = subprocess.run(
    [sys.executable, "-c", script],
    cwd=Path(__file__).resolve().parents[1],
    capture_output=True,
    text=True,
    check=False,
)

self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
```

Test copy rule:

- Add tests that reopened PPTX text contains German slide copy and does not contain the full raw user question on the cover.
- Add tests that reopened PPTX text contains visible table notes such as `Zeilen 1-10 von 50` and `Weitere Spalten ausgeblendet`.
- Add subprocess boundary tests for `presentation_planner.py` and `presentation_export.py` to ensure neither imports Streamlit.

**Validation and failure pattern**  
Source: `evaluation/test_presentation_export.py` lines 454-554 and 611-729

```python
cases = [
    (
        "failed_execution",
        {"execution_success": False},
        "execution",
    ),
    (
        "failed_validation",
        {"validation_success": False, "sql_valid": True},
        "validation",
    ),
    (
        "zero_row_count",
        {
            "query_result": {
                "columns": ["region", "shipment_count"],
                "rows": [("Sued", 90)],
                "row_count": 0,
            },
            "row_count": 0,
        },
        "row",
    ),
]
```

```python
(
    "table_row_limit",
    SlideDeckSpec(
        title="Deck",
        slides=[
            SlideSpec(
                slide_type="table_evidence",
                layout_name="agent_05_full_content",
                title="Table",
                table_columns=["region"],
                table_rows=[["Sued"]] * 11,
            )
        ],
    ),
    "row limit",
),
```

Test copy rule:

- Add focused tests for long title shortening, overflow budget rejection, unsupported chart fallback, empty result behavior, table row and column truncation, and planner fallback warnings.
- Add a rich text test by iterating `shape.text_frame.paragraphs` and `paragraph.runs`, then asserting at least one important number or phrase has `run.font.bold`.

---

### `evaluation/test_streamlit_presentation_export.py` (test, event-driven request-response)

**Analog:** `evaluation/test_streamlit_presentation_export.py`

**Use this file for:** protecting the Streamlit boundary if `streamlit_app.py` changes.

**Fake module loading pattern**  
Source: `evaluation/test_streamlit_presentation_export.py` lines 117-205

```python
def _load_streamlit_app() -> types.ModuleType:
    fake_streamlit = _module("streamlit", session_state=_SessionState())
    fake_pandas = _module("pandas", DataFrame=object)
    fake_altair = _module("altair")
    fake_yaml = _module("yaml")
    fake_db = _module("src.agent.db", get_active_backend_metadata=lambda: {})
    fake_golden = _module(
        "src.agent.golden_test_runner",
        load_golden_questions=lambda: [],
        run_golden_tests=lambda *args, **kwargs: [],
    )

    fake_presentation_export = _module(
        "src.agent.presentation_export",
        PPTX_MIME_TYPE="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        build_presentation_export=lambda **kwargs: types.SimpleNamespace(
            available=True,
            content=b"pptx",
            filename="wuerth_logistics_run.pptx",
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            slide_count=5,
            warnings=[],
            unavailable_reason="",
        ),
        can_export_presentation=lambda record: types.SimpleNamespace(can_export=True, reason=""),
    )
```

**AST boundary and interaction pattern**  
Source: `evaluation/test_streamlit_presentation_export.py` lines 389-496 and 498-602

```python
def test_streamlit_imports_only_allowed_backend_export_symbols(self) -> None:
    source = STREAMLIT_APP_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    forbidden_module_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "src.agent.presentation_export":
            imported.update(alias.name for alias in node.names)

    self.assertEqual(
        imported,
        {"PPTX_MIME_TYPE", "build_presentation_export", "can_export_presentation"},
    )
```

```python
def test_streamlit_does_not_expose_slide_or_renderer_controls(self) -> None:
    source = STREAMLIT_APP_PATH.read_text(encoding="utf-8")
    forbidden_fragments = {
        "from pptx import",
        "Presentation(",
        "SlideDeckSpec",
        "SlideSpec",
        "PresentationExport",
        "validate_template",
        "validate_slide_deck_spec",
        "build_slide_deck_spec",
        "_render_presentation",
        "deck_spec",
        "include_closing=True",
        "slide_order",
        "slide preview",
        "chart type",
    }
```

```python
build_export.assert_called_once_with(record=record, include_closing=False)
self.assertIs(app.st.session_state["presentation_exports"]["ppt_export_chat-a_run-2"], export)
self.assertEqual(container.spinner_labels, ["Creating PPT..."])
self.assertEqual(container.downloads[0]["label"], "Download PPT")
self.assertEqual(container.downloads[0]["data"], b"created-pptx")
```

Test copy rule:

- If `streamlit_app.py` is untouched, do not add Phase 3 tests here.
- If warning copy or reason copy changes, extend these tests while keeping the same fake runtime pattern.

---

### `.env.example` (config)

**Analog:** `.env.example`

**Use this file for:** documenting non-secret planner toggles only if optional LLM planning or planner caps are implemented.

**Existing PowerPoint config pattern**  
Source: `.env.example` lines 14-19

```dotenv
# PowerPoint export. Set to "claude" only for explicit Claude PowerPoint Skill tests.
PRESENTATION_EXPORT_MODE=deterministic
ANTHROPIC_PRESENTATION_MODEL=claude-opus-4-8
ANTHROPIC_PRESENTATION_MAX_TOKENS=16000
ANTHROPIC_PRESENTATION_TIMEOUT_SECONDS=480
PRESENTATION_MAX_ROWS_FOR_CLAUDE=80
```

Config copy rule:

- Add new planner config next to this block if needed:

```dotenv
PRESENTATION_PLANNING_MODE=deterministic
PRESENTATION_PLANNING_MODEL=claude-sonnet-4-6
PRESENTATION_PLANNING_TIMEOUT_SECONDS=30
PRESENTATION_PLANNING_MAX_ROWS=50
PRESENTATION_PLANNING_MAX_TOKENS=2048
```

- Do not add secrets. Use existing `ANTHROPIC_API_KEY` only if LLM planning is explicitly enabled.
- Keep `PRESENTATION_EXPORT_MODE=deterministic` as the recommended default.

## Shared Patterns

### Backend Boundary

**Source:** `evaluation/test_presentation_export.py` lines 320-363 and `evaluation/test_streamlit_presentation_export.py` lines 476-496  
**Apply to:** `src/agent/presentation_planner.py`, `src/agent/presentation_export.py`, `streamlit_app.py`

Pattern:

- Planner/exporter modules must be importable without Streamlit.
- Streamlit must not import PPTX renderer internals.
- Tests should enforce this with subprocess and AST checks.

### Eligibility Before Rendering

**Source:** `src/agent/presentation_export.py` lines 1499-1545  
**Apply to:** all export paths

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
```

Pattern:

- Keep PowerPoint export available only for successful, validated runs with rows and columns.
- If Phase 3 chooses to support zero-row limitation decks, make that an explicit product decision and update eligibility tests.

### German Copy

**Source:** `src/agent/reporting_agent.py` lines 195-247 and `evaluation/test_presentation_export.py` lines 44-49  
**Apply to:** planner and exporter visible text

Pattern:

- Use concise German labels and management copy in generated decks.
- Tests can use ASCII transliterations where useful, but visible deck copy should be German.
- Avoid raw table explanations as executive summary text.

### Table Truncation

**Source:** `src/agent/presentation_export.py` lines 1643-1658 and 1194-1207  
**Apply to:** planner table pages, exporter table slides, tests

Pattern:

- Preserve SQL result order.
- Cap rows and columns per slide.
- Make truncation visible inside the deck, not only in `export.warnings`.
- Use German notes such as `Zeilen 1-10 von 50`, `Weitere Zeilen im Ergebnis`, and `Weitere Spalten ausgeblendet`.

### Top-N Evidence Charts

**Source:** `src/agent/visualization_spec.py` lines 317-351 and `src/agent/presentation_export.py` lines 1431-1467  
**Apply to:** planner chart decisions and exporter image rendering

Pattern:

- For categorical logistics evidence, choose horizontal top-N bars by default.
- Sort deterministically by count or metric descending, then label ascending for ties.
- Cap label count and label length. Aggregate the remainder as `Sonstige`.
- If chart rendering fails or shape is unsupported, create a table or limitation slide with a German reason.

### Rich Text

**Source:** `src/agent/presentation_export.py` lines 1334-1368  
**Apply to:** executive summary slide rendering and tests

Pattern:

- Current helpers set whole-paragraph bold. Add a run-based helper for emphasized spans.
- Tests should reopen the PPTX and inspect `run.font.bold`.
- Bold only key numbers, severity labels, primary finding labels, and short action phrases.

### Optional LLM Planning

**Source:** `src/llm/model_adapter.py` lines 113-169 and `src/agent/presentation_export.py` lines 920-971  
**Apply to:** optional planning mode only

Pattern:

- Send only capped, sanitized context: question, SQL, reporting metadata, result sample, column profiles, and precomputed aggregates.
- Locally validate returned JSON into `PresentationPlan`.
- Deterministic fallback must create a usable deck on every invalid, slow, unavailable, or costly planner outcome.
- Do not upload templates or ask an LLM to create `.pptx` files in Phase 3.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| none | n/a | n/a | All Phase 3 file-level changes have close local analogs. Optional schema-constrained LLM planning has no exact implementation, but `src/llm/model_adapter.py` provides invocation and fallback patterns. |

## Compatibility Pitfalls

| Area | Pitfall | Source |
|------|---------|--------|
| Cover title | `_deck_title()` currently uses raw `user_question`, which caused overflow. | `src/agent/presentation_export.py` lines 1721-1725 |
| Table notes | `_render_content_slide()` replaces content with a table and returns, so body notes disappear. | `src/agent/presentation_export.py` lines 1194-1207 |
| Existing chart renderer | `_chart_image()` supports bar/line only and uses vertical bars by default. | `src/agent/presentation_export.py` lines 1431-1467 |
| Streamlit boundary | Existing tests forbid renderer internals in Streamlit. | `evaluation/test_streamlit_presentation_export.py` lines 476-496 |
| Legacy Claude PPTX mode | Existing direct PPTX generation path is not the Phase 3 strategy. | `src/agent/presentation_export.py` lines 193-219; `.env.example` lines 14-19 |
| Test environment | Current tests reopen PPTX bytes with `python-pptx`, not PowerPoint. | `evaluation/test_presentation_export.py` lines 225-231 |

## Metadata

**Analog search scope:** `src/agent/`, `src/llm/`, `streamlit_app.py`, `evaluation/`, `.env.example`, `requirements.txt`, `evaluation/wuerth_local/solution_sql/`

**Files scanned:** 13 primary files and phase artifacts

**Pattern extraction date:** 2026-06-22

**Project skills:** No repo-local `.codex/skills/` or `.agents/skills/` directories found.
