from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import os
import re
from typing import Any, Callable


TITLE_LIMIT = 52
TABLE_ROWS_PER_PAGE = 10
TABLE_COLUMN_LIMIT = 5
TABLE_PAGE_LIMIT = 3
TOP_N_CATEGORY_LIMIT = 8
TOP_N_LABEL_LIMIT = 32
EXECUTIVE_BULLET_LIMIT = 8
SUPPORTED_INPUT_CHART_TYPES = {"none", "bar", "line", "top_n_bar"}
DEFAULT_PRESENTATION_PLANNING_MODEL = "claude-sonnet-4-6"
DEFAULT_PRESENTATION_PLANNING_TIMEOUT_SECONDS = 30
DEFAULT_PRESENTATION_PLANNING_MAX_ROWS = 50
DEFAULT_PRESENTATION_PLANNING_MAX_TOKENS = 2048
PLANNER_PAYLOAD_MARKER = "PLANNER_PAYLOAD_JSON:\n"
PLANNER_REQUIRED_KEYS = {
    "title",
    "language",
    "executive_bullets",
    "charts",
    "table_pages",
    "caveats",
    "warnings",
    "audit",
}
PlannerInvocation = Callable[[str], Any]


@dataclass(frozen=True)
class PresentationPlanningConfig:
    mode: str = "deterministic"
    model: str = DEFAULT_PRESENTATION_PLANNING_MODEL
    timeout_seconds: int = DEFAULT_PRESENTATION_PLANNING_TIMEOUT_SECONDS
    max_rows: int = DEFAULT_PRESENTATION_PLANNING_MAX_ROWS
    max_tokens: int = DEFAULT_PRESENTATION_PLANNING_MAX_TOKENS

    @classmethod
    def from_env(cls) -> PresentationPlanningConfig:
        """Load non-secret planner toggles, defaulting to deterministic mode."""

        raw_mode = os.getenv("PRESENTATION_PLANNING_MODE", "deterministic").strip().lower()
        mode = raw_mode if raw_mode in {"deterministic", "llm"} else "deterministic"
        return cls(
            mode=mode,
            model=_env_text("PRESENTATION_PLANNING_MODEL", DEFAULT_PRESENTATION_PLANNING_MODEL),
            timeout_seconds=_env_int(
                "PRESENTATION_PLANNING_TIMEOUT_SECONDS",
                DEFAULT_PRESENTATION_PLANNING_TIMEOUT_SECONDS,
                minimum=1,
                maximum=300,
            ),
            max_rows=_env_int(
                "PRESENTATION_PLANNING_MAX_ROWS",
                DEFAULT_PRESENTATION_PLANNING_MAX_ROWS,
                minimum=1,
                maximum=200,
            ),
            max_tokens=_env_int(
                "PRESENTATION_PLANNING_MAX_TOKENS",
                DEFAULT_PRESENTATION_PLANNING_MAX_TOKENS,
                minimum=256,
                maximum=8192,
            ),
        )


@dataclass(frozen=True)
class TextSpan:
    text: str
    bold: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": str(self.text),
            "bold": bool(self.bold),
        }


@dataclass(frozen=True)
class ExecutiveBullet:
    spans: list[TextSpan] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "spans": [span.to_dict() for span in self.spans],
        }


@dataclass(frozen=True)
class EvidenceChartPlan:
    chart_type: str
    title: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    orientation: str = "vertical"
    fallback_reason: str = ""
    render_allowed: bool = True
    x_label: str = ""
    y_label: str = ""
    notes: list[str] = field(default_factory=list)
    category_column: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart_type": str(self.chart_type),
            "title": str(self.title),
            "rows": [_json_safe_dict(row) for row in self.rows],
            "orientation": str(self.orientation),
            "fallback_reason": str(self.fallback_reason),
            "render_allowed": bool(self.render_allowed),
            "x_label": str(self.x_label),
            "y_label": str(self.y_label),
            "notes": [str(note) for note in self.notes],
            "category_column": str(self.category_column),
        }


@dataclass(frozen=True)
class EvidenceTablePage:
    page_number: int
    columns: list[str]
    rows: list[dict[str, Any]]
    row_range_label: str
    notes: list[str] = field(default_factory=list)
    hidden_columns: list[str] = field(default_factory=list)
    start_row: int = 1
    end_row: int = 0
    total_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": int(self.page_number),
            "columns": [str(column) for column in self.columns],
            "rows": [_json_safe_dict(row) for row in self.rows],
            "row_range_label": str(self.row_range_label),
            "notes": [str(note) for note in self.notes],
            "hidden_columns": [str(column) for column in self.hidden_columns],
            "start_row": int(self.start_row),
            "end_row": int(self.end_row),
            "total_rows": int(self.total_rows),
        }


