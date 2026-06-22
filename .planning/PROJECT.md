# Wuerth Logistics Agent Presentation Export

## What This Is

This project continues the existing Wuerth logistics agent prototype and makes its output presentation-ready. The agent already answers logistics questions through the Streamlit UI, routes requests, generates safe SQL, executes against supported scenarios, builds summaries, renders simple charts, and exports result tables. The next increment turns successful agent output into Wuerth-branded PowerPoint slides using `assets/templates/PPT_Vorlage_Wuerth.pptx`, while closing the remaining presentation-readiness gaps around memory governance, documentation, and richer visuals.

## Core Value

Users can turn a validated logistics analysis result into a clear Wuerth-branded PowerPoint output with minimal manual cleanup.

## Requirements

### Validated

- [x] Streamlit chat UI can run logistics-analysis requests through the active orchestrator path.
- [x] Router classifies user intent, SQL need, clarification need, complexity, output mode, language, and safety blocks.
- [x] SQL agent can generate, validate, execute, repair, and answer read-only SQL queries against active scenarios.
- [x] Scenario configuration supports demo, Wuerth local CSV, and optional Databricks scenarios.
- [x] PostgreSQL local workflow is available through Docker Compose and scenario-specific backend adapters.
- [x] Deterministic reporting layer creates German management summaries, KPI cards, table plans, chart plans, caveats, and audit metadata.
- [x] Streamlit can render result tables and simple bar or line charts from executed query results.
- [x] Streamlit can export result data as CSV and Excel.
- [x] Memory templates can be created, edited, approved, deactivated, reactivated, and audited in the existing memory store.
- [x] Golden-question evaluation exists and issue #7 is treated as already done for this scope.
- [x] Wuerth PowerPoint master template is tracked at `assets/templates/PPT_Vorlage_Wuerth.pptx`.
- [x] Backend PowerPoint generation can turn a successful validated orchestrator-like record into deterministic Wuerth-branded PPTX bytes.
- [x] Slide-generation contract supports dynamic ordered slides, repeatable evidence slides, result-data mapping, table/chart limits, content budgets, and template safety validation.
- [x] PowerPoint export tests cover template path resolution, output creation, invalid records, missing or unsafe templates, deterministic bytes, and no Streamlit dependency in the backend exporter.

### Active

- [ ] Expose PowerPoint export in Streamlit as a create-then-download action after a successful analysis run.
- [ ] Improve memory-template retrieval so approved active templates include richer metadata and retrieval uses router memory intent where available.
- [ ] Make retrieved memory-template usage visible in logs or trace output while keeping generated candidates out of automatic prompt construction.
- [ ] Add role-based access control for memory-template actions: Viewer, Contributor, Reviewer, and Admin.
- [ ] Restrict approval to Reviewer/Admin and deactivation plus role management to Admin.
- [ ] Add or verify audit logging for template changes with action, role, and timestamp.
- [ ] Extend visualization support beyond the current one-dimension bar/line contract where it directly helps presentation output.
- [ ] Update final documentation with architecture, implemented versus conceptual components, limitations, demo instructions, and business value.

### Out of Scope

- Issue #7 evaluation-set implementation - already present and excluded from this project.
- Blindly merging `origin/4-add-reporting-agent-for-final-business-explanation-and-chart-suggestion` - that branch is stale and would remove newer `dev` code.
- Replacing the current Streamlit/LangGraph architecture - this project extends the existing architecture.
- Building a production authentication system for all app access - only lightweight role checks for memory-template actions are in scope.
- Solving missing Wuerth source-data columns such as revenue, turnover, packing cost, plant, shipping point, or shipment date - document limitations instead.
- Building a full BI dashboard or arbitrary slide designer - focus on repeatable analysis-to-PowerPoint export.
- Supporting PowerPoint generation from failed, unsafe, or unvalidated SQL results.

## Context

The repository is a brownfield Python prototype. `origin/dev` and `origin/main` now both point at the real codebase, while this work continues on `codex/remaining-github-issues`. The current codebase map is in `.planning/codebase/` and should be used for future planning.

