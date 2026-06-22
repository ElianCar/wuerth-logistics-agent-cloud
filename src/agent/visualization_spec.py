from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any


SUPPORTED_CHART_TYPES = {"none", "bar", "line"}
CHART_DISPLAY_ROW_LIMIT = 50
MAX_CATEGORICAL_VALUES = CHART_DISPLAY_ROW_LIMIT

_DATE_NAME_PATTERN = re.compile(
    r"(^|_)(date|datum|day|tag|week|woche|month|monat|quarter|quartal|year|jahr|time|zeit|period|periode|created_at|updated_at)($|_)",
    re.IGNORECASE,
)
_AGGREGATE_NAME_PATTERN = re.compile(
    r"(^|_)(count|cnt|sum|total|avg|average|min|max|revenue|sales|amount|cost|costs|quantity|qty|value|price|measure)($|_)",
    re.IGNORECASE,
)
_ID_NAME_PATTERN = re.compile(
    r"(^|_)(id|key)$|"
    r"(^|_)(order|customer|shipment|article|invoice|supplier|product|line_item|delivery|material)_(id|key|number)$|"
    r"(^|_)(o_orderkey|c_custkey|s_suppkey|p_partkey|l_orderkey|l_partkey|l_suppkey)$",
    re.IGNORECASE,
)
_CODE_NAME_PATTERN = re.compile(r"(^|_)(code|status|type|segment|mode|priority|region|nation|country)($|_)", re.IGNORECASE)


