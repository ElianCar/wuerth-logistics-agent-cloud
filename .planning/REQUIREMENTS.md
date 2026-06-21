# Requirements: Wuerth Logistics Agent Presentation Export

**Defined:** 2026-06-21
**Core Value:** Users can turn a validated logistics analysis result into a clear Wuerth-branded PowerPoint output with minimal manual cleanup.

## v1 Requirements

### Presentation Export

- [x] **PPT-01**: User can export a successful validated analysis run as a `.pptx` file from Streamlit.
- [x] **PPT-02**: Export uses the tracked Wuerth master template at `assets/templates/PPT_Vorlage_Wuerth.pptx` through a repo-relative path.
- [x] **PPT-03**: Export is blocked for failed SQL, unsafe SQL, clarification-only responses, missing query results, or unvalidated runs.
- [x] **PPT-04**: Generated deck includes a title or takeaway slide, result summary, KPI or key metric section, chart or table evidence, caveats or limitations, source tables, and run metadata.
- [ ] **PPT-05**: Generated deck preserves SQL result order for evidence tables and clearly marks row or column truncation.
- [x] **PPT-06**: Missing or unreadable PPT template produces a clear user-facing error and does not crash the Streamlit app.
- [x] **PPT-07**: Export logic is implemented in a testable backend module, not embedded in Streamlit callbacks.

### Slide Contract

- [x] **SPEC-01**: A fixed slide-generation contract defines allowed slide types, required fields, text budgets, table limits, chart limits, and fallback behavior.
- [x] **SPEC-02**: Slide spec validation rejects unsupported result shapes before PPT rendering.
- [x] **SPEC-03**: Deck generation uses deterministic local rendering rather than direct LLM-generated PPTX files.
- [x] **SPEC-04**: Optional LLM use, if added later, is limited to schema-constrained slide-spec JSON and still passes local validation before rendering.

### Visualization

- [x] **VIS-01**: PowerPoint export reuses the same chart eligibility rules as `src/agent/visualization_spec.py`.
- [x] **VIS-02**: User can export simple bar and line chart evidence when the current chart spec is renderable.
- [ ] **VIS-03**: Unsupported chart shapes fall back to a table or limitation slide with a reason.
- [ ] **VIS-04**: Presentation output can handle top-N categorical comparisons without unreadable slide overflow.

### Memory Governance

- [ ] **MEM-01**: Approved memory templates include intent, trigger phrases, KPIs, entities, source tables, and assumptions where available.
- [ ] **MEM-02**: Template retrieval uses router memory intent or an equivalent router-derived key when available.
- [ ] **MEM-03**: Retrieval only returns approved and active templates for the active scenario and dataset.
- [ ] **MEM-04**: Retrieval is capped to a small number of templates, maximum three.
- [ ] **MEM-05**: Retrieved template IDs are visible in run trace, logs, or reporting audit output.
- [ ] **MEM-06**: Generated memory candidates are never used automatically as prompt guidance before review approval.

### Memory RBAC

- [ ] **RBAC-01**: System defines Viewer, Contributor, Reviewer, and Admin roles for memory-template actions.
- [ ] **RBAC-02**: Contributor can create template candidates but cannot approve, deactivate, reactivate, or manage roles.
- [ ] **RBAC-03**: Reviewer can approve, reject, or request changes for template candidates.
- [ ] **RBAC-04**: Admin can deactivate and reactivate templates and manage memory roles.
- [ ] **RBAC-05**: Unauthorized memory-template actions are blocked by backend checks, not only hidden in the UI.
- [ ] **RBAC-06**: Template changes are logged with action, role, timestamp, and template or candidate ID.

### Documentation

- [ ] **DOC-01**: Documentation contains a final architecture diagram with router, SQL agent, reporting layer, semantic layer, memory, backend adapters, Databricks, Streamlit, and PowerPoint export.
- [ ] **DOC-02**: Documentation explains which components are implemented and which remain conceptual or future work.
- [ ] **DOC-03**: Documentation states known source-data limitations for Wuerth local data and supported explicit limitation behavior.
- [ ] **DOC-04**: Documentation includes short demo instructions for running the app and exporting a PowerPoint.
- [ ] **DOC-05**: Documentation explains business value in terms of reduced manual analysis and presentation preparation effort.

### Tests

