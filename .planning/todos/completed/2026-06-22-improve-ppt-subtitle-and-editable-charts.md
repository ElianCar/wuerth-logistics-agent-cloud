---
created: 2026-06-22T12:25:03.914Z
completed: 2026-06-22T12:39:00Z
title: Improve PPT subtitle and editable charts
area: presentation-export
files:
  - src/agent/presentation_export.py:432
  - src/agent/presentation_export.py:1255
  - src/agent/presentation_export.py:1281
  - src/agent/presentation_export.py:1588
  - src/agent/presentation_planner.py:867
  - evaluation/test_presentation_export.py:669
  - evaluation/test_presentation_export.py:739
---

## Problem

The generated title slide is much better, but the cover subtitle can still end with an ellipsis and can visually feel like raw analysis text pasted into a title page. The subtitle should be capped at about 170 characters without using trailing `...`; it should read like a concise German management subtitle.

Charts are currently rendered as image output in the deck. They look acceptable, but they are not editable in PowerPoint. Management users may need to adjust labels, colors, or series manually after export.

## Solution

1. Add a hard cover subtitle budget of about 170 characters in the presentation export path. Prefer sentence-aware truncation without `...`, and add tests that reopen the generated PPTX and assert no subtitle overflow marker appears.
2. Investigate native editable PowerPoint charts with `python-pptx` `slide.shapes.add_chart(...)` and embedded chart data. If the library supports the needed chart types cleanly, render simple bar, line, and possibly pie or doughnut charts as native charts first.
3. Keep the current image-based chart renderer as a fallback for chart shapes that cannot be represented well as native PowerPoint charts.
4. Add regression tests that detect native chart shapes for supported cases and still allow image fallback for unsupported or unsafe cases.

## Completion

Implemented cover subtitle trimming without ellipses and native editable PowerPoint charts for supported bar, horizontal top-N, and line chart specs. The existing PNG renderer remains as fallback when native chart generation is unavailable or unsuitable.
