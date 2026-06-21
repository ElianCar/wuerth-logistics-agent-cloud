---
phase: 02-streamlit-downloadable-deck-slice
reviewed: 2026-06-21T18:56:33Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - streamlit_app.py
  - evaluation/test_streamlit_presentation_export.py
findings:
  critical: 0
  warning: 4
  info: 0
  total: 4
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-06-21T18:56:33Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Reviewed the Streamlit PPT create/download slice and its source-level tests. The live Create PPT to Download PPT path delegates rendering to the backend and does not import PPTX renderer internals. No blocker-level production defect was found. The main production issue is stale PPTX bytes remaining in `st.session_state` after chat or scenario resets. The test module also has source-scan and fake-import defects that can mask regressions or create order-dependent failures.

Verification run during review:

- `python -m unittest evaluation.test_streamlit_presentation_export -v` passed, 13 tests OK.
- `python -m compileall streamlit_app.py evaluation/test_streamlit_presentation_export.py` passed.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: WARNING - Generated PPTX bytes survive chat deletion and scenario reset

**File:** `streamlit_app.py:524`

**Issue:** Phase 2 adds `st.session_state.presentation_exports` for generated deck bytes, but chat deletion only removes `st.session_state.chats[chat_id]`, and scenario reset only rebuilds chat/golden-test state at `streamlit_app.py:562-573`. Neither path clears the corresponding PPTX bytes. A deleted chat can therefore leave generated presentation content in the server-side session state. The key prevents normal UI redisplay, but the data retention still violates the expected cleanup boundary for generated exports.

**Fix:**

```python
def clear_presentation_exports_for_chat(chat_id: str) -> None:
    exports = presentation_exports_state()
    prefix = f"ppt_export_{chat_id}_"
    for key in list(exports):
        if key.startswith(prefix):
            del exports[key]

# Before or after deleting a chat:
clear_presentation_exports_for_chat(chat_id)
del st.session_state.chats[chat_id]

# When the data scenario changes:
st.session_state.presentation_exports = {}
```

### WR-02: WARNING - Test helper leaves a fake-imported `streamlit_app` in `sys.modules`

**File:** `evaluation/test_streamlit_presentation_export.py:137`

**Issue:** `_load_streamlit_app()` imports `streamlit_app` while `sys.modules` contains fake Streamlit and fake backend modules, then returns without removing the imported module. After the `patch.dict` exits, `sys.modules["streamlit_app"]` still points at a module wired to those fakes. Any later test in the same Python process that imports `streamlit_app` can receive the fake-backed module, making the suite order-dependent.

**Fix:**

```python
def _load_streamlit_app() -> types.ModuleType:
    ...
    with patch.dict(sys.modules, fake_modules):
        sys.modules.pop("streamlit_app", None)
        try:
            module = importlib.import_module("streamlit_app")
        finally:
            sys.modules.pop("streamlit_app", None)
    return module
```

### WR-03: WARNING - Create/Download transition tests can pass without exercising the UI behavior

**File:** `evaluation/test_streamlit_presentation_export.py:282`

**Issue:** The tests for Create PPT, Download PPT, spinner copy, and download fields are string searches over `streamlit_app.py`. They do not call `render_presentation_export_controls()`, do not simulate a clicked button, and do not assert that `presentation_exports_state()` is updated or that the stored export is rendered as a download button. A broken implementation could leave the approved strings in comments or dead code and still pass.

**Fix:** Add a small fake Streamlit container and functional tests around the helper:

```python
with patch.object(app, "can_export_presentation", return_value=types.SimpleNamespace(can_export=True, reason="")):
    with patch.object(app, "build_presentation_export", return_value=export):
        container = FakePresentationContainer(clicked=True)
        app.render_presentation_export_controls(record, 0, container)

exports = app.presentation_exports_state(app.st.session_state)
self.assertIs(exports[expected_key], export)
self.assertEqual(container.downloads[0]["label"], "Download PPT")
self.assertEqual(container.downloads[0]["data"], export.content)
```

Cover eligible-create-success, eligible-create-failure, existing-export-download, and ineligible-disabled states.

### WR-04: WARNING - Presentation boundary import test has both false negatives and false positives

**File:** `evaluation/test_streamlit_presentation_export.py:264`

**Issue:** `test_streamlit_imports_only_allowed_backend_export_symbols()` only inspects `ast.ImportFrom` nodes where `node.module == "src.agent.presentation_export"` and requires exactly one such block. It would miss `import src.agent.presentation_export as presentation_export`, which gives Streamlit access to backend internals through the module object. It would also fail a harmless refactor that splits the same three allowed imports across two import blocks.

**Fix:**

```python
allowed = {"PPTX_MIME_TYPE", "build_presentation_export", "can_export_presentation"}
imported_from_export: set[str] = set()
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module == "src.agent.presentation_export":
        imported_from_export.update(alias.name for alias in node.names)
    if isinstance(node, ast.Import):
        forbidden = {
            alias.name
            for alias in node.names
            if alias.name == "src.agent.presentation_export"
        }
        self.assertFalse(forbidden, forbidden)

self.assertEqual(imported_from_export, allowed)
```

---

_Reviewed: 2026-06-21T18:56:33Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
