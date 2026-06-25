# Stack Research: Branded PowerPoint Export

**Project:** Wuerth logistics agent PowerPoint export  
**Date:** 2026-06-21  
**Scope:** Best current stack for generating branded PowerPoint decks from structured agent output in this Python 3.11 Streamlit/LangGraph app.  
**Overall confidence:** HIGH for local deterministic rendering, MEDIUM for direct Anthropic PPT generation because the current API feature exists but is beta and has retention plus reproducibility tradeoffs.

## Recommendation

Use a hybrid stack:

1. Generate a strict `SlideDeckSpec` from existing agent output.
2. Validate it locally with typed Python models.
3. Render the `.pptx` deterministically with `python-pptx==1.0.2` from `assets/templates/PPT_Vorlage_Wuerth.pptx`.
4. Expose the bytes through `st.download_button` in `streamlit_app.py`.
5. Use Claude Opus only as an optional spec planner, not as the final PPTX renderer.

The renderer should live behind a new backend module such as `src/agent/presentation_export.py`. It should consume data already produced by `src/agent/orchestrator.py`, especially `reporting_result` from `src/agent/reporting_agent.py`, chart plans from `src/agent/visualization_spec.py`, `query_result`, `final_sql`, and `source_tables`. Tests should live in `evaluation/test_presentation_export.py` and should not require Microsoft PowerPoint.

This is the right boundary for this repo because the Wuerth deck is a brand artifact, not an open-ended creative document. Brand layout, template use, row limits, caveats, source SQL, chart choice, and failure behavior need deterministic tests. LLMs can help decide what belongs on slides, but the final file should be produced by code that is inspectable, repeatable, and local.

## Recommended Packages

| Package | Version verified | Role | Confidence | Recommendation |
|---------|------------------|------|------------|----------------|
| `python-pptx` | `1.0.2` on PyPI, released 2024-08-07 | Read and update `.pptx`, use template layouts, add slides, text, tables, images, and basic charts | HIGH | Add to `requirements.txt` and make it the renderer |
| `pydantic` | `2.13.4` on PyPI, released 2026-05-06 | Define and validate `SlideDeckSpec`, table specs, chart specs, overflow policy, and provenance fields | HIGH | Add explicitly if app code imports it directly |
| `anthropic` | `0.111.0` on PyPI, released 2026-06-18 | Optional direct Claude Messages API client for structured slide specs or development-time code drafting | MEDIUM | Use only if direct Anthropic structured output is needed beyond existing `langchain-anthropic` |
| `langchain-anthropic` | `1.4.6` on PyPI, released 2026-06-12 | Existing provider integration path for Claude inside the app | MEDIUM | Keep for current agent flow; do not make PPT rendering depend on LangChain |
| `vl-convert-python` | `1.9.0.post1` on PyPI, released 2026-01-21 | Optional Altair/Vega-Lite to PNG/SVG export for complex chart images | MEDIUM | Defer unless native `python-pptx` charts are insufficient |
| `streamlit` | `1.58.0` latest docs release, released 2026-05-28 | UI download button for PPTX bytes | HIGH | Current app already uses Streamlit; no special PPT package needed in UI |

### Minimal install set for this phase

```bash
pip install python-pptx==1.0.2 pydantic==2.13.4
```

Only add `anthropic==0.111.0` if the implementation chooses direct Anthropic structured outputs for the slide spec. Only add `vl-convert-python==1.9.0.post1` if charts must be exported as image assets from Altair rather than rendered as native PowerPoint charts.

## Option Comparison

| Option | Verdict | Why |
|--------|---------|-----|
| Deterministic local PPTX generation from `assets/templates/PPT_Vorlage_Wuerth.pptx` with `python-pptx` | Use as the renderer | Best fit for branded output, tests, Docker, local data handling, and reproducible failures |
| Direct Claude Opus / Anthropic API creates the PPTX | Do not use as primary renderer | Feasible via Agent Skills, but beta, less reproducible, harder to enforce Wuerth template fidelity, and not Zero Data Retention eligible |
| Claude generates slide content/spec/code, Python renders PPTX | Use selectively | Best balance: LLM handles narrative planning when needed, local renderer enforces brand and file structure |

## Deterministic Renderer: `python-pptx`

**Use this. Confidence: HIGH.**

`python-pptx` is the strongest fit because it is Python-native, works without a local PowerPoint installation, runs on Linux/Docker, can open an existing presentation, and can save a new `.pptx`. The official docs state that it supports creating, reading, and updating PowerPoint files, including use cases from database queries, analytics output, or JSON payloads. This maps directly to the current app.

Implementation shape:

```text
streamlit_app.py
  calls export action only

src/agent/presentation_export.py
  load template from assets/templates/PPT_Vorlage_Wuerth.pptx
  validate SlideDeckSpec
  add slides from known template layouts
  fill placeholders
  add tables and charts
  save to BytesIO

evaluation/test_presentation_export.py
  verify template path resolution
  verify output bytes are a valid pptx zip
  verify non-empty slides and expected text
  verify missing template fails with a controlled error
```

