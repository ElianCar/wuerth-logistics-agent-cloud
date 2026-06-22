# Domain Pitfalls

**Domain:** Wuerth logistics agent PowerPoint export
**Researched:** 2026-06-21
**Overall confidence:** HIGH for repo-specific risks, MEDIUM for renderer-specific risks until the PPTX library is chosen.

## Phase Labels Used

| Phase | Scope |
|-------|-------|
| Phase 1: Export Contract | Slide-generation contract, supported result shapes, template path resolution, deterministic export module. |
| Phase 2: Renderer And Template Validation | PPTX generation, template integrity checks, placeholder mapping, text overflow rules, file-level tests. |
| Phase 3: Presentation Visuals | Complex charts, table rendering, chart image strategy, visual truncation rules. |
| Phase 4: Memory Governance | Template retrieval metadata, role checks, approval/deactivation rules, audit identity. |
| Phase 5: Security And Privacy | Log redaction, prompt and SQL exposure controls, export content policy, template RBAC boundaries. |
| Phase 6: Documentation And Readiness | Final docs, demo guide, known limitations, golden result refresh policy. |

## Critical Pitfalls

### Pitfall 1: Binary PPT Template Drift Breaks Generation
**What goes wrong:** `assets/templates/PPT_Vorlage_Wuerth.pptx` is a binary master. Layout IDs, placeholder indexes, placeholder names, theme colors, embedded media, or master relationships can change with no useful git diff. A renderer that depends on brittle layout numbers can start writing titles into body boxes, dropping logos, or failing only after download.
**Warning signs:** Export code references numeric layout indexes directly; tests use a synthetic blank deck instead of `assets/templates/PPT_Vorlage_Wuerth.pptx`; generated files open with repaired-content warnings; slides are non-empty but Wuerth branding disappears; template updates arrive as binary replacements with no checksum or manifest change.
**Prevention:** Create a template manifest that maps semantic slots such as title, subtitle, KPI card, chart area, source note, and footer to concrete placeholders. Validate the manifest against `assets/templates/PPT_Vorlage_Wuerth.pptx` before each export. Store a checksum for approved template versions. Add tests under `evaluation/test_presentation_export.py` that open the real template, generate a deck, and extract expected slide text.
**Phase to address:** Phase 1 defines the manifest and supported layouts. Phase 2 enforces template validation in tests and runtime failure paths.

### Pitfall 2: Font And Text Overflow Produce Unusable Slides
**What goes wrong:** The reporting layer can produce long German summaries, caveats, SQL fragments, source tables, and category labels from `src/agent/reporting_agent.py`. PowerPoint placeholders do not guarantee readable shrink-to-fit behavior across machines, especially when Wuerth fonts are missing. Long labels can overlap charts, push footer text out of bounds, or silently disappear.
**Warning signs:** Slide titles wrap into three or more lines; KPI values overlap labels; German umlauts render inconsistently; table cells clip; warnings or caveats are missing from the deck; generated slides look acceptable on one machine but wrong on another.
**Prevention:** Treat slide text as bounded content. Define per-slot character budgets, truncation rules, fallback text, and font fallbacks. Put long SQL and raw row previews in an appendix slide only when explicitly enabled. Prefer summary bullets derived from `reporting_result` over full prose blocks. Add tests that feed long labels and long caveats through the renderer and assert overflow policy metadata.
**Phase to address:** Phase 1 defines text budgets. Phase 2 implements and tests overflow handling. Phase 6 documents the limitations for users.

### Pitfall 3: Chart Rendering Diverges Between Streamlit And PowerPoint
**What goes wrong:** Streamlit currently renders charts from `src/agent/visualization_spec.py` with Altair in `streamlit_app.py`. A PPTX renderer may use native PowerPoint charts, image export, or manual drawing. If the chart spec is not portable, the PowerPoint chart can show different ordering, truncation, units, axis labels, or row limits from the UI.
**Warning signs:** `streamlit_app.py` and the PPTX module each build chart data separately; chart sort order differs from `reporting_result["audit"]["chart_order"]`; PowerPoint charts ignore `display_row_limit`; chart notes about first 50 rows are omitted; unsupported charts are silently rendered as default bars.
**Prevention:** Make `src/agent/visualization_spec.py` the single chart contract. Render only chart specs with `render_allowed=True`. Preserve `category_order`, `display_row_limit`, `truncated`, `unit`, `x_label`, `y_label`, and warnings. If complex visuals need more shape types, extend the structured spec first, then update Streamlit and PPTX renderers from the same fields.
**Phase to address:** Phase 1 freezes the chart contract used by PPTX. Phase 3 expands visuals only after contract tests pass.

