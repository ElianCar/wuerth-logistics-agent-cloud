# Phase 3: Readable Evidence And Fallback Slice - Context

**Gathered:** 2026-06-22
**Status:** Ready for planning
**Mode:** Context synthesized from the user's PPT quality review and approved direction

<domain>
## Phase Boundary

This phase improves the generated Wuerth PowerPoint output quality after the first working export proved technically functional but not management-ready. It stays focused on PPT output only: German narrative quality, short presentation titles, readable executive summary slides, useful analytical charts, table truncation, and deterministic rendering into the existing Wuerth master.

The phase must not implement the memory governance/RBAC phase, a full BI dashboard, arbitrary slide editing controls, or direct Claude/Opus-generated `.pptx` files. The expensive Claude `.pptx` attempt failed to produce useful output and is explicitly not the production strategy.

</domain>

<decisions>
## Implementation Decisions

### Generation Strategy
- Keep `python-pptx` as the renderer and keep `src/agent/presentation_export.py` as the backend boundary for deck generation.
- Optional LLM use is allowed only for schema-constrained presentation planning JSON: outline, slide intent, chart recommendations, German copy draft, and emphasis hints.
- LLM output must pass local validation before rendering. If the planner is unavailable, invalid, too slow, or too expensive, fall back to deterministic local planning and still create a usable deck.
- Do not let an LLM generate raw `.pptx`, edit the PowerPoint file directly, generate Python code at runtime, or receive unbounded result data.
- Use Sonnet/high-quality planning when enabled for outline and chart choice. Keep the payload small: sanitized question, SQL, reporting metadata, capped result sample, column profiles, and precomputed aggregates.

### Language And Narrative
- Generated decks must default to German for all visible user-facing slide text: cover, executive summary, findings, chart captions, caveats, appendix, metadata, and fallback reasons.
- The handwritten user question must not be pasted verbatim onto the cover slide. Derive a short German presentation title instead.
- The cover title must be short enough for the cover title placeholder and must not overlap the subtitle, author, date, logo, or slide boundaries.
- Executive-summary content must use concise German management language, not raw table explanations or placeholder text.
- Important executive-summary information must be bolded through PowerPoint rich text runs: key numbers, severity labels, primary finding labels, and short action phrases.
- Numbers must be formatted sensibly for management output: whole counts with separators, thousands as `Tsd.` only where readability improves, millions as `Mio.`, billions as `Mrd.`, percentages with one decimal when needed, and no false precision.

### Analytical Content
- A deck that only repeats the SQL result table is unacceptable when there are useful dimensions in the result.
- The slide planner must inspect result shape and choose charts that add analytical value. For categorical logistics outputs, prefer top-N horizontal bars, concentration/Pareto-style views, or donut/pie charts only when a small number of categories explain the result cleanly.
- For the known query "Which order numbers have shipment records but no matching invoice records?", useful analysis includes at least distinct order numbers, total unmatched shipment rows, duplicate records per order, top `customer_material` groups, and top `shiptoparty` groups when those columns are present.
- Evidence tables are supporting material. They should be sampled, paginated, or moved later in the deck instead of being the main insight.
- Unsupported chart shapes must fall back to a readable table or limitation slide with a German reason.

### Layout And Overflow Control
- Use the renamed Wuerth master layouts and placeholder names already prepared in `assets/templates/PPT_Vorlage_Wuerth.pptx`.
- Every text insertion must pass placeholder-specific budgets before rendering. Long titles, summaries, bullets, table notes, chart labels, and appendix metadata must truncate, split, or move to additional slides.
- Evidence tables must preserve SQL result order and visibly mark row and column truncation.
- Top-N charts must cap label count and label length so chart images stay readable in the slide placeholder.
- Generated chart images should use matplotlib or another deterministic local renderer, then be placed into named visual placeholders.

### Streamlit Behavior
- Keep the Streamlit action model from Phase 2: `Create PPT` while generation runs, then `Download PPT` after a deck exists.
- Streamlit should show short backend warnings if the planner fell back or table/chart content was truncated, but it must not expose slide-builder controls in this phase.
- Streamlit must not contain PPT rendering logic. It should call backend export functions and display the returned bytes, filename, MIME type, warnings, and unavailable reason.

