---
phase: 03-readable-evidence-and-fallback-slice
plan: 03
subsystem: presentation-export
tags: [presentation-planning, json-validation, deterministic-fallback, unittest]

requires:
  - phase: 03-readable-evidence-and-fallback-slice
    provides: "03-02 rendered deterministic evidence and top-n charts into the PowerPoint export path"
provides:
  - "Disabled-by-default JSON presentation planning boundary"
  - "Bounded and sanitized planner payload construction"
  - "Strict JSON planner validation with deterministic fallback audit metadata"
  - "Fake-tested export fallback propagation"
affects: [presentation-export, reporting-output, streamlit-download]

tech-stack:
  added: []
  patterns:
    - "Optional planner invocation is dependency-injected and disabled unless PRESENTATION_PLANNING_MODE=llm"
    - "Planner JSON is parsed and validated before mutating PresentationPlan output"
    - "Export metadata carries planner fallback reasons and warning codes"

key-files:
  created:
    - .planning/phases/03-readable-evidence-and-fallback-slice/03-03-SUMMARY.md
  modified:
    - src/agent/presentation_planner.py
    - src/agent/presentation_export.py
    - evaluation/test_presentation_export.py
    - .env.example

key-decisions:
  - "Keep deterministic presentation planning as the default export path."
  - "Allow JSON planning only through explicit PRESENTATION_PLANNING_MODE=llm plus an injected invocation function."
  - "Treat any invalid, malformed, refused, unsupported, exception, or over-budget planner output as a deterministic fallback with audit metadata."

patterns-established:
  - "Planner payloads include only question, SQL, reporting metadata, capped rows, column profiles, aggregates, and deterministic defaults."
  - "Presentation export callers can pass planner config and fake invocation without introducing live LLM dependencies."

requirements-completed: [VIS-03, TEST-04]

duration: 11min
completed: 2026-06-22
---

# Phase 03 Plan 03: JSON Presentation Planning Boundary Summary

**Optional schema-constrained presentation planning with deterministic default behavior and safe fallback metadata.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-06-22T11:23:38Z
- **Completed:** 2026-06-22T11:34:59Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added `PresentationPlanningConfig.from_env()` with deterministic default mode and non-secret planner toggles in `.env.example`.
- Added a bounded planner payload and strict JSON validation boundary that accepts fake planner output only after schema, budget, chart, table, and audit checks.
- Integrated planner fallback warnings and audit metadata into presentation export while keeping `build_deterministic_presentation_export()` available.
- Added fake-only unit coverage for valid JSON planning and fallback cases without calling Anthropic, Gemini, OpenAI, Databricks, or local PowerPoint.

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: JSON planning boundary tests** - `6b620e9` (test)
2. **Task 1 GREEN: Optional JSON planner boundary** - `6c947e1` (feat)
3. **Task 2 RED: Export fallback propagation tests** - `e4899b4` (test)
4. **Task 2 GREEN: Export fallback propagation** - `496d795` (feat)

**Plan metadata:** pending docs commit.

_Note: TDD tasks used separate RED and GREEN commits._

## Files Created/Modified

- `src/agent/presentation_planner.py` - Added planner config, sanitized payload creation, strict JSON parsing, local validation, and deterministic fallback audit metadata.
- `src/agent/presentation_export.py` - Threaded optional planner config and invocation through export builders and exposed fallback metadata on `SlideDeckSpec`.
- `evaluation/test_presentation_export.py` - Added `PresentationPlanningJsonModeTests` with fake planner coverage for valid and fallback paths.
- `.env.example` - Documented non-secret planner toggles while recommending deterministic export mode.
- `.planning/phases/03-readable-evidence-and-fallback-slice/03-03-SUMMARY.md` - Captures execution record and verification results.

## Decisions Made

- Deterministic planning remains the normal export path because presentation export should not spend tokens or depend on provider availability by default.
- `PRESENTATION_PLANNING_MODE=llm` is the only path that can call the injected invocation function, which keeps tests fake-only and leaves provider wiring outside this boundary.
- JSON planner output must pass local validation before it can affect the `PresentationPlan`; all unsafe or unusable outputs fall back to the deterministic plan with warnings.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The linked-worktree branch gate was explicitly relaxed by the user for this run because project config has `workflow.use_worktrees=false` and execution is sequential on `codex/remaining-github-issues`.
- A malformed manual stub-scan command produced excessive read-only output outside the intended file set. It did not edit files, and the process was stopped before continuing.

## Known Stubs

None. Existing `placeholder` text in touched files belongs to template-placeholder handling and tests, not incomplete UI or data plumbing.

## Auth Gates

None.

## User Setup Required

None. The optional planner toggles are non-secret and documented in `.env.example`; deterministic export remains recommended.

## Verification

- `.\.venv\Scripts\python.exe -m unittest evaluation.test_presentation_export.PresentationPlanningJsonModeTests -v` - PASS, 7 tests
- `.\.venv\Scripts\python.exe -m unittest evaluation.test_presentation_export.PresentationPlanningJsonModeTests evaluation.test_presentation_export.PresentationExportPlanRenderingTests -v` - PASS, 12 tests
- `.\.venv\Scripts\python.exe -m unittest evaluation.test_presentation_export.PresentationExportSuccessTests -v` - PASS, 9 tests
- `.\.venv\Scripts\python.exe -m unittest evaluation.test_presentation_export -v` - PASS, 50 tests
- `.\.venv\Scripts\python.exe -m compileall src/agent/presentation_planner.py src/agent/presentation_export.py evaluation/test_presentation_export.py` - PASS

## TDD Gate Compliance

- RED gate: `6b620e9` and `e4899b4`
- GREEN gate: `6c947e1` and `496d795`
- Refactor gate: not needed

## Next Phase Readiness

Plan 03-04 can build on a deterministic-first export path with optional fake-tested JSON planner validation already isolated behind configuration and injection.

## Self-Check: PASSED

- Summary file exists.
- Plan-owned source, test, and config files exist.
- Task commits `6b620e9`, `6c947e1`, `e4899b4`, and `496d795` are present in git history.

---
*Phase: 03-readable-evidence-and-fallback-slice*
*Completed: 2026-06-22*
