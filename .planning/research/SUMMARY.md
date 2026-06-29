# Project Research Summary

**Project:** Wuerth Logistics Agent Presentation Export
**Domain:** Presentation-ready analytics-agent export for logistics analysis
**Researched:** 2026-06-21
**Confidence:** HIGH

## Executive Summary

This project extends an existing Python 3.11, Streamlit, and LangGraph logistics analysis prototype so successful agent results can be exported as Wuerth-branded PowerPoint decks. Experts build this kind of feature as a deterministic post-processing layer: validated query result in, bounded presentation spec in the middle, local PPTX renderer out. The deck should be a reliable export artifact, not a second agent workflow.

The recommended approach is to create a strict `SlideDeckSpec` from the current orchestrator record, validate it locally, and render `.pptx` bytes with `python-pptx==1.0.2` using `assets/templates/PPT_Vorlage_Wuerth.pptx`. Claude Opus API direct PPT creation should not be used as the production renderer. A hybrid approach is acceptable later only if Claude produces schema-constrained slide-spec JSON from capped, sanitized context, with `pydantic` validation and deterministic Python rendering still owning the final PowerPoint file.

The main risks are template drift, text overflow, misleading visuals, privacy leakage, and governance claims that exceed the prototype's actual security model. Mitigate them through a fixed slide contract, real-template tests, row and text budgets, explicit limitation slides, no-PowerPoint file-level tests, role-aware backend checks for memory actions, and documentation that separates implemented behavior from conceptual or future work.

## Key Findings

### Recommended Stack

Use the existing app stack and add a small PowerPoint export layer. Keep model calls out of final file generation. The renderer should be testable without Microsoft PowerPoint and should use the tracked Wuerth template from repo assets.

**Core technologies:**

- `python-pptx==1.0.2`: local `.pptx` renderer - works without PowerPoint, can open templates, add slides, add text, tables, and native charts.
- `pydantic==2.13.4`: spec validation - enforces allowed layouts, row caps, text budgets, chart types, provenance, and failure behavior.
- Existing `streamlit`: UI delivery - use `st.download_button` with PPTX bytes and the official PowerPoint MIME type.
- Existing `src/agent/reporting_agent.py`: deterministic content source - already creates summaries, KPI cards, caveats, chart plans, table plans, and audit metadata.
- Existing `src/agent/visualization_spec.py`: chart contract - keep one source of truth for Streamlit and PPT chart decisions.
- Optional `anthropic==0.111.0`: later slide-spec planner only - do not use it for direct PPTX file creation.
- Optional `vl-convert-python==1.9.0.post1`: later chart-image export only - defer until native PowerPoint charts cannot cover required visuals.

**Direct Claude Opus API vs hybrid renderer recommendation:**

Do not ship direct Claude Opus API PPT creation. It is harder to reproduce, harder to test, less reliable for Wuerth template fidelity, and has data-retention and opaque execution tradeoffs. The production path should be:

```text
orchestrator record
  -> deterministic base SlideDeckSpec
  -> optional Claude slide-spec JSON planner later
  -> local pydantic validation
  -> python-pptx renderer using Wuerth template
  -> Streamlit download
```

For v1, skip Claude for slide planning too. The current reporting layer already provides deterministic slide-ready content.

### Table-Stakes Requirements For REQUIREMENTS.md

Carry these forward as explicit requirements:

- PowerPoint export appears only after successful validated analysis runs.
- Export never runs for failed, unsafe, clarification-only, or unvalidated SQL results.
- Export uses `assets/templates/PPT_Vorlage_Wuerth.pptx` through a repo-relative path.
- A fixed slide-generation contract defines layouts, placeholders, text overflow, table caps, chart fallback, caveats, sources, and audit fields.
- Deck includes a title or takeaway slide, KPI or summary slide, chart or table evidence, caveats and limitations, source tables, run metadata, and compact audit information.
- Unsupported Wuerth KPI gaps such as revenue, packing cost, shipment date, plant, shipping point, and currency limitations are shown as limitations, not fabricated metrics.
- Chart rendering follows `src/agent/visualization_spec.py`; unsupported chart shapes must fall back to table or limitation text with a reason.
- Tables preserve SQL result order, cap rows and columns, and show truncation notes.
- Export tests do not require local Microsoft PowerPoint.
- Missing template, changed template, empty results, long text, and unsupported result shapes fail clearly or degrade predictably.
- Streamlit exposes only a thin download action and does not own template parsing or slide layout logic.
- Memory-template retrieval metadata is visible in trace or audit output when approved templates influence a run.
- Memory-template RBAC covers Viewer, Contributor, Reviewer, and Admin actions, with backend enforcement and role-aware audit logs.
- Final docs explain setup, demo flow, implemented versus conceptual components, known source-data limitations, and the prototype security boundary.