### Pitfall 4: Unsupported Result Shapes Become Misleading Slides
**What goes wrong:** The current visualization contract supports `none`, `bar`, and `line` only, with one safe dimension and one numeric measure. Real SQL results can include multiple metrics, multiple grouping dimensions, high-cardinality categories, empty result sets, scalar values, mixed data types, or limitation-only rows. Forcing all of that into a chart or KPI layout can mislead users.
**Warning signs:** Decks generated from failed or unsafe runs; charts appear for scalar limitation answers; multiple numeric columns get collapsed without a warning; high-cardinality categories render unreadable axes; empty results produce blank slides instead of an explicit "no result" message.
**Prevention:** Add a slide-level export eligibility gate around successful validation and execution from `src/agent/orchestrator.py`. Define supported result shapes up front: scalar KPI, KPI row, one-dimension table, one-dimension chart, limitation slide, and appendix table. Unsupported shapes must produce a clear explanatory slide or block export with a user-facing reason.
**Phase to address:** Phase 1 owns result-shape gating. Phase 2 tests missing template, empty result, scalar result, table-only result, and unsupported multi-dimension result behavior.

### Pitfall 5: Letting Claude Opus Or Another API Model Create PPTX Directly
**What goes wrong:** Asking Claude Opus or any LLM API to produce the PPTX file directly pushes layout, binary packaging, safety filtering, and brand rules into a probabilistic step. The repo already has deterministic post-SQL reporting in `src/agent/reporting_agent.py` and deterministic chart specs in `src/agent/visualization_spec.py`. Bypassing those contracts makes outputs harder to test and easier to leak prompt, SQL, or raw data.
**Warning signs:** Prompts ask the model to return base64 PPTX, XML parts, or a completed slide deck; generated decks vary across retries for the same input; no stable fixture can assert placeholder contents; errors are "model made a bad slide" rather than schema validation failures; the model sees the whole template package or internal notes.
**Prevention:** Use the LLM only upstream where the project already uses it: routing, SQL generation, and final answer text through `src/llm/model_adapter.py` and `src/agent/langgraph_sql_agent.py`. Convert approved agent output into a strict JSON-like presentation spec, validate it, then use a deterministic renderer in a new module such as `src/agent/presentation_export.py`. If an LLM ever drafts slide copy, validate length, fields, and allowed content before rendering.
**Phase to address:** Phase 1 must reject direct API-created PPTX as an architecture choice. Phase 2 builds the deterministic renderer. Phase 5 audits prompt and content exposure.

### Pitfall 6: PowerPoint Exports Leak Sensitive Prompts, SQL, Or Business Data
**What goes wrong:** The app currently displays SQL, source tables, reporting audit data, and result rows in `streamlit_app.py`. Logs in `src/agent/logging_utils.py` store user questions, generated SQL, final SQL, answer previews, feedback, and comments. A PPTX export can accidentally include raw SQL, internal prompts, error messages, hidden speaker notes, full result tables, or unredacted sensitive rows.
**Warning signs:** Deck notes contain debug metadata; appendix slides include complete SQL by default; downloaded PPTX files include hidden text from prior slide placeholders; log files and exported decks share raw user questions; stakeholder decks include unsupported source columns or identifiers.
**Prevention:** Define an export content policy separate from UI display. Default deck content should include summary, caveats, visible KPI/table/chart data, source table names, and run metadata that is safe to share. Keep raw SQL, prompts, router traces, and detailed audit JSON out of the deck unless an explicit internal-debug export mode is added. Redact or cap sensitive values before writing logs and before creating slides.
**Phase to address:** Phase 1 defines deck content. Phase 5 implements privacy controls and redaction tests.

