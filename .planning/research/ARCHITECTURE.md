# Architecture Research: PowerPoint Export And Rich Visualization

**Project:** Wuerth Logistics Agent PowerPoint export
**Domain:** Streamlit and LangGraph logistics analysis app
**Researched:** 2026-06-21
**Overall confidence:** HIGH for repo boundaries, MEDIUM for PPTX rendering details until the template layouts are inspected in implementation

## Executive Recommendation

PowerPoint export should be a deterministic post-processing layer that starts after the existing orchestrator has produced a successful record. Do not put PPTX generation into `streamlit_app.py`, `src/agent/router.py`, `src/agent/langgraph_sql_agent.py`, or any backend adapter. The right primary module is `src/agent/presentation_export.py`, with template path constants in that same module for the first implementation.

The exporter should consume the existing output record shape: `query_result`, `reporting_result`, `chart_spec`, `final_sql`, `source_tables`, `run_id`, and `user_question`. This keeps export independent from SQL generation and database execution. The exporter must not import `src.agent.langgraph_sql_agent`, `src.agent.db`, or `src.agent.sql_validator`. It only needs pandas-style result shaping, `python-pptx`, and local file/path helpers.

Claude Opus should not render PowerPoint files. For the first export version, Claude Opus should not generate slide specs either, because `src/agent/reporting_agent.py` already creates deterministic summaries, KPI cards, caveats, table plans, chart plans, and audit metadata. If later phases need more narrative slide copy, use Claude Opus only to produce a constrained JSON `SlideSpec` after reporting, validate that JSON, and still render PPTX deterministically in `src/agent/presentation_export.py`.

`streamlit_app.py` should expose export as a thin download action in `render_record()`: check that the record is exportable, call one backend function, then pass returned bytes to `st.download_button`. Memory retrieval logs, RBAC, and final docs should also move behind backend/service modules so `streamlit_app.py` remains a UI shell rather than the place where governance, logging, and export logic accumulate.

## Current Architecture Signals

The current primary flow is already suitable for PPT export:

```text
`streamlit_app.py`
  -> `src/agent/orchestrator.py`
  -> `src/agent/router.py`
  -> `src/agent/langgraph_sql_agent.py`
  -> `src/agent/reporting_agent.py`
  -> `src/agent/visualization_spec.py`
  -> Streamlit table/chart/CSV/XLSX rendering
```

The key existing result artifacts are:

| Artifact | Produced By | Current Use | PPT Export Use |
|----------|-------------|-------------|----------------|
| `query_result` | `src/agent/langgraph_sql_agent.py` via `src/agent/orchestrator.py` | DataFrame preview, CSV/XLSX export | Table slide data and chart data |
| `reporting_result` | `src/agent/reporting_agent.py` | Management summary, KPI cards, audit | Title/summary slide, KPI slide, caveats, audit appendix |
| `chart_spec` | `src/agent/orchestrator.py` alias of `reporting_result["chart_plan"]` | Streamlit Altair chart | Chart slide rendering plan |
| `final_sql` | SQL agent | SQL display and logs | Appendix or speaker-note style audit content |
| `source_tables` | SQL agent and validator path | UI source table display | Source attribution and audit slide |

The existing docs in `.planning/codebase/ARCHITECTURE.md` and `.planning/codebase/STRUCTURE.md` already call out `src/agent/presentation_export.py` as the intended place for PowerPoint generation. Use that path.

## Recommended Architecture

```text
Successful orchestrator record
  query_result
  reporting_result
  chart_spec
  final_sql
  source_tables
  run_id
  user_question
        |
        v
`src/agent/presentation_export.py`
  validate exportability
  normalize record to `PresentationInput`
  build deterministic `SlideSpec` list
  render `.pptx` from Wuerth template
  return `PresentationExport`
        |
        v
`streamlit_app.py`
  show download button
  no template logic
  no slide layout logic
  no SQL or memory logic
```

### Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| `src/agent/presentation_export.py` | Own PPT template path constants, exportability checks, slide spec construction, deterministic PPTX rendering, filename generation, and renderer errors. | Consumes dictionaries from orchestrator records; reads `assets/templates/PPT_Vorlage_Wuerth.pptx`; returns bytes/metadata to UI. |
| `src/agent/reporting_agent.py` | Keep deterministic management summary, KPI cards, caveats, table plan, chart plan, and audit. | Feeds `reporting_result` into the exporter. |
| `src/agent/visualization_spec.py` | Keep deterministic chart spec selection from already returned data. Extend here for richer chart types. | Feeds `chart_spec` into Streamlit and PPT renderers. |
| `streamlit_app.py` | Add a small export button area in `render_record()`. | Calls `can_export_presentation(record)` and `build_presentation_export(record)`. |
| `src/agent/memory_retriever.py` | Retrieve approved active templates and log retrieval usage. | Called by SQL agent, not by Streamlit export. |
| `src/agent/memory_service.py` | New service boundary for memory actions with RBAC enforcement. | UI calls this instead of direct store writes. |
| `src/agent/memory_rbac.py` | New role/action matrix for Viewer, Contributor, Reviewer, and Admin. | Used by `memory_service.py` and tested without Streamlit. |
| `src/agent/logging_utils.py` | Own structured CSV log helpers. | Add memory retrieval and PPT export log helpers here. |

## PPTX Module Placement

Use one focused module first:

```text
`src/agent/presentation_export.py`
```

Put these constants there:

```python
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PPTX_TEMPLATE_PATH = PROJECT_ROOT / "assets" / "templates" / "PPT_Vorlage_Wuerth.pptx"
PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
DEFAULT_PRESENTATION_BASENAME = "wuerth_logistics_analysis"
```

Rationale:

- The template path is an export concern, not UI state and not scenario config.
- The path must be repo-relative. Never use Leon's local source path from the original template copy.
- Keeping constants with the exporter makes tests straightforward: override `template_path` in `build_presentation_export()`.
- If the module grows beyond one file, split later into `src/agent/presentation_spec.py` and `src/agent/pptx_renderer.py`. Do not start with that split unless the template layout mapping becomes large.

Recommended public API:

```python
def can_export_presentation(record: dict[str, Any]) -> tuple[bool, str]:
    ...

def build_presentation_export(
    record: dict[str, Any],
    *,
    template_path: Path = DEFAULT_PPTX_TEMPLATE_PATH,
) -> PresentationExport:
    ...
```

`PresentationExport` should be a small frozen dataclass with:

```python
content: bytes
filename: str
mime_type: str
slide_count: int
warnings: list[str]
```

## Data Contract

The exporter should accept one orchestrator record, then normalize it internally:

```text
`record["query_result"]`
`record["reporting_result"]`
`record["chart_spec"]`
`record["final_sql"]`
`record["source_tables"]`
`record["run_id"]`
`record["user_question"]`
`record["execution_success"]`
`record["validation_success"]`
```

The exporter must validate:

- `execution_success` is true.
- `validation_success` or `sql_valid` is true.
- `query_result.columns` and `query_result.rows` exist.
- `reporting_result` is a dictionary.
- `assets/templates/PPT_Vorlage_Wuerth.pptx` exists and can be opened.

The exporter should prefer `reporting_result["chart_plan"]` over `record["chart_spec"]` when both exist, because the orchestrator currently sets `chart_spec` from `reporting_result["chart_plan"]`. Treat `chart_spec` as a compatibility alias for UI and existing tests.

Do not pass raw SQL agent state into the exporter. Normalize to an internal `PresentationInput` so the PPT layer is stable even if `src/agent/orchestrator.py` changes its internal state keys.

## Slide Contract

Use a deterministic `SlideSpec` list. The first version should be simple:

| Slide | Source Fields | Purpose |
|-------|---------------|---------|
| Title and takeaway | `user_question`, `reporting_result.summary`, `run_id` | State the question and short result. |
| KPI summary | `reporting_result.kpi_cards`, `reporting_result.interpretation` | Show scalar values or key comparison. |
| Chart or table | `chart_spec`, `query_result` | Render the best visual if allowed, otherwise render a compact result table. |
| Caveats and sources | `reporting_result.caveats`, `source_tables`, `reporting_result.audit` | Make limitations explicit. |
| SQL appendix | `final_sql`, `row_count`, `selected_model`, `fallback_used` | Auditability for technical review. |

The slide spec should be renderer-agnostic:

