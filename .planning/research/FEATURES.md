# Feature Landscape

**Domain:** Presentation-ready analytics-agent export for Wuerth logistics analysis
**Researched:** 2026-06-21
**Scope:** GitHub issues #5, #6, #8, #21; issue #7 excluded
**Confidence:** HIGH for repo-grounded behavior, MEDIUM for PowerPoint rendering specifics until template placeholders are inspected in implementation

## Context

The repo already has a working analysis path: `streamlit_app.py` calls `src/agent/orchestrator.py`, which routes, generates validated SQL, executes it, then builds deterministic reporting output through `src/agent/reporting_agent.py` and `src/agent/visualization_spec.py`. Streamlit already renders the final answer, management summary, result table, simple chart, SQL, source tables, trace steps, reporting audit, CSV export, and XLSX export in `streamlit_app.py`.

The missing v1 feature is a deterministic PowerPoint export built from the successful orchestrator record. The canonical template asset is `assets/templates/PPT_Vorlage_Wuerth.pptx`. No source code imports that template yet, `requirements.txt` has no PowerPoint package, and no `src/agent/presentation_export.py` exists.

Issue #21 should be interpreted narrowly: richer visuals are useful only when they make the generated PowerPoint presentation clearer. This should extend the existing deterministic chart contract, not create a free-form BI dashboard or slide designer.

## Table Stakes

Features users will reasonably expect from a v1 presentation export. Missing any of these makes the export feel unfinished or untrustworthy.