- [x] **TEST-01**: Tests verify PPT template path resolution and missing-template failure behavior.
- [x] **TEST-02**: Tests verify a generated PPTX file is created, non-empty, and openable by the chosen Python library without local Microsoft PowerPoint.
- [x] **TEST-03**: Tests verify export eligibility blocks failed, unsafe, clarification-only, and unvalidated records.
- [ ] **TEST-04**: Tests verify long text, empty result, unsupported chart shape, and table truncation behavior.
- [ ] **TEST-05**: Tests verify memory RBAC blocks unauthorized backend actions.
- [ ] **TEST-06**: Tests verify memory retrieval returns only approved active templates and exposes used template IDs.

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced Slides

- **ADV-01**: User can include grouped bars, multi-line trends, heatmaps, or other richer visuals when result shape is deterministic and readable.
- **ADV-02**: User can choose between multiple deck layouts or slide ordering presets.
- **ADV-03**: User can include a generated appendix with full audit details and SQL provenance.

### LLM Slide Planning

- **LLM-01**: Claude can produce schema-constrained slide-spec JSON from sanitized, capped context.
- **LLM-02**: LLM-generated slide specs are validated locally and rendered deterministically.
- **LLM-03**: LLM slide planning records prompt context, model, validation warnings, and fallback behavior.

### Governance

- **GOV-01**: App-wide authentication protects all Streamlit pages and export actions.
- **GOV-02**: Memory roles persist per user identity rather than through a local prototype role selector.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Direct Claude-generated PowerPoint files | Harder to reproduce, validate, and keep faithful to the Wuerth template. |
| Runtime LLM-generated Python code for slide creation | Unsafe and difficult to test. |
| Arbitrary slide designer | Too broad for a reliable v1 export path. |
| Full BI dashboard export | The goal is repeatable analysis-to-PowerPoint output. |
| App-wide production authentication | Only memory-template action RBAC is in v1 scope. |
| Solving missing Wuerth source-data fields | Missing revenue, packing cost, shipment-date, plant, and currency fields must be documented as limitations. |
| Reimplementing evaluation issue #7 | Golden questions and evaluation infrastructure already exist. |
| Merging stale reporting branch as-is | It would remove newer routing, orchestration, visualization, and Wuerth-local code. |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PPT-01 | Phase 2 | Complete |
| PPT-02 | Phase 1 | Complete |
| PPT-03 | Phase 1 | Complete |
| PPT-04 | Phase 2 | Complete |
| PPT-05 | Phase 3 | Pending |
| PPT-06 | Phase 1 | Complete |
| PPT-07 | Phase 1 | Complete |
| SPEC-01 | Phase 1 | Complete |
| SPEC-02 | Phase 1 | Complete |
| SPEC-03 | Phase 1 | Complete |
| SPEC-04 | Phase 1 | Complete |
| VIS-01 | Phase 2 | Complete |
| VIS-02 | Phase 2 | Complete |
| VIS-03 | Phase 3 | Pending |
| VIS-04 | Phase 3 | Pending |
| MEM-01 | Phase 4 | Pending |
| MEM-02 | Phase 4 | Pending |
| MEM-03 | Phase 4 | Pending |
| MEM-04 | Phase 4 | Pending |
| MEM-05 | Phase 4 | Pending |
| MEM-06 | Phase 4 | Pending |
| RBAC-01 | Phase 4 | Pending |
| RBAC-02 | Phase 4 | Pending |
| RBAC-03 | Phase 4 | Pending |
| RBAC-04 | Phase 4 | Pending |
| RBAC-05 | Phase 4 | Pending |
| RBAC-06 | Phase 4 | Pending |
| DOC-01 | Phase 5 | Pending |
| DOC-02 | Phase 5 | Pending |
| DOC-03 | Phase 5 | Pending |
| DOC-04 | Phase 5 | Pending |
| DOC-05 | Phase 5 | Pending |
| TEST-01 | Phase 1 | Complete |
| TEST-02 | Phase 1 | Complete |
| TEST-03 | Phase 1 | Complete |
| TEST-04 | Phase 3 | Pending |
| TEST-05 | Phase 4 | Pending |
| TEST-06 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 38 total
- Mapped to phases: 38
- Unmapped: 0
- Duplicate mappings: 0

---
*Requirements defined: 2026-06-21*
*Last updated: 2026-06-21 after roadmap creation*