```python
{
    "layout": "summary",
    "title": "...",
    "body": "...",
    "kpi_cards": [...],
    "chart_spec": {...},
    "table": {"columns": [...], "rows": [...]},
    "notes": [...],
}
```

Text overflow should be handled in the deterministic renderer, not by the LLM. Use predictable rules:

- Cap title length and wrap body text.
- Use max row counts for tables.
- Move extra rows or caveats to appendix slides.
- Add warnings to `PresentationExport.warnings` when truncation happens.

## Claude Opus Boundary

Do not use Claude Opus for PPTX rendering. Rendering needs file I/O, template layout matching, table/chart placement, and overflow behavior. Those are deterministic engineering tasks.

For v1, do not use Claude Opus for slide planning either. The existing `src/agent/reporting_agent.py` already produces German management summaries and caveats from the executed SQL result without an LLM call. This is cheaper, easier to test, and reproducible.

If later work needs richer slide wording, add a separate optional planner:

```text
`src/agent/presentation_planner.py`
```

That planner may call Claude Opus only after SQL execution and reporting. It should produce constrained JSON matching the local `SlideSpec` schema. Then validate the JSON and pass it to the same deterministic renderer in `src/agent/presentation_export.py`.

The planner must not:

- Generate SQL.
- Execute SQL.
- Read the PowerPoint template.
- Write `.pptx` files.
- Bypass `reporting_result` caveats or audit fields.

## Richer Visualization

Keep chart selection in `src/agent/visualization_spec.py`. It already has the right contract: no LLM, no database, no Streamlit import, no SQL generation. Extend that contract rather than creating a presentation-only chart planner.

Recommended progression:

1. Keep the current `bar`, `line`, and `none` types stable.
2. Add richer chart types only when the returned `query_result` shape is unambiguous.
3. Add `stacked_bar` or `grouped_bar` before more open-ended types, because logistics breakdowns often need category plus segment plus measure.
4. Add `multi_series_line` when one time dimension, one series dimension, and one measure are present.
5. Defer arbitrary chart generation and free-form visual grammar.

The Streamlit Altair renderer currently lives in `render_chart_from_spec()` inside `streamlit_app.py`. That is acceptable for the current app, but richer visualization will make it too large. The next extraction should be:

```text
`src/agent/visualization_rendering.py`
```

Suggested functions:

```python
def dataframe_from_query_result(query_result: dict[str, Any]) -> pd.DataFrame:
    ...

def build_altair_chart(chart_spec: dict[str, Any], df: pd.DataFrame) -> alt.Chart | None:
    ...
```

PowerPoint rendering can either map `chart_spec` to native PowerPoint charts in `src/agent/presentation_export.py` or render a chart image through a dedicated helper later. For v1, prefer native PowerPoint tables/charts where the template supports them, because tests can validate file structure without a browser or local PowerPoint installation.

## Streamlit Integration

Add the UI in `render_record()` near the existing CSV/XLSX export controls:

```text
`streamlit_app.py`
  `render_record()`
    existing CSV download
    existing XLSX download
    new PPTX download
```

The UI layer should do only this:

1. Check `can_export_presentation(record)`.
2. On button click, call `build_presentation_export(record)`.
3. Render `st.download_button()` with `PresentationExport.content`.
4. Show a short `st.warning()` if export is unavailable or generated with truncation warnings.

Do not add template path handling, slide layout mapping, text wrapping, chart conversion, or file writes to `streamlit_app.py`.

## Memory Retrieval Logs, RBAC, And Docs

The memory UI is already large in `streamlit_app.py`. Issue #5 and issue #6 should not add more governance logic there.

### Memory retrieval logs

Keep retrieval in:

```text
`src/agent/memory_retriever.py`
```

Add structured logging through:

```text
`src/agent/logging_utils.py`
`logs/memory_retrieval_log.csv`
```

Log fields should include:

- `run_id`
- `timestamp`
- `scenario_id`
- `dataset_id`
- `memory_intent_key`
- `question_hash` or short safe question text
- `template_ids`
- `scores`
- `templates_used_in_prompt`
- `retrieval_reason`

