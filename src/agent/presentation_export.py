from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from pptx import Presentation
from pptx.util import Inches, Pt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "assets" / "templates" / "PPT_Vorlage_Wuerth.pptx"
PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MAX_TABLE_ROWS_PER_SLIDE = 5
MAX_TABLE_COLUMNS_PER_SLIDE = 6
MAX_BODY_ITEMS_PER_SLIDE = 8
MAX_BODY_TEXT_CHARS_PER_SLIDE = 700
EXPECTED_TEMPLATE_SHA256 = "041DE8AC3214DC1892F127021F223D5B9C9D5571B10D6949D022B5A357190EA5"
FIXED_PPTX_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

LAYOUT_COVER = "Agent 01 Cover"
LAYOUT_SUMMARY = "Agent 02 Executive Summary"
LAYOUT_KPI = "Agent 03 KPI Overview"
LAYOUT_CHART = "Agent 04 Chart Evidence"
LAYOUT_TABLE = "Agent 05 Table Evidence"
LAYOUT_COMPARISON = "Agent 06 Comparison"
LAYOUT_CAVEATS = "Agent 07 Caveats And Sources"
LAYOUT_METADATA = "Agent 08 Appendix Metadata"
LAYOUT_CLOSING = "Agent 09 Closing"

SLIDE_TYPE_LAYOUTS = {
    "cover": {LAYOUT_COVER},
    "executive_summary": {LAYOUT_SUMMARY},
    "kpi_overview": {LAYOUT_KPI},
    "chart_evidence": {LAYOUT_CHART},
    "table_evidence": {LAYOUT_TABLE},
    "comparison": {LAYOUT_COMPARISON},
    "caveats_sources": {LAYOUT_CAVEATS},
    "appendix_metadata": {LAYOUT_METADATA},
    "closing": {LAYOUT_CLOSING},
}
BODY_REQUIRED_SLIDE_TYPES = {
    "cover",
    "executive_summary",
    "kpi_overview",
    "chart_evidence",
    "comparison",
    "caveats_sources",
    "appendix_metadata",
    "closing",
}
TABLE_REQUIRED_SLIDE_TYPES = {"table_evidence"}
SUPPORTED_CHART_TYPES = {"bar", "line"}


