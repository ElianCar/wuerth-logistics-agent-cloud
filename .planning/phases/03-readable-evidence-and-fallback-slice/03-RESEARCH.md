# Phase 03: Readable Evidence And Fallback Slice - Research

**Researched:** 2026-06-22
**Domain:** Deterministic PowerPoint evidence planning, German narrative generation, overflow control, and chart/table fallback behavior
**Confidence:** HIGH for existing code and renderer APIs, MEDIUM for exact visual-budget thresholds

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
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

### Deferred Ideas (OUT OF SCOPE)
## Deferred Ideas

- Memory governance and RBAC remain Phase 4.
- Final README/demo documentation remains Phase 5 unless Phase 3 adds small config documentation needed for tests.
- Full interactive slide layout selection and arbitrary user-controlled chart choice stay out of scope.
- Direct Claude/Opus-generated `.pptx` files stay out of scope because the smoke test was expensive and did not return useful output.
</user_constraints>

## Summary

Phase 3 should add a presentation planning layer between the successful validated agent record and `SlideDeckSpec` rendering. The existing exporter already owns eligibility, template validation, dynamic slide specs, deterministic PPTX rendering, PNG chart generation, warning propagation, and normalized PPTX bytes in `src/agent/presentation_export.py`. [VERIFIED: codebase grep] The current weak points are the Phase 1 slide content assumptions: `_deck_title()` uses the raw user question, several visible slide labels are English, summary rendering uses plain text only, chart support accepts only existing bar/line payloads, and table truncation warnings are not visible enough inside the deck. [VERIFIED: src/agent/presentation_export.py]

The planning layer should be deterministic by default and should profile result data before slides are built. [VERIFIED: 03-CONTEXT.md] It should produce a small internal `PresentationPlan` with German title, executive bullets, bold spans, numeric metrics, evidence chart plans, table page plans, truncation notes, fallback reasons, and audit metadata. [VERIFIED: 03-CONTEXT.md] Optional LLM use may fill this same plan schema only after receiving capped, sanitized context and must fall back to the deterministic planner on any error. [VERIFIED: 03-CONTEXT.md] Anthropic's current structured-output docs support JSON schema constrained responses through `output_config.format`, but also document token-cost, refusal, max-token, and schema-complexity caveats, so local validation remains required. [CITED: https://platform.claude.com/docs/en/build-with-claude/structured-outputs]