### Pitfall 7: Template RBAC Is Treated As Product Security
**What goes wrong:** `.planning/PROJECT.md` scopes lightweight roles for memory-template actions, but `streamlit_app.py` currently has no app-level login or identity provider. `src/agent/memory_store.py` writes `actor="manual_review"` by default. Adding Viewer, Contributor, Reviewer, and Admin checks only around template buttons does not secure the whole app, because users can still run SQL, view SQL, download data, and access Streamlit pages if the app is exposed.
**Warning signs:** Documentation says "secure" or "role protected" without naming the lack of app authentication; role selection lives only in `st.session_state`; approval, disable, or reactivate buttons call `approve_candidate`, `disable_template`, or `reactivate_template` without a verified actor; audit rows all show `manual_review`.
**Prevention:** Keep the scope honest: lightweight RBAC governs memory-template actions only. Add a single role enforcement helper used by Streamlit buttons and backend memory functions. Persist actor and role in audit rows. Do not present this as production auth. Document that external deployment needs real authentication, per-user identity, and network controls.
**Phase to address:** Phase 4 implements role checks and audit identity. Phase 5 documents the security boundary and deployment risk.

### Pitfall 8: Streamlit Monolith Hides Export Coupling
**What goes wrong:** `streamlit_app.py` owns chat state, model config, result rendering, CSV/XLSX export, memory review, template approval, and golden-test UI. Adding PPTX rendering directly there will make a 1300-plus-line controller responsible for binary generation, template validation, chart conversion, and role checks.
**Warning signs:** New code imports PPTX libraries inside `streamlit_app.py`; export logic reads `st.session_state` directly; tests need Streamlit to instantiate decks; PPTX errors are handled inside UI callbacks only; memory governance and export changes touch the same large functions.
**Prevention:** Create a pure backend export module, for example `src/agent/presentation_export.py`, that accepts `record` or a narrowed presentation spec and returns bytes plus validation metadata. Keep `streamlit_app.py` limited to checking export eligibility, calling the export function, and exposing `st.download_button`.
**Phase to address:** Phase 1 defines the module boundary. Phase 2 implements renderer tests outside Streamlit. Phase 4 keeps RBAC helper logic out of view callbacks.

### Pitfall 9: Tests Require Installed PowerPoint
**What goes wrong:** CI and local Python test runs should not require Microsoft PowerPoint. If verification depends on opening the deck in PowerPoint or exporting screenshots through Office COM automation, tests become Windows-only, flaky, and hard to run in Docker.
**Warning signs:** `evaluation/test_presentation_export.py` imports COM automation; tests are skipped unless PowerPoint is installed; assertions only check that PowerPoint can open the file manually; no file-level checks exist for slide count, text, relationships, and media.
**Prevention:** Use file-level tests first: generated `.pptx` is a ZIP package, contains expected slide parts, has no broken relationships, includes expected text, and has non-empty media/chart content. If optional rendering is added later, make it an extra smoke test, not the mandatory gate. Follow the repo testing pattern in `.planning/codebase/TESTING.md` with `unittest` and temporary directories.
**Phase to address:** Phase 2 owns mandatory no-PowerPoint tests. Phase 3 may add optional visual smoke checks if a renderer is available.

### Pitfall 10: Stale Golden Results And Docs Create False Confidence
**What goes wrong:** `evaluation/demo/golden_results.jsonl` already contains many failed and errored records, and final docs can easily drift from implementation. A PPTX export could pass a narrow demo while docs still claim unsupported data columns, chart types, or security controls are implemented.
**Warning signs:** Final docs describe conceptual components as implemented; golden results are committed as if they were a passing baseline; docs mention PowerPoint export before `requirements.txt` has a PPTX dependency; README examples show charts or columns that `semantic_layer/databricks/wuerth_semantic_layer.yaml` marks unavailable.
**Prevention:** Treat generated golden output as runtime evidence, not a stable fixture unless curated. Refresh or archive stale `evaluation/*/golden_results.jsonl` before final documentation. Add a documentation checklist that maps claims to implemented files such as `src/agent/presentation_export.py`, `evaluation/test_presentation_export.py`, `streamlit_app.py`, and `src/agent/memory_store.py`.
**Phase to address:** Phase 6 owns documentation freshness. Phase 2 and Phase 3 should update tests before docs claim readiness.

## Moderate Pitfalls

### Pitfall 11: Memory Templates Become A Prompt Injection Or Quality Channel
**What goes wrong:** `src/agent/memory_retriever.py` loads approved active templates by token scoring. `src/agent/memory_store.py` stores `sql_skeleton`, trigger phrases, notes, generated SQL, final SQL, and feedback-derived content. A bad approval can route future SQL generation toward stale joins, unsupported KPIs, or malicious instructions hidden in template notes.
**Warning signs:** Approved templates contain broad prose instructions; retrieval does not show which template was used; templates from one scenario affect another; reviewers approve candidates without seeing source tables, final SQL, and validation status; generated candidates are automatically injected into prompts.
**Prevention:** Keep generated candidates out of prompt construction until reviewed. Restrict retrieval to approved, active, scenario-matched, dataset-matched templates. Show retrieved template IDs in logs or trace output. Validate `sql_skeleton` through `src/agent/memory_validation.py` and `src/agent/sql_validator.py`. Require Reviewer/Admin approval before activation.
**Phase to address:** Phase 4 owns governance and retrieval visibility. Phase 5 reviews prompt-injection and cross-scenario leakage.