@dataclass(frozen=True)
class PlanningAudit:
    planning_mode: str
    selected_chart_types: list[str] = field(default_factory=list)
    row_truncated: bool = False
    column_truncated: bool = False
    fallback_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "planning_mode": str(self.planning_mode),
            "selected_chart_types": [str(chart_type) for chart_type in self.selected_chart_types],
            "row_truncated": bool(self.row_truncated),
            "column_truncated": bool(self.column_truncated),
            "fallback_reasons": [str(reason) for reason in self.fallback_reasons],
            "warnings": [str(warning) for warning in self.warnings],
        }


@dataclass(frozen=True)
class PresentationPlan:
    title: str
    language: str = "de"
    executive_bullets: list[ExecutiveBullet] = field(default_factory=list)
    charts: list[EvidenceChartPlan] = field(default_factory=list)
    table_pages: list[EvidenceTablePage] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    audit: PlanningAudit = field(default_factory=lambda: PlanningAudit(planning_mode="deterministic"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": str(self.title),
            "language": str(self.language),
            "executive_bullets": [bullet.to_dict() for bullet in self.executive_bullets],
            "charts": [chart.to_dict() for chart in self.charts],
            "table_pages": [page.to_dict() for page in self.table_pages],
            "caveats": [str(caveat) for caveat in self.caveats],
            "warnings": [str(warning) for warning in self.warnings],
            "audit": self.audit.to_dict(),
        }


def build_presentation_plan(
    *,
    record: dict[str, Any],
    config: PresentationPlanningConfig | None = None,
    planner_invocation: PlannerInvocation | None = None,
) -> PresentationPlan:
    """Build a presentation plan with optional validated JSON planning.

    Deterministic planning is the default. The optional JSON planner is only
    invoked when `config.mode == "llm"` and a caller injects an invocation
    function. Every planner failure returns the deterministic plan with fallback
    audit metadata.
    """

    safe_record = record if isinstance(record, dict) else {}
    deterministic_plan = _build_deterministic_presentation_plan(record=safe_record)
    planning_config = config or PresentationPlanningConfig.from_env()

    if planning_config.mode != "llm":
        return deterministic_plan

    if planner_invocation is None:
        return _fallback_plan(deterministic_plan, "planner_invocation_missing")

    try:
        payload = _build_planner_payload(
            record=safe_record,
            deterministic_plan=deterministic_plan,
            config=planning_config,
        )
        prompt = _build_planner_prompt(payload=payload, config=planning_config)
        response = planner_invocation(prompt)
        return _parse_planner_response(
            response,
            deterministic_plan=deterministic_plan,
        )
    except Exception as error:
        return _fallback_plan(deterministic_plan, f"{type(error).__name__}: {error}")


def _build_deterministic_presentation_plan(*, record: dict[str, Any]) -> PresentationPlan:
    """Build a deterministic German presentation plan from a validated result record.

    The planner only inspects data already present in the record. It does not
    execute SQL, call a database, render PowerPoint, import Streamlit, or call
    model clients.
    """

    safe_record = record if isinstance(record, dict) else {}
    query = safe_record.get("query_result") if isinstance(safe_record.get("query_result"), dict) else {}
    reporting = safe_record.get("reporting_result") if isinstance(safe_record.get("reporting_result"), dict) else {}
    columns = [str(column) for column in query.get("columns", []) or []]
    raw_rows = list(query.get("rows", []) or [])
    total_rows = _effective_row_count(safe_record, query, raw_rows)
    rows = _normalized_rows(columns, raw_rows)

    table_pages, table_row_truncated, table_column_truncated = _build_table_pages(
        columns=columns,
        rows=rows,
        total_rows=total_rows,
    )
    charts, chart_fallbacks = _build_chart_plans(
        columns=columns,
        rows=rows,
        reporting=reporting,
    )
    executive_bullets = _build_executive_bullets(
        title=derive_presentation_title(safe_record),
        columns=columns,
        rows=rows,
        total_rows=total_rows,
    )
    warnings = _unique([
        *(["table_rows_truncated"] if table_row_truncated else []),
        *(["table_columns_truncated"] if table_column_truncated else []),
        *(["chart_fallback"] if chart_fallbacks else []),
    ])

    return PresentationPlan(
        title=derive_presentation_title(safe_record),
        language="de",
        executive_bullets=executive_bullets,
        charts=charts,
        table_pages=table_pages,
        caveats=_string_list(reporting.get("caveats")),
        warnings=warnings,
        audit=PlanningAudit(
            planning_mode="deterministic",
            selected_chart_types=[chart.chart_type for chart in charts],
            row_truncated=table_row_truncated,
            column_truncated=table_column_truncated,
            fallback_reasons=chart_fallbacks,
            warnings=warnings,
        ),
    )


def derive_presentation_title(record: dict[str, Any]) -> str:
    """Return a short German title derived from a successful result record."""

    if not isinstance(record, dict):
        return "Logistik-Auswertung"

    question = str(record.get("user_question") or "").strip()
    query = record.get("query_result") if isinstance(record.get("query_result"), dict) else {}
    columns = [str(column) for column in query.get("columns", []) or []]
    normalized_context = _normalize_text(" ".join([question, *columns]))

    if (
        {"order_number", "shiptoparty", "customer_material"}.issubset(set(columns))
        or ("shipment" in normalized_context and "invoice" in normalized_context)
        or ("sendung" in normalized_context and "rechnung" in normalized_context)
    ):
        return "Sendungen ohne passende Rechnung"
    if "region" in normalized_context:
        return "Lieferungen nach Region"
    if "customer" in normalized_context or "kunde" in normalized_context:
        return "Kundenanalyse Logistik"
    if "shipment" in normalized_context or "sendung" in normalized_context:
        return "Sendungsanalyse"
    return _trim_text("Logistik-Auswertung", TITLE_LIMIT)


def format_management_number(value: Any, *, percentage: bool = False) -> str:
    """Format counts, large numbers, and percentages for German management slides."""

    number = _decimal_or_none(value)
    if number is None:
        return str(value)

    if percentage:
        percent = number * Decimal("100") if abs(number) <= Decimal("1") else number
        return f"{_format_decimal(percent, places=1)}%"

    absolute = abs(number)
    if absolute >= Decimal("1000000000"):
        return f"{_format_decimal(number / Decimal('1000000000'), places=1)} Mrd."
    if absolute >= Decimal("1000000"):
        return f"{_format_decimal(number / Decimal('1000000'), places=1)} Mio."
    if number == number.to_integral_value():
        return f"{int(number):,}".replace(",", ".")
    return _format_decimal(number, places=2, grouping=True)


def _build_planner_payload(
    *,
    record: dict[str, Any],
    deterministic_plan: PresentationPlan,
    config: PresentationPlanningConfig,
) -> dict[str, Any]:
    query = record.get("query_result") if isinstance(record.get("query_result"), dict) else {}
    reporting = record.get("reporting_result") if isinstance(record.get("reporting_result"), dict) else {}
    columns = [str(column) for column in query.get("columns", []) or []]
    raw_rows = list(query.get("rows", []) or [])
    total_rows = _effective_row_count(record, query, raw_rows)
    rows = _normalized_rows(columns, raw_rows)
    capped_rows = rows[:config.max_rows]

    return {
        "question": _sanitize_text(record.get("user_question"), limit=500),
        "sql": _sanitize_text(record.get("final_sql"), limit=2000),
        "reporting_metadata": _sanitize_json(
            {
                "summary": reporting.get("summary"),
                "interpretation": reporting.get("interpretation"),
                "caveats": reporting.get("caveats"),
                "chart_plan": reporting.get("chart_plan"),
                "table_plan": reporting.get("table_plan"),
                "kpi_cards": reporting.get("kpi_cards"),
                "display_notes": reporting.get("display_notes"),
                "audit": reporting.get("audit"),
            },
            text_limit=500,
        ),
        "result_sample": {
            "columns": [_sanitize_text(column, limit=80) for column in columns],
            "rows": [_sanitize_json(row, text_limit=120) for row in capped_rows],
            "row_count": total_rows,
            "rows_in_payload": len(capped_rows),
        },
        "column_profiles": _build_column_profiles(columns=columns, rows=rows),
        "aggregates": _build_aggregates(columns=columns, rows=rows, total_rows=total_rows),
        "deterministic_defaults": _sanitize_json(deterministic_plan.to_dict(), text_limit=500),
        "planner_limits": {
            "max_rows": int(config.max_rows),
            "max_tokens": int(config.max_tokens),
            "timeout_seconds": int(config.timeout_seconds),
            "title_limit": TITLE_LIMIT,
            "table_rows_per_page": TABLE_ROWS_PER_PAGE,
            "table_column_limit": TABLE_COLUMN_LIMIT,
            "supported_chart_types": sorted(SUPPORTED_INPUT_CHART_TYPES),
        },
    }


def _build_planner_prompt(*, payload: dict[str, Any], config: PresentationPlanningConfig) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return (
        "Return one strict JSON object for a German PowerPoint presentation plan. "
        "Use only the provided schema fields. Do not include prose outside JSON. "
        "Allowed chart_type values are none, bar, line, and top_n_bar. "
        f"Model hint: {config.model}. Token budget: {config.max_tokens}.\n"
        f"{PLANNER_PAYLOAD_MARKER}{payload_json}"
    )


def _parse_planner_response(
    response: Any,
    *,
    deterministic_plan: PresentationPlan,
) -> PresentationPlan:
    response_text = _response_text(response)
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid_json: {error.msg}") from error

    if not isinstance(parsed, dict):
        raise ValueError("planner response must be a JSON object")
    if "refusal" in parsed:
        raise ValueError("planner_refusal")

    missing_keys = sorted(PLANNER_REQUIRED_KEYS - set(parsed))
    if missing_keys:
        raise ValueError(f"planner response missing keys: {', '.join(missing_keys)}")
    unexpected_keys = sorted(set(parsed) - PLANNER_REQUIRED_KEYS)
    if unexpected_keys:
        raise ValueError(f"planner response has unsupported keys: {', '.join(unexpected_keys)}")

    title = _required_text(parsed["title"], field_name="title", limit=TITLE_LIMIT)
    language = _required_text(parsed["language"], field_name="language", limit=8)
    if language != "de":
        raise ValueError("planner language must be de")

    executive_bullets = _validated_executive_bullets(parsed["executive_bullets"])
    charts = _validated_charts(parsed["charts"])
    table_pages = _validated_table_pages(parsed["table_pages"])
    caveats = _validated_string_list(parsed["caveats"], field_name="caveats", limit=220, max_items=8)
    warnings = _validated_string_list(parsed["warnings"], field_name="warnings", limit=160, max_items=8)
    audit_payload = parsed["audit"]
    if not isinstance(audit_payload, dict):
        raise ValueError("audit must be an object")
    audit_fallbacks = _validated_string_list(
        audit_payload.get("fallback_reasons", []),
        field_name="audit.fallback_reasons",
        limit=220,
        max_items=8,
    )
    audit_warnings = _validated_string_list(
        audit_payload.get("warnings", []),
        field_name="audit.warnings",
        limit=160,
        max_items=8,
    )

    audit = PlanningAudit(
        planning_mode="llm",
        selected_chart_types=[chart.chart_type for chart in charts],
        row_truncated=any(page.total_rows > page.end_row for page in table_pages),
        column_truncated=any(page.hidden_columns for page in table_pages),
        fallback_reasons=_unique([*audit_fallbacks, *[chart.fallback_reason for chart in charts if chart.fallback_reason]]),
        warnings=_unique([*warnings, *audit_warnings]),
    )
    return PresentationPlan(
        title=title,
        language=language,
        executive_bullets=executive_bullets,
        charts=charts,
        table_pages=table_pages,
        caveats=caveats,
        warnings=_unique(warnings),
        audit=audit,
    )


def _fallback_plan(plan: PresentationPlan, reason: str) -> PresentationPlan:
    reason_text = _sanitize_text(reason, limit=180) or "planner_failed"
    warning = f"planner_fallback:{reason_text}"
    warnings = _unique([*plan.warnings, warning])
    audit = PlanningAudit(
        planning_mode="fallback",
        selected_chart_types=[chart.chart_type for chart in plan.charts],
        row_truncated=plan.audit.row_truncated,
        column_truncated=plan.audit.column_truncated,
        fallback_reasons=_unique([reason_text, *plan.audit.fallback_reasons]),
        warnings=_unique([*warnings, *plan.audit.warnings]),
    )
    return replace(plan, warnings=warnings, audit=audit)


def _validated_executive_bullets(value: Any) -> list[ExecutiveBullet]:
    if not isinstance(value, list) or not value:
        raise ValueError("executive_bullets must be a non-empty list")
    if len(value) > EXECUTIVE_BULLET_LIMIT:
        raise ValueError("executive_bullets exceeds item budget")

    bullets: list[ExecutiveBullet] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"executive_bullets[{index}] must be an object")
        spans_value = item.get("spans")
        if not isinstance(spans_value, list) or not spans_value:
            raise ValueError(f"executive_bullets[{index}].spans must be a non-empty list")
        spans: list[TextSpan] = []
        for span_index, span in enumerate(spans_value, start=1):
            if not isinstance(span, dict):
                raise ValueError(f"executive_bullets[{index}].spans[{span_index}] must be an object")
            text = _required_text(
                span.get("text"),
                field_name=f"executive_bullets[{index}].spans[{span_index}].text",
                limit=220,
            )
            spans.append(TextSpan(text=text, bold=bool(span.get("bold"))))
        bullet = ExecutiveBullet(spans=spans)
        if len(bullet.text) > 260:
            raise ValueError(f"executive_bullets[{index}] exceeds text budget")
        bullets.append(bullet)
    return bullets


