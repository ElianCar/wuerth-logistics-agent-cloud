from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any


TITLE_LIMIT = 52
TABLE_ROWS_PER_PAGE = 10
TABLE_COLUMN_LIMIT = 5
TABLE_PAGE_LIMIT = 3
TOP_N_CATEGORY_LIMIT = 8
TOP_N_LABEL_LIMIT = 32
SUPPORTED_INPUT_CHART_TYPES = {"none", "bar", "line", "top_n_bar"}


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


def build_presentation_plan(*, record: dict[str, Any]) -> PresentationPlan:
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