### Pitfall 12: File-Based Memory State Races In Multi-User Streamlit
**What goes wrong:** Memory candidates and templates are YAML files under `memory/`, with CSV audit logs. `src/agent/memory_store.py` uses atomic replace patterns, but there is no multi-user lock. Two Streamlit users can approve, edit, disable, or reactivate templates based on stale copies.
**Warning signs:** A candidate disappears after another user acts; audit timestamps show conflicting updates within seconds; backup files accumulate after simple review actions; disabled templates reappear as active; reviewers see stale proposed YAML after rerun.
**Prevention:** Add optimistic concurrency checks using `updated_at`, template version, and current status. At minimum, reload before write and reject stale operations. For shared use, move memory state to a small database or add file locking. Keep audit append behavior independent from template writes.
**Phase to address:** Phase 4 for role and state integrity. Phase 5 if the app is exposed beyond a single trusted local user.

### Pitfall 13: Binary Template Safety Is Ignored
**What goes wrong:** `.planning/codebase/CONCERNS.md` notes embedded OLE object entries in `assets/templates/PPT_Vorlage_Wuerth.pptx`. Even without detected macros or external relationships at the time of inspection, a future binary replacement can introduce macros, external links, remote media, or hidden objects.
**Warning signs:** Template updates are accepted without package inspection; generated decks preserve unknown embedded objects; exported PPTX files contain external relationship targets; template checksum changes without review.
**Prevention:** Add a template safety scan that checks the PPTX ZIP for `vbaProject.bin`, external relationships, embedded objects, unexpected media, and package anomalies. Fail closed if the template does not match the approved checksum unless the reviewer updates the manifest deliberately.
**Phase to address:** Phase 2 owns package validation. Phase 5 owns policy for distributing generated decks.

### Pitfall 14: Large Result Sets Overload The Export Path
**What goes wrong:** Backends can return full result sets, and `streamlit_app.py` currently converts rows to a DataFrame for preview and CSV/XLSX download. A PPTX export that tries to place full tables or all categories onto slides can blow memory, create huge files, or produce unreadable decks.
**Warning signs:** PPTX generation time grows with row count; generated files are tens of MB for simple questions; decks include hundreds of rows; chart images are blank or clipped; Streamlit locks during export.
**Prevention:** Set export-specific row, column, and byte budgets. Use table previews and appendix limits. Use `reporting_result["table_plan"]`, `chart_plan["display_row_limit"]`, and explicit truncation notes. Refuse export or require a smaller SQL result when limits are exceeded.
**Phase to address:** Phase 1 defines budgets. Phase 2 tests limits. Phase 3 tunes visual behavior for larger charts.

### Pitfall 15: PPTX Dependency Drift Breaks Rendering
**What goes wrong:** `requirements.txt` has no pinned versions and no PPTX package. Adding a renderer without pinning can make builds change behavior around chart XML, image sizing, zip output, or relationship names.
**Warning signs:** `requirements.txt` adds `python-pptx` or another renderer without a version; CI and local generated decks differ; tests assert only that bytes exist; rebuilds alter slide XML without code changes.
**Prevention:** Pick one renderer, pin it, and wrap it behind a small internal API. Add deterministic fixture tests that compare extracted slide text and key package structure rather than raw binary bytes. Keep renderer-specific code out of `streamlit_app.py`.
**Phase to address:** Phase 2 owns renderer choice and version pinning.

### Pitfall 16: Cross-Scenario Data Or Template Leakage
**What goes wrong:** Scenario selection is central in `src/config/scenarios.py`, while memory, evaluation, semantic layers, and backend settings all depend on the active scenario. PPTX export can accidentally mix Wuerth local data, demo TPC-H labels, Databricks metadata, or memory templates if it reads global state late or uses cached records incorrectly.
**Warning signs:** Deck footer names a different scenario than the sidebar; Wuerth export shows TPC-H table names; memory template IDs from `memory/demo/` appear in a Wuerth run; generated filenames lack scenario or run ID; tests do not switch scenarios.
**Prevention:** Bind scenario, dataset, source tables, and run ID into the presentation spec at export time from the orchestrator result. Do not let the PPTX renderer query active scenario state independently except for locating the template asset. Add tests that generate records for two scenarios and verify isolation.
**Phase to address:** Phase 1 for spec shape. Phase 2 for scenario-isolation tests. Phase 4 for memory retrieval scope.