The active app is `streamlit_app.py`, which calls `src/agent/orchestrator.py`. The orchestrator runs `src/agent/router.py`, model selection, `src/agent/langgraph_sql_agent.py`, and deterministic reporting through `src/agent/reporting_agent.py` and `src/agent/visualization_spec.py`. The existing visualization contract is intentionally conservative: `bar`, `line`, or `none`.

The Wuerth PowerPoint template was provided as `C:\Users\leonk\projects\wuerth-logistics-agent\database\PPT_Vorlage_Wuerth.pptx` and copied into the working branch at `assets/templates/PPT_Vorlage_Wuerth.pptx`. No current source code imports this template, no PowerPoint dependency is installed, and no PPTX output path exists yet.

Open GitHub issues considered in scope:

| Issue | Title | Scope Decision |
|-------|-------|----------------|
| #5 | Improve memory template retrieval and template structure | Active support work |
| #6 | Add role based access control for memory template actions | Active support work |
| #8 | Document final architecture and implementation status | Active support work |
| #21 | Complex Graphical visualisation | Active, interpreted through presentation-ready visual output |

Issue #7 is excluded because evaluation assets and golden-question infrastructure already exist.

## Constraints

- **Base branch**: Build from `origin/dev` behavior on local branch `codex/remaining-github-issues`.
- **Tech stack**: Python 3.11, Streamlit, LangGraph, pandas, Altair, PostgreSQL, optional Databricks.
- **Template asset**: Use `assets/templates/PPT_Vorlage_Wuerth.pptx`; do not hardcode Leon's local project path.
- **Output safety**: Generate PowerPoint only from successful, validated query results.
- **Architecture boundary**: Keep PPT generation behind a pure backend/export module, then expose a thin Streamlit download button.
- **Testing**: Use existing `unittest` style under `evaluation/test_*.py`; PPT export tests should not require local PowerPoint installation.
- **Documentation**: Final docs must explain implemented versus conceptual parts and known source-data limitations.
- **Security**: Existing app lacks broad app-level auth; avoid presenting lightweight template RBAC as full production security.
- **Data limits**: Local Wuerth CSV source data lacks several business columns; unsupported KPI answers should remain explicit limitations.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Frame project as PPT-first | The final goal is PowerPoint output from agent result data; remaining issues are supporting work. | Confirmed in Phase 1 |
| Store PPT master under `assets/templates/` | A branded output template is an asset, not database input. | Implemented in Phase 1 |
| Use `python-pptx` for deterministic local rendering | It keeps PPT generation testable without PowerPoint or direct LLM-generated files. | Approved and implemented in Phase 1 |
| Normalize generated PPTX ZIP packages | Raw `python-pptx` output can contain non-repeatable ZIP metadata. | Implemented in Phase 1 |
| Treat known think-cell OLE entries as warnings | The current Wuerth template contains known OLE entries; macros and external relationships still block export. | Implemented in Phase 1 |
| Exclude issue #7 | Evaluation set is already present and should not distract from remaining work. | Confirmed |
| Do not merge stale reporting branch | The branch contains old reporting ideas but would delete newer routing, orchestration, visualization, and Wuerth-local code. | Confirmed |
| Build on current `dev` architecture | Current Streamlit and LangGraph flow already owns answer, reporting, chart, and export metadata. | Confirmed in Phase 1 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** via `$gsd-transition`:
1. Requirements invalidated? Move to Out of Scope with reason.
2. Requirements validated? Move to Validated with phase reference.
3. New requirements emerged? Add to Active.
4. Decisions to log? Add to Key Decisions.
5. "What This Is" still accurate? Update if drifted.

**After each milestone** via `$gsd-complete-milestone`:
1. Full review of all sections.
2. Core Value check: still the right priority?
3. Audit Out of Scope: reasons still valid?
4. Update Context with current state.

---
*Last updated: 2026-06-21 after Phase 1 completion*