Why `python-pptx` beats alternatives here:

- It preserves the local Wuerth template asset and lets the implementation bind to known layouts/placeholders.
- It keeps all generated result data local after SQL execution.
- It makes tests straightforward: inspect slide count, extracted text, package contents, and failure cases.
- It fits the existing Python 3.11 stack and `requirements.txt` model.
- It avoids Windows-only automation and does not require Microsoft Office in Docker.

Known constraints:

- It will not magically solve brand layout. The phase still needs a slide contract for supported layouts, placeholder names, text overflow, chart/table caps, and fallback slides.
- The PowerPoint format has features that `python-pptx` does not support. If the Wuerth template uses unsupported advanced features, keep them in the master and only populate supported placeholders.
- The template is binary. Add tests that fail clearly when layout IDs, placeholders, or expected names change.
- The current template has previously been flagged in `.planning/codebase/CONCERNS.md` for embedded OLE entries. Add a package safety scan before distributing generated decks.

### Chart approach

For the MVP, use native `python-pptx` charts for the existing simple `bar` and `line` chart contract from `src/agent/visualization_spec.py`. Native charts remain editable in PowerPoint and avoid an extra rendering dependency.

Use `vl-convert-python` later only if `src/agent/visualization_spec.py` grows beyond simple PowerPoint-native charts and needs pixel-perfect Altair chart images. That tradeoff is simple: images look closer to Streamlit Altair charts, but they are less editable inside PowerPoint.

## Direct Anthropic / Claude Opus PPT Generation

**Do not use as the primary export stack. Confidence: MEDIUM.**

The current Anthropic docs make direct PPT generation feasible. Anthropic provides Agent Skills for PowerPoint (`pptx`) in the API, and the Skills guide says Skills integrate with the Messages API through code execution. The current Opus-tier model listed by Anthropic is `claude-opus-4-8`, and the Opus page says to use `claude-opus-4-8` via the Claude API.

That does not make it the right production renderer for this app.

Reasons to avoid direct Claude-created PPTX as the main path:

- **Brand determinism:** The app must use `assets/templates/PPT_Vorlage_Wuerth.pptx` reliably. LLM-created files can drift in layout, typography, placeholder use, table sizing, and chart styling.
- **Reproducibility:** A deterministic renderer can be tested against exact slide counts, text, and package structure. A model-generated PPTX will vary across calls and model updates.
- **Data governance:** Anthropic code execution and Agent Skills are not Zero Data Retention eligible. Official docs state code execution container data can be retained up to 30 days, and Files API artifacts persist until deleted.
- **Failure handling:** The current repo already has deterministic safety layers around SQL and reporting. A model-generated deck introduces a second opaque execution environment after the validated result.
- **Debuggability:** If a table overflows, a placeholder is wrong, or an embedded object breaks, local code can be fixed and covered by tests. A model output issue is harder to reduce to a stable regression test.

Direct Anthropic PPT creation is still useful for:

- one-off prototyping of target deck structures,
- generating draft layout ideas from the Wuerth template,
- development-time code suggestions that are reviewed before commit,
- exploratory demos where data is synthetic and brand fidelity is not binding.

Do not ship it as the user-facing export button for real Wuerth data.

## Hybrid LLM Spec + Deterministic Renderer

**Use this when the deck needs narrative planning. Confidence: HIGH.**

The best hybrid design is:

```text
Agent result data
  from src/agent/orchestrator.py

Deterministic base spec builder
  maps reporting_result/query_result/final_sql/source_tables
  into SlideDeckSpec

Optional Claude spec planner
  accepts capped, sanitized context
  returns schema-constrained JSON only

Local validator
  pydantic model validation
  row limits
  text length limits
  allowed layout IDs
  allowed chart types

Local PPTX renderer
  python-pptx + assets/templates/PPT_Vorlage_Wuerth.pptx

Streamlit download
  st.download_button with PPTX MIME type
```

Recommended spec contract:

```python
class SlideDeckSpec(BaseModel):
    title: str
    subtitle: str | None = None
    language: Literal["de", "en"]
    slides: list[SlideSpec]
    provenance: DeckProvenance

class SlideSpec(BaseModel):
    layout: Literal[
        "title_summary",
        "kpi_overview",
        "chart_with_commentary",
        "table_with_caveats",
        "methodology_appendix",
    ]
    title: str
    bullets: list[str] = []
    kpis: list[KpiSpec] = []
    chart: ChartSpec | None = None
    table: TableSpec | None = None
    notes: list[str] = []
```

Keep the MVP deterministic. The initial `SlideDeckSpec` can be built directly from `reporting_result` without calling an LLM. Add Claude later only for choosing slide sequence, shortening long explanations, creating German executive titles, or grouping caveats.

If direct Anthropic structured output is used, prefer the current official structured-output API over prompt-only JSON. Anthropic docs say structured outputs constrain responses to a schema through JSON outputs and strict tool use. Use `claude-opus-4-8` only when the deck planning problem is genuinely hard. For ordinary summary-to-slide conversion, a cheaper model or the existing deterministic reporting layer is enough.