### Testing And Cost Control
- Automated tests must not call live Anthropic, Gemini, OpenAI, Databricks, or PowerPoint.
- LLM planning tests should use stubs or deterministic fake responses that validate JSON parsing, local validation, fallback behavior, and audit metadata.
- Add regression coverage for German output, cover title shortening, rich-text bold executive summary runs, numeric formatting, overflow prevention, top-N chart planning, unsupported chart fallback, empty result behavior, table truncation, and generated PPTX reopenability.
- Keep `.env` secret handling unchanged. Do not print or commit API keys.

### the agent's Discretion
- The planner may choose whether to implement the LLM planner as a new module such as `src/agent/presentation_planner.py` or as focused helpers inside `src/agent/presentation_export.py`, as long as the backend boundary remains testable.
- The planner may choose the exact JSON schema names for presentation planning, but the schema must explicitly cover title, language, executive summary, emphasized text spans, charts, table plans, caveats, warnings, and fallback metadata.
- The planner may choose the exact split between deterministic profiling, LLM planning, and rendering tasks as long as deterministic fallback remains first-class.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/agent/presentation_export.py` currently owns export eligibility, template validation, slide-spec creation, deterministic PPT rendering, chart image generation, warnings, and `PresentationExport`.
- `src/agent/reporting_agent.py` already builds deterministic reporting output from executed query results.
- `src/agent/visualization_spec.py` contains current deterministic bar/line chart eligibility logic used by Streamlit and earlier PPT export work.
- `streamlit_app.py` owns UI state and calls the backend exporter. It should stay a thin caller.
- `evaluation/test_presentation_export.py` is the main PPT export regression test surface.
- `assets/templates/PPT_Vorlage_Wuerth.pptx` is the Wuerth master and already contains renamed automation layouts/placeholders from the user's manual preparation.

### Current Failure Evidence
- The exported cover slide used the raw user question and overflowed the cover layout.
- Executive-summary text was partly English or placeholder-like, was cut off, and lacked bold emphasis for important facts.
- Evidence slides overproduced table pages and did not add analytical value.
- The known no-invoice query returned rows with `order_number`, `shiptoparty`, and `customer_material`; these dimensions can support concentration and grouping analysis instead of just a table.

### Integration Points
- Add presentation-planning logic after a run has successful validated SQL results and before the slide spec is rendered.
- Keep generated chart/table artifacts inside the backend export module or a focused backend presentation module.
- Update `.env.example` only for non-secret planner toggles and model names.
- Add tests under `evaluation/test_*.py` using `unittest`.

</code_context>

<specifics>
## Specific Ideas

- Default mode can be `PRESENTATION_PLANNING_MODE=deterministic` or `llm`, but deterministic fallback must always be available.
- Candidate env vars: `PRESENTATION_PLANNING_MODE`, `PRESENTATION_PLANNING_MODEL`, `PRESENTATION_PLANNING_TIMEOUT_SECONDS`, `PRESENTATION_PLANNING_MAX_ROWS`, and `PRESENTATION_PLANNING_MAX_TOKENS`.
- A planning audit should record whether the deck used `deterministic`, `llm`, or `fallback`, plus validation warnings and selected chart types.
- For top-N categorical charts, combine the rest into `Sonstige` when categories exceed the chart budget.
- For table slides, show page ranges and truncation notes in German, for example `Zeilen 1-10 von 50` and `Weitere Spalten ausgeblendet`.
- Canonical refs downstream agents should read: `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/phases/01-deterministic-backend-deck-slice/01-CONTEXT.md`, `.planning/phases/02-streamlit-downloadable-deck-slice/02-CONTEXT.md`, `src/agent/presentation_export.py`, `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, `streamlit_app.py`, `evaluation/test_presentation_export.py`, `.env.example`, `requirements.txt`, and `assets/templates/PPT_Vorlage_Wuerth.pptx`.

</specifics>

<deferred>
## Deferred Ideas

- Memory governance and RBAC remain Phase 4.
- Final README/demo documentation remains Phase 5 unless Phase 3 adds small config documentation needed for tests.
- Full interactive slide layout selection and arbitrary user-controlled chart choice stay out of scope.
- Direct Claude/Opus-generated `.pptx` files stay out of scope because the smoke test was expensive and did not return useful output.

</deferred>