### Expected Features

**Must have:**

- Deterministic Wuerth-branded PPTX export from successful orchestrator records.
- Strict slide contract with known layouts and bounded content.
- Summary, KPI, chart or table, caveat, source, and audit content in the deck.
- Template path resolution and missing-template failure handling.
- Streamlit download button next to existing CSV/XLSX exports.
- Focused `unittest` coverage under `evaluation/`.
- Memory-template trace visibility and lightweight RBAC for template actions.
- Final documentation and repeatable demo instructions.

**Should have:**

- Template checksum or manifest validation.
- Evidence appendix with run id, scenario, model/fallback status, source tables, validation state, and memory template IDs.
- Presentation-specific chart upgrades: horizontal top-N bars, grouped bars, and one-series line variants when result shape is deterministic.
- Limitation-first decks for unsupported KPI questions.
- Generated deck metadata containing template path or checksum.

**Defer to v2+:**

- Direct Claude-created PowerPoint files.
- Arbitrary slide designer.
- Full BI dashboard or cross-filtering export.
- Runtime LLM-generated Python code.
- Maps, network graphs, Sankey diagrams, multi-axis charts, and interactive PowerPoint objects.
- App-wide production authentication.
- Unbounded full-result tables in slides.

### Architecture Direction

PowerPoint export should be a pure backend module that starts after the existing orchestrator has produced a successful record. Do not couple export to SQL generation, routing, database adapters, or Streamlit state. The exporter consumes dictionaries and returns bytes plus metadata.

**Major components:**

1. `src/agent/presentation_export.py` - owns exportability checks, template constants, input normalization, slide spec construction, PPTX rendering, filename generation, warnings, and renderer errors.
2. `src/agent/reporting_agent.py` - continues to own deterministic summary, KPI cards, caveats, table plan, chart plan, and audit fields.
3. `src/agent/visualization_spec.py` - remains the single chart contract for both Streamlit and PowerPoint.
4. `streamlit_app.py` - adds a small `render_record()` export area that checks eligibility, calls the backend exporter, and renders `st.download_button`.
5. `src/agent/memory_retriever.py` plus `src/agent/logging_utils.py` - logs retrieval metadata and exposes concise trace data.
6. `src/agent/memory_rbac.py` and `src/agent/memory_service.py` - recommended service boundary for role checks and memory-template actions.

**Build order:**

1. Define export module skeleton and record eligibility.
2. Build deterministic slide specs before writing PPTX files.
3. Implement PPTX rendering against the real Wuerth template.
4. Add Streamlit download surface.
5. Extend visualization contract only after basic export works.
6. Add memory retrieval logging and RBAC service modules.
7. Update final documentation and demo instructions.

## Critical Pitfalls And Risk Controls

1. **Template drift breaks generation** - create a template manifest or semantic placeholder mapping, validate it against the real template, and store a checksum for known-good template versions.
2. **Text overflow makes slides unusable** - define per-slot character budgets, row caps, truncation rules, appendix fallback, and warnings returned in `PresentationExport`.
3. **Streamlit and PowerPoint charts diverge** - keep `src/agent/visualization_spec.py` as the single contract and render only `render_allowed=True` specs.
4. **Unsupported result shapes become misleading slides** - gate export on validation and execution success, define supported shapes, and show clear limitation slides for empty, scalar, or unsupported outputs.
5. **Claude Opus directly creates unstable decks** - use Claude only as an optional validated JSON planner later, never as the renderer.
6. **Exports leak prompts, SQL, hidden notes, or sensitive data** - define a deck content policy, cap rows, omit prompts, keep raw SQL in a controlled appendix or omit by default, and strip hidden placeholder remnants.
7. **RBAC is mistaken for production security** - describe it as lightweight memory-template governance only, enforce roles in backend service functions, and document that real deployment needs authentication and identity.
8. **Tests depend on installed PowerPoint** - test PPTX as a ZIP package, inspect slide text and relationships, and avoid Office COM automation.
9. **Large result sets overload slides** - set export-specific row, column, and byte budgets with visible truncation notes.
10. **Docs overstate data completeness** - map every final claim to implemented paths and keep Wuerth source-data limitations visible.

## Implications For Roadmap

Based on the research, suggested phase structure:

