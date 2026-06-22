from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any


TITLE_LIMIT = 52


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


def _trim_text(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."