## Streamlit Integration

Use the existing UI model in `streamlit_app.py`: render export bytes, then call `st.download_button`.

Use this MIME type:

```text
application/vnd.openxmlformats-officedocument.presentationml.presentation
```

The Streamlit docs note that direct `data` passed to `st.download_button` is stored in memory while the user is connected. That is acceptable for small generated decks. Do not generate very large decks or unbounded table slides. Cap rows and columns before rendering.

## What Not To Use

| Do not use | Why | Better choice |
|------------|-----|---------------|
| `win32com`, COM automation, or local PowerPoint scripting | Windows and Office dependency, incompatible with Docker/Linux tests | `python-pptx` |
| LibreOffice headless as the primary generator | Heavy binary dependency, conversion fidelity can be hard to test | Use only as optional visual QA if needed |
| Anthropic Agent Skills as the production renderer | Beta, non-deterministic, not ZDR eligible, harder to enforce Wuerth template | Hybrid spec plus local renderer |
| Raw OOXML string manipulation across the whole PPTX | Fragile and hard to review | Use `python-pptx`; isolate tiny XML patches only if a specific unsupported feature requires it |
| Full arbitrary slide designer | Out of scope and will slow the roadmap | Fixed layout contract mapped to known template placeholders |
| Unbounded result tables in slides | Creates unreadable decks and memory risk | Top-N rows, summary tables, appendix cap, caveat note |
| LLM-generated Python code at runtime | Security and reproducibility risk | Commit reviewed renderer code in `src/agent/presentation_export.py` |

## Proposed Phase Stack

### Phase 1: Deterministic MVP

- Add `python-pptx==1.0.2`.
- Add `pydantic==2.13.4` if using typed spec models directly.
- Create `src/agent/presentation_export.py`.
- Use `assets/templates/PPT_Vorlage_Wuerth.pptx`.
- Render title, summary, KPI, table, caveat, and simple chart slides.
- Add `evaluation/test_presentation_export.py`.
- Add a Streamlit download action in `streamlit_app.py`.

### Phase 2: Optional LLM Slide Spec

- Add `anthropic==0.111.0` only if direct structured outputs are needed.
- Use existing `src/llm/model_adapter.py` if the current LangChain abstraction is enough.
- Keep Claude output limited to `SlideDeckSpec` JSON.
- Validate before rendering.
- Cap input rows and avoid sending unnecessary raw data.

### Phase 3: Richer Visuals

- Add `vl-convert-python==1.9.0.post1` only if native PowerPoint charts cannot express the required visuals.
- Keep native charts for simple bar/line outputs where editability matters.
- Add screenshot or extracted-text QA for generated decks if visual fidelity becomes important.

## Confidence Assessment

| Area | Confidence | Reason |
|------|------------|--------|
| `python-pptx` renderer | HIGH | Official docs and PyPI confirm template-friendly PPTX creation/update without PowerPoint, and it fits the repo architecture |
| Hybrid architecture | HIGH | Matches existing deterministic reporting boundary in `src/agent/reporting_agent.py` and keeps UI thin in `streamlit_app.py` |
| Direct Anthropic PPT generation | MEDIUM | Official Agent Skills support exists, but beta status, retention policy, and visual determinism need validation with the Wuerth template |
| Chart export plan | MEDIUM | Native PPTX charts are enough for current `bar`/`line`; complex visuals may need image export later |
| Package versions | HIGH | Verified from PyPI or official release/docs pages on 2026-06-21 |

## Sources

- `python-pptx` PyPI: https://pypi.org/project/python-pptx/
- `python-pptx` docs: https://python-pptx.readthedocs.io/en/latest/
- `python-pptx` placeholders docs: https://python-pptx.readthedocs.io/en/latest/user/placeholders-using.html
- Anthropic Python SDK PyPI: https://pypi.org/project/anthropic/
- Anthropic SDK repository: https://github.com/anthropics/anthropic-sdk-python
- Anthropic model overview: https://platform.claude.com/docs/en/about-claude/models/overview
- Anthropic Opus page: https://www.anthropic.com/claude/opus
- Anthropic Agent Skills quickstart: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/quickstart
- Anthropic Skills guide: https://platform.claude.com/docs/en/build-with-claude/skills-guide
- Anthropic code execution docs: https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool
- Anthropic API and data retention: https://platform.claude.com/docs/en/manage-claude/api-and-data-retention
- Anthropic structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Pydantic PyPI: https://pypi.org/project/pydantic/
- LangChain Anthropic PyPI: https://pypi.org/project/langchain-anthropic/
- Streamlit download button docs: https://docs.streamlit.io/develop/api-reference/widgets/st.download_button
- Streamlit release notes: https://docs.streamlit.io/develop/quick-reference/release-notes
- Altair saving charts docs: https://altair-viz.github.io/user_guide/saving_charts.html
- `vl-convert-python` PyPI: https://pypi.org/project/vl-convert-python/