| Feature | Why Expected | Complexity | Dependencies | Acceptance Signals |
|---------|--------------|------------|--------------|--------------------|
| PowerPoint export action after a successful analysis run | The project value is turning a validated logistics answer into a Wuerth-branded deck with minimal manual cleanup. | High | `streamlit_app.py`, new `src/agent/presentation_export.py`, `src/agent/orchestrator.py`, `src/agent/reporting_agent.py`, `assets/templates/PPT_Vorlage_Wuerth.pptx` | A PPTX download button appears only when `execution_success` and `validation_success` are true; generated file opens; slides are non-empty; failed, blocked, clarification, or unsafe runs do not export. |
| Fixed slide-generation contract | A deck generator needs stable layouts, data mappings, overflow rules, and failure behavior before touching a binary template. | High | New `src/agent/presentation_export.py`, `evaluation/test_presentation_export.py`, `src/agent/reporting_agent.py` | Tests assert slide count, required sections, title text, row caps, empty-result behavior, missing-template failure, and no mutation of input record data. |
| Use the Wuerth master template from repo assets | Brand readiness is a stated requirement and the template is already tracked. | Medium | `assets/templates/PPT_Vorlage_Wuerth.pptx`, `requirements.txt`, new path resolver in `src/agent/presentation_export.py` | Export resolves the template via a repo-relative path, never `C:\Users\...`; tests fail if the asset is missing; generated decks inherit the template theme/layout rather than creating a blank default deck. |
| Summary slide | Presentations need the answer before the detail. | Medium | `reporting_result["summary"]`, `reporting_result["kpi_cards"]`, `record["final_answer"]` | First content slide includes final answer or management summary, up to 4 KPI cards from `reporting_result["kpi_cards"]`, run id, scenario, and date. Long text is clipped or split predictably instead of overflowing placeholders. |
| Chart or table slide | The user needs visible evidence, not only prose. | High | `query_result`, `reporting_result["chart_plan"]`, `reporting_result["table_plan"]`, `src/agent/visualization_spec.py` | If `chart_plan.render_allowed` is true, deck contains a chart built from the same rows and columns as Streamlit. If no safe chart exists, deck contains a table-first slide with the chart rejection reason. Table preserves SQL order and uses a fixed row cap. |
| Caveats and limitations slide or section | Wuerth local data has missing KPI columns and join caveats; hiding this would make the export misleading. | Medium | `reporting_result["caveats"]`, `semantic_layer/wuerth_local/wuerth_semantic_layer.yaml`, `evaluation/wuerth_local/golden_questions.yaml` | Deck includes caveats such as missing revenue, packing cost, shipment date, plant, shipping point, unit gaps, 50-row chart cap, and many-to-many join risks when present in the reporting result. |
| SQL and source information | Presentation trust requires traceability to the actual query and tables. | Medium | `record["final_sql"]`, `record["generated_sql"]`, `record["source_tables"]`, `src/agent/sql_validator.py` | Deck includes final SQL, source tables, row count, validation/execution status, and any applied filters/sort/limit from `reporting_result["audit"]`. SQL text is readable, wrapped, and does not break slide layout. |
| Reporting audit visibility | The existing reporting layer already exposes audit metadata; PPT export should not discard it. | Medium | `reporting_result["audit"]`, `render_reporting_audit()` in `streamlit_app.py` | Deck includes a compact audit section: row count, rows visualized, chart type, chart truncation, table order preserved, metric column, category column, source tables, and warnings. |
| Memory-template trace visibility | Approved templates can influence SQL generation through `format_approved_template_context()` in `src/agent/langgraph_sql_agent.py`; users need to see that in a presentation context. | Medium | `src/agent/memory_retriever.py`, `src/agent/langgraph_sql_agent.py`, `src/agent/orchestrator.py`, `logs/router_log.csv` | Streamlit trace and PPT audit list retrieved approved template IDs, intent, score or rank, source run id, required tables, and whether no template was used. Pending/generated candidates never appear as prompt guidance or export trust evidence. |
| Lightweight RBAC for memory-template actions | Issue #6 requires accountability for create/edit/approve/disable actions, but broad app auth is out of scope. | High | `streamlit_app.py`, `src/agent/memory_store.py`, `memory/*/memory_audit_log.csv` | Viewer cannot create/edit/approve/disable; Contributor can create and edit candidates; Reviewer can approve/reject/mark needs changes; Admin can disable/reactivate templates and manage roles. Backend functions enforce role checks, not only button visibility. |
| Audit logging with role and timestamp | Current `AUDIT_COLUMNS` include actor and timestamp but no role. RBAC without role-aware audit is weak. | Medium | `src/agent/memory_store.py`, `memory/*/memory_audit_log.csv` | Each candidate/template action logs action, actor, role, timestamp, candidate id, template id, old status, new status, and comment. Existing audit readers tolerate old rows without role. |
| Final documentation and demo instructions | Issue #8 requires clear handoff: implemented vs conceptual, limitations, demo flow, and business value. | Medium | `README.md`, `.planning/PROJECT.md`, `scripts/validate_wuerth_local_setup.py`, `evaluation/run_evaluation.py` | Docs show how to validate setup, run Streamlit, select Wuerth local, run a supported analysis, export PPTX, inspect memory trace/RBAC, and demonstrate explicit limitations for unsupported KPIs. |

## Differentiators

Features that make the export better than a generic result dump, while still fitting v1.