def _validated_charts(value: Any) -> list[EvidenceChartPlan]:
    if not isinstance(value, list):
        raise ValueError("charts must be a list")
    if len(value) > 4:
        raise ValueError("charts exceeds item budget")

    charts: list[EvidenceChartPlan] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"charts[{index}] must be an object")
        chart_type = _required_text(item.get("chart_type"), field_name=f"charts[{index}].chart_type", limit=24).lower()
        if chart_type not in SUPPORTED_INPUT_CHART_TYPES:
            raise ValueError(f"charts[{index}] uses unsupported chart type: {chart_type}")
        title = _required_text(item.get("title"), field_name=f"charts[{index}].title", limit=90)
        render_allowed = bool(item.get("render_allowed"))
        rows = _validated_chart_rows(item.get("rows", []), field_name=f"charts[{index}].rows")
        if chart_type != "none" and render_allowed and not rows:
            raise ValueError(f"charts[{index}] requires rows when render_allowed is true")
        orientation = _optional_text(item.get("orientation", "vertical"), limit=24) or "vertical"
        if orientation not in {"vertical", "horizontal"}:
            raise ValueError(f"charts[{index}] has unsupported orientation")
        charts.append(
            EvidenceChartPlan(
                chart_type=chart_type,
                title=title,
                rows=rows,
                orientation=orientation,
                fallback_reason=_optional_text(item.get("fallback_reason", ""), limit=220),
                render_allowed=render_allowed,
                x_label=_optional_text(item.get("x_label", ""), limit=60),
                y_label=_optional_text(item.get("y_label", ""), limit=60),
                notes=_validated_string_list(item.get("notes", []), field_name=f"charts[{index}].notes", limit=160, max_items=4),
                category_column=_optional_text(item.get("category_column", ""), limit=80),
            )
        )
    return charts


