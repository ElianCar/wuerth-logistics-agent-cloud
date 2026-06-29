# Wuerth PowerPoint Master Layout Guide

## Purpose

The generated deck should use a small, stable set of Wuerth-branded layouts. The original master contained 34 layouts and 3 sample slides. The current automation master has been simplified to agent-specific layouts. The renderer should target this subset by layout name plus placeholder indexes.

## Current Template Notes

- Template path: `assets/templates/PPT_Vorlage_Wuerth.pptx`
- Current size: 16:9
- Current layout count: 9
- Current sample slide count: 1
- Current embedded OLE objects: 2
- Macros: none detected
- External relationships: none detected

The remaining embedded OLE objects are think-cell data objects. They should be ignored by automation targets and preserved only if deleting them from PowerPoint is not practical. Template validation should warn about them but should not block generation when there are no macros, no external relationships, and the target layouts can still render.

## Recommended Layouts To Keep

Use these as the automation subset. The names below should become stable layout names in the PowerPoint master.

| Automation Layout | Suggested Base Layout | Used For | Required Named Areas |
|-------------------|-----------------------|----------|----------------------|
| Agent 01 Cover | `Titel` or `Titel, hell alternativ` | First slide with analysis title and question | `deck_title`, `analysis_question`, `scenario`, `run_date` |
| Agent 02 Executive Summary | `Summary` or `Titel und Inhalt` | Main takeaway and short summary | `slide_title`, `takeaway`, `summary_bullets` |
| Agent 03 KPI Overview | `3-spaltig Bild + Erlaeuterung` variant | Up to three key metrics or findings | `kpi_1_label`, `kpi_1_value`, `kpi_1_note`, repeated through 3 |
| Agent 04 Chart Evidence | `Marginalspalte 70:30` or `Titel und Inhalt` | One main chart plus interpretation | `slide_title`, `chart_area`, `insight_text`, `source_note` |
| Agent 05 Table Evidence | `Titel und Inhalt` | Result rows when chart is not the best evidence | `slide_title`, `table_area`, `truncation_note`, `source_note` |
| Agent 06 Comparison | `Zwei Inhalte` or `Vergleich` | Side-by-side chart/table comparison | `slide_title`, `left_title`, `left_area`, `right_title`, `right_area` |
| Agent 07 Caveats And Sources | `Titel und Inhalt` | Limitations, assumptions, source tables | `slide_title`, `limitations`, `source_tables`, `assumptions` |
| Agent 08 Appendix Metadata | `Titel und Inhalt` | Run metadata and audit details | `slide_title`, `run_metadata`, `validation_state`, `memory_template_ids` |

Optional:

| Automation Layout | Suggested Base Layout | Used For |
|-------------------|-----------------------|----------|
| Agent 09 Closing | `Danke` or `Abschluss Logo` | Optional final slide |

## Current Layout Names

The current file exposes these layout names:

1. `Agent 01 Cover`
2. `Agent 02 Executive Summary`
3. `Agent 03 KPI Overview`
4. `Agent 04 Chart Evidence`
5. `Agent 05 Table Evidence`
6. `Agent 06 Comparison`
7. `Agent 07 Caveats And Sources`
8. `Agent 08 Appendix Metadata`
9. `Agent 09 Closing`

## Dynamic Deck Rule

The renderer must not always generate all 9 layouts. It should build a slide sequence from available content:

- Always include `Agent 01 Cover`.
- Include `Agent 02 Executive Summary` when a summary or takeaway exists.
- Include `Agent 03 KPI Overview` only when there are useful KPIs or up to three key findings.
- Repeat `Agent 04 Chart Evidence` for each supported chart evidence slide.
- Repeat `Agent 05 Table Evidence` for each table evidence slide or fallback.
- Use `Agent 06 Comparison` only for real side-by-side comparisons.
- Include `Agent 07 Caveats And Sources` when limitations, assumptions, or source tables need display.
- Include `Agent 08 Appendix Metadata` when run metadata, validation state, or memory template IDs are available.
- Include `Agent 09 Closing` only if the deck contract enables a closing slide.

Longer decks are preferable to overcrowded slides. Multiple `Agent 04` or `Agent 05` slides should be used instead of placing too much content on one slide.

## Layouts To Drop Or Defer

Drop these from the automation subset unless a human deck editor still needs them:

- 6 or 8 KPI chart grids
- Image-only grids
- Quote layouts
- Contact layout
- Chapter separator layouts
- Fullscreen image layouts
- Dense multi-column image plus explanation layouts
- Blank layout

The reason is simple: they either make automated content fitting harder or are not needed for logistics analysis output.

## Placeholder Guidance

For automation, visible placeholder text is helpful, but shape names matter more.

Recommended approach:

1. Rename each kept layout with the `Agent NN ...` naming scheme.
2. Key objects may stay with default PowerPoint names if the renderer targets layout name plus placeholder index.
3. Put visible placeholder text into each object, for example `{{deck_title}}`, `{{chart_area}}`, or `{{table_area}}`, when practical.
4. Avoid embedded Excel charts or linked objects in the clean master. Remaining think-cell data objects are an accepted warning only if they do not block rendering.
5. Use normal placeholders or plain shapes for areas where the renderer will insert text, charts, or tables.
6. Keep footer, date, and page number behavior consistent across all kept layouts.

## Screenshots

Screenshots are not required to map the template mechanically. They are useful for visual decisions. If the master is simplified, the best review input is one screenshot per kept layout at 16:9 size.
