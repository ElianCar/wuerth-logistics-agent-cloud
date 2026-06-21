# Roadmap: Wuerth Logistics Agent Presentation Export

## Overview

This roadmap turns successful Wuerth logistics analysis results into deterministic, Wuerth-branded PowerPoint output. The project uses vertical MVP slices: first a backend deck export path, then the Streamlit download surface, then readable evidence handling, then memory governance, and finally documentation and demo readiness. Config mode is `yolo`, but traceability, tests, and verification gates stay explicit.

## Scope Guardrails

- Issue #7 is excluded because golden-question evaluation already exists for this scope.
- Issues #5, #6, #8, and #21 are included in v1.
- The old `add-reporting-agent` branch is not a merge target. It can be used only as reference material.
- The Wuerth template path is `assets/templates/PPT_Vorlage_Wuerth.pptx`.
- A simplified clean Wuerth master is preferred: keep branding, masters, fonts, colors, logos, footers, and stable placeholders; remove embedded OLE objects, linked sample charts, and old sample content where practical.
- Direct Claude or Opus `.pptx` generation is out of v1 production scope. Future LLM use can only produce validated slide-spec JSON before deterministic local rendering.
- Streamlit uses a `Create PPT` action while generation runs, then exposes `Download PPT` only after a deck has been created.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions marked with INSERTED

- [ ] **Phase 1: Deterministic Backend Deck Slice** - Backend code can validate export eligibility and render a deterministic Wuerth PPTX from a successful record.
- [ ] **Phase 2: Streamlit Downloadable Deck Slice** - Users can download a Wuerth deck from a successful Streamlit analysis run.
- [ ] **Phase 3: Readable Evidence And Fallback Slice** - Evidence slides stay readable through truncation, top-N handling, and explicit fallbacks.
- [ ] **Phase 4: Memory Governance And RBAC Slice** - Approved memory use becomes traceable and memory-template actions are role-controlled.
- [ ] **Phase 5: Final Docs And Demo Slice** - Users can understand, run, demo, and explain the implemented Wuerth PPT export path.

## Phase Details

### Phase 1: Deterministic Backend Deck Slice

**Goal:** A successful validated orchestrator record can be turned into deterministic Wuerth PPTX bytes by a backend module, and invalid records fail clearly.
**Mode:** mvp
**Depends on:** Nothing (first phase)
**Requirements:** PPT-02, PPT-03, PPT-06, PPT-07, SPEC-01, SPEC-02, SPEC-03, SPEC-04, TEST-01, TEST-02, TEST-03
**Success Criteria** (what must be TRUE):

  1. A successful validated record resolves `assets/templates/PPT_Vorlage_Wuerth.pptx` through a repo-relative path, validates the usable master/layout assumptions, and produces a non-empty PPTX from backend code.
  2. Failed SQL, unsafe SQL, clarification-only responses, missing results, and unvalidated runs return export-unavailable reasons before rendering starts.
  3. A missing or unreadable template produces a clear error that Streamlit can display without crashing.
  4. Slide spec validation accepts only supported slide types, required fields, content budgets, table limits, chart limits, and deterministic renderer inputs.
  5. Direct LLM-generated PPTX files are impossible in the v1 production path.

**Verification approach:** Add focused `unittest` coverage for export eligibility, template path resolution, missing-template behavior, deterministic spec validation, and PPTX creation that can be opened by the chosen Python library without Microsoft PowerPoint.
**Plans:** 1/3 plans executed
Plans:

**Wave 1**

- [x] 01-01-PLAN.md - Verify deterministic PPTX renderer dependency gate

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 01-02-PLAN.md - Build successful-record backend PPTX export slice

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 01-03-PLAN.md - Harden eligibility, missing-template, and template safety behavior

### Phase 2: Streamlit Downloadable Deck Slice

**Goal:** Users can export a successful Streamlit analysis run as a Wuerth PowerPoint deck containing the core analysis narrative and evidence.
**Mode:** mvp
**Depends on:** Phase 1
**Requirements:** PPT-01, PPT-04, VIS-01, VIS-02
**Success Criteria** (what must be TRUE):

  1. User can click `Create PPT` after a successful validated analysis run, see generation progress, and then download the created `.pptx` through `Download PPT`.
  2. Generated deck includes a title or takeaway slide, result summary, KPI or key metric section, chart or table evidence, caveats or limitations, source tables, and run metadata.
  3. Simple bar and line chart evidence exports when the current `visualization_spec.py` contract marks the chart as renderable.
  4. PowerPoint chart eligibility uses the same deterministic rules as the Streamlit chart path.

**Verification approach:** Run backend export tests plus a manual Streamlit success-run check that confirms the download button, filename, MIME type, deck content, and absence of PPTX rendering logic from Streamlit callbacks.
**Plans:** TBD
**UI hint:** yes

### Phase 3: Readable Evidence And Fallback Slice

