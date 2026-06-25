---
phase: 03-readable-evidence-and-fallback-slice
plan: 01
subsystem: presentation-export
tags: [python, unittest, powerpoint, planner, evidence, visualization]

requires:
  - phase: 02-streamlit-downloadable-deck-slice
    provides: Streamlit can request backend PPTX export for successful validated records.
provides:
  - Pure deterministic presentation planner module
  - German title and management number formatting helpers
  - SQL-order evidence table page plans with row and column truncation notes
  - W05-style evidence profile bullets and top-N categorical chart plans
  - Unsupported chart and empty-result fallback planning metadata
affects: [presentation_export, phase-03-rendering, powerpoint-evidence, visualization]

tech-stack:
  added: []
  patterns:
    - Frozen dataclass planner contracts with explicit to_dict serialization
    - Pure post-SQL planner that imports no Streamlit, pptx, database, or model clients
    - Deterministic top-N categorical evidence with Sonstige aggregation

key-files:
  created:
    - src/agent/presentation_planner.py
  modified:
    - evaluation/test_presentation_export.py

key-decisions:
  - "Use a pure deterministic planner module before renderer integration."
  - "Duplicate the existing table budget values in the pure planner instead of importing presentation_export.py, preserving import isolation."
  - "Keep zero-row PPT export eligibility owned by can_export_presentation while allowing deterministic empty-result planning."

patterns-established:
  - "PresentationPlan.to_dict() is the stable JSON-serializable handoff shape for later renderer integration."
  - "EvidenceTablePage preserves SQL row order by slicing normalized result rows without sorting."
  - "PlanningAudit records planning_mode, selected chart types, truncation flags, warnings, and fallback reasons."

requirements-completed: [PPT-05, VIS-03, VIS-04, TEST-04]

duration: 8 min
completed: 2026-06-22
---

# Phase 03 Plan 01: Deterministic Presentation Planner Summary

**Pure German presentation planning layer with SQL-order evidence pages, W05 profiles, top-N Sonstige charts, and fallback audit metadata.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-22T10:55:57Z
- **Completed:** 2026-06-22T11:03:10Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `src/agent/presentation_planner.py` as a pure backend planner with frozen dataclasses and explicit `to_dict()` helpers.
- Added deterministic German title derivation and German management number formatting for counts, decimals, percentages, millions, and billions.
- Added evidence planning for SQL-order table pages, W05-like order/material/ship-to profiles, unsupported chart fallbacks, empty result planning, and top-N categorical charts with `Sonstige`.
- Extended `evaluation/test_presentation_export.py` with contract and evidence planner regression tests.

## Task Commits

Each task was committed through RED and GREEN TDD gates:

1. **Task 1 RED: planner contract tests** - `e0f552d` (test)
2. **Task 1 GREEN: planner contract helpers** - `cc9783a` (feat)
3. **Task 2 RED: planner evidence tests** - `278bcef` (test)
4. **Task 2 GREEN: deterministic evidence planner** - `cd7459c` (feat)

**Plan metadata:** pending final docs commit

## Files Created/Modified

- `src/agent/presentation_planner.py` - New deterministic planner contract, formatter helpers, table page planner, W05 profile extraction, chart fallback planning, and top-N categorical evidence planning.
- `evaluation/test_presentation_export.py` - Added `PresentationPlannerContractTests`, `PresentationPlannerEvidenceTests`, and W05 planner fixtures.

## Decisions Made

- Use a pure planner module instead of expanding `presentation_export.py`, keeping renderer and PPTX imports out of planner tests.
- Duplicate the current export table budgets in the planner to avoid importing `presentation_export.py`, because that module imports `pptx`.
- Keep empty-result export eligibility unchanged. `build_presentation_plan()` is deterministic for empty results, while `can_export_presentation()` still blocks zero-row deck export.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Authentication Gates

None.

## Known Stubs

None. Scoped scan found no new TODO, FIXME, placeholder, coming soon, or not available text in the planner changes. Empty defaults in dataclasses and tests are intentional contract defaults.

## TDD Gate Compliance

- RED gate present for Task 1: `e0f552d`
- GREEN gate present for Task 1: `cc9783a`
- RED gate present for Task 2: `278bcef`
- GREEN gate present for Task 2: `cd7459c`

## Verification

- `.\.venv\Scripts\python.exe -m unittest evaluation.test_presentation_export.PresentationPlannerContractTests -v` - PASS, 5 tests.
- `.\.venv\Scripts\python.exe -m unittest evaluation.test_presentation_export.PresentationPlannerEvidenceTests -v` - PASS, 5 tests.
- `.\.venv\Scripts\python.exe -m unittest evaluation.test_presentation_export.PresentationPlannerContractTests evaluation.test_presentation_export.PresentationPlannerEvidenceTests -v` - PASS, 10 tests.
- `.\.venv\Scripts\python.exe -m compileall src/agent/presentation_planner.py evaluation/test_presentation_export.py` - PASS.
- Extra regression: `.\.venv\Scripts\python.exe -m unittest evaluation.test_presentation_export -v` - PASS, 33 tests.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for `03-02`: renderer integration can consume `PresentationPlan`, render German slide labels and notes, and add rich text or top-N chart image handling without changing Streamlit.

## Self-Check: PASSED

- Created file exists: `src/agent/presentation_planner.py`
- Modified test file exists: `evaluation/test_presentation_export.py`
- Task commits found: `e0f552d`, `cc9783a`, `278bcef`, `cd7459c`
- No tracked file deletions were introduced.

---
*Phase: 03-readable-evidence-and-fallback-slice*
*Completed: 2026-06-22*
