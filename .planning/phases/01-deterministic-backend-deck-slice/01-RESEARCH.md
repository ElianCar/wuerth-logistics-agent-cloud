# Phase 1: Deterministic Backend Deck Slice - Research

**Researched:** 2026-06-21
**Domain:** Deterministic Python backend PPTX export from validated LangGraph orchestrator records
**Confidence:** HIGH for codebase boundaries and template facts, MEDIUM for package install readiness because `pip` and `slopcheck` were unavailable in this shell

<user_constraints>
## User Constraints (from CONTEXT.md)

Copied verbatim from `.planning/phases/01-deterministic-backend-deck-slice/01-CONTEXT.md`. [VERIFIED: 01-CONTEXT.md]

### Locked Decisions

#### Dynamic Slide Generation

- The deck generator must not always produce all 9 template layouts.
- Slide creation must be dynamic: include only slides supported by the available analysis content.
- The same layout can be used multiple times when needed, especially `Agent 04 Chart Evidence` and `Agent 05 Table Evidence`.
- Longer decks with readable repeated evidence slides are preferred over overcrowded slides.
- `Agent 09 Closing` is optional and should be controlled by the deck contract, not hardcoded into every deck.

#### Template Contract

- The current Wuerth master lives at `assets/templates/PPT_Vorlage_Wuerth.pptx`.
- The current master has 9 layouts and 1 sample slide.
- Current layout names are:
  - `Agent 01 Cover`
  - `Agent 02 Executive Summary`
  - `Agent 03 KPI Overview`
  - `Agent 04 Chart Evidence`
  - `Agent 05 Table Evidence`
  - `Agent 06 Comparison`
  - `Agent 07 Caveats And Sources Agent`
  - `1_Agent 08 Appendix Metadata`
  - `Agent 09 Closing`
- The renderer may target layout name plus placeholder index because Selection Pane object names were not normalized.
- The planner should include a template manifest or validation layer that records expected layout names, normalized aliases, placeholder indexes, and known warnings.

#### Think-Cell OLE Caveat

- The template still contains 2 think-cell OLE embeddings.
- Manual removal was not practical.
- Phase 1 should warn about embedded OLE entries during template validation, but should not fail generation solely because they exist.
- Macros or external relationships should remain blocking template safety findings.

#### Rendering Approach

- Direct Claude or Opus-generated `.pptx` files are out of scope.
- Runtime LLM-generated Python code is out of scope.
- The v1 path must be deterministic local rendering from a validated slide spec.
- Optional LLM slide planning is deferred and, if added later, may only produce schema-constrained slide-spec JSON that passes local validation before rendering.

#### Brownfield MVP Interpretation

- MVP mode means a thin vertical PPT export slice in the existing app architecture.
- Do not plan a generic walking skeleton for project scaffold, routing, database, and deployment. This repository already has the application skeleton.
- The first implementation slice should prove: successful record input -> dynamic slide deck spec -> validated Wuerth PPTX bytes -> tests can open the file without Microsoft PowerPoint.

### the agent's Discretion

- Choose exact Python model types, dataclass names, error classes, and helper function names that match existing repo style.
- Choose whether to use pydantic or frozen dataclasses for the first slide spec contract, as long as validation is deterministic and testable.
- Decide whether generated chart evidence in Phase 1 is represented as native PowerPoint charts, table fallback, or placeholder-safe text, as long as Phase 2 can extend it without rewriting the contract.

### Deferred Ideas (OUT OF SCOPE)

