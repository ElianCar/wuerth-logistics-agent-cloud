---
phase: 01-deterministic-backend-deck-slice
reviewed: 2026-06-21T16:09:42Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - src/agent/presentation_export.py
  - evaluation/test_presentation_export.py
  - requirements.txt
findings:
  critical: 2
  warning: 3
  info: 0
  total: 5
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-06-21T16:09:42Z
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

Reviewed the backend PowerPoint export module, its unittest coverage, and the new dependency entry. The export boundary is mostly well scoped, but the template safety audit has two blocking gaps: modified embedded objects can be accepted by filename alone, and external relationships are detected with fragile string matching. I also found validation and test issues that can produce misleading deck output or misleading test results.

Review execution note: tests were not run because the local Python interpreter used for review does not have `python-pptx` installed, so importing `pptx` fails in this environment.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: OLE allowlist trusts filenames even when the template changed

**Classification:** BLOCKER
**File:** `src/agent/presentation_export.py:468`
**Issue:** The audit only warns when the template SHA256 differs, then allows embedded OLE objects as long as their ZIP paths match `known_warning_entries` at lines 503-507. A modified template can replace `ppt/embeddings/oleObject1.bin` or `ppt/embeddings/oleObject2.bin` with different embedded content and still pass validation with `available=True`. That misses unsafe template content and allows active embedded payloads to be preserved in generated decks.
**Fix:**
```python
if ole_entries:
    if manifest.expected_sha256 and digest != manifest.expected_sha256:
        errors.append(
            "Template contains embedded objects but does not match the approved template hash."
        )
    else:
        warnings.extend(
            f"Template contains preserved OLE object warning: {entry}."
            for entry in ole_entries
        )
```
If custom templates should be allowed later, store and verify per-entry hashes instead of only ZIP paths.

### CR-02: External relationship detection can be bypassed by valid XML formatting

**Classification:** BLOCKER
**File:** `src/agent/presentation_export.py:787`
**Issue:** `_external_relationships()` scans `.rels` files for the exact strings `TargetMode="External"` or `TargetMode='External'`. XML allows whitespace around `=`, and a relationship file using `TargetMode = "External"` would not be blocked even though PowerPoint can still treat it as an external relationship. This can preserve external links in generated PPTX output.
**Fix:**
```python
from xml.etree import ElementTree

def _external_relationships(package: ZipFile) -> list[str]:
    relationships: list[str] = []
    for name in package.namelist():
        if not name.endswith(".rels"):
            continue
        try:
            root = ElementTree.fromstring(package.read(name))
        except (ElementTree.ParseError, KeyError):
            continue
        for relationship in root:
            if relationship.attrib.get("TargetMode", "").lower() == "external":
                relationships.append(name)
                break
    return sorted(relationships)
```

## Warnings

### WR-01: Chart evidence slides can validate without chart evidence

**Classification:** WARNING
**File:** `src/agent/presentation_export.py:280`
**Issue:** A chart slide is added whenever `chart_plan.get("render_allowed")` is truthy, but `_chart_table_rows()` can return an empty list when `x_axis` or `y_axis` is missing or absent from `query_result["columns"]`. `validate_slide_deck_spec()` only checks the chart type at lines 417-420, so an `Agent 04 Chart Evidence` slide can pass with body text but no chart data. It also permits `chart_type` values of `""` and `"none"` on a chart evidence slide. The generated deck can claim chart evidence exists when it does not.
**Fix:** Require `chart_evidence` slides to have `chart_type in {"bar", "line"}`, non-empty `table_columns`, and non-empty `table_rows`, or skip the chart slide and add a warning/caveat when the chart payload cannot be backed by result data.

### WR-02: Render failures raise instead of returning a fail-closed export object

**Classification:** WARNING
**File:** `src/agent/presentation_export.py:197`
**Issue:** `build_presentation_export()` returns structured unavailable exports for eligibility, slide spec, and template audit failures, but any `_render_presentation()` exception is re-raised as `PresentationExportError` at lines 197-203. A template can pass the current audit and still fail during layout lookup or shape rendering, which would crash a future Streamlit download path instead of producing an unavailable export with empty bytes.
**Fix:** Return `_unavailable_export("render_failed", warnings=[...], template_audit=audit, deck_spec=deck_spec)` from the `except` block. Keep the exception chained only for lower-level callers that explicitly request strict mode.

### WR-03: Streamlit import test is order-dependent and can fail for unrelated reasons

**Classification:** WARNING
**File:** `evaluation/test_presentation_export.py:167`
**Issue:** `test_backend_contract_does_not_import_streamlit_surfaces()` checks global `sys.modules` after calling `build_slide_deck_spec()`. If another test or test runner plugin imports `streamlit` earlier in the same process, this test fails even when `presentation_export` did nothing wrong. If the module was not imported earlier, the test passes but only because of global process state.
**Fix:**
```python
before = set(sys.modules)
build_slide_deck_spec(record=valid_record())
new_modules = set(sys.modules) - before

self.assertNotIn("streamlit", new_modules)
self.assertNotIn("streamlit_app", new_modules)
```
For an even stricter backend-boundary test, inspect the module source imports or import `src.agent.presentation_export` in an isolated subprocess.

---

_Reviewed: 2026-06-21T16:09:42Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
