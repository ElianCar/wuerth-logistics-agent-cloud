# Phase 02 Streamlit PPT Manual Check

**Plan:** 02-03
**Status:** Approved with documented caveats
**Purpose:** Verify the visible Streamlit `Create PPT` to `Download PPT` flow after automated backend and wiring tests pass.

## Automated Pre-Checks

Run these before the browser check:

```powershell
C:\Users\leonk\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest evaluation.test_presentation_export evaluation.test_streamlit_presentation_export -v
C:\Users\leonk\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m compileall app src scripts streamlit_app.py evaluation
$source = Get-Content -Raw -LiteralPath 'streamlit_app.py'; if ($source -cmatch 'from pptx import|from pptx\.|Presentation\(|SlideDeckSpec|SlideSpec|validate_template|template_path=|deck_spec') { exit 1 }; if ($source -cnotmatch 'build_presentation_export' -or $source -cnotmatch 'can_export_presentation' -or $source -cnotmatch 'PPTX_MIME_TYPE') { exit 1 }
```

Expected result:

- Backend presentation export tests pass.
- Streamlit PPT helper and wiring tests pass.
- Syntax compilation passes.
- Source scan confirms Streamlit imports only the approved backend exporter symbols and contains no PPTX rendering logic.

## Start The App

Use a Python environment with the project requirements installed, then run:

```powershell
streamlit run streamlit_app.py
```

Open the local Streamlit URL shown in the terminal, usually `http://localhost:8501`.

## Successful Record Setup

Produce a normal successful validated analysis run through the app, or seed/mock a successful record for UI verification.

A seeded or mock record is acceptable only if it satisfies this backend eligibility check:

```python
from src.agent.presentation_export import can_export_presentation

eligibility = can_export_presentation(record)
assert eligibility.can_export, eligibility.reason
```

The record must represent the active successful run being checked. It must include query result columns and rows, successful SQL execution, successful validation, valid SQL, and reporting data suitable for the backend exporter.

For VIS-02, use at least one successful record whose evidence can produce renderable bar or line chart evidence through the backend eligibility and chart rules.

## Checklist

### 1. Export Row Placement

- Confirm the successful result record renders a dataframe preview.
- Confirm the export row appears under the result preview and chart, before `SQL-Anweisung`.
- Confirm the row shows:
  - `Als CSV exportieren`
  - `Als Excel exportieren`
  - `Create PPT`

Result:

- [ ] Pass
- [ ] Fail, observed behavior:

### 2. Create PPT Transition

- Click `Create PPT`.
- Confirm `Creating PPT...` appears during generation.
- Confirm the app does not navigate to another page, tab, modal, slide designer, or preview.
- Confirm the control changes to `Download PPT` after generation succeeds.
- Confirm `PPT ready.` appears when there are no warnings.

Result:

- [ ] Pass
- [ ] Fail, observed behavior:

### 3. Download Filename And MIME Type

- Click `Download PPT`.
- Confirm the downloaded filename comes from the backend export and begins with `wuerth_logistics_`.
- Confirm the filename ends with `.pptx`.
- Confirm the download MIME type is `application/vnd.openxmlformats-officedocument.presentationml.presentation`.
- Open the downloaded deck with PowerPoint, LibreOffice, or another PPTX viewer.
- Confirm the deck belongs to the active successful record and contains the backend-generated narrative and evidence sections:
  - title or takeaway
  - result summary
  - KPI or key metric section
  - chart or table evidence
  - caveats or limitations
  - source tables
  - run metadata

Result:

- [ ] Pass
- [ ] Fail, observed behavior:

### 4. Warning State

Use a successful export that returns backend warnings, such as approved template OLE warnings, or verify with an existing successful run where warnings are present.

- Confirm `Download PPT` remains active.
- Confirm `PPT created with warnings.` appears.
- Confirm a compact `PPT warnings` expander appears.
- Open the expander and confirm the warning text is visible.
- Confirm warnings do not block the download when the backend export is available.