The SQL agent should attach concise retrieval metadata to the returned record, for example `memory_retrieval`, so Streamlit can display it inside the existing `render_step_log()` or audit expander. Streamlit should not calculate retrieval scores or read memory files directly for logs.

### RBAC

Add backend enforcement:

```text
`src/agent/memory_rbac.py`
`src/agent/memory_service.py`
```

`memory_rbac.py` owns:

- `MemoryRole`: `viewer`, `contributor`, `reviewer`, `admin`
- action constants: `create_candidate`, `edit_candidate`, `validate_candidate`, `approve_candidate`, `reject_candidate`, `disable_template`, `reactivate_template`, `manage_roles`
- `can(role, action)` and `require(role, action)`

`memory_service.py` owns role-aware operations and calls `src/agent/memory_store.py`. This keeps `src/agent/memory_store.py` focused on persistence and audit writes.

Permission recommendation:

| Action | Viewer | Contributor | Reviewer | Admin |
|--------|--------|-------------|----------|-------|
| View candidates/templates | yes | yes | yes | yes |
| Create candidate from successful run | no | yes | yes | yes |
| Edit pending candidate | no | yes | yes | yes |
| Validate YAML | no | yes | yes | yes |
| Approve/reject candidate | no | no | yes | yes |
| Disable/reactivate template | no | no | no | yes |
| Manage roles | no | no | no | yes |

Streamlit should only select or display the current role and call service functions. Buttons can be disabled for convenience, but backend service checks must be the real enforcement.

### Docs

Do not turn `streamlit_app.py` into product documentation. Put implementation status, limitations, demo instructions, and business value into project docs:

```text
`README.md`
`docs/powerpoint_export.md`
`docs/memory_governance.md`
```

If the project avoids a `docs/` directory, update `README.md` and keep deeper implementation notes in `.planning/`. The app should show only short operational labels and warnings.

## Build Order

1. Add the export module skeleton in `src/agent/presentation_export.py`.
   - Define template constants, dataclasses, `can_export_presentation()`, and input normalization.
   - Add `evaluation/test_presentation_export.py` for missing template, failed SQL, and successful input normalization.

2. Implement deterministic slide specs before PPTX rendering.
   - Build specs from `reporting_result`, `query_result`, and `chart_spec`.
   - Test slide count, expected titles, caveat propagation, row truncation warnings, and no SQL-agent imports.

3. Implement PPTX rendering against `assets/templates/PPT_Vorlage_Wuerth.pptx`.
   - Use `python-pptx`.
   - Return bytes, filename, slide count, and warnings.
   - Tests should open the generated `.pptx` and assert non-empty slides without requiring local PowerPoint.

4. Add the Streamlit download button.
   - Keep the change inside `render_record()`.
   - Reuse the existing result record and do not introduce new Streamlit state beyond an export button key.

5. Extend visualization only after basic PPTX export works.
   - Add richer chart types in `src/agent/visualization_spec.py`.
   - Add tests in `evaluation/test_visualization_spec.py`.
   - Extract Streamlit chart rendering to `src/agent/visualization_rendering.py` if chart rendering grows.

6. Add memory retrieval logging.
   - Add log helper in `src/agent/logging_utils.py`.
   - Call it from `src/agent/memory_retriever.py` or the SQL agent retrieval seam.
   - Surface only concise metadata in existing Streamlit trace/audit UI.

7. Add memory RBAC through service modules.
   - Implement `src/agent/memory_rbac.py`.
   - Implement `src/agent/memory_service.py`.
   - Update `streamlit_app.py` imports to use the service boundary.
   - Test role/action behavior without Streamlit.

8. Update final docs.
   - Document implemented versus conceptual parts.
   - Document Wuerth data limitations and template assumptions.
   - Keep user-facing app text short.

## Anti-Patterns To Avoid

### PPTX Logic In `streamlit_app.py`

**What goes wrong:** The app file becomes responsible for binary template parsing, slide layout, text fitting, chart rendering, and download state.

**Consequence:** Export behavior becomes hard to test and easy to break during UI changes.

**Instead:** Put rendering in `src/agent/presentation_export.py` and call it from a small UI block.

### Coupling Export To SQL Generation

**What goes wrong:** The exporter imports the SQL agent, database facade, validator, or router and starts depending on pre-execution state.