- Streamlit `Create PPT` and `Download PPT` UX is Phase 2.
- Richer chart selection and top-N readability work is Phase 3.
- Memory governance and RBAC are Phase 4.
- Final architecture and demo docs are Phase 5.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PPT-02 | Export uses the tracked Wuerth master template at `assets/templates/PPT_Vorlage_Wuerth.pptx` through a repo-relative path. [VERIFIED: .planning/REQUIREMENTS.md] | Use `Path(__file__).resolve().parents[2] / "assets" / "templates" / "PPT_Vorlage_Wuerth.pptx` in `src/agent/presentation_export.py`; the asset exists and has SHA256 `041DE8AC3214DC1892F127021F223D5B9C9D5571B10D6949D022B5A357190EA5`. [VERIFIED: local file hash] |
| PPT-03 | Export is blocked for failed SQL, unsafe SQL, clarification-only responses, missing query results, or unvalidated runs. [VERIFIED: .planning/REQUIREMENTS.md] | Gate on `execution_success`, `validation_success` or `sql_valid`, `needs_clarification`, `blocked_or_unsafe`, `query_result.columns`, and `query_result.rows` before rendering. [VERIFIED: src/agent/orchestrator.py; src/agent/langgraph_sql_agent.py] |
| PPT-06 | Missing or unreadable PPT template produces a clear user-facing error and does not crash the Streamlit app. [VERIFIED: .planning/REQUIREMENTS.md] | Return a structured export error from the backend module, not an uncaught renderer exception. [VERIFIED: AGENTS.md; .planning/codebase/ARCHITECTURE.md] |
| PPT-07 | Export logic is implemented in a testable backend module, not embedded in Streamlit callbacks. [VERIFIED: .planning/REQUIREMENTS.md] | Add `src/agent/presentation_export.py` and keep future `streamlit_app.py` integration as a thin consumer. [VERIFIED: .planning/codebase/STRUCTURE.md; .planning/codebase/ARCHITECTURE.md] |
| SPEC-01 | A fixed slide-generation contract defines allowed slide types, required fields, text budgets, table limits, chart limits, and fallback behavior. [VERIFIED: .planning/REQUIREMENTS.md] | Use frozen dataclasses and explicit validation for `SlideDeckSpec`, `SlideSpec`, `TemplateManifest`, and `PresentationExport`. [VERIFIED: AGENTS.md; .planning/codebase/CONVENTIONS.md] |
| SPEC-02 | Slide spec validation rejects unsupported result shapes before PPT rendering. [VERIFIED: .planning/REQUIREMENTS.md] | Validate the dynamic slide list before calling `python-pptx`, and return unavailable reasons or spec validation errors before opening the template. [CITED: https://python-pptx.readthedocs.io/en/latest/user/presentations.html] |
| SPEC-03 | Deck generation uses deterministic local rendering rather than direct LLM-generated PPTX files. [VERIFIED: .planning/REQUIREMENTS.md] | `python-pptx` supports local `.pptx` creation, reading, and updating without installed PowerPoint. [CITED: https://python-pptx.readthedocs.io/en/latest/] |
| SPEC-04 | Optional LLM use, if added later, is limited to schema-constrained slide-spec JSON and still passes local validation before rendering. [VERIFIED: .planning/REQUIREMENTS.md] | Phase 1 should not add LLM slide planning; the contract should make a future JSON planner an upstream input only. [VERIFIED: 01-CONTEXT.md] |
| TEST-01 | Tests verify PPT template path resolution and missing-template failure behavior. [VERIFIED: .planning/REQUIREMENTS.md] | Add `evaluation/test_presentation_export.py` with real template path tests and a temp missing path. [VERIFIED: .planning/codebase/TESTING.md] |
| TEST-02 | Tests verify a generated PPTX file is created, non-empty, and openable by the chosen Python library without local Microsoft PowerPoint. [VERIFIED: .planning/REQUIREMENTS.md] | Use `python-pptx` to reopen generated bytes and use `zipfile` package checks for slides and relationships. [CITED: https://python-pptx.readthedocs.io/en/latest/user/presentations.html; CITED: https://www.iana.org/assignments/media-types/application/vnd.openxmlformats-officedocument.presentationml.presentation] |
| TEST-03 | Tests verify export eligibility blocks failed, unsafe, clarification-only, and unvalidated records. [VERIFIED: .planning/REQUIREMENTS.md] | Reuse fake orchestrator record patterns from `evaluation/test_orchestrator.py` and assert structured unavailable reasons. [VERIFIED: evaluation/test_orchestrator.py] |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- Use Python 3.11, Streamlit, LangGraph, pandas, Altair, PostgreSQL, and optional Databricks as the project stack. [VERIFIED: AGENTS.md]
- Use `assets/templates/PPT_Vorlage_Wuerth.pptx`; do not hardcode a local user path. [VERIFIED: AGENTS.md]
- Generate PowerPoint only from successful, validated query results. [VERIFIED: AGENTS.md]
- Keep PPT generation behind a pure backend/export module, then expose a thin Streamlit download button later. [VERIFIED: AGENTS.md]
- Use existing `unittest` style under `evaluation/test_*.py`; PPT export tests must not require local PowerPoint. [VERIFIED: AGENTS.md; .planning/codebase/TESTING.md]
- Final docs must separate implemented and conceptual parts, and must name known source-data limitations. [VERIFIED: AGENTS.md]
- Existing app lacks broad app-level auth; do not present lightweight template RBAC as production security. [VERIFIED: AGENTS.md]
- Local Wuerth CSV source data lacks several business columns; unsupported KPI answers should stay explicit limitations. [VERIFIED: AGENTS.md]
- New Python modules should use lower_snake_case filenames, `from __future__ import annotations`, `pathlib.Path`, modern type hints, and existing frozen dataclass patterns. [VERIFIED: AGENTS.md; .planning/codebase/CONVENTIONS.md]
- Follow the user's instruction to avoid em dashes and the banned sentence structure. [VERIFIED: AGENTS.md]

## Summary

Phase 1 should build a deterministic backend slice in `src/agent/presentation_export.py` that accepts one completed orchestrator record and returns structured export availability, warnings, metadata, and PPTX bytes. [VERIFIED: .planning/codebase/ARCHITECTURE.md; VERIFIED: src/agent/orchestrator.py] The export boundary should start after `reporting_result` has been built, because `reporting_agent.py` already creates summary, interpretation, caveats, KPI cards, table plan, chart plan, and audit metadata from executed result data. [VERIFIED: src/agent/reporting_agent.py]

The current Wuerth template exists at `assets/templates/PPT_Vorlage_Wuerth.pptx`, is 257,768 bytes, has 1 sample slide, 9 slide layouts, 2 embedded OLE objects, no detected `vbaProject.bin`, and no detected external relationships in `.rels` files. [VERIFIED: local PPTX package scan] The local layout names are already normalized to `Agent 07 Caveats And Sources` and `Agent 08 Appendix Metadata`, even though the context document still lists older caveat names. [VERIFIED: local PPTX package scan; VERIFIED: 01-CONTEXT.md]

**Primary recommendation:** Use a frozen-dataclass slide contract plus explicit validators, render with `python-pptx` after a package legitimacy checkpoint, treat existing OLE entries as warnings, block macros and external relationships, and use the existing blank sample slide as the cover to avoid relying on unsupported slide deletion. [CITED: https://python-pptx.readthedocs.io/en/latest/api/slides.html; VERIFIED: local PPTX package scan]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Export eligibility | API / Backend | Streamlit later | Backend owns truth because it can check orchestrator record fields before UI display. [VERIFIED: src/agent/orchestrator.py; VERIFIED: AGENTS.md] |
| Slide spec construction | API / Backend | Reporting layer | The spec consumes `reporting_result`, `query_result`, and audit data after SQL execution. [VERIFIED: src/agent/reporting_agent.py] |
| Template validation | API / Backend | Static assets | The backend reads and validates `assets/templates/PPT_Vorlage_Wuerth.pptx` before rendering. [VERIFIED: .planning/PPT_TEMPLATE_GUIDE.md; VERIFIED: local PPTX package scan] |
| PPTX rendering | API / Backend | Static assets | Rendering is deterministic local file generation and should not live in Streamlit callbacks. [VERIFIED: AGENTS.md; CITED: https://python-pptx.readthedocs.io/en/latest/] |
| Download UX | Browser / Client | Streamlit server | Phase 2 will expose returned bytes through `st.download_button`, which accepts bytes and file-like objects. [CITED: https://docs.streamlit.io/develop/api-reference/widgets/st.download_button] |
| SQL safety | Existing SQL agent/backend | Export eligibility | Phase 1 must trust existing `validation_success` and `execution_success`, then fail closed if they are false. [VERIFIED: src/agent/langgraph_sql_agent.py; VERIFIED: src/agent/sql_validator.py] |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python standard library `dataclasses`, `typing`, `pathlib`, `io`, `zipfile`, `xml.etree` | Python 3.11 target [VERIFIED: Dockerfile; AGENTS.md] | Define immutable specs, repo-relative paths, byte streams, package safety checks, and XML relationship scans. [VERIFIED: .planning/codebase/CONVENTIONS.md] | Matches the repo's existing frozen dataclass and explicit validator style without adding validation dependency surface. [VERIFIED: .planning/codebase/CONVENTIONS.md] |
| `python-pptx` [ASSUMED: slopcheck unavailable] | 1.0.2 latest on PyPI, released 2024-08-07 [VERIFIED: https://pypi.org/project/python-pptx/] | Open the Wuerth template, add slides, fill placeholders, add tables, and save PPTX bytes. [CITED: https://python-pptx.readthedocs.io/en/latest/] | Official docs state it creates, reads, and updates `.pptx` files and does not require PowerPoint. [CITED: https://python-pptx.readthedocs.io/en/latest/] |
| Existing `src/agent/reporting_agent.py` | Current repo module [VERIFIED: codebase grep] | Source of summary, interpretation, caveats, KPI cards, table plan, chart plan, and audit metadata. [VERIFIED: src/agent/reporting_agent.py] | It is deterministic and explicitly avoids SQL generation, database calls, and LLM calls. [VERIFIED: src/agent/reporting_agent.py] |
| Existing `src/agent/visualization_spec.py` | Current repo module [VERIFIED: codebase grep] | Source of `bar`, `line`, and `none` chart eligibility. [VERIFIED: src/agent/visualization_spec.py] | It is already a deterministic shape validator for chart output. [VERIFIED: src/agent/visualization_spec.py] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `unittest` | Python 3.11 standard library [VERIFIED: .planning/codebase/TESTING.md] | Focused tests in `evaluation/test_presentation_export.py`. [VERIFIED: .planning/codebase/TESTING.md] | Use for eligibility, template path, missing template, generated bytes, and reopened deck tests. [VERIFIED: .planning/codebase/TESTING.md] |
| `pandas` | Already listed unpinned in `requirements.txt` [VERIFIED: requirements.txt] | Optional internal conversion from `query_result` to rows or table slices. [VERIFIED: src/agent/reporting_agent.py] | Use only if it simplifies row extraction; the exporter can also consume raw `query_result` lists directly. [ASSUMED] |
| `streamlit` | Already listed unpinned in `requirements.txt` [VERIFIED: requirements.txt] | Future Phase 2 consumer of bytes and MIME type. [CITED: https://docs.streamlit.io/develop/api-reference/widgets/st.download_button] | Do not import it in Phase 1 exporter. [VERIFIED: AGENTS.md] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Frozen dataclasses | `pydantic` [ASSUMED] | `pydantic` gives schema models but adds another dependency; dataclasses match the current repo style and are enough for deterministic validators in Phase 1. [VERIFIED: .planning/codebase/CONVENTIONS.md] |
| `python-pptx` | Raw OOXML edits | Raw OOXML is brittle for slide generation; keep XML work limited to template package safety scans. [CITED: https://learn.microsoft.com/en-us/office/open-xml/presentation/structure-of-a-presentationml-document] |
| Native PPT tables or simple charts | Altair image export | Images are useful later, but Phase 1 only needs a deterministic backend deck slice and can defer richer visuals. [VERIFIED: .planning/ROADMAP.md] |
| Deterministic local renderer | Direct LLM-generated PPTX | Direct LLM PPTX output is locked out of scope for v1. [VERIFIED: 01-CONTEXT.md] |

**Installation:**

```bash
pip install python-pptx==1.0.2
```

Planner note: add a human/package verification checkpoint before this install because `slopcheck` could not run in this shell. [VERIFIED: local `pip install slopcheck` command failure]

**Version verification:** `pip index versions python-pptx` could not run because `pip` is not on PATH in this shell; PyPI was used as the registry source for the current version and release date. [VERIFIED: local `pip index versions python-pptx` command failure; VERIFIED: https://pypi.org/project/python-pptx/]

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `python-pptx` [ASSUMED: slopcheck unavailable] | PyPI [VERIFIED: https://pypi.org/project/python-pptx/] | First PyPI release shown as 2013-01-26; latest 1.0.2 shown as 2024-08-07. [VERIFIED: https://pypi.org/project/python-pptx/] | PyPI page did not expose download counts in the inspected page. [VERIFIED: https://pypi.org/project/python-pptx/] | GitHub repository linked from PyPI project links. [VERIFIED: https://pypi.org/project/python-pptx/] | Not run because `pip` is unavailable. [VERIFIED: local command] | Approved only after planner inserts `checkpoint:human-verify` or reruns slopcheck in a Python environment. [VERIFIED: package legitimacy protocol] |

**Packages removed due to slopcheck [SLOP] verdict:** none, because slopcheck did not run. [VERIFIED: local command]

**Packages flagged as suspicious [SUS]:** none detected, because slopcheck did not run. [VERIFIED: local command]

If slopcheck remains unavailable at planning time, keep `python-pptx` tagged `[ASSUMED]` and gate the dependency change behind human verification. [VERIFIED: package legitimacy protocol]

## Architecture Patterns

### System Architecture Diagram

```text
Successful orchestrator record
  execution_success, validation_success, query_result
  reporting_result, chart_spec, final_sql, source_tables
        |
        v
src/agent/presentation_export.py
  can_export_presentation(record)
  normalize to PresentationInput
  build dynamic SlideDeckSpec
  validate template manifest and package safety
        |
        v
python-pptx renderer
  reuse existing blank cover slide
  add only needed dynamic slides
  repeat chart/table evidence layouts when needed
        |
        v
PresentationExport
  content bytes, filename, MIME type, slide_count
  warnings, unavailable_reason, template_audit
        |
        v
Phase 2 Streamlit consumer
  st.download_button(data=bytes, mime=PPTX_MIME_TYPE)
```

This flow starts only after the existing SQL and reporting path completes. [VERIFIED: src/agent/orchestrator.py; VERIFIED: src/agent/reporting_agent.py]

### Recommended Project Structure

```text
src/
└── agent/
    └── presentation_export.py       # Export eligibility, deck spec, template validation, PPTX rendering

evaluation/
└── test_presentation_export.py      # unittest coverage for eligibility, template path, missing template, bytes

assets/
└── templates/
    └── PPT_Vorlage_Wuerth.pptx      # Existing Wuerth master template
```

This placement follows the codebase map's recommendation for new PowerPoint export code. [VERIFIED: .planning/codebase/STRUCTURE.md]

### Pattern 1: Export Eligibility Gate

**What:** Reject records before slide spec construction when they are failed, unsafe, clarification-only, missing results, or unvalidated. [VERIFIED: .planning/REQUIREMENTS.md]

**When to use:** Run this as the first public check in `can_export_presentation(record)`. [VERIFIED: AGENTS.md]

**Example:**

```python
# Source: src/agent/orchestrator.py record fields and Phase 1 requirements.
def unavailable_reason(record: dict[str, object]) -> str:
    if record.get("blocked_or_unsafe"):
        return "blocked_request"
    if record.get("needs_clarification"):
        return "clarification_needed"
    if not record.get("execution_success"):
        return "sql_execution_failed"
    if not bool(record.get("validation_success", record.get("sql_valid", False))):
        return "sql_validation_failed"

    query_result = record.get("query_result")
    if not isinstance(query_result, dict):
        return "missing_query_result"
    if not query_result.get("columns") or not query_result.get("rows"):
        return "missing_query_rows"
    return ""
```

This mirrors the successful-run fields produced by `run_sql_agent()` and preserved by `run_orchestrator()`. [VERIFIED: src/agent/langgraph_sql_agent.py; VERIFIED: src/agent/orchestrator.py]

### Pattern 2: Dynamic Slide List Contract

**What:** Build `SlideDeckSpec.slides` as an ordered list, not as one field per possible layout. [VERIFIED: 01-CONTEXT.md]

**When to use:** Always include cover, then conditionally append summary, KPI, evidence, caveats/sources, appendix, and optional closing slides. [VERIFIED: .planning/PPT_TEMPLATE_GUIDE.md]

**Example:**

```python
# Source: .planning/PPT_TEMPLATE_GUIDE.md dynamic deck rule.
@dataclass(frozen=True)
class SlideDeckSpec:
    title: str
    slides: tuple["SlideSpec", ...]
    template_sha256: str


@dataclass(frozen=True)
class SlideSpec:
    slide_type: str
    layout_name: str
    title: str
    body: tuple[str, ...] = ()
    table: "TableSpec | None" = None
    chart: "ChartSpec | None" = None
    warnings: tuple[str, ...] = ()
```

The planner should require validation for `slide_type`, `layout_name`, text budgets, table caps, and chart caps before `python-pptx` runs. [VERIFIED: .planning/REQUIREMENTS.md]

### Pattern 3: Template Manifest And Safety Scan

**What:** Represent expected layout names, placeholder indexes, known warning entries, and blocking package findings in code. [VERIFIED: 01-CONTEXT.md; VERIFIED: local PPTX package scan]

**When to use:** Run once before rendering and expose the audit in `PresentationExport.warnings` or `PresentationExport.template_audit`. [VERIFIED: .planning/PPT_TEMPLATE_GUIDE.md]

**Current verified template facts:**

| Fact | Value |
|------|-------|
| Template path | `assets/templates/PPT_Vorlage_Wuerth.pptx` [VERIFIED: local file check] |
| SHA256 | `041DE8AC3214DC1892F127021F223D5B9C9D5571B10D6949D022B5A357190EA5` [VERIFIED: local file hash] |
| Slide count | 1 sample slide [VERIFIED: local PPTX package scan] |
| Layout count | 9 [VERIFIED: local PPTX package scan] |
| OLE entries | `ppt/embeddings/oleObject1.bin`, `ppt/embeddings/oleObject2.bin` [VERIFIED: local PPTX package scan] |
| External relationships | 0 found [VERIFIED: local PPTX relationship scan] |
| Macro project | No `vbaProject.bin` found [VERIFIED: local PPTX package scan] |

**Current layout names verified from the file:**

1. `Agent 01 Cover` [VERIFIED: local PPTX package scan]
2. `Agent 02 Executive Summary` [VERIFIED: local PPTX package scan]
3. `Agent 03 KPI Overview` [VERIFIED: local PPTX package scan]
4. `Agent 04 Chart Evidence` [VERIFIED: local PPTX package scan]
5. `Agent 05 Table Evidence` [VERIFIED: local PPTX package scan]
6. `Agent 06 Comparison` [VERIFIED: local PPTX package scan]
7. `Agent 07 Caveats And Sources` [VERIFIED: local PPTX package scan]
8. `Agent 08 Appendix Metadata` [VERIFIED: local PPTX package scan]
9. `Agent 09 Closing` [VERIFIED: local PPTX package scan]

### Pattern 4: Existing Blank Sample Slide As Cover

**What:** Use the existing single blank sample slide as the cover slide, then append additional slides dynamically. [VERIFIED: local PPTX package scan]

**Why:** The public `python-pptx` `Slides` API documents `add_slide`, indexed access, length, and iteration, but no public slide deletion method. [CITED: https://python-pptx.readthedocs.io/en/latest/api/slides.html]

**Implementation note:** The sample slide is related to `slideLayout1.xml`, which is `Agent 01 Cover`, and currently contains no text. [VERIFIED: local PPTX package scan]

### Anti-Patterns to Avoid

- **Always rendering all 9 layouts:** This violates the locked dynamic-deck decision. [VERIFIED: 01-CONTEXT.md]
- **Putting PPTX logic in `streamlit_app.py`:** This violates the project backend boundary. [VERIFIED: AGENTS.md]
- **Deleting the sample slide through private python-pptx internals first:** The public API does not document slide deletion, and the sample slide already matches cover layout. [CITED: https://python-pptx.readthedocs.io/en/latest/api/slides.html; VERIFIED: local PPTX package scan]
- **Direct LLM-generated PPTX or runtime LLM Python code:** This is out of scope and makes deterministic tests weak. [VERIFIED: 01-CONTEXT.md]
- **Raw OOXML generation for normal slides:** Microsoft documents PresentationML as multiple package parts and relationships, so hand-written package generation is easy to break. [CITED: https://learn.microsoft.com/en-us/office/open-xml/presentation/structure-of-a-presentationml-document]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PPTX package creation | Custom ZIP and XML writer for slides | `python-pptx` [ASSUMED: slopcheck unavailable] | Official docs support opening existing presentations, adding slides, placeholders, tables, and charts. [CITED: https://python-pptx.readthedocs.io/en/latest/] |
| Slide validation | Ad hoc dict checks scattered across UI and renderer | Frozen dataclasses plus one validator function | Existing repo style uses explicit data contracts and deterministic validators. [VERIFIED: .planning/codebase/CONVENTIONS.md] |
| Export eligibility | UI-only disabled buttons | Backend `can_export_presentation(record)` | Backend checks are testable and keep Phase 2 UI thin. [VERIFIED: AGENTS.md] |
| Template safety | Manual PowerPoint inspection only | `zipfile` relationship and package scan | PPTX is a ZIP package containing OPC parts, and IANA notes `.pptx` is the macro-free presentation subtype. [CITED: https://www.iana.org/assignments/media-types/application/vnd.openxmlformats-officedocument.presentationml.presentation] |
| Chart eligibility | A second PPT-only chart planner | Existing `src/agent/visualization_spec.py` | Current chart spec is deterministic and already rejects unsupported shapes. [VERIFIED: src/agent/visualization_spec.py] |

**Key insight:** The hard part is not making any PPTX file; it is making invalid exports impossible and template drift visible before binary rendering starts. [VERIFIED: .planning/REQUIREMENTS.md; VERIFIED: local PPTX package scan]

## Common Pitfalls

### Pitfall 1: Treating Think-Cell OLE As Either Invisible Or Fatal

**What goes wrong:** The template contains two embedded OLE files, and a naive validator either ignores them completely or blocks every export. [VERIFIED: local PPTX package scan]

**Why it happens:** `.pptx` files can contain embedded object parts, and this specific template still has `ppt/embeddings/oleObject1.bin` and `ppt/embeddings/oleObject2.bin`. [CITED: https://learn.microsoft.com/en-us/office/open-xml/presentation/structure-of-a-presentationml-document; VERIFIED: local PPTX package scan]

**How to avoid:** Warn for these two known OLE entries, fail for `vbaProject.bin`, external relationships, unexpected embedded objects, or ActiveX entries. [VERIFIED: 01-CONTEXT.md; VERIFIED: local PPTX package scan]

**Warning signs:** Template hash changes, OLE count changes, or `.rels` entries include `TargetMode="External"`. [VERIFIED: local PPTX relationship scan]

### Pitfall 2: Rendering The Sample Slide Plus A Duplicate Cover

**What goes wrong:** The generated deck can accidentally keep the existing blank sample slide and append a second cover. [VERIFIED: local PPTX package scan]

**Why it happens:** `python-pptx` publicly documents adding slides, but not deleting slides. [CITED: https://python-pptx.readthedocs.io/en/latest/api/slides.html]

**How to avoid:** Fill the existing sample slide as cover when it uses `Agent 01 Cover`; only append additional dynamic slides. [VERIFIED: local PPTX package scan]

**Warning signs:** Generated slide count is one greater than `SlideDeckSpec.slides`, or slide 1 has no text. [ASSUMED]

### Pitfall 3: Spec Validation After Template Rendering

**What goes wrong:** Invalid records or unsupported shapes can partially render before the exporter fails. [VERIFIED: .planning/REQUIREMENTS.md]

**Why it happens:** It is tempting to validate while filling placeholders. [ASSUMED]

**How to avoid:** Order the functions as eligibility -> input normalization -> slide spec -> spec validation -> template validation -> render. [VERIFIED: .planning/research/ARCHITECTURE.md]

**Warning signs:** Tests for failed SQL create PPTX bytes, or missing template is checked before failed record eligibility. [ASSUMED]

### Pitfall 4: Depending On Placeholder Position Instead Of `idx`

**What goes wrong:** Placeholder lookup breaks when PowerPoint changes shape order. [CITED: https://python-pptx.readthedocs.io/en/latest/user/placeholders-using.html]

**Why it happens:** Placeholder collection lookup uses `idx`, and the docs state those values are not necessarily contiguous. [CITED: https://python-pptx.readthedocs.io/en/latest/user/placeholders-using.html]

**How to avoid:** Use layout name plus expected placeholder `idx`, and store the mapping in a manifest. [VERIFIED: .planning/PPT_TEMPLATE_GUIDE.md; CITED: https://python-pptx.readthedocs.io/en/latest/user/placeholders-using.html]

**Warning signs:** Renderer targets `slide.shapes[2]` or relies on Selection Pane names. [ASSUMED]

### Pitfall 5: Overpromising Chart Support In Phase 1

**What goes wrong:** The backend slice turns into a chart fidelity project. [VERIFIED: .planning/ROADMAP.md]

**Why it happens:** `python-pptx` supports many chart types, but the repo's current deterministic chart contract only supports `none`, `bar`, and `line`. [CITED: https://python-pptx.readthedocs.io/en/latest/user/charts.html; VERIFIED: src/agent/visualization_spec.py]

**How to avoid:** Phase 1 can render chart evidence as placeholder-safe text or table fallback, as long as the contract leaves room for Phase 2 and Phase 3. [VERIFIED: 01-CONTEXT.md; VERIFIED: .planning/ROADMAP.md]

**Warning signs:** Phase 1 tasks add grouped bars, top-N readability, or Altair image export. [VERIFIED: .planning/ROADMAP.md]

## Code Examples

Verified patterns from official sources and repo contracts.

### Open Template, Fill Existing Cover, Save Bytes

```python
# Source: python-pptx presentations and slides docs.
from io import BytesIO
from pathlib import Path

from pptx import Presentation


def render_bytes(template_path: Path, title: str) -> bytes:
    prs = Presentation(str(template_path))
    cover = prs.slides[0]
    cover.shapes.title.text = title

    output = BytesIO()
    prs.save(output)
    return output.getvalue()
```

`Presentation(path)` opens an existing `.pptx`, and python-pptx can save to a file-like object. [CITED: https://python-pptx.readthedocs.io/en/latest/user/presentations.html]

### Lookup Layout By Name

```python
# Source: python-pptx slide layout API.
def require_layout(prs, layout_name: str):
    layout = prs.slide_layouts.get_by_name(layout_name)
    if layout is None:
        raise PresentationTemplateError(f"Missing layout: {layout_name}")
    return layout
```

`SlideLayouts.get_by_name()` is documented in the current API page. [CITED: https://python-pptx.readthedocs.io/en/latest/api/slides.html]

### Placeholder Lookup By Stable `idx`

```python
# Source: python-pptx placeholder docs.
def set_placeholder_text(slide, idx: int, text: str) -> None:
    try:
        placeholder = slide.placeholders[idx]
    except KeyError as error:
        raise PresentationTemplateError(f"Missing placeholder idx: {idx}") from error
    placeholder.text = text
```

The placeholder docs say lookup is by `idx`, not by list position, and missing keys raise `KeyError`. [CITED: https://python-pptx.readthedocs.io/en/latest/user/placeholders-using.html]

### Add A Small Table

```python
# Source: python-pptx table docs.
def add_table(slide, rows: list[tuple[object, ...]], columns: list[str], x, y, width, height) -> None:
    shape = slide.shapes.add_table(len(rows) + 1, len(columns), x, y, width, height)
    table = shape.table
    for column_index, column_name in enumerate(columns):
        table.cell(0, column_index).text = str(column_name)
    for row_index, row in enumerate(rows, start=1):
        for column_index, value in enumerate(row):
            table.cell(row_index, column_index).text = "" if value is None else str(value)
```

`add_table()` returns a graphic frame and the table is accessed through `shape.table`. [CITED: https://python-pptx.readthedocs.io/en/latest/user/table.html]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fixed decks that always include every available layout | Dynamic slide list based on available content | Locked for Phase 1 on 2026-06-21 [VERIFIED: 01-CONTEXT.md] | Planner must create tasks for conditional and repeatable slide generation. [VERIFIED: 01-CONTEXT.md] |
| Layout-index-only rendering | Layout name plus placeholder `idx` manifest | Verified from python-pptx placeholder docs and current template scan [CITED: https://python-pptx.readthedocs.io/en/latest/user/placeholders-using.html; VERIFIED: local PPTX package scan] | Planner should include a manifest validation task before rendering. [VERIFIED: .planning/PPT_TEMPLATE_GUIDE.md] |
| Direct model-produced PPTX | Deterministic local renderer from validated spec | Locked out of v1 on 2026-06-21 [VERIFIED: 01-CONTEXT.md] | Planner should make direct LLM-generated PPTX impossible by API shape and tests. [VERIFIED: .planning/REQUIREMENTS.md] |
| Local PowerPoint automation | Library/file-level PPTX tests | Required by project constraints [VERIFIED: AGENTS.md] | Tests should run without Microsoft PowerPoint. [CITED: https://python-pptx.readthedocs.io/en/latest/] |

**Deprecated/outdated:**

- The older layout names in `01-CONTEXT.md` for layouts 7 and 8 are stale against the current file, because the file now exposes normalized names. [VERIFIED: local PPTX package scan; VERIFIED: 01-CONTEXT.md]
- Planning a generic MVP scaffold is out of scope because this is a brownfield vertical backend export slice. [VERIFIED: 01-CONTEXT.md]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Frozen dataclasses are enough for the first slide spec contract. [ASSUMED] | Standard Stack | If validation becomes nested or externally serialized, planner may need to add `pydantic` with a separate package gate. |
| A2 | Using the existing blank sample slide as the cover is acceptable visually. [ASSUMED] | Architecture Patterns | If branding requires a newly added cover slide, planner needs a supported sample-slide removal strategy or a no-slide template. |
| A3 | Phase 1 can represent chart evidence as table fallback or placeholder-safe text. [ASSUMED] | Common Pitfalls | If stakeholders require native chart output in Phase 1, planner must add chart rendering and tests earlier. |
| A4 | Human/package verification can substitute for unavailable `slopcheck` during planning. [ASSUMED] | Package Legitimacy Audit | If no verification is possible, dependency installation should be blocked until a Python environment can run the package gate. |

## Open Questions (RESOLVED)

1. **Should raw SQL appear in the Phase 1 appendix spec?**
   - What we know: `final_sql` is present in orchestrator records and Streamlit already displays SQL. [VERIFIED: src/agent/orchestrator.py; VERIFIED: streamlit_app.py]
   - What's unclear: Phase 1 requirements do not require raw SQL in the generated deck. [VERIFIED: .planning/REQUIREMENTS.md]
   - Recommendation: Keep SQL out of visible Phase 1 slides by default, but include a structured metadata field so Phase 2 or Phase 5 can decide. [ASSUMED]
   - RESOLVED: Keep raw SQL out of visible Phase 1 slides by default. Allow a structured metadata field for future documentation or appendix decisions.

2. **Should template hash mismatch warn or block?**
   - What we know: The current hash is `041DE8AC3214DC1892F127021F223D5B9C9D5571B10D6949D022B5A357190EA5`. [VERIFIED: local file hash]
   - What's unclear: The project has no committed template manifest yet. [VERIFIED: rg --files; .planning/PPT_TEMPLATE_GUIDE.md]
   - Recommendation: In Phase 1, block if required layouts are missing, warn on hash mismatch unless macros or external relationships are found. [ASSUMED]
   - RESOLVED: Warn on template hash mismatch when required layouts exist and no macros or external relationships are present. Block missing required layouts, macros, external relationships, unexpected active content, or an unreadable template.

3. **How much table data should Phase 1 allow?**
   - What we know: Current chart display cap is 50 rows and reporting table plan preserves SQL order. [VERIFIED: src/agent/visualization_spec.py; VERIFIED: src/agent/reporting_agent.py]
   - What's unclear: Phase 3 owns readable evidence and table truncation behavior. [VERIFIED: .planning/ROADMAP.md]
   - Recommendation: Use a small Phase 1 table cap, record truncation warnings, and defer top-N readability tuning to Phase 3. [ASSUMED]
   - RESOLVED: Use a small deterministic table cap suitable for tests and basic evidence, record truncation warnings, and defer richer top-N and readability tuning to Phase 3.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| `python` | Running tests and package install | no | none on PATH [VERIFIED: local command] | Use a properly activated Python 3.11 environment or Docker workflow. [ASSUMED] |
| `python3` | Running tests | no | none on PATH [VERIFIED: local command] | Use a properly activated Python 3.11 environment or Docker workflow. [ASSUMED] |
| `py` | Windows Python launcher | no | none on PATH [VERIFIED: local command] | Use explicit Python path or install launcher. [ASSUMED] |
| `pip` | Package install and slopcheck | no | none on PATH [VERIFIED: local command] | Use the explicit bundled Python runtime with `-m pip` after Python is available. [ASSUMED] |
| `ctx7` | Context7 documentation fallback | no | none on PATH [VERIFIED: local command] | Official docs were fetched via web. [CITED: https://python-pptx.readthedocs.io/en/latest/] |
| `slopcheck` | Package legitimacy gate | no | install failed because `pip` is unavailable [VERIFIED: local command] | Planner must rerun in a Python environment or add human verification. [VERIFIED: package legitimacy protocol] |
| `docker` | Possible project runtime fallback | yes | 29.4.3, with config access warning [VERIFIED: local command] | Use `docker-compose` if direct Python is absent. [ASSUMED] |
| `docker compose` | Compose plugin | no | unknown command [VERIFIED: local command] | Use `docker-compose`. [VERIFIED: local command] |
| `docker-compose` | Project local stack | yes | v5.1.3 [VERIFIED: local command] | none |
| Microsoft PowerPoint | PPTX test opening | not required | none | `python-pptx` works without installed PowerPoint. [CITED: https://python-pptx.readthedocs.io/en/latest/] |

**Missing dependencies with no fallback:**

- None for research writing. [VERIFIED: local commands]

**Missing dependencies with fallback:**

- Direct `python` and `pip` are missing, so planner should include environment setup or Docker-based verification before implementation tests. [VERIFIED: local commands]
- `ctx7` is missing, so official web docs were used for library documentation. [VERIFIED: local command; CITED: https://python-pptx.readthedocs.io/en/latest/]

## Security Domain

Security enforcement is enabled by default because `.planning/config.json` does not set `security_enforcement` to `false`. [VERIFIED: .planning/config.json]

### Applicable ASVS Categories

OWASP ASVS provides a basis for testing web application technical security controls, and the current stable version is 5.0.0. [CITED: https://owasp.org/www-project-application-security-verification-standard/]

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| Authentication | no new auth in Phase 1 | Do not add or claim app-level auth in this phase. [VERIFIED: AGENTS.md] |
| Session Management | no new session behavior | Keep exporter pure and stateless; Phase 2 can store generated bytes in Streamlit state if needed. [ASSUMED] |
| Access Control | yes, export eligibility | Backend export gate blocks invalid records regardless of UI state. [VERIFIED: .planning/REQUIREMENTS.md] |
| Input Validation | yes | Validate orchestrator record shape, slide spec, text budgets, table limits, chart limits, and template package safety. [VERIFIED: .planning/REQUIREMENTS.md] |
| Cryptography | no new crypto | Do not invent encryption; PPTX MIME registration notes this subtype is not encrypted by OOXML itself. [CITED: https://www.iana.org/assignments/media-types/application/vnd.openxmlformats-officedocument.presentationml.presentation] |
| File and Resources | yes | Read only repo-relative template by default, reject missing or unreadable templates, and scan package relationships. [VERIFIED: AGENTS.md; VERIFIED: local PPTX package scan] |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Direct export from failed or unsafe record | Tampering | Backend eligibility gate before spec creation and rendering. [VERIFIED: .planning/REQUIREMENTS.md] |
| Macro or external-link template replacement | Elevation of privilege / Information disclosure | Block `vbaProject.bin`, `TargetMode="External"`, external URLs, and unexpected active content. [CITED: https://www.iana.org/assignments/media-types/application/vnd.openxmlformats-officedocument.presentationml.presentation; VERIFIED: local PPTX relationship scan] |
| Hidden debug data in generated deck | Information disclosure | Keep prompts, raw traces, and full audit JSON out of visible slides and notes by default. [ASSUMED] |
| Path override outside repo | Tampering | Default to repo-relative template path; tests may inject temp paths only. [VERIFIED: AGENTS.md] |
| LLM-created PPTX bypasses validators | Tampering / Repudiation | Do not expose an API that accepts model-produced PPTX bytes as production output. [VERIFIED: 01-CONTEXT.md] |

## Sources

### Primary (HIGH confidence)

- `.planning/phases/01-deterministic-backend-deck-slice/01-CONTEXT.md` - locked decisions, discretion, and deferred scope. [VERIFIED: file read]
- `.planning/REQUIREMENTS.md` - Phase 1 requirement IDs and acceptance criteria. [VERIFIED: file read]
- `.planning/ROADMAP.md` - phase scope and success criteria. [VERIFIED: file read]
- `.planning/PPT_TEMPLATE_GUIDE.md` - dynamic deck rule, layout guidance, OLE caveat. [VERIFIED: file read]
- `.planning/codebase/ARCHITECTURE.md` and `.planning/codebase/STRUCTURE.md` - module placement and boundaries. [VERIFIED: file read]
- `.planning/codebase/TESTING.md` - `unittest` conventions and no-PowerPoint testing guidance. [VERIFIED: file read]
- `AGENTS.md` - project constraints and coding conventions. [VERIFIED: file read]
- `src/agent/orchestrator.py`, `src/agent/langgraph_sql_agent.py`, `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, `streamlit_app.py` - current record shape and reporting outputs. [VERIFIED: codebase grep and file read]
- `assets/templates/PPT_Vorlage_Wuerth.pptx` - local package scan, layout names, placeholder indexes, OLE entries, relationship scan, file hash. [VERIFIED: local PPTX package scan]
- `python-pptx` docs - presentations, slides, placeholders, tables, charts. [CITED: https://python-pptx.readthedocs.io/en/latest/]
- PyPI `python-pptx` page - package version, release date, Python version support, project links. [VERIFIED: https://pypi.org/project/python-pptx/]
- IANA PPTX media type registration - MIME type, ZIP/OPC nature, macro-free subtype. [CITED: https://www.iana.org/assignments/media-types/application/vnd.openxmlformats-officedocument.presentationml.presentation]
- OWASP ASVS project page - ASVS purpose and current stable version. [CITED: https://owasp.org/www-project-application-security-verification-standard/]

### Secondary (MEDIUM confidence)

- `.planning/research/SUMMARY.md`, `.planning/research/STACK.md`, `.planning/research/ARCHITECTURE.md`, `.planning/research/PITFALLS.md` - prior project research used for cross-checking, with current phase scope narrowed by `01-CONTEXT.md`. [VERIFIED: file read]
- Streamlit `st.download_button` docs - future Phase 2 byte consumer details. [CITED: https://docs.streamlit.io/develop/api-reference/widgets/st.download_button]
- Microsoft Learn PresentationML structure page - package parts and relationships background. [CITED: https://learn.microsoft.com/en-us/office/open-xml/presentation/structure-of-a-presentationml-document]

### Tertiary (LOW confidence)

- None used as primary decision evidence. [VERIFIED: source review]

## Metadata

**Confidence breakdown:**

- Standard stack: MEDIUM - `python-pptx` is strongly supported by official docs and PyPI, but package legitimacy remains gated because `slopcheck` and `pip` were unavailable locally. [CITED: https://python-pptx.readthedocs.io/en/latest/; VERIFIED: local command]
- Architecture: HIGH - repo docs and current source agree on a backend export module after orchestrator/reporting. [VERIFIED: .planning/codebase/ARCHITECTURE.md; VERIFIED: src/agent/orchestrator.py]
- Template facts: HIGH - layout names, placeholders, OLE entries, external relationships, slide count, and hash were inspected from the local `.pptx` package. [VERIFIED: local PPTX package scan]
- Pitfalls: HIGH - risks map directly to phase decisions, template scan, and `python-pptx` public API behavior. [VERIFIED: 01-CONTEXT.md; CITED: https://python-pptx.readthedocs.io/en/latest/api/slides.html]
- Validation architecture: omitted because `workflow.nyquist_validation` is explicitly `false`. [VERIFIED: .planning/config.json]

**Research date:** 2026-06-21
**Valid until:** 2026-07-21 for package and documentation claims; template facts are valid until `assets/templates/PPT_Vorlage_Wuerth.pptx` changes. [ASSUMED]