def _validated_chart_rows(value: Any, *, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    if len(value) > TOP_N_CATEGORY_LIMIT + 1:
        raise ValueError(f"{field_name} exceeds row budget")

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{field_name}[{index}] must be an object")
        label = _required_text(item.get("label"), field_name=f"{field_name}[{index}].label", limit=TOP_N_LABEL_LIMIT)
        value_number = _decimal_or_none(item.get("value"))
        if value_number is None:
            raise ValueError(f"{field_name}[{index}].value must be numeric")
        rows.append({
            "label": label,
            "source_label": _optional_text(item.get("source_label", label), limit=120),
            "value": _json_safe_value(value_number),
        })
    return rows


def _validated_table_pages(value: Any) -> list[EvidenceTablePage]:
    if not isinstance(value, list):
        raise ValueError("table_pages must be a list")
    if len(value) > TABLE_PAGE_LIMIT:
        raise ValueError("table_pages exceeds page budget")

    pages: list[EvidenceTablePage] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"table_pages[{index}] must be an object")
        columns = _validated_string_list(
            item.get("columns"),
            field_name=f"table_pages[{index}].columns",
            limit=80,
            max_items=TABLE_COLUMN_LIMIT,
        )
        rows_value = item.get("rows")
        if not isinstance(rows_value, list):
            raise ValueError(f"table_pages[{index}].rows must be a list")
        if len(rows_value) > TABLE_ROWS_PER_PAGE:
            raise ValueError(f"table_pages[{index}].rows exceeds row budget")
        rows: list[dict[str, Any]] = []
        for row_number, row in enumerate(rows_value, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"table_pages[{index}].rows[{row_number}] must be an object")
            rows.append({
                column: _sanitize_text(row.get(column, ""), limit=80)
                for column in columns
            })
        pages.append(
            EvidenceTablePage(
                page_number=_validated_int(item.get("page_number", index), field_name=f"table_pages[{index}].page_number"),
                columns=columns,
                rows=rows,
                row_range_label=_required_text(
                    item.get("row_range_label"),
                    field_name=f"table_pages[{index}].row_range_label",
                    limit=80,
                ),
                notes=_validated_string_list(item.get("notes", []), field_name=f"table_pages[{index}].notes", limit=160, max_items=4),
                hidden_columns=_validated_string_list(
                    item.get("hidden_columns", []),
                    field_name=f"table_pages[{index}].hidden_columns",
                    limit=80,
                    max_items=20,
                ),
                start_row=_validated_int(item.get("start_row", 1), field_name=f"table_pages[{index}].start_row"),
                end_row=_validated_int(item.get("end_row", len(rows)), field_name=f"table_pages[{index}].end_row"),
                total_rows=_validated_int(item.get("total_rows", len(rows)), field_name=f"table_pages[{index}].total_rows"),
            )
        )
    return pages