**Consequence:** A presentation export can change query behavior or fail when no database connection is available.

**Instead:** Export only from completed result records with successful validation and execution.

### Asking Claude Opus To Create The File

**What goes wrong:** File layout, overflow, and template use become probabilistic.

**Consequence:** Generated decks are harder to test, reproduce, and debug.

**Instead:** Use Claude Opus only as an optional JSON slide planner later. Keep PPTX rendering deterministic.

### Building A General Slide Designer

**What goes wrong:** The project drifts from "analysis result to Wuerth deck" into arbitrary presentation tooling.

**Consequence:** The MVP loses focus and expands layout, editing, and UX scope.

**Instead:** Support a small fixed set of layouts derived from `reporting_result` and `query_result`.

### Adding RBAC Only As Disabled Buttons

**What goes wrong:** Users can still reach write functions if another UI path calls them.

**Consequence:** The role model is cosmetic.

**Instead:** Put permission checks in `src/agent/memory_service.py` or store-level write wrappers, then let Streamlit reflect those decisions.

## Testing Implications

Add focused `unittest` coverage under `evaluation/`, matching current conventions:

```text
`evaluation/test_presentation_export.py`
`evaluation/test_visualization_spec.py`
`evaluation/test_memory_rbac.py`
`evaluation/test_memory_retrieval_logging.py`
```

Minimum PPT export tests:

- Template path resolves to `assets/templates/PPT_Vorlage_Wuerth.pptx`.
- Missing template returns a controlled error.
- Failed or unvalidated SQL records are not exportable.
- Successful record produces non-empty PPTX bytes.
- Generated deck has non-empty slides.
- Table rows are capped with a warning when needed.
- Export module does not import SQL generation or database modules.

No test should require local Microsoft PowerPoint.

## Roadmap Implications

Recommended phase split:

1. **Deterministic PPTX Core**
   - Build `src/agent/presentation_export.py`, slide spec creation, template loading, and tests.
   - This reduces risk before touching UI.

2. **Streamlit Export Surface**
   - Add one download button in `streamlit_app.py`.
   - Verify export only appears after successful SQL results.

3. **Richer Visualization Contract**
   - Extend `src/agent/visualization_spec.py` and optionally extract `src/agent/visualization_rendering.py`.
   - Keep chart selection deterministic and shape-based.

4. **Memory Governance**
   - Add retrieval logs, `src/agent/memory_rbac.py`, and `src/agent/memory_service.py`.
   - Replace direct Streamlit write calls with service calls.

5. **Documentation And Demo Hardening**
   - Document what is implemented, what remains conceptual, and which Wuerth data fields are missing.

This order works because PPT export depends on stable result records, while RBAC and retrieval logging are adjacent support work. Richer visualization can safely follow basic deck generation because it extends the existing `chart_spec` contract.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Module placement | HIGH | Existing codebase maps and current boundaries both point to `src/agent/presentation_export.py`. |
| Data contract | HIGH | `query_result`, `reporting_result`, and `chart_spec` are already present in orchestrator records. |
| Streamlit boundary | HIGH | `streamlit_app.py` already has CSV/XLSX downloads in `render_record()`, so PPT can follow the same thin UI pattern. |
| Claude Opus role | HIGH | Deterministic rendering is clearly required for testable template output. LLM planning should be optional and validated. |
| Rich visualization details | MEDIUM | The spec boundary is clear, but exact chart types should be chosen after seeing real Wuerth result shapes. |
| PPTX template layouts | MEDIUM | The template path is known, but layout names/placeholders need implementation-time inspection. |
| Memory RBAC implementation | MEDIUM | Role requirements are clear, but current direct imports in `streamlit_app.py` mean the service refactor needs careful staging. |

## Source Basis

- `.planning/PROJECT.md`
- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/STRUCTURE.md`
- `.planning/codebase/CONVENTIONS.md`
- `.planning/codebase/TESTING.md`
- `streamlit_app.py`
- `src/agent/orchestrator.py`
- `src/agent/reporting_agent.py`
- `src/agent/visualization_spec.py`
- `src/agent/memory_store.py`
- `src/agent/memory_retriever.py`
- `src/agent/logging_utils.py`
- `requirements.txt`