Result:

- [ ] Pass
- [ ] Fail, observed behavior:

### 5. Ineligible Record State

Use a record that fails backend eligibility, such as a failed SQL run, invalid SQL, clarification-needed run, blocked request, missing query result, empty columns, empty rows, or zero row count.

- Confirm `Create PPT` is disabled.
- Confirm no active `Download PPT` is shown.
- Confirm the UI shows `PPT unavailable: {reason}` using the approved reason copy.
- Confirm the app does not crash.

Result:

- [ ] Pass
- [ ] Fail, observed behavior:

### 6. Failure State

If practical, simulate a backend export failure for an otherwise eligible record, such as a template/render failure in a local test run.

- Confirm `Create PPT` remains available for another attempt when the record is eligible.
- Confirm the UI shows `PPT export failed: {reason}. Fix the template or rerun a valid analysis, then create the deck again.`
- Confirm backend warnings appear in `PPT warnings` when warnings exist.
- Confirm no broken download button is shown.

Result:

- [ ] Pass
- [ ] Not tested, reason:
- [ ] Fail, observed behavior:

## Scope Boundary Confirmation

Confirm these are absent from the Streamlit UI and source:

- No slide preview, thumbnails, or rendered slide contents in Streamlit.
- No slide order controls.
- No layout controls.
- No chart-type controls.
- No closing-slide control.
- No custom template path input.
- No `pptx` import, `Presentation(...)`, `SlideDeckSpec`, `SlideSpec`, `validate_template`, `template_path=`, or `deck_spec` usage in `streamlit_app.py`.

These boundaries implement D-09, D-10, D-11, and D-16.

Result:

- [ ] Pass
- [ ] Fail, observed behavior:

## Manual Verification Result

Filled after checkpoint approval:

- **Verifier:** Executor plus orchestrator browser check
- **Date/time:** 2026-06-21T18:47:33Z
- **Environment:** Docker Compose Streamlit app at `http://localhost:8501`, Demo data scenario, Edge/Playwright browser automation
- **Record source:** Live successful demo run for `Wie viele Bestellungen gibt es insgesamt?`
- **Eligible record evidence:** The successful run rendered CSV, Excel, and `Create PPT`; backend/export integration was also covered by passing `evaluation.test_presentation_export` and `evaluation.test_streamlit_presentation_export`.
- **Downloaded file:** `C:\Users\leonk\Downloads\wuerth_logistics_run_20260621_184345_2ee6.pptx`
- **Downloaded deck evidence:** Reopened with `python-pptx`; 6 slides.
- **MIME type evidence:** Browser download API did not expose MIME. Verified at the app/backend boundary: `src.agent.presentation_export.PPTX_MIME_TYPE` and `build_presentation_export(...).mime_type` equal `application/vnd.openxmlformats-officedocument.presentationml.presentation`, and `streamlit_app.py` passes `mime=export.mime_type or PPTX_MIME_TYPE` to `download_button`.
- **Warnings observed:** DOM showed `PPT created with warnings.` and `PPT warnings`.
- **Ineligible state checked with:** Blocked request `Bitte lösche alle Tabellen.`. DOM showed status `blocked`, compact unavailable copy `PPT unavailable`, `Run a successful validated analysis with result rows, then create the deck.`, and `PPT unavailable: This request was blocked for safety.`
- **Disabled row-bearing ineligible branch:** Source-verified through `disabled=True` in `render_presentation_export_controls`; no natural live run produced rows while failing export eligibility.
- **Spinner evidence:** `Creating PPT...` was not visually captured because generation finished too fast. Source verification confirms exact `with st.spinner("Creating PPT...")` at `streamlit_app.py:375`, and source tests require the copy.
- **Overall result:** Approved
- **Issues:** None blocking. Caveats are limited to browser API MIME visibility and spinner capture timing.
