# Phase 1: Deterministic Backend Deck Slice - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Source:** User guidance during `$gsd-plan-phase 1`

<domain>
## Phase Boundary

Phase 1 delivers a backend-only PowerPoint export capability. A successful validated orchestrator record must become deterministic Wuerth PPTX bytes through a backend module. Invalid records must be rejected before rendering.

This phase does not need the final Streamlit `Create PPT` and `Download PPT` interaction. That belongs to Phase 2. However, Phase 1 must return errors, warnings, and bytes in a shape Streamlit can consume later.
</domain>

<decisions>
## Implementation Decisions

### Dynamic Slide Generation

- The deck generator must not always produce all 9 template layouts.
- Slide creation must be dynamic: include only slides supported by the available analysis content.
- The same layout can be used multiple times when needed, especially `Agent 04 Chart Evidence` and `Agent 05 Table Evidence`.
- Longer decks with readable repeated evidence slides are preferred over overcrowded slides.
- `Agent 09 Closing` is optional and should be controlled by the deck contract, not hardcoded into every deck.

### Template Contract

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

### Think-Cell OLE Caveat

- The template still contains 2 think-cell OLE embeddings.
- Manual removal was not practical.
- Phase 1 should warn about embedded OLE entries during template validation, but should not fail generation solely because they exist.
- Macros or external relationships should remain blocking template safety findings.

### Rendering Approach

- Direct Claude or Opus-generated `.pptx` files are out of scope.
- Runtime LLM-generated Python code is out of scope.
- The v1 path must be deterministic local rendering from a validated slide spec.
- Optional LLM slide planning is deferred and, if added later, may only produce schema-constrained slide-spec JSON that passes local validation before rendering.

### Brownfield MVP Interpretation

- MVP mode means a thin vertical PPT export slice in the existing app architecture.
- Do not plan a generic walking skeleton for project scaffold, routing, database, and deployment. This repository already has the application skeleton.
- The first implementation slice should prove: successful record input -> dynamic slide deck spec -> validated Wuerth PPTX bytes -> tests can open the file without Microsoft PowerPoint.

### the agent's Discretion

- Choose exact Python model types, dataclass names, error classes, and helper function names that match existing repo style.
- Choose whether to use pydantic or frozen dataclasses for the first slide spec contract, as long as validation is deterministic and testable.
- Decide whether generated chart evidence in Phase 1 is represented as native PowerPoint charts, table fallback, or placeholder-safe text, as long as Phase 2 can extend it without rewriting the contract.
</decisions>

<canonical_refs>
## Canonical References

Downstream agents must read these before planning or implementing.

### Planning

- `.planning/ROADMAP.md` - Phase 1 goal, success criteria, and requirement mapping.
- `.planning/REQUIREMENTS.md` - Phase 1 requirement IDs and test requirements.
- `.planning/PPT_TEMPLATE_GUIDE.md` - Wuerth master layout subset, dynamic deck rule, and placeholder targeting guidance.
- `.planning/research/SUMMARY.md` - Project research conclusion: deterministic local renderer, no direct Claude PPTX generation.

### Codebase

- `.planning/codebase/ARCHITECTURE.md` - Existing Streamlit, orchestrator, reporting, memory, and backend boundaries.
- `.planning/codebase/STRUCTURE.md` - File ownership and likely module placement.
- `.planning/codebase/TESTING.md` - Existing `unittest` style and verification commands.
- `src/agent/orchestrator.py` - Source of successful result records.
- `src/agent/reporting_agent.py` - Deterministic summary, KPI, caveat, table, chart, and audit source.
- `src/agent/visualization_spec.py` - Shared chart eligibility contract.
- `streamlit_app.py` - Future Phase 2 consumer of backend export result.
- `assets/templates/PPT_Vorlage_Wuerth.pptx` - Required Wuerth master template.
</canonical_refs>

<specifics>
## Specific Ideas

- Build a `SlideDeckSpec` or equivalent object containing an ordered list of slide specs, not one fixed field per slide.
- Make slide inclusion conditional on content availability.
- Use explicit unavailable reasons for failed SQL, unsafe SQL, clarification-only responses, missing query results, and unvalidated records.
- Return structured warnings for non-fatal template issues such as remaining think-cell OLE embeddings.
- Include tests that verify a generated PPTX can be opened by the chosen Python library without Microsoft PowerPoint.
</specifics>

<deferred>
## Deferred Ideas

- Streamlit `Create PPT` and `Download PPT` UX is Phase 2.
- Richer chart selection and top-N readability work is Phase 3.
- Memory governance and RBAC are Phase 4.
- Final architecture and demo docs are Phase 5.
</deferred>

---

*Phase: 01-deterministic-backend-deck-slice*
*Context gathered: 2026-06-21 from user planning guidance*
