# Wuerth PowerPoint Master Layout Guide

## Purpose

The generated deck should use a small, stable set of Wuerth-branded layouts. The current master contains 34 layouts and 3 sample slides. That is useful for humans, but too broad for reliable automation. The renderer should target a clean subset with predictable layout names and shape names.

## Current Template Notes

- Template path: `assets/templates/PPT_Vorlage_Wuerth.pptx`
- Current size: 16:9
- Current layout count: 34
- Current sample slide count: 3
- Current embedded OLE objects: 4

Embedded OLE objects should be removed from the automation master if possible. Keep Wuerth branding, masters, fonts, colors, logos, footers, and page numbering.

## Recommended Layouts To Keep

Use these as the automation subset. The names below should become stable layout names in the PowerPoint master.

| Automation Layout | Suggested Base Layout | Used For | Required Named Areas |
|-------------------|-----------------------|----------|----------------------|
| Agent 01 Cover | `Titel` or `Titel, hell alternativ` | First slide with analysis title and question | `deck_title`, `analysis_question`, `scenario`, `run_date` |
| Agent 02 Executive Summary | `Summary` or `Titel und Inhalt` | Main takeaway and short summary | `slide_title`, `takeaway`, `summary_bullets` |
| Agent 03 KPI Overview | `4 x KPI-Diagramme` | Up to four key metrics | `kpi_1_label`, `kpi_1_value`, `kpi_1_note`, repeated through 4 |
| Agent 04 Chart Evidence | `Marginalspalte 70:30` or `Titel und Inhalt` | One main chart plus interpretation | `slide_title`, `chart_area`, `insight_text`, `source_note` |
| Agent 05 Table Evidence | `Titel und Inhalt` | Result rows when chart is not the best evidence | `slide_title`, `table_area`, `truncation_note`, `source_note` |
| Agent 06 Comparison | `Zwei Inhalte` or `Vergleich` | Side-by-side chart/table comparison | `slide_title`, `left_title`, `left_area`, `right_title`, `right_area` |
| Agent 07 Caveats And Sources | `Titel und Inhalt` | Limitations, assumptions, source tables | `slide_title`, `limitations`, `source_tables`, `assumptions` |
| Agent 08 Appendix Metadata | `Titel und Inhalt` | Run metadata and audit details | `slide_title`, `run_metadata`, `validation_state`, `memory_template_ids` |

Optional:

| Automation Layout | Suggested Base Layout | Used For |
|-------------------|-----------------------|----------|
| Agent 09 Closing | `Danke` or `Abschluss Logo` | Optional final slide |

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
2. Rename key objects in PowerPoint's Selection Pane using the required names above.
3. Put visible placeholder text into each object, for example `{{deck_title}}`, `{{chart_area}}`, or `{{table_area}}`.
4. Avoid embedded Excel charts or linked objects in the clean master.
5. Use normal placeholders or plain shapes for areas where the renderer will insert text, charts, or tables.
6. Keep footer, date, and page number behavior consistent across all kept layouts.

## Screenshots

Screenshots are not required to map the template mechanically. They are useful for visual decisions. If the master is simplified, the best review input is one screenshot per kept layout at 16:9 size.