@dataclass(frozen=True)
class SlideSpec:
    slide_type: str
    layout_name: str
    title: str
    body: list[str] = field(default_factory=list)
    table_columns: list[str] = field(default_factory=list)
    table_rows: list[list[str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SlideDeckSpec:
    title: str
    slides: list[SlideSpec]
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TemplateManifest:
    required_layouts: tuple[str, ...]
    optional_layouts: tuple[str, ...] = ()
    layout_aliases: dict[str, str] = field(default_factory=dict)
    placeholder_indexes: dict[str, dict[str, int]] = field(default_factory=dict)
    known_warning_entries: tuple[str, ...] = ()
    expected_sha256: str = ""


@dataclass(frozen=True)
class TemplateAudit:
    available: bool
    template_path: str
    sha256: str = ""
    slide_count: int = 0
    layout_names: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    ole_entries: list[str] = field(default_factory=list)
    external_relationships: list[str] = field(default_factory=list)
    macro_entries: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PresentationExport:
    available: bool
    content: bytes
    filename: str
    mime_type: str
    slide_count: int
    warnings: list[str]
    unavailable_reason: str = ""
    template_audit: TemplateAudit | None = None
    deck_spec: SlideDeckSpec | None = None


@dataclass(frozen=True)
class PresentationEligibility:
    can_export: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.can_export


class PresentationExportError(ValueError):
    """Raised when deterministic PPTX rendering fails unexpectedly."""


DEFAULT_TEMPLATE_MANIFEST = TemplateManifest(
    required_layouts=(
        LAYOUT_COVER,
        LAYOUT_SUMMARY,
        LAYOUT_KPI,
        LAYOUT_CHART,
        LAYOUT_TABLE,
        LAYOUT_CAVEATS,
        LAYOUT_METADATA,
    ),
    optional_layouts=(LAYOUT_COMPARISON, LAYOUT_CLOSING),
    layout_aliases={
        "Agent 07 Caveats And Sources Agent": LAYOUT_CAVEATS,
        "1_Agent 08 Appendix Metadata": LAYOUT_METADATA,
    },
    placeholder_indexes={
        LAYOUT_COVER: {"title": 0, "subtitle": 1, "body": 14},
        LAYOUT_SUMMARY: {"title": 0, "body": 13, "content": 14},
        LAYOUT_KPI: {"title": 0, "body": 13},
        LAYOUT_CHART: {"title": 0, "body": 13, "content": 32},
        LAYOUT_TABLE: {"title": 0, "body": 13, "content": 14},
        LAYOUT_CAVEATS: {"title": 0, "body": 13, "content": 14},
        LAYOUT_METADATA: {"title": 0, "body": 13, "content": 14},
    },
    known_warning_entries=(
        "ppt/embeddings/oleObject1.bin",
        "ppt/embeddings/oleObject2.bin",
    ),
    expected_sha256=EXPECTED_TEMPLATE_SHA256,
)


def build_presentation_export(
    *,
    record: dict[str, Any],
    include_closing: bool = False,
    template_path: Path | str = DEFAULT_TEMPLATE_PATH,
) -> PresentationExport:
    """Build deterministic PPTX bytes from an already validated agent result.

    This function does not generate SQL, execute SQL, call a database, call an
    LLM, or import Streamlit. It only inspects an existing orchestrator record
    and renders a validated local slide spec through the Wuerth template.
    """

    eligibility = can_export_presentation(record)
    if not eligibility.can_export:
        return _unavailable_export(eligibility.reason)

    try:
        deck_spec = build_slide_deck_spec(record=record, include_closing=include_closing)
    except PresentationExportError as error:
        return _unavailable_export(str(error))

    spec_errors = validate_slide_deck_spec(deck_spec)
    if spec_errors:
        return _unavailable_export("slide_spec_invalid", warnings=spec_errors, deck_spec=deck_spec)

    audit = validate_template(template_path=template_path)
    if audit.errors:
        return _unavailable_export(
            "template_invalid",
            warnings=[*audit.warnings, *audit.errors],
            template_audit=audit,
            deck_spec=deck_spec,
        )

    try:
        content = _render_presentation(
            deck_spec=deck_spec,
            template_path=Path(template_path),
        )
        reopened = Presentation(BytesIO(content))
    except Exception as error:
        return _unavailable_export(
            "render_failed",
            warnings=[f"PPTX rendering failed: {type(error).__name__}."],
            template_audit=audit,
            deck_spec=deck_spec,
        )

    warnings = [*deck_spec.warnings, *audit.warnings]
    return PresentationExport(
        available=True,
        content=content,
        filename=_filename_for(record),
        mime_type=PPTX_MIME_TYPE,
        slide_count=len(reopened.slides),
        warnings=_unique(warnings),
        unavailable_reason="",
        template_audit=audit,
        deck_spec=deck_spec,
    )


def can_export_presentation(record: dict[str, Any]) -> PresentationEligibility:
    """Return whether a record is eligible for deterministic PPTX export."""

    reason = _record_unavailable_reason(record)
    return PresentationEligibility(can_export=not reason, reason=reason)


def build_slide_deck_spec(
    *,
    record: dict[str, Any],
    include_closing: bool = False,
) -> SlideDeckSpec:
    """Build an ordered, dynamic slide spec from a successful record."""

    eligibility = can_export_presentation(record)
    if not eligibility.can_export:
        raise PresentationExportError(eligibility.reason)

    reporting = _dict_or_empty(record.get("reporting_result"))
    query = _dict_or_empty(record.get("query_result"))
    source_tables = _string_list(record.get("source_tables"))
    title = _deck_title(record)
    warnings: list[str] = []

    slides: list[SlideSpec] = [
        SlideSpec(
            slide_type="cover",
            layout_name=LAYOUT_COVER,
            title=title,
            body=[
                _text_or_default(record.get("user_question"), "Validated logistics analysis"),
                f"Scenario sources: {_source_text(source_tables)}",
                f"Run ID: {_text_or_default(record.get('run_id'), 'not recorded')}",
            ],
            metadata={"run_id": str(record.get("run_id", ""))},
        )
    ]

    summary_body = _summary_body(reporting)
    if summary_body:
        slides.append(
            SlideSpec(
                slide_type="executive_summary",
                layout_name=LAYOUT_SUMMARY,
                title="Executive Summary",
                body=summary_body,
            )
        )

    kpi_cards = _list_of_dicts(reporting.get("kpi_cards"))
    if kpi_cards:
        slides.append(
            SlideSpec(
                slide_type="kpi_overview",
                layout_name=LAYOUT_KPI,
                title="KPI Overview",
                body=_kpi_body(kpi_cards),
            )
        )

    chart_plan = _dict_or_empty(reporting.get("chart_plan") or record.get("chart_spec"))
    if chart_plan.get("render_allowed"):
        chart_columns = _chart_table_columns(chart_plan)
        chart_rows = _chart_table_rows(query, chart_plan)
        chart_type = str(chart_plan.get("chart_type") or "").lower()
        if chart_type not in SUPPORTED_CHART_TYPES or len(chart_columns) != 2 or not chart_rows:
            warnings.append("Chart evidence was skipped because the chart payload is not backed by result data.")
        else:
            slides.append(
                SlideSpec(
                    slide_type="chart_evidence",
                    layout_name=LAYOUT_CHART,
                    title=str(chart_plan.get("title") or "Chart Evidence"),
                    body=_chart_body(chart_plan, reporting),
                    table_columns=chart_columns,
                    table_rows=chart_rows,
                    metadata={"chart_type": chart_type},
                )
            )

    table_columns, table_rows, table_warnings = _table_content(query)
    warnings.extend(table_warnings)
    for index, chunk in enumerate(_chunks(table_rows, MAX_TABLE_ROWS_PER_SLIDE), start=1):
        slides.append(
            SlideSpec(
                slide_type="table_evidence",
                layout_name=LAYOUT_TABLE,
                title=f"Table Evidence {index}",
                body=[
                    "Rows follow the validated SQL result order.",
                    f"Showing rows {(index - 1) * MAX_TABLE_ROWS_PER_SLIDE + 1}-{(index - 1) * MAX_TABLE_ROWS_PER_SLIDE + len(chunk)}.",
                ],
                table_columns=table_columns,
                table_rows=chunk,
            )
        )

    caveat_body = _caveats_body(reporting, source_tables)
    if caveat_body:
        slides.append(
            SlideSpec(
                slide_type="caveats_sources",
                layout_name=LAYOUT_CAVEATS,
                title="Caveats And Sources",
                body=caveat_body,
            )
        )

    metadata_body = _metadata_body(record)
    if metadata_body:
        slides.append(
            SlideSpec(
                slide_type="appendix_metadata",
                layout_name=LAYOUT_METADATA,
                title="Appendix Metadata",
                body=metadata_body,
                metadata={"final_sql": str(record.get("final_sql") or "")},
            )
        )

    if include_closing:
        slides.append(
            SlideSpec(
                slide_type="closing",
                layout_name=LAYOUT_CLOSING,
                title="Closing",
                body=["Generated from a validated logistics analysis result."],
            )
        )

    return SlideDeckSpec(
        title=title,
        slides=slides,
        warnings=_unique(warnings),
        metadata={
            "run_id": str(record.get("run_id", "")),
            "final_sql": str(record.get("final_sql") or ""),
            "source_tables": ",".join(source_tables),
        },
    )


def validate_slide_deck_spec(
    deck_spec: SlideDeckSpec,
    *,
    manifest: TemplateManifest = DEFAULT_TEMPLATE_MANIFEST,
) -> list[str]:
    errors: list[str] = []
    allowed_layouts = set(manifest.required_layouts) | set(manifest.optional_layouts)
    repeatable_layouts = {LAYOUT_CHART, LAYOUT_TABLE}

    if not deck_spec.slides:
        errors.append("Slide deck spec must contain at least one slide.")
        return errors

    if deck_spec.slides[0].layout_name != LAYOUT_COVER:
        errors.append("First slide must use Agent 01 Cover.")

    layout_names = [slide.layout_name for slide in deck_spec.slides]
    if layout_names == [
        LAYOUT_COVER,
        LAYOUT_SUMMARY,
        LAYOUT_KPI,
        LAYOUT_CHART,
        LAYOUT_TABLE,
        LAYOUT_COMPARISON,
        LAYOUT_CAVEATS,
        LAYOUT_METADATA,
        LAYOUT_CLOSING,
    ]:
        errors.append("Slide deck spec appears to be a fixed 9-slide deck.")

    for index, slide in enumerate(deck_spec.slides, start=1):
        allowed_layouts_for_type = SLIDE_TYPE_LAYOUTS.get(slide.slide_type)
        if allowed_layouts_for_type is None:
            errors.append(f"Slide {index} has unsupported slide type: {slide.slide_type}.")
        elif slide.layout_name not in allowed_layouts_for_type:
            errors.append(
                f"Slide {index} layout {slide.layout_name} is not valid for slide type {slide.slide_type}."
            )
        if slide.layout_name not in allowed_layouts:
            errors.append(f"Slide {index} uses unsupported layout: {slide.layout_name}.")
        if not slide.slide_type:
            errors.append(f"Slide {index} has no slide_type.")
        if not slide.title:
            errors.append(f"Slide {index} has no title.")
        if len(slide.title) > 140:
            errors.append(f"Slide {index} title exceeds text budget.")
        body_text_size = sum(len(item) for item in slide.body)
        if body_text_size > MAX_BODY_TEXT_CHARS_PER_SLIDE:
            errors.append(f"Slide {index} body exceeds text budget.")
        if len(slide.body) > MAX_BODY_ITEMS_PER_SLIDE:
            errors.append(f"Slide {index} body exceeds item budget.")
        if slide.slide_type in BODY_REQUIRED_SLIDE_TYPES and not any(str(item).strip() for item in slide.body):
            errors.append(f"Slide {index} is missing required content.")
        if slide.slide_type in TABLE_REQUIRED_SLIDE_TYPES and (not slide.table_columns or not slide.table_rows):
            errors.append(f"Slide {index} is missing required table content.")
        if len(slide.table_rows) > MAX_TABLE_ROWS_PER_SLIDE:
            errors.append(f"Slide {index} table exceeds row limit.")
        if len(slide.table_columns) > MAX_TABLE_COLUMNS_PER_SLIDE:
            errors.append(f"Slide {index} table exceeds column limit.")
        if slide.table_rows and not slide.table_columns:
            errors.append(f"Slide {index} has rows without table columns.")
        if slide.slide_type == "chart_evidence":
            chart_type = str(slide.metadata.get("chart_type") or "").lower()
            if chart_type not in SUPPORTED_CHART_TYPES:
                errors.append(f"Slide {index} has unsupported chart payload: {chart_type}.")
            if not slide.table_columns or not slide.table_rows:
                errors.append(f"Slide {index} chart evidence is missing required result data.")

    repeated = {
        layout_name
        for layout_name in layout_names
        if layout_names.count(layout_name) > 1 and layout_name not in repeatable_layouts
    }
    for layout_name in sorted(repeated):
        errors.append(f"Layout is not repeatable in Phase 1: {layout_name}.")

    return errors


def validate_template(
    *,
    template_path: Path | str = DEFAULT_TEMPLATE_PATH,
    manifest: TemplateManifest = DEFAULT_TEMPLATE_MANIFEST,
) -> TemplateAudit:
    path = Path(template_path)
    safe_path = _safe_path(path)
    if not path.exists():
        return TemplateAudit(
            available=False,
            template_path=safe_path,
            errors=[f"Template file is missing: {safe_path}."],
        )
    if not path.is_file():
        return TemplateAudit(
            available=False,
            template_path=safe_path,
            errors=[f"Template path is not a file: {safe_path}."],
        )

    warnings: list[str] = []
    errors: list[str] = []
    ole_entries: list[str] = []
    macro_entries: list[str] = []
    external_relationships: list[str] = []

    try:
        digest = sha256(path.read_bytes()).hexdigest().upper()
    except OSError as error:
        return TemplateAudit(
            available=False,
            template_path=safe_path,
            errors=[f"Template file is not readable: {type(error).__name__}."],
        )

    if manifest.expected_sha256 and digest != manifest.expected_sha256:
        warnings.append("Template SHA256 differs from the inspected Phase 1 template.")

    try:
        with ZipFile(path) as package:
            names = package.namelist()
            ole_entries = sorted(name for name in names if name.startswith("ppt/embeddings/"))
            macro_entries = sorted(name for name in names if name.lower().endswith("vbaproject.bin"))
            active_x_entries = sorted(name for name in names if "/activeX/" in name or name.startswith("ppt/activeX/"))
            if active_x_entries:
                errors.extend(f"Template contains unsupported ActiveX content: {entry}." for entry in active_x_entries)
            if macro_entries:
                errors.extend(f"Template contains macro content: {entry}." for entry in macro_entries)
            external_relationships = _external_relationships(package)
    except BadZipFile:
        return TemplateAudit(
            available=False,
            template_path=safe_path,
            sha256=digest,
            errors=["Template is not a readable PPTX ZIP package."],
        )
    except OSError as error:
        return TemplateAudit(
            available=False,
            template_path=safe_path,
            sha256=digest,
            errors=[f"Template package scan failed: {type(error).__name__}."],
        )

    if external_relationships:
        errors.extend(
            f"Template contains external relationship: {relationship}."
            for relationship in external_relationships
        )

    unknown_ole = sorted(set(ole_entries) - set(manifest.known_warning_entries))
    if unknown_ole:
        errors.extend(f"Template contains unexpected embedded object: {entry}." for entry in unknown_ole)
    if ole_entries and manifest.expected_sha256 and digest != manifest.expected_sha256:
        errors.append("Template contains embedded objects but does not match the approved template hash.")
    elif ole_entries:
        warnings.extend(f"Template contains preserved OLE object warning: {entry}." for entry in ole_entries)

    try:
        presentation = Presentation(str(path))
        layout_names = [layout.name for layout in presentation.slide_layouts]
        slide_count = len(presentation.slides)
    except Exception as error:
        return TemplateAudit(
            available=False,
            template_path=safe_path,
            sha256=digest,
            warnings=warnings,
            errors=[*errors, f"Template cannot be opened by python-pptx: {type(error).__name__}."],
            ole_entries=ole_entries,
            external_relationships=external_relationships,
            macro_entries=macro_entries,
        )

    missing_layouts = [layout for layout in manifest.required_layouts if layout not in layout_names]
    if missing_layouts:
        errors.extend(f"Template is missing required layout: {layout}." for layout in missing_layouts)
    if slide_count and presentation.slides[0].slide_layout.name != LAYOUT_COVER:
        errors.append("Template sample slide does not use Agent 01 Cover.")

    return TemplateAudit(
        available=not errors,
        template_path=safe_path,
        sha256=digest,
        slide_count=slide_count,
        layout_names=layout_names,
        warnings=_unique(warnings),
        errors=errors,
        ole_entries=ole_entries,
        external_relationships=external_relationships,
        macro_entries=macro_entries,
    )


def _render_presentation(*, deck_spec: SlideDeckSpec, template_path: Path) -> bytes:
    presentation = Presentation(str(template_path))
    if not presentation.slides:
        cover_slide = presentation.slides.add_slide(_layout_by_name(presentation, LAYOUT_COVER))
    else:
        cover_slide = presentation.slides[0]

    _render_slide(cover_slide, deck_spec.slides[0])
    for slide_spec in deck_spec.slides[1:]:
        slide = presentation.slides.add_slide(_layout_by_name(presentation, slide_spec.layout_name))
        _render_slide(slide, slide_spec)

    output = BytesIO()
    presentation.save(output)
    return _normalize_pptx_package(output.getvalue())


def _normalize_pptx_package(content: bytes) -> bytes:
    normalized = BytesIO()
    with ZipFile(BytesIO(content), "r") as source, ZipFile(normalized, "w") as target:
        for name in sorted(source.namelist()):
            original = source.getinfo(name)
            info = ZipInfo(filename=name, date_time=FIXED_PPTX_TIMESTAMP)
            info.compress_type = ZIP_DEFLATED
            info.external_attr = original.external_attr
            info.comment = original.comment
            target.writestr(info, source.read(name))
    return normalized.getvalue()


def _render_slide(slide: Any, slide_spec: SlideSpec) -> None:
    _set_slide_title(slide, slide_spec.title)
    body = [item for item in slide_spec.body if item]
    if body:
        _add_body_box(slide, body)
    if slide_spec.table_rows:
        _add_table(slide, slide_spec.table_columns, slide_spec.table_rows)


def _layout_by_name(presentation: Any, layout_name: str) -> Any:
    layout = presentation.slide_layouts.get_by_name(layout_name)
    if layout is None:
        raise PresentationExportError(f"Template layout missing: {layout_name}.")
    return layout


def _set_slide_title(slide: Any, title: str) -> None:
    if getattr(slide.shapes, "title", None) is not None:
        slide.shapes.title.text = title
        return
    box = slide.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(11.6), Inches(0.7))
    box.text_frame.text = title


def _add_body_box(slide: Any, body: list[str]) -> None:
    box = slide.shapes.add_textbox(Inches(0.8), Inches(1.35), Inches(11.4), Inches(1.65))
    text_frame = box.text_frame
    text_frame.clear()
    for index, item in enumerate(body):
        paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
        paragraph.text = item
        paragraph.level = 0
        paragraph.font.size = Pt(15)


def _add_table(slide: Any, columns: list[str], rows: list[list[str]]) -> None:
    if not columns or not rows:
        return
    top = Inches(3.15)
    height = Inches(2.85)
    shape = slide.shapes.add_table(
        len(rows) + 1,
        len(columns),
        Inches(0.8),
        top,
        Inches(11.5),
        height,
    )
    table = shape.table
    for column_index, column_name in enumerate(columns):
        cell = table.cell(0, column_index)
        cell.text = column_name
        for paragraph in cell.text_frame.paragraphs:
            paragraph.font.size = Pt(11)
            paragraph.font.bold = True
    for row_index, row in enumerate(rows, start=1):
        for column_index, value in enumerate(row):
            cell = table.cell(row_index, column_index)
            cell.text = value
            for paragraph in cell.text_frame.paragraphs:
                paragraph.font.size = Pt(10)


def _record_unavailable_reason(record: dict[str, Any]) -> str:
    if not isinstance(record, dict):
        return "record_missing"
    if record.get("blocked_or_unsafe"):
        return "blocked_request"
    if record.get("needs_clarification"):
        return "clarification_needed"
    if not record.get("execution_success"):
        return "sql_execution_failed"
    if record.get("validation_success") is not True:
        return "sql_validation_failed"
    if record.get("sql_valid") is not True:
        return "sql_validation_failed"

    query = record.get("query_result")
    if not isinstance(query, dict):
        return "missing_query_result"
    columns = query.get("columns") or []
    rows = query.get("rows") or []
    if not columns:
        return "missing_query_columns"
    if not rows:
        return "missing_query_rows"
    effective_row_count = _effective_row_count(record, query, rows)
    if effective_row_count == 0:
        return "zero_row_count"
    return ""


def _unavailable_export(
    reason: str,
    *,
    warnings: list[str] | None = None,
    template_audit: TemplateAudit | None = None,
    deck_spec: SlideDeckSpec | None = None,
) -> PresentationExport:
    return PresentationExport(
        available=False,
        content=b"",
        filename="",
        mime_type=PPTX_MIME_TYPE,
        slide_count=0,
        warnings=warnings or [],
        unavailable_reason=reason,
        template_audit=template_audit,
        deck_spec=deck_spec,
    )


def _summary_body(reporting: dict[str, Any]) -> list[str]:
    body: list[str] = []
    summary = str(reporting.get("summary") or "").strip()
    interpretation = str(reporting.get("interpretation") or "").strip()
    if interpretation:
        body.append(_trim_text(interpretation, 220))
    body.extend(_extract_summary_lines(summary, limit=4))
    return _unique([item for item in body if item])[:MAX_BODY_ITEMS_PER_SLIDE]


def _extract_summary_lines(summary: str, *, limit: int) -> list[str]:
    if not summary:
        return []
    lines = []
    for part in re.split(r"\n+|(?<=\.)\s+", summary):
        text = _trim_text(part.strip(), 220)
        if text:
            lines.append(text)
        if len(lines) >= limit:
            break
    return lines


def _kpi_body(kpi_cards: list[dict[str, Any]]) -> list[str]:
    body = []
    for card in kpi_cards[:3]:
        label = _text_or_default(card.get("label"), "KPI")
        value = _text_or_default(card.get("value"), "")
        note = str(card.get("note") or "").strip()
        body.append(_trim_text(f"{label}: {value}" + (f" ({note})" if note else ""), 180))
    return body


def _chart_body(chart_plan: dict[str, Any], reporting: dict[str, Any]) -> list[str]:
    body = [
        f"Chart type: {_text_or_default(chart_plan.get('chart_type'), 'unknown')}",
        f"X axis: {_text_or_default(chart_plan.get('x_axis'), 'not provided')}",
        f"Y axis: {_text_or_default(chart_plan.get('y_axis'), 'not provided')}",
    ]
    reason = str(chart_plan.get("reason") or "").strip()
    if reason:
        body.append(_trim_text(reason, 200))
    interpretation = str(reporting.get("interpretation") or "").strip()
    if interpretation:
        body.append(_trim_text(interpretation, 220))
    return body[:MAX_BODY_ITEMS_PER_SLIDE]


def _chart_table_columns(chart_plan: dict[str, Any]) -> list[str]:
    columns = [chart_plan.get("x_axis"), chart_plan.get("y_axis")]
    return [str(column) for column in columns if column]


def _chart_table_rows(query: dict[str, Any], chart_plan: dict[str, Any]) -> list[list[str]]:
    columns = [str(column) for column in query.get("columns", []) or []]
    chart_columns = _chart_table_columns(chart_plan)
    if len(chart_columns) != 2 or not all(column in columns for column in chart_columns):
        return []
    indexes = [columns.index(column) for column in chart_columns]
    rows = []
    for row in list(query.get("rows", []) or [])[:MAX_TABLE_ROWS_PER_SLIDE]:
        rows.append([_stringify(_row_value(row, columns[index], index)) for index in indexes])
    return rows


def _table_content(query: dict[str, Any]) -> tuple[list[str], list[list[str]], list[str]]:
    columns = [str(column) for column in query.get("columns", []) or []]
    rows = list(query.get("rows", []) or [])
    warnings: list[str] = []
    if len(columns) > MAX_TABLE_COLUMNS_PER_SLIDE:
        warnings.append("Result table columns were truncated for Phase 1 slide readability.")
        columns = columns[:MAX_TABLE_COLUMNS_PER_SLIDE]
    table_rows = []
    for row in rows:
        table_rows.append([
            _stringify(_row_value(row, column, index))
            for index, column in enumerate(columns)
        ])
    if len(table_rows) > MAX_TABLE_ROWS_PER_SLIDE:
        warnings.append("Result table was split across multiple Agent 05 Table Evidence slides.")
    return columns, table_rows, warnings


def _caveats_body(reporting: dict[str, Any], source_tables: list[str]) -> list[str]:
    body = [str(caveat) for caveat in reporting.get("caveats", []) or [] if str(caveat).strip()]
    if source_tables:
        body.append(f"Source tables: {_source_text(source_tables)}")
    body.extend(str(note) for note in reporting.get("display_notes", []) or [] if str(note).strip())
    return [_trim_text(item, 220) for item in body[:MAX_BODY_ITEMS_PER_SLIDE]]


def _metadata_body(record: dict[str, Any]) -> list[str]:
    source_tables = _string_list(record.get("source_tables"))
    body = [
        f"Run ID: {_text_or_default(record.get('run_id'), 'not recorded')}",
        f"Execution success: {bool(record.get('execution_success'))}",
        f"SQL validation: {bool(record.get('validation_success') or record.get('sql_valid'))}",
        f"Rows returned: {int(record.get('row_count', 0) or 0)}",
        f"Source tables: {_source_text(source_tables)}",
        f"Generated at: {_text_or_default(record.get('generated_at'), 'not recorded')}",
    ]
    candidates = record.get("template_candidates")
    if isinstance(candidates, list) and candidates:
        ids = [
            str(candidate.get("template_id") or candidate.get("candidate_id") or candidate.get("id"))
            for candidate in candidates
            if isinstance(candidate, dict)
        ]
        if ids:
            body.append(f"Memory template IDs: {', '.join(ids)}")
    return body[:MAX_BODY_ITEMS_PER_SLIDE]


def _external_relationships(package: ZipFile) -> list[str]:
    relationships = []
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


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _deck_title(record: dict[str, Any]) -> str:
    question = str(record.get("user_question") or "").strip()
    if question:
        return _trim_text(question, 90)
    return "Wuerth Logistics Analysis"


def _filename_for(record: dict[str, Any]) -> str:
    run_id = str(record.get("run_id") or "analysis")
    safe_run_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id).strip("_") or "analysis"
    return f"wuerth_logistics_{safe_run_id}.pptx"


def _source_text(source_tables: list[str]) -> str:
    return ", ".join(source_tables) if source_tables else "not recorded"


def _text_or_default(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text if text else default


def _trim_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _row_value(row: Any, column: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(column)
    if isinstance(row, (list, tuple)) and index < len(row):
        return row[index]
    return None


def _effective_row_count(record: dict[str, Any], query: dict[str, Any], rows: list[Any]) -> int:
    for value in (record.get("row_count"), query.get("row_count")):
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return len(rows)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return _trim_text(str(value), 80)


def _chunks(values: list[list[str]], size: int) -> list[list[list[str]]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def _safe_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