def build_visualization_spec(
    *,
    user_question: str,
    router_context: dict[str, Any] | None = None,
    output_mode: str = "",
    query_result: dict[str, Any] | None = None,
    execution_success: bool = False,
    validation_success: bool = False,
    row_count: int | None = None,
    final_sql: str = "",
    source_tables: list[str] | None = None,
    semantic_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic post-SQL chart specification.

    This function does not call an LLM, access a database, generate SQL, execute
    SQL, or import Streamlit. It only inspects already available result data and
    metadata and returns a JSON-serializable chart spec.
    """

    router_context = router_context or {}
    query_result = query_result or {}
    source_tables = source_tables or []
    semantic_metadata = semantic_metadata or {}

    if not _chart_requested(router_context, output_mode):
        return _no_chart("No explicit chart request was made.")

    if not execution_success:
        return _no_chart("SQL execution did not succeed.")
    if not validation_success:
        return _no_chart("SQL validation did not succeed.")

    columns = [str(column) for column in query_result.get("columns", [])]
    rows = list(query_result.get("rows", []) or [])
    effective_row_count = int(row_count if row_count is not None else query_result.get("row_count", len(rows)) or 0)

    if not columns:
        return _no_chart("The SQL result has no columns.")
    if not rows or effective_row_count == 0:
        return _no_chart("The SQL result is empty.")
    if len(columns) == 1 and len(rows) == 1:
        return _no_chart("Single scalar results are table-only in visualization v1.")
    chart_rows = rows[:CHART_DISPLAY_ROW_LIMIT]
    chart_truncated = effective_row_count > CHART_DISPLAY_ROW_LIMIT or len(rows) > CHART_DISPLAY_ROW_LIMIT
    chart_note = (
        "Die Visualisierung zeigt die ersten 50 Zeilen in der Reihenfolge des SQL Ergebnisses."
        if chart_truncated
        else ""
    )
    sort_strategy = _resolve_sort_strategy(user_question, router_context)

    profiles = [_profile_column(column, chart_rows, index) for index, column in enumerate(columns)]
    numeric_measures = [profile for profile in profiles if profile["kind"] == "numeric_measure"]
    time_dimensions = [profile for profile in profiles if profile["kind"] == "date_or_time_dimension"]
    categorical_dimensions = [
        profile
        for profile in profiles
        if profile["kind"] == "categorical_dimension" and int(profile["distinct_count"]) <= MAX_CATEGORICAL_VALUES
    ]
    unsupported_dimensions = [
        profile
        for profile in profiles
        if profile["kind"] == "categorical_dimension" and int(profile["distinct_count"]) > MAX_CATEGORICAL_VALUES
    ]

    if unsupported_dimensions and not time_dimensions:
        names = ", ".join(profile["name"] for profile in unsupported_dimensions)
        return _no_chart(f"Categorical dimension cardinality is too high for v1: {names}.")

    measure_selection = _select_numeric_measure(
        numeric_measures,
        user_question=user_question,
        final_sql=final_sql,
    )
    if not measure_selection["measure"]:
        return _no_chart(str(measure_selection["reason"]))

    measure = measure_selection["measure"]
    warnings = list(measure_selection["warnings"])

    non_measure_profiles = [profile for profile in profiles if profile["name"] != measure["name"]]
    non_measure_dimensions = [
        profile
        for profile in non_measure_profiles
        if profile["kind"] in {"categorical_dimension", "date_or_time_dimension", "identifier", "unknown"}
    ]

    if time_dimensions:
        if len(time_dimensions) != 1:
            return _no_chart("Multiple time dimensions are ambiguous for visualization v1.")
        time_dimension = time_dimensions[0]
        extra_dimensions = [
            profile
            for profile in non_measure_dimensions
            if profile["name"] != time_dimension["name"] and profile["kind"] != "numeric_measure"
        ]
        if extra_dimensions:
            return _no_chart("Line charts with additional dimensions are not supported in visualization v1.")
        return _chart_spec(
            chart_type="line",
            x_axis=time_dimension["name"],
            y_axis=measure["name"],
            category_order=_ordered_categories(
                dimension_name=time_dimension["name"],
                measure_name=measure["name"],
                columns=columns,
                rows=chart_rows,
                sort_strategy=sort_strategy,
            ),
            title=f"{_label_for(measure, semantic_metadata)} by {_label_for(time_dimension, semantic_metadata)}",
            x_label=_label_for(time_dimension, semantic_metadata),
            y_label=_label_for(measure, semantic_metadata),
            unit=_unit_for(measure, semantic_metadata),
            reason="Chart requested and result has one time dimension with one numeric measure.",
            confidence=0.82,
            warnings=warnings,
            x_type="temporal",
            y_type="quantitative",
            value_axis_starts_at_zero=False,
            display_row_limit=CHART_DISPLAY_ROW_LIMIT,
            truncated=chart_truncated,
            note=chart_note,
            sort_strategy=sort_strategy,
        )

    if len(categorical_dimensions) != 1:
        if not categorical_dimensions:
            return _no_chart("No safe categorical business dimension was found for a bar chart.")
        return _no_chart("Multiple categorical dimensions are ambiguous for visualization v1.")

    categorical_dimension = categorical_dimensions[0]
    extra_dimensions = [
        profile
        for profile in non_measure_dimensions
        if profile["name"] != categorical_dimension["name"] and profile["kind"] != "numeric_measure"
    ]
    if extra_dimensions:
        return _no_chart("Bar charts with additional dimensions are not supported in visualization v1.")

    return _chart_spec(
        chart_type="bar",
        x_axis=categorical_dimension["name"],
        y_axis=measure["name"],
        category_order=_ordered_categories(
            dimension_name=categorical_dimension["name"],
            measure_name=measure["name"],
            columns=columns,
            rows=chart_rows,
            sort_strategy=sort_strategy,
        ),
        title=f"{_label_for(measure, semantic_metadata)} by {_label_for(categorical_dimension, semantic_metadata)}",
        x_label=_label_for(categorical_dimension, semantic_metadata),
        y_label=_label_for(measure, semantic_metadata),
        unit=_unit_for(measure, semantic_metadata),
        reason="Chart requested and result has one categorical dimension with one numeric measure.",
        confidence=0.84,
        warnings=warnings,
        x_type="categorical",
        y_type="quantitative",
        value_axis_starts_at_zero=True,
        display_row_limit=CHART_DISPLAY_ROW_LIMIT,
        truncated=chart_truncated,
        note=chart_note,
        sort_strategy=sort_strategy,
    )


def _chart_requested(router_context: dict[str, Any], output_mode: str) -> bool:
    for key in ("chart_request", "needs_chart", "chart_requested"):
        if key in router_context:
            return bool(router_context.get(key))
    mode = str(router_context.get("output_mode") or output_mode or "").strip().lower()
    return mode == "chart_plus_table"


def _no_chart(reason: str, warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "chart_type": "none",
        "x_axis": None,
        "y_axis": None,
        "series": None,
        "title": "",
        "x_label": "",
        "y_label": "",
        "unit": "",
        "reason": reason,
        "confidence": 0.0,
        "render_allowed": False,
        "warnings": warnings or [],
        "orientation": "vertical",
        "category_order": [],
        "x_type": "",
        "y_type": "",
        "value_axis_starts_at_zero": False,
        "display_row_limit": CHART_DISPLAY_ROW_LIMIT,
        "truncated": False,
        "note": "",
        "sort": {"mode": "none", "explicit": False},
    }


def _chart_spec(
    *,
    chart_type: str,
    x_axis: str,
    y_axis: str,
    category_order: list[str],
    title: str,
    x_label: str,
    y_label: str,
    unit: str,
    reason: str,
    confidence: float,
    warnings: list[str],
    x_type: str,
    y_type: str,
    value_axis_starts_at_zero: bool,
    display_row_limit: int,
    truncated: bool,
    note: str,
    sort_strategy: dict[str, Any],
) -> dict[str, Any]:
    if chart_type not in SUPPORTED_CHART_TYPES:
        return _no_chart(f"Unsupported chart type: {chart_type}.")
    return {
        "chart_type": chart_type,
        "x_axis": x_axis,
        "y_axis": y_axis,
        "series": None,
        "title": title,
        "x_label": x_label,
        "y_label": y_label,
        "unit": unit,
        "reason": reason,
        "confidence": confidence,
        "render_allowed": True,
        "warnings": warnings,
        "orientation": "vertical",
        "category_order": category_order,
        "x_type": x_type,
        "y_type": y_type,
        "value_axis_starts_at_zero": value_axis_starts_at_zero,
        "display_row_limit": display_row_limit,
        "truncated": truncated,
        "note": note,
        "sort": sort_strategy,
    }


def _resolve_sort_strategy(user_question: str, router_context: dict[str, Any]) -> dict[str, Any]:
    explicit_context = router_context.get("chart_sort") or router_context.get("sort_order") or router_context.get("sort")
    text = _normalize_name(" ".join(str(part) for part in (user_question, explicit_context or "") if part))
    tokens = set(text.split("_")) if text else set()

    if tokens.intersection({"alphabetical", "alphabetic", "alphabetically", "alphabetisch", "lexicographic"}):
        return {
            "mode": "alphabetical",
            "field": "category",
            "direction": "ascending",
            "explicit": True,
        }

    if tokens.intersection({"descending", "desc", "absteigend", "highest", "largest", "biggest", "top"}):
        return {
            "mode": "measure",
            "field": "value",
            "direction": "descending",
            "explicit": True,
        }

    if tokens.intersection({"ascending", "asc", "aufsteigend", "lowest", "smallest"}):
        return {
            "mode": "measure",
            "field": "value",
            "direction": "ascending",
            "explicit": True,
        }

    return {
        "mode": "sql_result_order",
        "field": "row_order",
        "direction": "original",
        "explicit": False,
    }


def _ordered_categories(
    *,
    dimension_name: str,
    measure_name: str,
    columns: list[str],
    rows: list[Any],
    sort_strategy: dict[str, Any],
) -> list[str]:
    dimension_index = columns.index(dimension_name)
    measure_index = columns.index(measure_name)
    entries: list[dict[str, Any]] = []
    for position, row in enumerate(rows):
        entries.append(
            {
                "position": position,
                "category": _json_safe_category(_row_value(row, dimension_name, dimension_index)),
                "measure": _decimal_or_none(_row_value(row, measure_name, measure_index)),
            }
        )

    mode = str(sort_strategy.get("mode", "sql_result_order"))
    if mode == "alphabetical":
        entries = sorted(entries, key=lambda entry: entry["category"].casefold())
    elif mode == "measure":
        direction = str(sort_strategy.get("direction", "descending"))
        numeric_entries = [entry for entry in entries if entry["measure"] is not None]
        missing_entries = [entry for entry in entries if entry["measure"] is None]
        numeric_entries = sorted(
            numeric_entries,
            key=lambda entry: entry["measure"],
            reverse=direction == "descending",
        )
        entries = numeric_entries + missing_entries

    return _unique_preserving_order([entry["category"] for entry in entries])


def _profile_column(column: str, rows: list[Any], index: int) -> dict[str, Any]:
    values = [_row_value(row, column, index) for row in rows]
    non_null_values = [value for value in values if value is not None]
    distinct_values = {str(value) for value in non_null_values}
    normalized_name = _normalize_name(column)

    if not non_null_values:
        kind = "unknown"
    elif _is_date_name(normalized_name) and _mostly_date_like(non_null_values, normalized_name):
        kind = "date_or_time_dimension"
    elif _is_identifier_name(normalized_name):
        kind = "identifier"
    elif _is_code_or_category_name(normalized_name):
        kind = "categorical_dimension"
    elif _all_numeric_like(non_null_values):
        kind = "numeric_measure" if _is_measure_name(normalized_name) or len(distinct_values) > 1 else "unknown"
    elif _mostly_date_like(non_null_values, normalized_name):
        kind = "date_or_time_dimension"
    elif _looks_categorical(non_null_values):
        kind = "categorical_dimension"
    else:
        kind = "unknown"

    return {
        "name": column,
        "normalized_name": normalized_name,
        "kind": kind,
        "distinct_count": len(distinct_values),
        "non_null_count": len(non_null_values),
    }


def _row_value(row: Any, column: str, index: int) -> Any:
    if isinstance(row, dict):
        return row.get(column)
    if isinstance(row, (list, tuple)) and index < len(row):
        return row[index]
    return None


def _select_numeric_measure(
    numeric_measures: list[dict[str, Any]],
    *,
    user_question: str,
    final_sql: str,
) -> dict[str, Any]:
    if not numeric_measures:
        return {"measure": None, "reason": "No safe numeric measure was found.", "warnings": []}
    if len(numeric_measures) == 1:
        return {"measure": numeric_measures[0], "reason": "", "warnings": []}

    selected = _measure_requested_by_text(numeric_measures, user_question)
    if selected is None:
        selected = _measure_requested_by_text(numeric_measures, final_sql)
    if selected is None:
        return {
            "measure": None,
            "reason": "Multiple numeric measures are ambiguous for visualization v1.",
            "warnings": [],
        }

    return {
        "measure": selected,
        "reason": "",
        "warnings": [
            "Multiple numeric measures were present; selected the measure explicitly referenced by the request."
        ],
    }


def _measure_requested_by_text(
    numeric_measures: list[dict[str, Any]],
    text: str,
) -> dict[str, Any] | None:
    normalized_text = _normalize_name(text)
    matches = [
        measure
        for measure in numeric_measures
        if measure["normalized_name"] and measure["normalized_name"] in normalized_text
    ]
    return matches[0] if len(matches) == 1 else None


def _label_for(profile: dict[str, Any], semantic_metadata: dict[str, Any]) -> str:
    columns = semantic_metadata.get("columns") if isinstance(semantic_metadata.get("columns"), dict) else {}
    metadata = columns.get(profile["name"], {}) if isinstance(columns, dict) else {}
    label = metadata.get("business_name") or metadata.get("label") if isinstance(metadata, dict) else None
    return str(label) if label else _humanize_name(profile["name"])


def _unit_for(profile: dict[str, Any], semantic_metadata: dict[str, Any]) -> str:
    columns = semantic_metadata.get("columns") if isinstance(semantic_metadata.get("columns"), dict) else {}
    metadata = columns.get(profile["name"], {}) if isinstance(columns, dict) else {}
    unit = metadata.get("unit") if isinstance(metadata, dict) else None
    return str(unit) if unit else ""


def _normalize_name(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(value).lower())).strip("_")


def _humanize_name(value: str) -> str:
    return _normalize_name(value).replace("_", " ").title()


def _is_identifier_name(normalized_name: str) -> bool:
    return bool(_ID_NAME_PATTERN.search(normalized_name))


def _is_date_name(normalized_name: str) -> bool:
    return bool(_DATE_NAME_PATTERN.search(normalized_name))


def _is_measure_name(normalized_name: str) -> bool:
    return bool(_AGGREGATE_NAME_PATTERN.search(normalized_name))


def _is_code_or_category_name(normalized_name: str) -> bool:
    return bool(_CODE_NAME_PATTERN.search(normalized_name))


def _all_numeric_like(values: list[Any]) -> bool:
    return all(_is_numeric_like(value) for value in values)


def _is_numeric_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float, Decimal)):
        return True
    if isinstance(value, str):
        try:
            Decimal(value.strip())
            return True
        except (InvalidOperation, ValueError):
            return False
    return False


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


def _json_safe_category(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _mostly_date_like(values: list[Any], normalized_name: str) -> bool:
    if normalized_name in {"year", "jahr", "o_year", "o_jahr", "fiscal_year", "fiscal_jahr"}:
        return all(_is_year_like(value) for value in values)
    date_like_count = sum(1 for value in values if _is_date_like(value))
    return bool(values) and date_like_count / len(values) >= 0.8


def _is_date_like(value: Any) -> bool:
    if isinstance(value, (date, datetime)):
        return True
    if isinstance(value, str):
        text = value.strip()
        return bool(
            re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)
            or re.fullmatch(r"\d{4}-\d{2}", text)
            or re.fullmatch(r"\d{4}[-_/]?(Q[1-4]|q[1-4])", text)
        )
    return _is_year_like(value)


def _is_year_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        year = int(value)
    except (TypeError, ValueError):
        return False
    return 1900 <= year <= 2200


def _looks_categorical(values: list[Any]) -> bool:
    return all(not isinstance(value, (dict, list, tuple)) for value in values)