def _validated_string_list(value: Any, *, field_name: str, limit: int, max_items: int) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    if len(value) > max_items:
        raise ValueError(f"{field_name} exceeds item budget")
    return [
        _required_text(item, field_name=f"{field_name}[{index}]", limit=limit)
        for index, item in enumerate(value, start=1)
        if _sanitize_text(item, limit=limit)
    ]


def _validated_int(value: Any, *, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an integer") from error
    if parsed < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return parsed


def _required_text(value: Any, *, field_name: str, limit: int) -> str:
    text = _clean_text(value)
    if not text:
        raise ValueError(f"{field_name} is required")
    if len(text) > limit:
        raise ValueError(f"{field_name} exceeds text budget")
    return text


def _optional_text(value: Any, *, limit: int) -> str:
    return _sanitize_text(value, limit=limit)


def _response_text(response: Any) -> str:
    if isinstance(response, str):
        return response.strip()
    response_text = getattr(response, "response_text", None)
    if isinstance(response_text, str):
        return response_text.strip()
    return str(response).strip()


def _build_column_profiles(*, columns: list[str], rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for column in columns:
        values = [row.get(column, "") for row in rows]
        non_empty = [value for value in values if value != ""]
        numeric_values = [_decimal_or_none(value) for value in non_empty]
        numeric_values = [value for value in numeric_values if value is not None]
        top_values = _top_counts(non_empty)[:5]
        profile: dict[str, Any] = {
            "name": _sanitize_text(column, limit=80),
            "kind": "numeric_measure" if non_empty and len(numeric_values) == len(non_empty) else "categorical_dimension",
            "non_null_count": len(non_empty),
            "distinct_count": len(set(non_empty)),
            "sample_values": [_sanitize_text(value, limit=80) for value in non_empty[:5]],
            "top_values": [
                {"value": _sanitize_text(value, limit=80), "count": count}
                for value, count in top_values
            ],
        }
        if numeric_values:
            profile["numeric_min"] = _json_safe_value(min(numeric_values))
            profile["numeric_max"] = _json_safe_value(max(numeric_values))
            profile["numeric_sum"] = _json_safe_value(sum(numeric_values, Decimal("0")))
        profiles.append(profile)
    return profiles


def _build_aggregates(*, columns: list[str], rows: list[dict[str, str]], total_rows: int) -> dict[str, Any]:
    numeric_sums: dict[str, Any] = {}
    for column in columns:
        values = [_decimal_or_none(row.get(column)) for row in rows]
        numeric_values = [value for value in values if value is not None]
        if numeric_values:
            numeric_sums[column] = _json_safe_value(sum(numeric_values, Decimal("0")))
    return {
        "row_count": int(total_rows),
        "returned_rows": len(rows),
        "column_count": len(columns),
        "numeric_sums": numeric_sums,
    }


def _sanitize_json(value: Any, *, text_limit: int) -> Any:
    if isinstance(value, dict):
        return {
            _sanitize_text(key, limit=80): _sanitize_json(item, text_limit=text_limit)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json(item, text_limit=text_limit) for item in value[:100]]
    if isinstance(value, tuple):
        return [_sanitize_json(item, text_limit=text_limit) for item in value[:100]]
    if isinstance(value, Decimal):
        return _json_safe_value(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _sanitize_text(value, limit=text_limit)


def _sanitize_text(value: Any, *, limit: int) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = "".join(character for character in text if character >= " " or character in "\n\t")
    return re.sub(r"\s+", " ", text).strip()


def _env_text(name: str, default: str) -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _json_safe_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _json_safe_value(value) for key, value in row.items()}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalized_rows(columns: list[str], rows: list[Any]) -> list[dict[str, str]]:
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        normalized_row: dict[str, str] = {}
        for index, column in enumerate(columns):
            normalized_row[column] = _stringify(_row_value(row, column, index), limit=80)
        normalized_rows.append(normalized_row)
    return normalized_rows


def _build_table_pages(
    *,
    columns: list[str],
    rows: list[dict[str, str]],
    total_rows: int,
) -> tuple[list[EvidenceTablePage], bool, bool]:
    if not columns or not rows:
        return [], bool(total_rows), False

    visible_columns = columns[:TABLE_COLUMN_LIMIT]
    hidden_columns = columns[TABLE_COLUMN_LIMIT:]
    row_budget = TABLE_ROWS_PER_PAGE * TABLE_PAGE_LIMIT
    visible_rows = rows[:row_budget]
    row_truncated = total_rows > len(visible_rows) or len(rows) > len(visible_rows)
    column_truncated = bool(hidden_columns)
    pages: list[EvidenceTablePage] = []

    for chunk_start in range(0, len(visible_rows), TABLE_ROWS_PER_PAGE):
        chunk = visible_rows[chunk_start:chunk_start + TABLE_ROWS_PER_PAGE]
        start_row = chunk_start + 1
        end_row = chunk_start + len(chunk)
        row_range_label = f"Zeilen {start_row}-{end_row} von {total_rows}"
        notes = [row_range_label]
        if row_truncated and end_row < total_rows:
            notes.append("Weitere Zeilen im Ergebnis ausgeblendet")
        if column_truncated:
            notes.append("Weitere Spalten ausgeblendet")
        page_rows = [
            {column: row.get(column, "") for column in visible_columns}
            for row in chunk
        ]
        pages.append(
            EvidenceTablePage(
                page_number=len(pages) + 1,
                columns=visible_columns,
                rows=page_rows,
                row_range_label=row_range_label,
                notes=notes,
                hidden_columns=hidden_columns,
                start_row=start_row,
                end_row=end_row,
                total_rows=total_rows,
            )
        )

    return pages, row_truncated, column_truncated


def _build_chart_plans(
    *,
    columns: list[str],
    rows: list[dict[str, str]],
    reporting: dict[str, Any],
) -> tuple[list[EvidenceChartPlan], list[str]]:
    fallback_reasons: list[str] = []
    charts: list[EvidenceChartPlan] = []
    chart_plan = reporting.get("chart_plan") if isinstance(reporting.get("chart_plan"), dict) else {}
    chart_type = str(chart_plan.get("chart_type") or "none").strip().lower()
    render_requested = bool(chart_plan.get("render_allowed"))

    if render_requested and chart_type not in SUPPORTED_INPUT_CHART_TYPES:
        reason = (
            f"Diagrammtyp {chart_type} wird fuer PowerPoint noch nicht unterstuetzt. "
            "Die Evidenz wird als Tabelle geplant."
        )
        fallback_reasons.append(reason)
        charts.append(
            EvidenceChartPlan(
                chart_type="none",
                title="Darstellungshinweis",
                rows=[],
                orientation="horizontal",
                fallback_reason=reason,
                render_allowed=False,
                notes=[reason],
            )
        )

    if not rows:
        reason = "Keine Ergebniszeilen fuer eine Visualisierung vorhanden."
        fallback_reasons.append(reason)
        charts.append(
            EvidenceChartPlan(
                chart_type="none",
                title="Darstellungshinweis",
                rows=[],
                orientation="horizontal",
                fallback_reason=reason,
                render_allowed=False,
                notes=[reason],
            )
        )
        return charts, _unique(fallback_reasons)

    for column in _preferred_category_columns(columns):
        chart = _top_n_chart(column=column, rows=rows)
        if chart is not None:
            charts.append(chart)

    if not charts:
        reason = "Keine robuste kategoriale Struktur fuer ein Diagramm erkannt. Die Evidenz wird als Tabelle geplant."
        fallback_reasons.append(reason)
        charts.append(
            EvidenceChartPlan(
                chart_type="none",
                title="Darstellungshinweis",
                rows=[],
                orientation="horizontal",
                fallback_reason=reason,
                render_allowed=False,
                notes=[reason],
            )
        )

    return charts, _unique(fallback_reasons)


def _top_n_chart(*, column: str, rows: list[dict[str, str]]) -> EvidenceChartPlan | None:
    values = [row.get(column, "") for row in rows if row.get(column, "")]
    if not values:
        return None

    counts = Counter(values)
    sorted_items = sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    if len(sorted_items) > TOP_N_CATEGORY_LIMIT:
        kept = sorted_items[:TOP_N_CATEGORY_LIMIT]
        other_count = sum(count for _, count in sorted_items[TOP_N_CATEGORY_LIMIT:])
        sorted_items = [*kept, ("Sonstige", other_count)]
        sorted_items = sorted(sorted_items, key=lambda item: (-item[1], item[0].casefold()))

    chart_rows = [
        {
            "label": _trim_label(label),
            "source_label": label,
            "value": int(count),
        }
        for label, count in sorted_items
    ]
    return EvidenceChartPlan(
        chart_type="top_n_bar",
        title=f"Top {_display_column_name(column)}",
        rows=chart_rows,
        orientation="horizontal",
        render_allowed=True,
        x_label=_display_column_name(column),
        y_label="Evidenzzeilen",
        category_column=column,
    )


def _preferred_category_columns(columns: list[str]) -> list[str]:
    preferred = ["customer_material", "shiptoparty", "order_number"]
    selected = [column for column in preferred if column in columns]
    if selected:
        return selected
    for column in columns:
        normalized = _normalize_text(column)
        if any(token in normalized for token in ("region", "customer", "material", "ship", "party", "status")):
            selected.append(column)
    return selected[:2]


def _build_executive_bullets(
    *,
    title: str,
    columns: list[str],
    rows: list[dict[str, str]],
    total_rows: int,
) -> list[ExecutiveBullet]:
    if {"order_number", "shiptoparty", "customer_material"}.issubset(set(columns)):
        return _build_w05_bullets(rows)
    return [
        _bullet(
            (format_management_number(total_rows), True),
            (f" Ergebniszeilen in der Auswertung {title}.", False),
        )
    ]


def _build_w05_bullets(rows: list[dict[str, str]]) -> list[ExecutiveBullet]:
    order_values = [row.get("order_number", "") for row in rows if row.get("order_number", "")]
    distinct_orders = len(set(order_values))
    returned_rows = len(rows)
    shipment_total = sum((_decimal_or_none(row.get("shipment_rows")) or Decimal("0")) for row in rows)
    order_counts = _top_counts(order_values)
    material_counts = _top_counts(row.get("customer_material", "") for row in rows if row.get("customer_material", ""))
    shipto_counts = _top_counts(row.get("shiptoparty", "") for row in rows if row.get("shiptoparty", ""))
    bullets = [
        _bullet((format_management_number(distinct_orders), True), (" Auftraege ohne passende Rechnung im sichtbaren Ergebnis.", False)),
        _bullet((format_management_number(returned_rows), True), (" Evidenzzeilen wurden fuer die Pruefung geplant.", False)),
        _bullet((format_management_number(shipment_total), True), (" Sendungszeilen sind in den Trefferzeilen betroffen.", False)),
    ]

    duplicate_orders = [(value, count) for value, count in order_counts if count > 1]
    if duplicate_orders:
        value, count = duplicate_orders[0]
        bullets.append(
            _bullet(
                ("Auftrag ", False),
                (value, True),
                (f" erscheint mehrfach ({format_management_number(count)} Evidenzzeilen).", False),
            )
        )
    if material_counts:
        value, count = material_counts[0]
        bullets.append(
            _bullet(
                (value, True),
                (f" ist die staerkste Materialgruppe ({format_management_number(count)} Evidenzzeilen).", False),
            )
        )
    if shipto_counts:
        value, count = shipto_counts[0]
        bullets.append(
            _bullet(
                (value, True),
                (f" ist die staerkste Ship-to-Party-Gruppe ({format_management_number(count)} Evidenzzeilen).", False),
            )
        )
    return bullets


def _top_counts(values: Any) -> list[tuple[str, int]]:
    counts = Counter(str(value) for value in values if str(value).strip())
    return sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))