**Primary recommendation:** Implement `src/agent/presentation_planner.py` as a pure, deterministic planning/profile module, then adapt `presentation_export.py` to render validated plans with `python-pptx` rich text runs, matplotlib horizontal top-N charts, German fallback slides, and explicit truncation notes. [VERIFIED: 03-CONTEXT.md] [VERIFIED: codebase grep]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Export eligibility | Backend export module | Streamlit display | `can_export_presentation()` already owns record eligibility and Streamlit only displays controls and reasons. [VERIFIED: src/agent/presentation_export.py] [VERIFIED: streamlit_app.py] |
| Presentation data profiling | Backend export/planning module | Reporting layer | Profiling inspects returned rows after SQL success and before slide rendering; it should not call SQL or Streamlit. [VERIFIED: src/agent/reporting_agent.py] |
| German narrative planning | Backend export/planning module | Optional LLM provider | Default German copy is a phase requirement; optional LLM output must be JSON only and locally validated. [VERIFIED: 03-CONTEXT.md] |
| Rich text and number formatting | Backend renderer | Planning module | `python-pptx` exposes text frames, paragraphs, runs, and run font properties, so final emphasis belongs in PPT rendering helpers. [CITED: https://python-pptx.readthedocs.io/en/latest/user/text.html] |
| Top-N evidence charts | Backend export/planning module | matplotlib image renderer | Phase 2 already keeps PPT rendering out of Streamlit, and the exporter already inserts chart images into named placeholders. [VERIFIED: streamlit_app.py] [VERIFIED: src/agent/presentation_export.py] |
| Streamlit PPT UX | Streamlit | Backend export module | Phase 2 established `Create PPT` then `Download PPT` state keyed per record; Phase 3 should only surface backend warnings. [VERIFIED: 02-CONTEXT.md] |
| Test verification | `evaluation/test_*.py` | `.venv` or Docker runtime | Current tests are `unittest` based and reopen PPTX bytes with `python-pptx`, not PowerPoint. [VERIFIED: evaluation/test_presentation_export.py] |

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PPT-05 | Generated deck preserves SQL result order for evidence tables and clearly marks row or column truncation. [VERIFIED: .planning/REQUIREMENTS.md] | Use table page plans that slice rows in original returned order, add German page-range notes, and add visible row/column truncation notes. [VERIFIED: src/agent/presentation_export.py] |
| VIS-03 | Unsupported chart shapes fall back to a table or limitation slide with a reason. [VERIFIED: .planning/REQUIREMENTS.md] | Extend chart planning so every rejected chart returns a German fallback reason carried into `SlideSpec.warnings` or a limitation slide. [VERIFIED: src/agent/visualization_spec.py] |
| VIS-04 | Presentation output can handle top-N categorical comparisons without unreadable slide overflow. [VERIFIED: .planning/REQUIREMENTS.md] | Add top-N categorical profile rules, horizontal bar chart rendering, label truncation, and `Sonstige` aggregation where categories exceed the chart budget. [VERIFIED: 03-CONTEXT.md] |
| TEST-04 | Tests verify long text, empty result, unsupported chart shape, and table truncation behavior. [VERIFIED: .planning/REQUIREMENTS.md] | Extend `evaluation/test_presentation_export.py` with deterministic records and inspect reopened PPTX text, tables, runs, warnings, and slide counts. [VERIFIED: evaluation/test_presentation_export.py] |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- Use Python modules in lower_snake_case and tests as `evaluation/test_*.py`. [VERIFIED: AGENTS.md]
- Keep new non-UI behavior under `src/agent/` or another backend module, not in `streamlit_app.py`. [VERIFIED: AGENTS.md]
- Resolve assets with `Path`; do not hardcode local project paths. [VERIFIED: AGENTS.md]
- Keep PPT generation behind a pure backend/export module and expose only a thin Streamlit action. [VERIFIED: AGENTS.md]
- Generate PowerPoint only from successful, validated query results. [VERIFIED: AGENTS.md]
- Use existing `unittest` style and avoid tests that require Microsoft PowerPoint. [VERIFIED: AGENTS.md]
- Do not present lightweight RBAC or template controls as production security in this phase. [VERIFIED: AGENTS.md]
- Local Wuerth data lacks several business columns; unsupported KPI answers must stay explicit limitations. [VERIFIED: AGENTS.md] [VERIFIED: semantic_layer/databricks/wuerth_semantic_layer.yaml]

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `python-pptx` | 1.0.2, uploaded 2024-08-07 [VERIFIED: PyPI JSON] | Open, modify, render, and reopen `.pptx` files locally. [CITED: https://python-pptx.readthedocs.io/] | It supports slide creation, text placeholders, images, text boxes, font bolding, and tables without Microsoft PowerPoint. [CITED: https://python-pptx.readthedocs.io/] |
| `matplotlib` | 3.11.0, uploaded 2026-06-12 [VERIFIED: PyPI JSON] | Deterministic PNG chart rendering for PPT placeholders. [VERIFIED: requirements.txt] | Official docs support non-interactive `Agg` output and `savefig()` image output, matching testable server-side rendering. [CITED: https://matplotlib.org/stable/install/index.html] [CITED: https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html] |
| `pandas` | 3.0.3, uploaded 2026-05-11 [VERIFIED: PyPI JSON] | DataFrame profiling, grouping, numeric coercion, and deterministic aggregation. [VERIFIED: src/agent/reporting_agent.py] | It is already used in reporting and Streamlit result rendering, and official install docs confirm PyPI distribution. [VERIFIED: codebase grep] [CITED: https://pandas.pydata.org/docs/getting_started/install.html] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `anthropic` / `langchain-anthropic` | Existing unpinned requirement [VERIFIED: requirements.txt] | Optional structured planning JSON only. [VERIFIED: 03-CONTEXT.md] | Use only behind an opt-in planner mode, with capped context and deterministic fallback. [VERIFIED: 03-CONTEXT.md] |
| Python stdlib `json`, `dataclasses`, `Decimal`, `zipfile`, `unittest` | Python runtime [VERIFIED: codebase grep] | Plan validation, numeric formatting, PPTX package normalization, and tests. [VERIFIED: src/agent/presentation_export.py] [VERIFIED: evaluation/test_presentation_export.py] | Prefer stdlib validation first because no new package is needed. [VERIFIED: requirements.txt] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `python-pptx` deterministic rendering | Direct Claude/Opus PPTX generation | Rejected by user-approved scope because the direct attempt was expensive and did not produce useful output. [VERIFIED: 03-CONTEXT.md] |
| Matplotlib PNG charts | Native PowerPoint charts | PNG charts are simpler to validate and already fit the exporter pattern; native chart manipulation would expand the renderer contract. [VERIFIED: src/agent/presentation_export.py] [ASSUMED] |
| Deterministic local planner | LLM-only planning | LLM-only planning violates the required fallback behavior and would make tests depend on a live provider. [VERIFIED: 03-CONTEXT.md] |

**Installation:**

```bash
# No new package install is recommended for Phase 3.
# Use the existing project dependency file when provisioning a clean runtime:
python -m pip install -r requirements.txt
```

**Version verification:** `pip index versions` reported `python-pptx` 1.0.2, `matplotlib` 3.11.0, and `pandas` 3.0.3 as installed and latest in the repo venv. [VERIFIED: local command]

## Package Legitimacy Audit

> Phase 3 should not add new external packages. [VERIFIED: requirements.txt] The table audits the existing packages this phase should rely on. [VERIFIED: local command]

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `python-pptx` | PyPI | Latest upload 2024-08-07 [VERIFIED: PyPI JSON] | Not collected; no new install planned [VERIFIED: local command] | `github.com/scanny/python-pptx` [VERIFIED: PyPI JSON] | OK; note says established despite `python-` naming [VERIFIED: slopcheck] | Approved existing dependency |
| `matplotlib` | PyPI | Latest upload 2026-06-12 [VERIFIED: PyPI JSON] | Not collected; no new install planned [VERIFIED: local command] | `matplotlib.org` [VERIFIED: PyPI JSON] | OK [VERIFIED: slopcheck] | Approved existing dependency |
| `pandas` | PyPI | Latest upload 2026-05-11 [VERIFIED: PyPI JSON] | Not collected; no new install planned [VERIFIED: local command] | Official docs at `pandas.pydata.org` [CITED: https://pandas.pydata.org/docs/getting_started/install.html] | OK [VERIFIED: slopcheck] | Approved existing dependency |

**Packages removed due to slopcheck [SLOP] verdict:** none. [VERIFIED: slopcheck]
**Packages flagged as suspicious [SUS]:** none. [VERIFIED: slopcheck]
**Audit limitation:** `slopcheck --json` was unsupported in installed `slopcheck` 0.6.1 and the Windows `.exe` shim was blocked by Application Control; `python -m slopcheck ...` produced plain-text OK verdicts before its follow-up install subprocess failed. [VERIFIED: local command]

## Architecture Patterns

### System Architecture Diagram

```text
Successful validated record
  -> presentation_export.can_export_presentation()
  -> presentation_planner.profile_result()
       -> column profiles
       -> W05 no-invoice aggregates
       -> text budgets and table pages
       -> chart candidate decisions
  -> optional presentation_planner.plan_with_llm_json()
       -> schema validation
       -> deterministic fallback on unavailable, invalid, slow, or costly planner
  -> PresentationPlan
       -> German title
       -> executive bullets with emphasis spans
       -> evidence chart/table/fallback plans
       -> warnings and audit metadata
  -> presentation_export.build_slide_deck_spec()
  -> python-pptx deterministic rendering
       -> rich text runs
       -> matplotlib PNG charts
       -> SQL-order table slides
       -> visible truncation notes
  -> PresentationExport bytes, filename, warnings
  -> Streamlit shows warnings and Download PPT
```

This flow preserves the Phase 1 and Phase 2 boundary: Streamlit calls backend functions and does not render PPTX objects. [VERIFIED: 02-CONTEXT.md] [VERIFIED: streamlit_app.py]

### Recommended Project Structure

```text
src/
├── agent/
│   ├── presentation_planner.py       # New pure planning/profile layer
│   ├── presentation_export.py        # Existing renderer and export boundary
│   ├── reporting_agent.py            # Existing post-SQL summary source
│   └── visualization_spec.py         # Existing Streamlit-compatible v1 chart rules
evaluation/
└── test_presentation_export.py       # Extend with Phase 3 regression cases
```

`presentation_planner.py` should be the first new module if the implementation becomes more than a few helpers, because the existing exporter is already 1,700+ lines and mixes eligibility, Claude legacy code, deterministic spec creation, template checks, rendering, and helpers. [VERIFIED: src/agent/presentation_export.py] [ASSUMED]

### Pattern 1: Typed Presentation Plan Before SlideSpec

**What:** Create a validated intermediate plan before `SlideSpec` creation. [VERIFIED: 03-CONTEXT.md]  
**When to use:** Use for all Phase 3 decks because table pages, chart choices, German title, bold spans, fallback reasons, and warnings should be validated before rendering. [VERIFIED: 03-CONTEXT.md]

```python
# Source: project pattern uses frozen dataclasses in backend result/config records.
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EmphasisSpan:
    text: str
    bold: bool = False


@dataclass(frozen=True)
class ExecutiveBullet:
    runs: list[EmphasisSpan]


@dataclass(frozen=True)
class PresentationPlan:
    title: str
    language: str = "de"
    executive_bullets: list[ExecutiveBullet] = field(default_factory=list)
    chart_plans: list[dict[str, object]] = field(default_factory=list)
    table_plans: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
```

### Pattern 2: Deterministic Result Profile

**What:** Normalize `query_result` into rows, profile columns, compute counts, and produce precomputed aggregates used by local and optional LLM planning. [VERIFIED: 03-CONTEXT.md]  
**When to use:** Use before chart selection and summary writing. [VERIFIED: 03-CONTEXT.md]

Rules:
- Preserve original row order by storing `_row_index` and never sorting table pages. [VERIFIED: PPT-05]
- Detect numeric measures with `Decimal` or `pandas.to_numeric(errors="coerce")`. [VERIFIED: src/agent/reporting_agent.py]
- Detect likely categories from non-numeric text columns with repeated values. [VERIFIED: src/agent/visualization_spec.py]
- Compute W05-specific profile metrics when columns include `order_number`, `shiptoparty`, `customer_material`, and `shipment_rows`. [VERIFIED: evaluation/wuerth_local/solution_sql/w05_shipments_without_invoices.sql]

### Pattern 3: German Rich Text Rendering With Runs

**What:** Render each executive bullet as one paragraph with runs. [CITED: https://python-pptx.readthedocs.io/en/latest/user/text.html]  
**When to use:** Use for executive summary and callout text that needs bold key numbers or phrases. [VERIFIED: 03-CONTEXT.md]

```python
# Source: python-pptx docs describe paragraph.add_run() and run.font.bold.
from pptx.util import Pt


def set_rich_bullets(shape, bullets: list[ExecutiveBullet], font_size: int) -> None:
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    for index, bullet in enumerate(bullets):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.level = 0
        for span in bullet.runs:
            run = paragraph.add_run()
            run.text = span.text
            run.font.size = Pt(font_size)
            run.font.bold = span.bold
```

### Pattern 4: Bounded Top-N Chart Plan

**What:** For categorical evidence, aggregate value counts or metric sums into top categories, cap labels, and combine overflow into `Sonstige`. [VERIFIED: 03-CONTEXT.md]  
**When to use:** Use when a categorical column has repeated values and a count or measure can be shown without many labels. [VERIFIED: 03-CONTEXT.md]

Recommended default budgets:
- Top-N labels: 8 plus optional `Sonstige`. [ASSUMED]
- Label length: 32 to 40 characters, with ellipsis and full value retained in table/metadata. [ASSUMED]
- Chart type: horizontal bar for categories with long labels. [ASSUMED]
- Fallback: German limitation slide if no readable metric or category exists. [VERIFIED: VIS-03]

### Anti-Patterns to Avoid

- **Raw question cover titles:** `_deck_title()` currently trims `user_question`; Phase 3 must derive a short German title instead. [VERIFIED: src/agent/presentation_export.py] [VERIFIED: 03-CONTEXT.md]
- **English slide chrome in generated content:** Current deterministic slides use labels such as `Executive Summary`, `Result Snapshot`, and `Evidence Table`; Phase 3 requires German visible text. [VERIFIED: src/agent/presentation_export.py] [VERIFIED: 03-CONTEXT.md]
- **Table-only evidence for W05:** W05 has usable dimensions and `shipment_rows`, so only repeating result rows fails the approved analytical-content requirement. [VERIFIED: evaluation/wuerth_local/solution_sql/w05_shipments_without_invoices.sql] [VERIFIED: 03-CONTEXT.md]
- **Direct LLM PPTX mode expansion:** Existing code still contains `PRESENTATION_EXPORT_MODE=claude`, file uploads, and Claude PPTX Skill calls; Phase 3 should not build on that path. [VERIFIED: src/agent/presentation_export.py] [VERIFIED: .env.example] [VERIFIED: 03-CONTEXT.md]

## Data Profiling And Chart Rules

### General Profiling Rules

| Result Shape | Rule | Output |
|--------------|------|--------|
| Empty columns or missing query result | Keep export unavailable, matching existing eligibility behavior. [VERIFIED: src/agent/presentation_export.py] | Existing unavailable reason. |
| Zero returned rows | For Phase 3 TEST-04, add a direct test for existing unavailable behavior or intentionally allow an empty-result limitation deck only if product decides that zero-row evidence is exportable. [VERIFIED: .planning/REQUIREMENTS.md] [ASSUMED] | Open question. |
| One scalar value | Use KPI slide and summary, no chart. [VERIFIED: src/agent/visualization_spec.py] | KPI evidence. |
| One category and one numeric measure | Use horizontal top-N bar when category count is bounded. [VERIFIED: 03-CONTEXT.md] | Chart plus table page. |
| Multiple categorical columns and no explicit chart | Pick the strongest repeated logistics dimension for analysis: `customer_material`, then `shiptoparty`, then `order_number` duplicates. [VERIFIED: 03-CONTEXT.md] [ASSUMED] | Top-N charts or concentration bullets. |
| Multiple numeric measures | Choose no chart unless the planner has an explicit schema-valid selection. [VERIFIED: src/agent/visualization_spec.py] | Fallback table or limitation slide. |
| Unsupported chart type in `chart_plan` | Do not fail the deck; add a German reason and fall back to table/limitation slide. [VERIFIED: VIS-03] | Fallback slide. |

### W05 No-Invoice Query Rules

For `Shipment records without matching invoice records`, the reference SQL returns `order_number`, `shiptoparty`, `customer_material`, and `shipment_rows` sorted by `order_number`, `shiptoparty`, and `customer_material`. [VERIFIED: evaluation/wuerth_local/solution_sql/w05_shipments_without_invoices.sql]

Required planning outputs:
- KPI cards: distinct order numbers, unmatched shipment key rows, and total `shipment_rows`. [VERIFIED: 03-CONTEXT.md]
- Duplicate analysis: top order numbers by summed `shipment_rows` or count of unmatched grouped rows. [VERIFIED: 03-CONTEXT.md]
- Top `customer_material` groups by summed `shipment_rows` or row count. [VERIFIED: 03-CONTEXT.md]
- Top `shiptoparty` groups by summed `shipment_rows` or row count. [VERIFIED: 03-CONTEXT.md]
- Table evidence: original SQL order, page note such as `Zeilen 1-10 von 50`, visible column-truncation note when columns exceed budget. [VERIFIED: PPT-05]

Do not infer business causes from unmatched records because the semantic layer says invoices and shipments may not match one-to-one due to timing and many-to-many risk. [VERIFIED: semantic_layer/databricks/wuerth_semantic_layer.yaml]

### Chart Choice Rules

| Candidate | Use When | Budget | Fallback |
|-----------|----------|--------|----------|
| Horizontal top-N bar | Repeated categorical labels with count or summed measure. [VERIFIED: 03-CONTEXT.md] | 8 categories plus `Sonstige`. [ASSUMED] | Table with German reason. |
| Pareto/concentration view | Top categories explain a large visible share of rows or measure. [VERIFIED: 03-CONTEXT.md] | Top 8 with cumulative percentage line optional. [ASSUMED] | Horizontal bar without cumulative line. |
| Grouped/stacked bars | Only if one category plus one small series dimension and bounded combinations. [VERIFIED: VIS-04] [ASSUMED] | Max 6 categories x 3 series. [ASSUMED] | Separate top-N slides or table. |
| Multi-line | Only for one time dimension, one numeric measure, and max 4 series. [VERIFIED: src/agent/visualization_spec.py] [ASSUMED] | Max 12 time points. [ASSUMED] | Table or line without series. |
| Donut/pie | Only for 2 to 5 categories and a meaningful part-of-whole total. [VERIFIED: 03-CONTEXT.md] [ASSUMED] | No long labels. [ASSUMED] | Horizontal bar. |

## German Narrative And Formatting Strategy

- Title derivation should convert the user question into a short German business title such as `Sendungen ohne passende Rechnung`, not paste the full question. [VERIFIED: 03-CONTEXT.md]
- Executive bullets should be generated from metrics and caveats, not from raw table rows. [VERIFIED: 03-CONTEXT.md]
- Numeric formatting should be centralized in `format_management_number()` so summary, KPI cards, chart labels, and table notes agree. [VERIFIED: 03-CONTEXT.md]
- Counts should use German thousands separators, for example `12.345`. [VERIFIED: src/agent/reporting_agent.py]
- Large values should use `Mio.` or `Mrd.` when that improves readability, and percentages should usually use one decimal. [VERIFIED: 03-CONTEXT.md]
- Bold emphasis should be represented as spans in the plan and rendered with run-level `font.bold`, because `python-pptx` exposes run-level font properties. [CITED: https://python-pptx.readthedocs.io/en/latest/api/text.html]

Recommended German copy templates:
- `Kurzfazit: {bold_metric} {noun} ohne passende Rechnung im sichtbaren Ergebnis.`
- `Auffaelligkeit: {bold_group} konzentriert die meisten Ausnahmen.`
- `Datenhinweis: Joins basieren auf Auftrag, Ship-to-Party und Materialkandidat; das Mapping braucht fachliche Bestaetigung.`

## Overflow And Truncation Strategy

### Text

- Add placeholder-specific budgets for cover title, subtitle, executive bullets, bullet count, footer source, chart captions, and metadata. [VERIFIED: 03-CONTEXT.md]
- Use split-to-next-slide before shrinking below readable font sizes. [VERIFIED: 01-CONTEXT.md]
- Use `TextFrame.word_wrap = True`, margins, and run-level formatting in renderer helpers. [CITED: https://python-pptx.readthedocs.io/en/latest/api/text.html]
- Avoid relying only on `fit_text()` because it depends on local font matching and can silently create tiny text if used as the primary strategy. [CITED: https://python-pptx.readthedocs.io/en/latest/api/text.html] [ASSUMED]

### Tables

- Keep table pages in source SQL row order. [VERIFIED: PPT-05]
- Use deterministic windows, for example rows `0:10`, `10:20`, and stop after a configured slide cap. [ASSUMED]
- Include visible German notes: `Zeilen 1-10 von 50`, `Weitere Zeilen im Export gekuerzt`, and `Weitere Spalten ausgeblendet`. [VERIFIED: 03-CONTEXT.md]
- Store full `row_count`, visible row range, visible columns, hidden columns, and truncation flags in slide metadata. [VERIFIED: SPEC-01]

### Chart Labels

- Render top-N category charts horizontally when labels are long. [ASSUMED]
- Shorten display labels in the chart image but keep full labels in supporting tables or metadata. [ASSUMED]
- Use `matplotlib` `tight_layout()` and `savefig()` for bounded PNG output. [CITED: https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.tight_layout.html] [CITED: https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html]

## Existing Extension Points

| File | Current Pattern | Phase 3 Extension |
|------|-----------------|-------------------|
| `src/agent/presentation_export.py` | `build_presentation_export()` routes to deterministic or legacy Claude mode. [VERIFIED: src/agent/presentation_export.py] | Keep deterministic default, add planner mode separate from direct PPTX mode, and avoid expanding legacy Claude PPTX path. [VERIFIED: 03-CONTEXT.md] |
| `src/agent/presentation_export.py` | `build_slide_deck_spec()` creates cover, summary, KPI, chart, table, caveats, metadata slides. [VERIFIED: src/agent/presentation_export.py] | Build slides from `PresentationPlan` instead of raw reporting fields. [ASSUMED] |
| `src/agent/presentation_export.py` | `_set_shape_text()` and `_set_shape_bullets()` render plain text and trim strings. [VERIFIED: src/agent/presentation_export.py] | Add `_set_shape_rich_bullets()` and preserve emphasis spans. [CITED: https://python-pptx.readthedocs.io/en/latest/user/text.html] |
| `src/agent/presentation_export.py` | `_chart_image()` supports bar and line image rendering. [VERIFIED: src/agent/presentation_export.py] | Add horizontal bar orientation, label truncation, top-N rows, and German axis labels. [ASSUMED] |
| `src/agent/reporting_agent.py` | Builds German summaries and table plan with `preserve_sql_order=True`. [VERIFIED: src/agent/reporting_agent.py] | Reuse metadata but make PPT copy shorter and more executive. [VERIFIED: 03-CONTEXT.md] |
| `src/agent/visualization_spec.py` | Supports only `none`, `bar`, and `line`; rejects ambiguous extra dimensions. [VERIFIED: src/agent/visualization_spec.py] | Keep Streamlit v1 contract stable while presentation planner adds PPT-only top-N evidence. [ASSUMED] |
| `streamlit_app.py` | Calls backend export and renders warnings; no PPTX objects in UI. [VERIFIED: streamlit_app.py] | Surface new backend warnings without adding slide-builder controls. [VERIFIED: 03-CONTEXT.md] |
| `evaluation/test_presentation_export.py` | Uses fake records, fake Claude client, `unittest`, and `Presentation(BytesIO(...))`. [VERIFIED: evaluation/test_presentation_export.py] | Add Phase 3 tests for W05, German text, rich runs, top-N, unsupported shape, empty result, and truncation notes. [VERIFIED: TEST-04] |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PPTX package generation | Raw Open XML zip editing for slides | `python-pptx` | Official docs support slides, placeholders, text, images, and tables; existing tests reopen generated PPTX bytes. [CITED: https://python-pptx.readthedocs.io/] [VERIFIED: evaluation/test_presentation_export.py] |
| Chart image rendering | Manual PNG drawing or SVG string rendering | `matplotlib` | Official docs support non-interactive output and `savefig()`; project already depends on it. [CITED: https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html] [VERIFIED: requirements.txt] |
| SQL re-execution for evidence | New database calls during export | Existing `query_result` plus deterministic profiling | Export safety requires successful validated query results and the exporter is post-SQL. [VERIFIED: AGENTS.md] [VERIFIED: src/agent/presentation_export.py] |
| Direct LLM deck files | LLM-generated `.pptx` or runtime Python code | Validated JSON plan plus deterministic rendering | Direct PPTX generation is explicitly out of scope and failed the previous attempt. [VERIFIED: 03-CONTEXT.md] |
| Streamlit slide rendering | PPTX logic in callbacks | Backend export/planner module | AGENTS.md and Phase 2 require Streamlit to remain a thin caller. [VERIFIED: AGENTS.md] [VERIFIED: 02-CONTEXT.md] |

**Key insight:** Phase 3 is primarily a planning and validation problem, not a template problem. The renderer can only keep slides readable if text, table, and chart budgets are decided before shapes are populated. [VERIFIED: 03-CONTEXT.md] [ASSUMED]

## Common Pitfalls

### Pitfall 1: Cover Title Uses Raw Question

**What goes wrong:** Long user questions overflow the cover slide and make the deck look unedited. [VERIFIED: 03-CONTEXT.md]  
**Why it happens:** `_deck_title()` currently trims `record["user_question"]` to 90 characters. [VERIFIED: src/agent/presentation_export.py]  
**How to avoid:** Add deterministic German title derivation with fixed max length, stop-word removal, W05-specific title templates, and fallback `Logistik-Auswertung`. [ASSUMED]  
**Warning signs:** Reopened deck text contains the full user question on the first slide. [VERIFIED: evaluation/test_presentation_export.py]

### Pitfall 2: Rich Text Lost By Setting Paragraph Text

**What goes wrong:** All executive-summary text has the same formatting and key numbers are not emphasized. [VERIFIED: 03-CONTEXT.md]  
**Why it happens:** Current helpers assign `paragraph.text` and then format existing runs uniformly. [VERIFIED: src/agent/presentation_export.py]  
**How to avoid:** Build runs explicitly with `paragraph.add_run()` and set `run.font.bold` per span. [CITED: https://python-pptx.readthedocs.io/en/latest/api/text.html]  
**Warning signs:** Test inspection finds zero bold runs on the executive summary slide. [ASSUMED]

### Pitfall 3: Table Truncation Exists Only As Backend Warning

**What goes wrong:** Users cannot tell in the deck which rows or columns are hidden. [VERIFIED: PPT-05]  
**Why it happens:** `_table_content()` currently adds warnings but the table slide body is not rendered when `table_rows` exist. [VERIFIED: src/agent/presentation_export.py]  
**How to avoid:** Put truncation notes in a visible text box or table footer shape, or create a compact caption above the rendered table. [ASSUMED]  
**Warning signs:** Reopened PPTX has table rows but no `Zeilen` or `Weitere Spalten` text. [ASSUMED]

### Pitfall 4: Chart Eligibility Is Confused With Presentation Usefulness

**What goes wrong:** The exporter skips useful categorical analysis because `visualization_spec.py` rejects extra dimensions for v1 Streamlit charts. [VERIFIED: src/agent/visualization_spec.py]  
**Why it happens:** The Streamlit chart contract is intentionally conservative. [VERIFIED: AGENTS.md]  
**How to avoid:** Keep `visualization_spec.py` stable and add PPT-only evidence chart planning from profiles. [ASSUMED]  
**Warning signs:** W05 decks contain only repeated table pages although `customer_material` and `shiptoparty` are present. [VERIFIED: 03-CONTEXT.md]

### Pitfall 5: Optional LLM Planner Becomes A Hidden Cost Path

**What goes wrong:** Deck creation becomes slow, expensive, or unavailable when a model fails. [VERIFIED: 03-CONTEXT.md]  
**Why it happens:** Existing direct Claude PPTX path uploads files and returns unavailable on failure, without deterministic fallback from that path. [VERIFIED: src/agent/presentation_export.py]  
**How to avoid:** Use deterministic planning by default and treat LLM planning as an optional JSON-producing enhancer that falls back locally. [VERIFIED: 03-CONTEXT.md]  
**Warning signs:** Tests require Anthropic credentials or assert Claude file-upload behavior for Phase 3 features. [VERIFIED: evaluation/test_presentation_export.py]

## Code Examples

### Management Number Formatting

```python
# Source: Phase 3 context requires Mio./Mrd./percent formatting.
from decimal import Decimal, InvalidOperation


def format_management_number(value: object, *, percentage: bool = False) -> str:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if percentage:
        return f"{number:.1f}%".replace(".", ",")
    absolute = abs(number)
    if absolute >= Decimal("1000000000"):
        return f"{number / Decimal('1000000000'):.1f} Mrd.".replace(".", ",")
    if absolute >= Decimal("1000000"):
        return f"{number / Decimal('1000000'):.1f} Mio.".replace(".", ",")
    return f"{int(number):,}".replace(",", ".") if number == number.to_integral_value() else f"{number:.2f}".replace(".", ",")
```

### W05 Profile Extraction

```python
# Source: W05 fixture returns order_number, shiptoparty, customer_material, shipment_rows.
from collections import Counter


def profile_unmatched_shipments(rows: list[dict[str, object]]) -> dict[str, object]:
    order_numbers = [str(row.get("order_number", "")) for row in rows if row.get("order_number")]
    shipment_rows = [int(row.get("shipment_rows") or 0) for row in rows]
    return {
        "distinct_order_numbers": len(set(order_numbers)),
        "unmatched_key_rows": len(rows),
        "total_unmatched_shipment_rows": sum(shipment_rows),
        "top_duplicate_orders": Counter(order_numbers).most_common(8),
        "top_customer_material": Counter(str(row.get("customer_material", "")) for row in rows).most_common(8),
        "top_shiptoparty": Counter(str(row.get("shiptoparty", "")) for row in rows).most_common(8),
    }
```

### Unsupported Chart Fallback

```python
# Source: VIS-03 requires table or limitation fallback with a reason.
def fallback_slide(reason: str) -> SlideSpec:
    return SlideSpec(
        slide_type="caveats_sources",
        layout_name=LAYOUT_CAVEATS,
        title="Darstellungshinweis",
        body=[
            "Die angefragte Visualisierung wurde nicht gerendert.",
            f"Grund: {reason}",
            "Die Evidenz wird als geordnete Tabelle gezeigt.",
        ],
        metadata={"section_label": "FALLBACK"},
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Direct LLM-generated PPTX | Deterministic `python-pptx` rendering from validated specs | Locked in Phase 1 and reaffirmed in Phase 3 context [VERIFIED: 01-CONTEXT.md] [VERIFIED: 03-CONTEXT.md] | Keeps output testable and prevents uncontrolled API spend. [VERIFIED: 03-CONTEXT.md] |
| Raw result table as evidence | Analytical profile plus chart/table/fallback evidence | Phase 3 scope [VERIFIED: 03-CONTEXT.md] | Gives management-readable insight instead of row dumps. [VERIFIED: 03-CONTEXT.md] |
| Prompted JSON only | JSON schema constrained outputs where enabled, plus local validation | Anthropic structured outputs docs current as of 2026-06-22 [CITED: https://platform.claude.com/docs/en/build-with-claude/structured-outputs] | Optional LLM planner can be safer, but still needs local fallback due refusals, token limits, and cost. [CITED: https://platform.claude.com/docs/en/build-with-claude/structured-outputs] |

**Deprecated/outdated:**
- Expanding `PRESENTATION_EXPORT_MODE=claude` direct PPTX generation is out of scope. [VERIFIED: 03-CONTEXT.md]
- Making `streamlit_app.py` inspect slide specs or chart payloads is out of scope. [VERIFIED: 02-CONTEXT.md] [VERIFIED: 03-CONTEXT.md]

## Risks And Sequencing

### Recommended Sequence

1. Add deterministic planner/profile module and tests for title, W05 metrics, numeric formatting, table page plans, and chart decisions. [VERIFIED: 03-CONTEXT.md]
2. Adapt `build_slide_deck_spec()` to consume the plan and produce German slide labels, fallback slides, and visible truncation notes. [VERIFIED: src/agent/presentation_export.py]
3. Add rich text rendering helpers and tests that reopen PPTX and inspect bold runs. [CITED: https://python-pptx.readthedocs.io/en/latest/api/text.html]
4. Add horizontal top-N matplotlib rendering and tests for label budgets. [CITED: https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html]
5. Add optional LLM planner stubs only after deterministic behavior is green; keep it disabled by default. [VERIFIED: 03-CONTEXT.md]
6. Update `.env.example` only if adding non-secret planner toggles, and remove or clearly segregate direct Claude PPTX settings from recommended Phase 3 mode. [VERIFIED: .env.example] [VERIFIED: 03-CONTEXT.md]

### Files Likely To Change

- `src/agent/presentation_planner.py` new. [ASSUMED]
- `src/agent/presentation_export.py` for plan consumption, rich text, German labels, chart orientation, table notes, and fallback slides. [VERIFIED: src/agent/presentation_export.py]
- `evaluation/test_presentation_export.py` for Phase 3 regression coverage. [VERIFIED: evaluation/test_presentation_export.py]
- `.env.example` if planner mode and planner limits are introduced. [VERIFIED: 03-CONTEXT.md]
- `requirements.txt` should not change unless a future decision adds a JSON-schema validator, which is not recommended for Phase 3. [VERIFIED: requirements.txt] [ASSUMED]

### Main Risks

- Visual overflow cannot be proven perfectly without PowerPoint rendering, but reopened PPTX inspection can catch text presence, slide counts, table dimensions, image existence, and bold runs. [VERIFIED: evaluation/test_presentation_export.py] [ASSUMED]
- `python-pptx` `fit_text()` depends on local fonts when no font file is provided, so budgets and slide splitting should be primary. [CITED: https://python-pptx.readthedocs.io/en/latest/api/text.html] [ASSUMED]
- Matplotlib 3.11.0 is newly released as of 2026-06-12; the repo venv has it and current tests pass, but pinning is absent. [VERIFIED: PyPI JSON] [VERIFIED: local unittest]
- Existing `.env.example` exposes direct Claude PPTX configuration names that conflict with the approved Phase 3 direction. [VERIFIED: .env.example] [VERIFIED: 03-CONTEXT.md]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A new `presentation_planner.py` is cleaner than adding all helpers to the current exporter. | Architecture Patterns | If wrong, planner can keep helpers in `presentation_export.py`, but file complexity may grow. |
| A2 | Top-N chart default should be 8 categories plus optional `Sonstige`. | Data Profiling And Chart Rules | If too high or low, charts may still overflow or hide useful categories. |
| A3 | Horizontal bars are the best default for long categorical labels. | Data Profiling And Chart Rules | If template placeholder geometry differs, vertical bars or tables may be clearer. |
| A4 | `fit_text()` should not be primary overflow control. | Overflow And Truncation Strategy | If font availability is stable in deployment, fit_text could be useful as a secondary guard. |
| A5 | No new JSON-schema dependency is needed for Phase 3. | Files Likely To Change | If schema validation grows complex, a future checkpoint may approve `jsonschema` or Pydantic. |

## Open Questions (RESOLVED)

1. **RESOLVED: Should zero-row results become exportable limitation decks?**
   - What we know: Current eligibility rejects missing rows and zero row count. [VERIFIED: src/agent/presentation_export.py]
   - Decision: Keep zero-row export unavailable for Phase 3 and cover empty-result behavior through the existing unavailable path plus tests. [RESOLVED: 03-PLAN]
   - Rationale: Phase 3 improves readable exports from successful result data; changing zero-row product behavior would expand export eligibility beyond the current validated contract. [VERIFIED: src/agent/presentation_export.py]

2. **RESOLVED: Should direct Claude PPTX mode be removed, hidden, or left untouched?**
   - What we know: Existing code and `.env.example` include direct Claude PPTX mode. [VERIFIED: src/agent/presentation_export.py] [VERIFIED: .env.example]
   - Decision: Do not expand direct Claude PPTX mode in Phase 3. Leave legacy code untouched unless needed for safe separation, and keep `PRESENTATION_EXPORT_MODE=deterministic` as the documented default. [RESOLVED: 03-PLAN]
   - Rationale: The user-approved strategy rejects direct LLM-generated PPTX after the failed expensive attempt. Optional model use may only produce validated planning JSON. [VERIFIED: 03-CONTEXT.md]

3. **RESOLVED: Should optional LLM planning ship in Phase 3 or remain a deterministic-only extension point?**
   - What we know: Optional LLM JSON planning is allowed, not required. [VERIFIED: 03-CONTEXT.md]
   - Decision: Ship deterministic planning first. If an optional JSON planner hook is implemented, it must be disabled by default, fake-tested only, locally validated, and must fall back deterministically on any failure. [RESOLVED: 03-PLAN]
   - Rationale: The immediate quality problem is solvable with deterministic profiling, German copy rules, top-N evidence, and renderer fixes; live LLM planning would add cost and test fragility. [VERIFIED: 03-CONTEXT.md]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Repo `.venv` Python | Current test execution | yes [VERIFIED: local command] | Python 3.12.13 [VERIFIED: local command] | Docker Python 3.11 target [VERIFIED: AGENTS.md] |
| Default `python` | Ad-hoc shell execution | yes but wrong env [VERIFIED: local command] | Python 3.14.5, missing `pptx` [VERIFIED: local command] | Use `.venv\Scripts\python.exe` |
| Python 3.11 via `py -3.11` | Project target runtime | no [VERIFIED: local command] | Not installed via launcher [VERIFIED: local command] | Docker image uses Python 3.11 [VERIFIED: AGENTS.md] |
| `python-pptx` | PPTX rendering and tests | yes in `.venv` [VERIFIED: local command] | 1.0.2 [VERIFIED: local command] | Install `requirements.txt` |
| `matplotlib` | PNG charts | yes in `.venv` [VERIFIED: local command] | 3.11.0 [VERIFIED: local command] | Fallback to table/limitation slide |
| `pandas` | Profiling and reporting | yes in `.venv` [VERIFIED: local command] | 3.0.3 [VERIFIED: local command] | Use stdlib counters for simple top-N |
| Docker | Python 3.11 container fallback | yes [VERIFIED: local command] | 29.4.3 [VERIFIED: local command] | `.venv` for local tests |
| `ctx7` | Context7 docs lookup fallback | no [VERIFIED: local command] | n/a | Official docs via web search/open |

**Missing dependencies with no fallback:** none for research. [VERIFIED: local command]

**Missing dependencies with fallback:**
- Python 3.11 launcher runtime is missing locally, but Docker and the existing `.venv` can run tests. [VERIFIED: local command] [VERIFIED: AGENTS.md]
- Default `python` cannot import `pptx`; use `.venv\Scripts\python.exe` for local verification commands. [VERIFIED: local command]

## Security Domain

Security enforcement is enabled by default because `.planning/config.json` does not set `security_enforcement` to `false`. [VERIFIED: .planning/config.json]

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| Authentication | no | Phase 3 does not add app login or memory RBAC. [VERIFIED: 03-CONTEXT.md] |
| Session Management | no | Phase 3 keeps existing Streamlit export state only. [VERIFIED: 02-CONTEXT.md] |
| Access Control | no | Memory/RBAC work is Phase 4. [VERIFIED: 03-CONTEXT.md] |
| Validation, Sanitization, and Encoding | yes | Validate planner JSON, cap result payloads, enforce slide budgets, and escape/render text through `python-pptx` APIs. [CITED: https://owasp.org/www-project-application-security-verification-standard/] [VERIFIED: 03-CONTEXT.md] |
| Stored Cryptography | no | Phase 3 does not add secrets storage or cryptographic features. [VERIFIED: 03-CONTEXT.md] |
| Error Handling and Logging | yes | Return structured warnings/unavailable reasons and do not print secrets. [VERIFIED: AGENTS.md] [VERIFIED: src/agent/presentation_export.py] |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection into optional planner | Tampering | Send capped, structured context; require JSON schema validation; deterministic fallback on invalid output. [VERIFIED: 03-CONTEXT.md] |
| Sensitive data leakage to LLM | Information disclosure | Do not send unbounded rows, secrets, `.env`, or external credentials; keep payload to sanitized question, SQL, metadata, profiles, and capped samples. [VERIFIED: 03-CONTEXT.md] |
| Active content in PPT template | Tampering | Continue template scan that blocks macros and external relationships while warning on known OLE entries. [VERIFIED: src/agent/presentation_export.py] |
| Misleading unsupported KPI output | Integrity | Keep missing Wuerth data limitations explicit; do not invent revenue, packing cost, plant, shipment date, or currency. [VERIFIED: semantic_layer/databricks/wuerth_semantic_layer.yaml] |
| Broken or unreadable generated deck | Availability | Validate slide budgets before rendering and fall back to table/limitation slides. [VERIFIED: 03-CONTEXT.md] |

## Sources

### Primary (HIGH confidence)

- `AGENTS.md` - project constraints, architecture, conventions, and testing rules. [VERIFIED: local read]
- `.planning/PROJECT.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md` - phase scope, requirements, and current completion status. [VERIFIED: local read]
- `.planning/phases/03-readable-evidence-and-fallback-slice/03-CONTEXT.md` - user-approved Phase 3 constraints and detailed scope. [VERIFIED: local read]
- `.planning/phases/01-deterministic-backend-deck-slice/01-CONTEXT.md` and `.planning/phases/02-streamlit-downloadable-deck-slice/02-CONTEXT.md` - prior phase decisions. [VERIFIED: local read]
- `src/agent/presentation_export.py`, `src/agent/reporting_agent.py`, `src/agent/visualization_spec.py`, `streamlit_app.py`, `evaluation/test_presentation_export.py`, `.env.example`, `requirements.txt` - existing code patterns and extension points. [VERIFIED: local read]
- `evaluation/wuerth_local/solution_sql/w05_shipments_without_invoices.sql` and `semantic_layer/databricks/wuerth_semantic_layer.yaml` - W05 result shape, join mapping, and source-data limitations. [VERIFIED: local read]
- python-pptx official docs: https://python-pptx.readthedocs.io/ and https://python-pptx.readthedocs.io/en/latest/user/text.html - PPTX capabilities and rich text runs. [CITED: official docs]
- Matplotlib official docs: https://matplotlib.org/stable/install/index.html, https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.savefig.html, and https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.tight_layout.html - non-interactive backend, image saving, and layout. [CITED: official docs]
- Anthropic structured outputs docs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs - optional JSON schema constrained planning caveats. [CITED: official docs]

### Secondary (MEDIUM confidence)

- PyPI package pages and PyPI JSON API for current package versions and upload dates. [VERIFIED: PyPI JSON] [CITED: https://pypi.org/project/python-pptx/] [CITED: https://pypi.org/project/matplotlib/] [CITED: https://pypi.org/project/pandas/]
- `slopcheck` plain-text audit of `python-pptx`, `matplotlib`, and `pandas`. [VERIFIED: local command]

### Tertiary (LOW confidence)

- Exact visual thresholds such as top 8 categories, 32 to 40 character labels, and grouped bar limits are design assumptions pending implementation screenshots or manual deck inspection. [ASSUMED]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Packages are already in `requirements.txt`, installed in `.venv`, verified with `pip index versions`, slopcheck OK, and documented by official sources. [VERIFIED: requirements.txt] [VERIFIED: local command] [CITED: official docs]
- Architecture: HIGH - Existing boundary and extension points are clear in `presentation_export.py`, `streamlit_app.py`, and Phase 1/2 context. [VERIFIED: codebase grep] [VERIFIED: 01-CONTEXT.md] [VERIFIED: 02-CONTEXT.md]
- Pitfalls: HIGH for existing issues directly visible in code and context, MEDIUM for exact overflow thresholds. [VERIFIED: src/agent/presentation_export.py] [ASSUMED]

**Research date:** 2026-06-22
**Valid until:** 2026-07-22 for deterministic exporter guidance; re-check LLM structured-output docs within 7 days if optional LLM planning is implemented. [ASSUMED]