| Feature | Value Proposition | Complexity | Dependencies | Acceptance Signals |
|---------|-------------------|------------|--------------|--------------------|
| Presentation-specific visualization upgrade for issue #21 | The current chart contract only supports one-dimensional bar/line charts. A controlled upgrade makes the deck useful for real logistics comparisons. | High | `src/agent/visualization_spec.py`, `streamlit_app.py`, new PPT chart renderer, `evaluation/test_visualization_spec.py` | Supports horizontal top-N bars for long labels, grouped bars for one category plus one series plus one measure, and line charts with one optional series when deterministic. Unsupported shapes return an explicit reason and fall back to table. |
| Evidence appendix slide | Gives reviewers enough traceability to trust or challenge the result without opening the app. | Medium | `record`, `reporting_result["audit"]`, memory retrieval metadata, `logs/router_log.csv` | Appendix contains run id, model used, fallback flag, attempts, router intent, complexity tier, memory intent key, retrieved template IDs, SQL status, and source tables. |
| Limitation-first export for unsupported Wuerth KPI questions | For W01/W03-style questions, a good deck should explain why no numeric analysis is possible instead of exporting empty visuals. | Medium | `semantic_layer/wuerth_local/wuerth_semantic_layer.yaml`, `evaluation/wuerth_local/golden_questions.yaml`, `src/agent/reporting_agent.py` | Revenue and packing-cost questions produce a limitation slide with no fabricated KPI card, no fake chart, and source-data gap wording aligned with Wuerth semantic guidance. |
| One-click demo deck scenario | Helps issue #8 by giving a repeatable narrative for final review. | Medium | `README.md`, `streamlit_app.py`, `evaluation/wuerth_local/golden_questions.yaml` | Docs identify 2 to 3 demo questions: one successful chart/table result, one unmatched invoice/shipment result, and one unsupported KPI limitation. The generated deck names include run id or timestamp. |
| Template usage trace | Binary PPT templates are hard to review in git; recording which template produced a deck reduces ambiguity. | Low | `assets/templates/PPT_Vorlage_Wuerth.pptx`, new template checksum helper | Generated deck metadata or audit slide includes template path and checksum. Tests assert the checksum is captured, not hard-coded. |

## Anti-Features

Features to explicitly avoid in v1.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Arbitrary slide designer | It would compete with PowerPoint and expand scope beyond the project value. | Generate a fixed deck from known agent output sections. |
| Full BI dashboard or cross-filtering workbook | The app already has Streamlit for interaction; PPT export should be a static presentation handoff. | Keep CSV/XLSX exports for raw data and PPTX for curated narrative output. |
| LLM-generated slide content after SQL execution | The reporting layer is deterministic and already designed to avoid extra model calls. | Use `src/agent/reporting_agent.py` output and deterministic formatting. |
| PowerPoint export from failed, unsafe, or unvalidated SQL | It would give invalid outputs a polished presentation wrapper. | Allow export only from successful validated runs. |
| Hardcoded local template path | The project explicitly moved the template into `assets/templates/`. | Resolve `assets/templates/PPT_Vorlage_Wuerth.pptx` relative to the repository or module. |
| PPTX construction inside `streamlit_app.py` | The file already owns too much UI logic and is hard to test. | Put generation in `src/agent/presentation_export.py`; Streamlit only calls it and provides `st.download_button`. |
| Raw many-to-many Wuerth join visualization | Joins between invoices and shipments can multiply measures. | Visualize only pre-aggregated query results and surface join caveats. |
| Invented revenue, packing cost, plant, shipping point, or shipment date | The local Wuerth CSV does not expose those fields. | Return explicit limitations from semantic guidance and include them in caveats. |
| Production-grade authentication claim | The project only scopes lightweight memory-action RBAC. | Document RBAC as prototype governance for memory templates, not app-wide security. |
| Unbounded full-result tables in slides | Large tables are unreadable and can bloat PPTX files. | Use a slide row cap, preserve SQL order, and point users to CSV/XLSX for full data. |
| Macro/OLE manipulation in generated decks | The template has embedded OLE objects per codebase concerns; adding active content increases risk. | Treat the template as a static master and add only text, tables, and charts through a chosen PPTX library. |

## Feature Dependencies

```text
Validated orchestrator result
  -> deterministic reporting_result from `src/agent/reporting_agent.py`
  -> slide-generation contract
  -> `src/agent/presentation_export.py`
  -> Streamlit download in `streamlit_app.py`
  -> `evaluation/test_presentation_export.py`

`assets/templates/PPT_Vorlage_Wuerth.pptx`
  -> template path resolver
  -> placeholder/layout mapping
  -> generated deck

Issue #21 visualization support
  -> extend `src/agent/visualization_spec.py`
  -> render same chart contract in Streamlit and PPT
  -> chart fallback reasons in reporting audit

Issue #5 memory retrieval improvements
  -> approved template metadata and scoring
  -> trace_steps/reporting audit/export audit
  -> presentation trust section

Issue #6 RBAC
  -> role-aware memory_store actions
  -> role-aware audit columns
  -> UI button gating plus backend enforcement

Issue #8 docs/demo
  -> stable export feature
  -> known demo questions
  -> limitations and implemented/conceptual boundaries
```