**Goal:** Users can export readable evidence slides even when result rows, labels, text, or chart shapes would otherwise overflow.
**Mode:** mvp
**Depends on:** Phase 2
**Requirements:** PPT-05, VIS-03, VIS-04, TEST-04
**Success Criteria** (what must be TRUE):

  1. Evidence tables preserve SQL result order and clearly mark row or column truncation.
  2. Unsupported chart shapes fall back to a table or limitation slide with a visible reason.
  3. Top-N categorical comparisons render as readable presentation output without slide overflow, with deterministic validators deciding whether horizontal bars, grouped or stacked bars, simple multi-line charts, or Pareto-style concentration views are safe for the result shape.
  4. Long text, empty result, unsupported chart shape, and table truncation cases are covered by automated tests.

**Verification approach:** Run presentation export tests with long text, empty results, unsupported charts, and top-N categorical data, then inspect generated sample deck text for truncation notes and fallback reasons.
**Plans:** TBD

### Phase 4: Memory Governance And RBAC Slice

**Goal:** Approved memory templates can influence future runs in a traceable way, while memory-template actions are controlled by backend role checks.
**Mode:** mvp
**Depends on:** Phase 3
**Requirements:** MEM-01, MEM-02, MEM-03, MEM-04, MEM-05, MEM-06, RBAC-01, RBAC-02, RBAC-03, RBAC-04, RBAC-05, RBAC-06, TEST-05, TEST-06
**Success Criteria** (what must be TRUE):

  1. Approved active templates expose intent, trigger phrases, KPIs, entities, source tables, assumptions, scenario, and dataset metadata where available.
  2. Retrieval uses router memory intent or an equivalent router-derived key when available, filters to the active scenario and dataset, and returns at most three approved active templates.
  3. Run trace, logs, or reporting audit output shows retrieved template IDs when approved templates influence a run.
  4. Generated memory candidates are never used as prompt guidance before review approval.
  5. Viewer, Contributor, Reviewer, and Admin permissions block unauthorized backend actions and log action, role, timestamp, and template or candidate ID.

**Verification approach:** Add memory retrieval and RBAC `unittest` coverage for approved-active filtering, cap behavior, trace exposure, generated-candidate exclusion, backend authorization blocks, and audit fields.
**Plans:** TBD

### Phase 5: Final Docs And Demo Slice

**Goal:** Users can understand the implemented architecture, known limits, demo flow, and business value of the Wuerth PowerPoint export without reading source code.
**Mode:** mvp
**Depends on:** Phase 4
**Requirements:** DOC-01, DOC-02, DOC-03, DOC-04, DOC-05
**Success Criteria** (what must be TRUE):

  1. Documentation contains a final architecture diagram covering router, SQL agent, reporting layer, semantic layer, memory, backend adapters, Databricks, Streamlit, and PowerPoint export.
  2. Documentation separates implemented behavior from conceptual or future work, including the v1 exclusion of direct Claude-generated PPTX files.
  3. Documentation states Wuerth local source-data limitations and the supported explicit limitation behavior.
  4. Documentation includes short demo instructions for running the app and exporting a Wuerth PowerPoint.
  5. Documentation explains the business value as reduced manual analysis and presentation preparation effort.

**Verification approach:** Review docs against implemented files, run the documented demo commands where practical, and confirm every stated limitation maps to current semantic layer or code behavior.
**Plans:** TBD

## Requirement Coverage

| Requirement | Phase |
|-------------|-------|
| PPT-01 | Phase 2 |
| PPT-02 | Phase 1 |
| PPT-03 | Phase 1 |
| PPT-04 | Phase 2 |
| PPT-05 | Phase 3 |
| PPT-06 | Phase 1 |
| PPT-07 | Phase 1 |
| SPEC-01 | Phase 1 |
| SPEC-02 | Phase 1 |
| SPEC-03 | Phase 1 |
| SPEC-04 | Phase 1 |
| VIS-01 | Phase 2 |
| VIS-02 | Phase 2 |
| VIS-03 | Phase 3 |
| VIS-04 | Phase 3 |
| MEM-01 | Phase 4 |
| MEM-02 | Phase 4 |
| MEM-03 | Phase 4 |
| MEM-04 | Phase 4 |
| MEM-05 | Phase 4 |
| MEM-06 | Phase 4 |
| RBAC-01 | Phase 4 |
| RBAC-02 | Phase 4 |
| RBAC-03 | Phase 4 |
| RBAC-04 | Phase 4 |
| RBAC-05 | Phase 4 |
| RBAC-06 | Phase 4 |
| DOC-01 | Phase 5 |
| DOC-02 | Phase 5 |
| DOC-03 | Phase 5 |
| DOC-04 | Phase 5 |
| DOC-05 | Phase 5 |
| TEST-01 | Phase 1 |
| TEST-02 | Phase 1 |
| TEST-03 | Phase 1 |
| TEST-04 | Phase 3 |
| TEST-05 | Phase 4 |
| TEST-06 | Phase 4 |

**Coverage:** 38/38 v1 requirements mapped exactly once.

## Progress

**Execution Order:**
Phases execute in numeric order: 1, 2, 3, 4, 5.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Deterministic Backend Deck Slice | 1/3 | In Progress | - |
| 2. Streamlit Downloadable Deck Slice | 0/TBD | Not started | - |
| 3. Readable Evidence And Fallback Slice | 0/TBD | Not started | - |
| 4. Memory Governance And RBAC Slice | 0/TBD | Not started | - |
| 5. Final Docs And Demo Slice | 0/TBD | Not started | - |