### Phase 1: Deterministic Export Contract

**Rationale:** The slide contract, eligibility rules, and template path must be stable before rendering or UI work.
**Delivers:** `src/agent/presentation_export.py` skeleton, exportability checks, `PresentationInput`, `SlideDeckSpec`, content budgets, and tests for failed or unsupported records.
**Addresses:** Fixed slide-generation contract, successful-run-only export, limitation handling, no Streamlit monolith growth.
**Avoids:** Invalid exports, unsupported result shapes, direct Claude-created decks, SQL-generation coupling.

### Phase 2: PPTX Renderer And Template Validation

**Rationale:** Rendering is the core project value and carries the highest binary-template risk.
**Delivers:** `python-pptx` renderer, template validation, non-empty generated decks, row/text truncation behavior, missing-template errors, and no-PowerPoint tests.
**Uses:** `python-pptx==1.0.2`, optional `pydantic==2.13.4`, `assets/templates/PPT_Vorlage_Wuerth.pptx`.
**Avoids:** Template drift, font overflow, broken relationships, dependency drift, PowerPoint-only tests.

### Phase 3: Streamlit Export Surface

**Rationale:** UI should come after backend export behavior is testable.
**Delivers:** PPTX download button in `render_record()`, export unavailable reasons, generated filename, MIME type, and warning display.
**Addresses:** One-click export after successful analysis and no export for failed, unsafe, or clarification records.
**Avoids:** PPTX logic in `streamlit_app.py` and accidental exports from invalid records.

### Phase 4: Presentation Visuals

**Rationale:** Richer visuals are valuable only once the deck exists and the shared chart contract is stable.
**Delivers:** Controlled `visualization_spec.py` extensions for horizontal top-N bars, grouped bars, and simple multi-series lines, with Streamlit and PPT renderers reading the same spec.
**Addresses:** Issue #21 within the presentation scope.
**Avoids:** Divergent charts, arbitrary chart grammar, unreadable high-cardinality visuals.

### Phase 5: Memory Governance And Traceability

**Rationale:** Polished decks need to show whether approved memory shaped the answer, and issue #5/#6 support this trust layer.
**Delivers:** memory retrieval log fields, trace metadata, `memory_rbac.py`, `memory_service.py`, role-aware audit rows, and backend role enforcement.
**Addresses:** Approved template metadata, retrieval visibility, Viewer/Contributor/Reviewer/Admin actions, audit role and timestamp.
**Avoids:** prompt injection through bad templates, cosmetic-only RBAC, stale file-state races where possible.

### Phase 6: Documentation And Demo Readiness

**Rationale:** Final docs should follow implementation so they do not describe conceptual behavior as done.
**Delivers:** setup validation, Streamlit run instructions, Wuerth local demo questions, PPT export steps, limitations, implemented/conceptual boundary, and security caveats.
**Addresses:** Issue #8 and final handoff.
**Avoids:** stale golden-result confidence and overstated source-data completeness.

### Phase Ordering Rationale

- Export contract comes first because every later phase depends on eligibility, slide shape, row caps, and template path rules.
- Renderer comes before UI so tests can validate generated files without clicking through Streamlit.
- UI comes before richer charts so users get value from the current deterministic reporting output.
- Visualization is separate because it changes shared chart behavior and needs its own tests.
- Memory governance is adjacent support work and should not block the core export path unless project priorities change.
- Documentation comes last because it must describe actual implemented files, not intended architecture.

### Research Flags

Phases likely needing deeper research during planning:

- **Phase 2:** Inspect real Wuerth template layouts, placeholders, embedded objects, relationships, and checksum strategy.
- **Phase 4:** Validate real Wuerth result shapes before adding grouped or multi-series chart support.
- **Phase 5:** Review current memory store write paths and decide whether optimistic concurrency or file locking is needed.
- **Phase 6:** Re-check golden results and semantic-layer limitations before final docs claim readiness.

Phases with standard patterns where extra research can be skipped:

- **Phase 1:** Standard typed contract and eligibility-gate work.
- **Phase 3:** Standard Streamlit download-button integration.
- **Basic Phase 5 RBAC matrix:** Standard role/action helper pattern, assuming no production auth claim.

## Key Repo Paths To Use