## MVP Recommendation

Prioritize:

1. Build `src/agent/presentation_export.py` around a strict export input contract: `reporting_result`, `query_result`, `final_sql`, `source_tables`, run metadata, and template path.
2. Generate a fixed Wuerth-branded deck with summary, chart/table evidence, caveats, SQL/source info, and audit details.
3. Add the Streamlit download action beside existing CSV/XLSX export in `render_record()` in `streamlit_app.py`.
4. Add memory-template trace visibility before or alongside PPT export, because a polished deck needs to show whether approved memory shaped the answer.
5. Add lightweight RBAC for memory-template actions, with role in audit logs.
6. Extend visualization only for bounded presentation cases from issue #21: horizontal top-N bars, grouped bars, and line charts with one optional series. Defer everything else.
7. Update docs and demo instructions after the export path works.

Defer:

- Arbitrary chart grammar, custom slide editing, maps, network graphs, Sankey diagrams, multi-axis charts, interactive PowerPoint objects, and app-wide authentication. These are not needed to make v1 presentation-ready.

## Acceptance Signals By Area

| Area | Acceptance Signals |
|------|--------------------|
| Export availability | PPTX button appears only for successful validated records; generated file name includes run id; failed/unsafe/no-SQL records have no export button. |
| Template usage | Export reads `assets/templates/PPT_Vorlage_Wuerth.pptx`; tests fail when it is missing; output is based on that master. |
| Content completeness | Deck includes final answer or summary, table or chart, caveats, SQL, source tables, row count, run id, model/fallback status, and reporting audit. |
| Chart behavior | Existing bar/line tests still pass; new issue #21 cases have deterministic chart selection or explicit no-chart reasons. |
| Table behavior | Table slide preserves SQL result order, caps rows, shows truncation note, and does not silently drop columns. |
| Wuerth data limitations | Unsupported revenue, packing cost, plant, shipping point, shipment date, or currency questions export limitation text, not fake metrics. |
| Memory trust | Retrieved approved template IDs and metadata appear in trace/audit; pending generated candidates are never used as prompt context or export evidence. |
| RBAC | Viewer, Contributor, Reviewer, and Admin permissions are enforced in both UI and backend memory actions; audit rows include role. |
| Tests | `python -m unittest discover -s evaluation -p "test_*.py"` includes presentation export tests; tests do not require local PowerPoint. |
| Documentation | README or final docs include setup validation, Streamlit run command, Wuerth local demo path, export steps, known limitations, and implemented vs conceptual components. |

## Source Anchors

- Project scope and issue mapping: `.planning/PROJECT.md`
- Existing architecture: `.planning/codebase/ARCHITECTURE.md`
- Existing file placement guidance: `.planning/codebase/STRUCTURE.md`
- Known risks and gaps: `.planning/codebase/CONCERNS.md`
- Streamlit result rendering and CSV/XLSX export: `streamlit_app.py`
- Reporting result contract: `src/agent/reporting_agent.py`
- Current visualization contract: `src/agent/visualization_spec.py`
- Orchestrator record construction and trace fields: `src/agent/orchestrator.py`
- Approved memory prompt context: `src/agent/langgraph_sql_agent.py`
- Memory lifecycle and audit writer: `src/agent/memory_store.py`
- Memory retrieval: `src/agent/memory_retriever.py`
- Wuerth semantic limitations: `semantic_layer/wuerth_local/wuerth_semantic_layer.yaml`
- Wuerth golden behavior: `evaluation/wuerth_local/golden_questions.yaml`
- PowerPoint template: `assets/templates/PPT_Vorlage_Wuerth.pptx`
