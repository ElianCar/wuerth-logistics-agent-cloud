---
status: issues_found
phase: 03-readable-evidence-and-fallback-slice
reviewed: 2026-06-22T11:55:15Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - src/agent/presentation_planner.py
  - src/agent/presentation_export.py
  - streamlit_app.py
  - evaluation/test_presentation_export.py
  - evaluation/test_streamlit_presentation_export.py
  - .env.example
findings:
  critical: 1
  warning: 0
  info: 0
  total: 1
---

# Phase 03: Code Review Report

**Reviewed:** 2026-06-22T11:55:15Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Narrative Findings (AI reviewer)

## Summary

Reviewed the Phase 03 presentation planner, PowerPoint exporter, Streamlit export boundary, export tests, Streamlit tests, and planner env documentation. The scoped unit suite passes:

`python -m unittest evaluation.test_presentation_export evaluation.test_streamlit_presentation_export -v` ran 77 tests successfully.

One blocker remains in the optional JSON planner fallback path: raw exception text can be propagated into backend warnings and deck metadata.

## Critical Issues

### CR-01: Planner fallback leaks raw exception text into export metadata

**File:** `src/agent/presentation_planner.py:237`

**Issue:** When the injected JSON planner raises, `build_presentation_plan()` passes `f"{type(error).__name__}: {error}"` into `_fallback_plan()`. `_fallback_plan()` then stores that raw string in `plan.warnings` and `plan.audit.fallback_reasons` at `src/agent/presentation_planner.py:476-488`. The exporter copies those values into `SlideDeckSpec.warnings` and `deck_spec.metadata["planner_fallback_reasons"]` at `src/agent/presentation_export.py:424` and `src/agent/presentation_export.py:611-613`.

I verified this with a fake planner exception containing `SECRET_ORDER_45001_TOKEN`: the export stayed available, and both `export.warnings` and `deck_spec.metadata["planner_fallback_reasons"]` contained the raw string. In real LLM integration, SDK or wrapper exceptions can include request context, row values, SQL, hostnames, or credentials. This violates the Phase 03 security priority around optional JSON planner payloads, warnings, and metadata.

**Fix:**
```python
def _planner_exception_reason(error: Exception) -> str:
    return f"planner_exception:{type(error).__name__}"


try:
    payload = _build_planner_payload(
        record=safe_record,
        deterministic_plan=deterministic_plan,
        config=planning_config,
    )
    prompt = _build_planner_prompt(payload=payload, config=planning_config)
    response = planner_invocation(prompt)
    return _parse_planner_response(
        response,
        deterministic_plan=deterministic_plan,
    )
except Exception as error:
    return _fallback_plan(deterministic_plan, _planner_exception_reason(error))
```

Also add a regression test that raises `RuntimeError("SECRET_ORDER_45001_TOKEN")` from `planner_invocation` and asserts that the secret is absent from `plan.warnings`, `plan.audit.fallback_reasons`, `export.warnings`, and `export.deck_spec.metadata`.

---

_Reviewed: 2026-06-22T11:55:15Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