def _bullet(*parts: tuple[str, bool]) -> ExecutiveBullet:
    return ExecutiveBullet(spans=[TextSpan(text, bold=bold) for text, bold in parts if text])


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _effective_row_count(record: dict[str, Any], query: dict[str, Any], rows: list[Any]) -> int:
    for value in (record.get("row_count"), query.get("row_count")):
        if value is None:
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)
    return len(rows)


def _row_value(row: Any, column: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(column)
    if isinstance(row, (list, tuple)) and index < len(row):
        return row[index]
    return None


def _stringify(value: Any, *, limit: int) -> str:
    if value is None:
        return ""
    return _trim_text(str(value), limit)


def _decimal_or_none(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
    return None


def _format_decimal(number: Decimal, *, places: int, grouping: bool = False) -> str:
    quantizer = Decimal("1") if places <= 0 else Decimal("1").scaleb(-places)
    rounded = number.quantize(quantizer, rounding=ROUND_HALF_UP)
    text = f"{rounded:,.{places}f}" if grouping else f"{rounded:.{places}f}"
    text = text.rstrip("0").rstrip(".")
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _normalize_text(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value).lower())).strip("_")


def _display_column_name(column: str) -> str:
    return _normalize_text(column).replace("_", " ").title()


def _trim_label(value: str) -> str:
    return _trim_text(value, TOP_N_LABEL_LIMIT)


def _trim_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


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