- `.planning/PROJECT.md` - project scope, active requirements, constraints, and issue mapping.
- `.planning/research/STACK.md` - stack decision details and package version guidance.
- `.planning/research/FEATURES.md` - table-stakes features, differentiators, anti-features, acceptance signals.
- `.planning/research/ARCHITECTURE.md` - module boundaries, data contract, build order.
- `.planning/research/PITFALLS.md` - phase warnings and mitigation plan.
- `assets/templates/PPT_Vorlage_Wuerth.pptx` - required Wuerth PowerPoint master template.
- `streamlit_app.py` - UI location for the eventual download button inside `render_record()`.
- `src/agent/orchestrator.py` - source of completed result records.
- `src/agent/reporting_agent.py` - deterministic summary, KPI, caveat, table, chart, and audit source.
- `src/agent/visualization_spec.py` - shared deterministic chart contract.
- `src/agent/presentation_export.py` - new recommended backend export module.
- `src/agent/memory_retriever.py` - approved template retrieval and future retrieval trace metadata.
- `src/agent/memory_store.py` - current memory persistence and audit writer.
- `src/agent/logging_utils.py` - structured logging helpers.
- `src/agent/memory_rbac.py` - new recommended role/action matrix.
- `src/agent/memory_service.py` - new recommended backend service for role-aware memory actions.
- `semantic_layer/wuerth_local/wuerth_semantic_layer.yaml` - Wuerth local data limitations and semantic guidance.
- `evaluation/wuerth_local/golden_questions.yaml` - demo and limitation behavior reference.
- `evaluation/test_presentation_export.py` - new recommended export test file.
- `evaluation/test_visualization_spec.py` - existing or extended visualization contract tests.
- `README.md`, `docs/powerpoint_export.md`, `docs/memory_governance.md` - final documentation targets if the project uses `docs/`.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | `python-pptx`, `pydantic`, Streamlit download, and existing deterministic reporting fit the repo and were researched against current docs and package versions. Direct Claude PPT generation is feasible but weaker for production rendering. |
| Features | HIGH | Table-stakes features are strongly grounded in `.planning/PROJECT.md`, current Streamlit behavior, active GitHub issue scope, and existing agent outputs. |
| Architecture | HIGH | Existing codebase maps and research agree on `src/agent/presentation_export.py`, thin Streamlit integration, deterministic reporting reuse, and no SQL-agent coupling. |
| Pitfalls | HIGH | Risks are repo-specific and tied to known binary template behavior, current Streamlit monolith pressure, existing memory files, Wuerth data gaps, and testing constraints. |

**Overall confidence:** HIGH

### Gaps To Address

- **Template placeholder map:** Inspect `assets/templates/PPT_Vorlage_Wuerth.pptx` during implementation and create a manifest or semantic mapping before relying on placeholder indexes.
- **Template safety:** Scan the PPTX package for embedded objects, macros, external relationships, and unexpected media before distributing generated decks.
- **Exact chart upgrade scope:** Choose grouped and multi-series chart support only after checking real Wuerth query result shapes.
- **Export privacy policy:** Decide whether raw SQL appears by default, only in an internal appendix, or not at all.
- **Memory concurrency:** Current YAML/CSV memory storage may need reload-before-write, optimistic concurrency, or locking for shared Streamlit use.
- **Docs target paths:** Decide whether final docs live only in `README.md` or also in `docs/powerpoint_export.md` and `docs/memory_governance.md`.

## Sources

### Project And Repo Sources

- `.planning/PROJECT.md` - scope, active requirements, constraints, and issue decisions.
- `.planning/research/STACK.md` - stack recommendation, package versions, and Claude Opus tradeoffs.
- `.planning/research/FEATURES.md` - expected features, anti-features, and acceptance signals.
- `.planning/research/ARCHITECTURE.md` - component boundaries, data flow, and build order.
- `.planning/research/PITFALLS.md` - critical pitfalls, phase warnings, and mitigations.
- `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/STRUCTURE.md`, `.planning/codebase/CONCERNS.md`, `.planning/codebase/TESTING.md` - cited by the research files as codebase grounding.
- `streamlit_app.py`, `src/agent/orchestrator.py`, `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, `src/agent/memory_store.py`, `src/agent/memory_retriever.py`, `src/agent/logging_utils.py` - cited implementation anchors.

### External Sources From Stack Research

- `python-pptx` PyPI and docs - PPTX creation/update, placeholders, template usage.
- Anthropic API docs, model overview, Agent Skills, code execution, data retention, and structured outputs - Claude Opus direct PPT generation feasibility and tradeoffs.
- `pydantic` PyPI - typed validation package version.
- `streamlit` docs - `st.download_button` behavior.
- Altair and `vl-convert-python` docs - optional chart image export path.

---
*Research completed: 2026-06-21*
*Ready for roadmap: yes*