## Minor Pitfalls

### Pitfall 17: Raw SQL In Decks Becomes The User-Facing Product
**What goes wrong:** Users may forward decks to people who do not understand SQL. If raw SQL is prominent, the deck feels like a developer artifact instead of a management-ready output.
**Warning signs:** First slide contains SQL; source-table slides are longer than the insight slide; business caveats are missing while query internals are present.
**Prevention:** Keep SQL in an optional technical appendix or omit it by default. Put source tables and caveats in small footer or appendix sections. Lead with `reporting_result["summary"]`, KPI cards, and supported visuals.
**Phase to address:** Phase 1 for deck information architecture. Phase 6 for documentation examples.

### Pitfall 18: Download UI Allows Export From Invalid Records
**What goes wrong:** `streamlit_app.py` can render failed records, SQL errors, and retry flows. A PowerPoint button added near CSV/XLSX downloads could become visible for records that have no successful SQL result.
**Warning signs:** PPTX button appears when `execution_success` is false; exports are possible for clarification or safety-block responses; generated decks contain "(kein SQL erzeugt)" or empty tables.
**Prevention:** Gate export on `execution_success`, `validation_success`, non-empty `reporting_result`, and supported result shape. Show the blocked reason instead of a disabled silent button.
**Phase to address:** Phase 1 defines eligibility. Phase 2 tests failed, unsafe, and empty states.

### Pitfall 19: Documentation Overstates Wuerth Data Completeness
**What goes wrong:** The Wuerth local semantic layer marks revenue, turnover, packing cost, shipment date, plant, shipping point, and some join assumptions as unavailable or needing confirmation. A polished PPTX export can make prototype answers look more complete than the source data supports.
**Warning signs:** Final docs use screenshots or decks with unavailable KPIs; limitation slides are omitted; demo guide does not explain unsupported metrics; business users ask for revenue or packing cost and receive a chart instead of a limitation.
**Prevention:** Put data limitations into final docs and into generated limitation slides. Keep unsupported KPI behavior explicit in `src/agent/langgraph_sql_agent.py` and tests such as `evaluation/test_wuerth_local_scenario.py`.
**Phase to address:** Phase 6 owns docs. Phase 1 ensures export supports limitation slides.

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|----------------|------------|
| PowerPoint export contract | Template drift, unsupported result shapes, invalid export eligibility. | Define a presentation spec before writing PPTX bytes. Test against `assets/templates/PPT_Vorlage_Wuerth.pptx`. |
| PPTX renderer | Font overflow, broken relationships, no-PowerPoint test gap. | Use file-level package tests, text extraction, manifest validation, and strict content budgets. |
| Complex visuals | Divergence between Altair UI charts and PPTX visuals. | Extend `src/agent/visualization_spec.py` first, then render the same spec in Streamlit and PPTX. |
| Memory governance | Stale or malicious templates enter prompts. | Add role checks, audit actor/role, active approved-only retrieval, and visible retrieval trace metadata. |
| Security and privacy | Raw SQL, prompts, logs, and hidden slide content leak. | Redact logs, define deck content policy, strip hidden notes, and keep raw SQL optional. |
| Streamlit integration | Export logic increases monolith risk. | Keep `streamlit_app.py` as a thin trigger around `src/agent/presentation_export.py`. |
| Final documentation | Docs claim features that are conceptual or stale. | Map every claim to implemented paths and refreshed tests before final docs are marked complete. |

## Sources

- `.planning/PROJECT.md`
- `.planning/codebase/CONCERNS.md`
- `.planning/codebase/TESTING.md`
- `.planning/codebase/INTEGRATIONS.md`
- `.planning/codebase/ARCHITECTURE.md`
- `streamlit_app.py`
- `src/agent/reporting_agent.py`
- `src/agent/visualization_spec.py`
- `src/agent/memory_store.py`
- `src/agent/memory_retriever.py`
- `src/agent/logging_utils.py`
- `requirements.txt`
