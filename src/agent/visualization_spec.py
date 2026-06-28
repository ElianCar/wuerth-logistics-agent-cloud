from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any


SUPPORTED_CHART_TYPES = {"none", "bar", "line", "area", "scatter", "pie", "grouped_bar", "stacked_bar", "faceted_bar", "measure_bar"}
CHART_DISPLAY_ROW_LIMIT = 50
MAX_CATEGORICAL_VALUES = CHART_DISPLAY_ROW_LIMIT

_DATE_NAME_PATTERN = re.compile(
    r"(^|_)(date|datum|day|tag|week|woche|month|monat|quarter|quartal|year|jahr|time|zeit|period|periode|created_at|updated_at)($|_)",
    re.IGNORECASE,
)
_AGGREGATE_NAME_PATTERN = re.compile(
    r"(^|_)(count|cnt|sum|total|avg|average|min|max|revenue|sales|amount|cost|costs|quantity|qty|value|price|measure|"
    r"umsatz|menge|anzahl|anteil|prozent|percent|positionen|position|gewicht|kosten|summe|durchschnitt)($|_)",
    re.IGNORECASE,
)
_ID_NAME_PATTERN = re.compile(
    r"(^|_)(id|key)$|"
    r"(^|_)(order|customer|shipment|article|invoice|supplier|product|line_item|delivery|material)_(id|key|number)$|"
    r"(^|_)(o_orderkey|c_custkey|s_suppkey|p_partkey|l_orderkey|l_partkey|l_suppkey)$",
    re.IGNORECASE,
)
_CODE_NAME_PATTERN = re.compile(r"(^|_)(code|status|type|segment|mode|priority|region|nation|country)($|_)", re.IGNORECASE)
# Ranking / row-ordering helper columns (e.g. RANK() OVER ... AS revenue_rank). Their
# integer values (1, 2, 3 …) would otherwise be mistaken for a measure, inflating the
# measure count and breaking grouped/faceted detection. They are ordinal helpers, not
# business metrics, so they are excluded from both axes and measures.
_RANK_NAME_PATTERN = re.compile(
    r"(^|_)(rank|rang|ranking|rownum|row_number|rownumber|rangfolge)($|_)",
    re.IGNORECASE,
)
# German/English business dimension names. A column whose name matches this is treated
# as a categorical dimension even when its values look numeric (Würth encodes plants and
# products as numeric text codes, e.g. plant="9191"). Checked after the measure-name
# pattern so mixed names like "produkt_umsatz" still resolve to a measure.
_DIMENSION_NAME_PATTERN = re.compile(
    r"(^|_)(vertriebszentrum|plant|werk|standort|lager|warehouse|produkt|product|artikel|material|"
    r"sparte|segment|kunde|customer|kategorie|category|land|region|nation|country|status|typ|type)($|_)",
    re.IGNORECASE,
)

# Authoritative mapping from semantic-layer ``semantic_type`` to a chart profile kind.
_SEMANTIC_TYPE_TO_KIND = {
    "monetary_measure": "numeric_measure",
    "measure": "numeric_measure",
    "date": "date_or_time_dimension",
    "date_period": "date_or_time_dimension",
    "organizational_code": "categorical_dimension",
    "categorical_code": "categorical_dimension",
    "product_identifier": "categorical_dimension",
    "warehouse_location": "categorical_dimension",
    "quantity_code": "categorical_dimension",
    "currency_code": "categorical_dimension",
    "boolean_flag": "categorical_dimension",
    "identifier": "identifier",
    "customer_identifier": "identifier",
    "delivery_identifier": "identifier",
    "count_or_item_index": "identifier",
    "uninterpreted": "unknown",
}


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

    output_mode_normalized = str(router_context.get("output_mode") or output_mode or "").strip().lower()
    if output_mode_normalized == "table":
        return _no_chart("Table-only output mode was requested.")

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

    profiles = [_profile_column(column, chart_rows, index, semantic_metadata) for index, column in enumerate(columns)]
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

    # 1. faceted_bar: 2 categorical + 2 numeric (e.g. Top-N Produkte je Vertriebszentrum)
    if len(categorical_dimensions) == 2 and len(numeric_measures) == 2:
        return _build_faceted_bar(
            categorical_dimensions,
            numeric_measures,
            columns=columns,
            rows=chart_rows,
            sort_strategy=sort_strategy,
            semantic_metadata=semantic_metadata,
            truncated=chart_truncated,
            note=chart_note,
        )

    # 2. grouped_bar: 2 categorical + 1 numeric
    if len(categorical_dimensions) == 2 and len(numeric_measures) == 1:
        return _build_grouped_bar(
            categorical_dimensions,
            numeric_measures[0],
            columns=columns,
            rows=chart_rows,
            sort_strategy=sort_strategy,
            semantic_metadata=semantic_metadata,
            truncated=chart_truncated,
            note=chart_note,
        )

    # 3. scatter: 2+ numeric, no categorical/temporal dimension, and enough points.
    #    A single-row scatter would just be one meaningless dot, so require >= 3 rows;
    #    fewer rows fall through to the measure_bar fallback below.
    if (
        len(numeric_measures) >= 2
        and not time_dimensions
        and not categorical_dimensions
        and len(chart_rows) >= 3
    ):
        return _build_scatter(
            numeric_measures,
            semantic_metadata=semantic_metadata,
            truncated=chart_truncated,
            note=chart_note,
        )

    # Without any numeric measure there is nothing to plot.
    if not numeric_measures:
        return _no_chart("No safe numeric measure was found.")

    # 4. measure_bar: numeric measures but no dimension of any kind to plot against
    #    (e.g. a single-row KPI result like `anzahl_auftraege | anteil_prozent`).
    #    Each measure becomes one bar so the result is always chartable. We require a
    #    genuinely dimensionless result: identifier and high-cardinality columns must
    #    NOT silently disappear into an anonymous measure bar.
    identifier_dimensions = [profile for profile in profiles if profile["kind"] == "identifier"]
    has_any_dimension = bool(
        time_dimensions or categorical_dimensions or unsupported_dimensions or identifier_dimensions
    )
    if not has_any_dimension:
        return _build_measure_bar(
            numeric_measures,
            semantic_metadata=semantic_metadata,
            truncated=chart_truncated,
            note=chart_note,
            warnings=[],
        )

    # Remaining types need a single primary measure. Per "rather one chart too many",
    # an ambiguous multi-measure result no longer aborts: we pick the first measure
    # and attach a warning instead of returning _no_chart.
    if len(numeric_measures) == 1:
        measure = numeric_measures[0]
        warnings = []
    else:
        measure_selection = _select_numeric_measure(
            numeric_measures,
            user_question=user_question,
            final_sql=final_sql,
        )
        if measure_selection["measure"]:
            measure = measure_selection["measure"]
            warnings = list(measure_selection["warnings"])
        else:
            measure = numeric_measures[0]
            warnings = [
                "Mehrere numerische Kennzahlen vorhanden; automatisch die erste Kennzahl gewählt."
            ]

    # 4. area: 1 temporal + 1 numeric (clean time series only)
    if time_dimensions:
        if len(time_dimensions) == 1:
            time_dimension = time_dimensions[0]
            extra_dimensions = [
                profile
                for profile in profiles
                if profile["name"] not in {time_dimension["name"], measure["name"]}
                and profile["kind"] not in {"identifier", "unknown", "numeric_measure"}
            ]
            if not extra_dimensions:
                return _build_area(
                    time_dimension,
                    measure,
                    columns=columns,
                    rows=chart_rows,
                    sort_strategy=sort_strategy,
                    semantic_metadata=semantic_metadata,
                    truncated=chart_truncated,
                    note=chart_note,
                    warnings=warnings,
                )
        # Messy time structure (multiple time dimensions, or extra dimensions alongside
        # the date). With >=2 measures a relationship scatter is more useful than nothing,
        # so fall through to the scatter fallback below; otherwise there is no clean chart.
        if len(numeric_measures) < 2:
            return _no_chart("Time charts with additional dimensions are not supported.")

    # 5. pie / donut: only when the user explicitly asks (keyword in question).
    #    Checked BEFORE bar so an explicit "Kreisdiagramm" wins over the default bar.
    _PIE_KEYWORDS = {"pie", "donut", "kreisdiagramm", "kuchendiagramm", "anteil", "anteile", "torte"}
    question_words = {w.lower().strip("?!.,;:") for w in user_question.split()}
    if question_words & _PIE_KEYWORDS and len(categorical_dimensions) == 1:
        return _build_pie(
            categorical_dimensions[0],
            measure,
            columns=columns,
            rows=chart_rows,
            semantic_metadata=semantic_metadata,
            truncated=chart_truncated,
            note=chart_note,
            warnings=warnings,
        )

    # 6. bar: 1 categorical + 1 numeric (default for comparison data)
    if len(categorical_dimensions) == 1:
        if not unsupported_dimensions:
            extra_dimensions = [
                profile
                for profile in profiles
                if profile["name"] not in {categorical_dimensions[0]["name"], measure["name"]}
                and profile["kind"] not in {"identifier", "unknown", "numeric_measure"}
            ]
            if not extra_dimensions:
                return _build_bar(
                    categorical_dimensions[0],
                    measure,
                    columns=columns,
                    rows=chart_rows,
                    sort_strategy=sort_strategy,
                    semantic_metadata=semantic_metadata,
                    truncated=chart_truncated,
                    note=chart_note,
                    warnings=warnings,
                )
        # Could not build a clean bar (cardinality too high, or an extra non-measure
        # dimension such as a date). With >=2 measures fall through to the scatter
        # fallback; otherwise report why no chart was produced.
        if len(numeric_measures) < 2:
            if unsupported_dimensions:
                names = ", ".join(p["name"] for p in unsupported_dimensions)
                return _no_chart(f"Categorical dimension cardinality is too high: {names}.")
            return _no_chart("Bar charts with additional dimensions are not supported.")

    # 7. scatter fallback: two or more measures but no clean dimensional structure (e.g.
    #    row-level "Umsatz und Lieferkosten je Lieferposition" with incidental date /
    #    identifier columns). A relationship scatter beats returning no chart at all.
    if len(numeric_measures) >= 2 and len(chart_rows) >= 3:
        return _build_scatter(
            numeric_measures,
            semantic_metadata=semantic_metadata,
            truncated=chart_truncated,
            note=chart_note,
        )

    if not categorical_dimensions:
        return _no_chart("No safe categorical business dimension was found for a chart.")
    return _no_chart("No suitable chart structure was detected.")


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
        "series_column": None,
        "series_values": [],
        "second_metric": None,
        "facet_column": None,
        "measure_columns": [],
        "donut": False,
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
    series_column: str | None = None,
    series_values: list[str] | None = None,
    second_metric: str | None = None,
    facet_column: str | None = None,
    measure_columns: list[str] | None = None,
    donut: bool = False,
    orientation: str = "vertical",
) -> dict[str, Any]:
    if chart_type not in SUPPORTED_CHART_TYPES:
        return _no_chart(f"Unsupported chart type: {chart_type}.")
    return {
        "chart_type": chart_type,
        "x_axis": x_axis,
        "y_axis": y_axis,
        "series": None,
        "series_column": series_column,
        "series_values": series_values or [],
        "second_metric": second_metric,
        "facet_column": facet_column,
        "measure_columns": measure_columns or [],
        "donut": donut,
        "title": title,
        "x_label": x_label,
        "y_label": y_label,
        "unit": unit,
        "reason": reason,
        "confidence": confidence,
        "render_allowed": True,
        "warnings": warnings,
        "orientation": orientation,
        "category_order": category_order,
        "x_type": x_type,
        "y_type": y_type,
        "value_axis_starts_at_zero": value_axis_starts_at_zero,
        "display_row_limit": display_row_limit,
        "truncated": truncated,
        "note": note,
        "sort": sort_strategy,
    }


def _build_bar(
    categorical: dict[str, Any],
    measure: dict[str, Any],
    *,
    columns: list[str],
    rows: list[Any],
    sort_strategy: dict[str, Any],
    semantic_metadata: dict[str, Any],
    truncated: bool,
    note: str,
    warnings: list[str],
) -> dict[str, Any]:
    return _chart_spec(
        chart_type="bar",
        x_axis=categorical["name"],
        y_axis=measure["name"],
        category_order=_ordered_categories(
            dimension_name=categorical["name"],
            measure_name=measure["name"],
            columns=columns,
            rows=rows,
            sort_strategy=sort_strategy,
        ),
        title=f"{_label_for(measure, semantic_metadata)} by {_label_for(categorical, semantic_metadata)}",
        x_label=_label_for(categorical, semantic_metadata),
        y_label=_label_for(measure, semantic_metadata),
        unit=_unit_for(measure, semantic_metadata),
        reason="Result has one categorical dimension with one numeric measure.",
        confidence=0.84,
        warnings=warnings,
        x_type="categorical",
        y_type="quantitative",
        value_axis_starts_at_zero=True,
        display_row_limit=CHART_DISPLAY_ROW_LIMIT,
        truncated=truncated,
        note=note,
        sort_strategy=sort_strategy,
    )


def _build_area(
    time_dimension: dict[str, Any],
    measure: dict[str, Any],
    *,
    columns: list[str],
    rows: list[Any],
    sort_strategy: dict[str, Any],
    semantic_metadata: dict[str, Any],
    truncated: bool,
    note: str,
    warnings: list[str],
) -> dict[str, Any]:
    return _chart_spec(
        chart_type="area",
        x_axis=time_dimension["name"],
        y_axis=measure["name"],
        category_order=_ordered_categories(
            dimension_name=time_dimension["name"],
            measure_name=measure["name"],
            columns=columns,
            rows=rows,
            sort_strategy=sort_strategy,
        ),
        title=f"{_label_for(measure, semantic_metadata)} über Zeit",
        x_label=_label_for(time_dimension, semantic_metadata),
        y_label=_label_for(measure, semantic_metadata),
        unit=_unit_for(measure, semantic_metadata),
        reason="Result has one time dimension with one numeric measure.",
        confidence=0.82,
        warnings=warnings,
        x_type="temporal",
        y_type="quantitative",
        value_axis_starts_at_zero=False,
        display_row_limit=CHART_DISPLAY_ROW_LIMIT,
        truncated=truncated,
        note=note,
        sort_strategy=sort_strategy,
    )


def _build_pie(
    categorical: dict[str, Any],
    measure: dict[str, Any],
    *,
    columns: list[str],
    rows: list[Any],
    semantic_metadata: dict[str, Any],
    truncated: bool,
    note: str,
    warnings: list[str],
) -> dict[str, Any]:
    donut = int(categorical.get("distinct_count", 0)) > 3
    return _chart_spec(
        chart_type="pie",
        x_axis=categorical["name"],
        y_axis=measure["name"],
        category_order=_ordered_categories(
            dimension_name=categorical["name"],
            measure_name=measure["name"],
            columns=columns,
            rows=rows,
            sort_strategy={"mode": "measure", "field": "value", "direction": "descending", "explicit": False},
        ),
        title=f"Anteile: {_label_for(measure, semantic_metadata)} nach {_label_for(categorical, semantic_metadata)}",
        x_label=_label_for(categorical, semantic_metadata),
        y_label=_label_for(measure, semantic_metadata),
        unit=_unit_for(measure, semantic_metadata),
        reason="Result has one categorical dimension (≤8 values) with one numeric measure.",
        confidence=0.80,
        warnings=warnings,
        x_type="categorical",
        y_type="quantitative",
        value_axis_starts_at_zero=True,
        display_row_limit=CHART_DISPLAY_ROW_LIMIT,
        truncated=truncated,
        note=note,
        sort_strategy={"mode": "measure", "field": "value", "direction": "descending", "explicit": False},
        donut=donut,
    )


def _build_scatter(
    numeric_measures: list[dict[str, Any]],
    *,
    semantic_metadata: dict[str, Any],
    truncated: bool,
    note: str,
) -> dict[str, Any]:
    x_measure = numeric_measures[0]
    y_measure = numeric_measures[1]
    return _chart_spec(
        chart_type="scatter",
        x_axis=x_measure["name"],
        y_axis=y_measure["name"],
        category_order=[],
        title=f"{_label_for(x_measure, semantic_metadata)} vs. {_label_for(y_measure, semantic_metadata)}",
        x_label=_label_for(x_measure, semantic_metadata),
        y_label=_label_for(y_measure, semantic_metadata),
        unit=_unit_for(y_measure, semantic_metadata),
        reason="Result has two numeric measures suitable for a scatter plot.",
        confidence=0.78,
        warnings=[],
        x_type="quantitative",
        y_type="quantitative",
        value_axis_starts_at_zero=False,
        display_row_limit=CHART_DISPLAY_ROW_LIMIT,
        truncated=truncated,
        note=note,
        sort_strategy={"mode": "sql_result_order", "field": "row_order", "direction": "original", "explicit": False},
    )


def _build_measure_bar(
    numeric_measures: list[dict[str, Any]],
    *,
    semantic_metadata: dict[str, Any],
    truncated: bool,
    note: str,
    warnings: list[str],
) -> dict[str, Any]:
    """Fallback chart for dimensionless results: render each measure as one bar.

    Used when the SQL result has one or more numeric measures but no categorical or
    time dimension to plot them against (e.g. a single-row KPI result). Honors the
    "rather one chart too many" philosophy by always producing a renderable chart.
    """
    measure_names = [measure["name"] for measure in numeric_measures]
    labels = [_label_for(measure, semantic_metadata) for measure in numeric_measures]
    unit = _unit_for(numeric_measures[0], semantic_metadata) if len(numeric_measures) == 1 else ""
    spec = _chart_spec(
        chart_type="measure_bar",
        x_axis=measure_names[0],
        y_axis=measure_names[0],
        measure_columns=measure_names,
        category_order=labels,
        title="Kennzahlenübersicht",
        x_label="Kennzahl",
        y_label="Wert",
        unit=unit,
        reason="Result has numeric measures but no category/time dimension; rendered as a measure comparison.",
        confidence=0.6,
        warnings=warnings,
        x_type="categorical",
        y_type="quantitative",
        value_axis_starts_at_zero=True,
        display_row_limit=CHART_DISPLAY_ROW_LIMIT,
        truncated=truncated,
        note=note,
        sort_strategy={"mode": "sql_result_order", "field": "row_order", "direction": "original", "explicit": False},
    )
    return spec


def _build_grouped_bar(
    categorical_dimensions: list[dict[str, Any]],
    measure: dict[str, Any],
    *,
    columns: list[str],
    rows: list[Any],
    sort_strategy: dict[str, Any],
    semantic_metadata: dict[str, Any],
    truncated: bool,
    note: str,
) -> dict[str, Any]:
    # series_column = categorical with fewer distinct values (grouping dimension)
    # x_axis = categorical with more distinct values (primary dimension)
    if categorical_dimensions[0]["distinct_count"] <= categorical_dimensions[1]["distinct_count"]:
        series_dim, x_dim = categorical_dimensions[0], categorical_dimensions[1]
    else:
        series_dim, x_dim = categorical_dimensions[1], categorical_dimensions[0]

    series_idx = columns.index(series_dim["name"])
    series_values = _unique_preserving_order(
        [_json_safe_category(_row_value(row, series_dim["name"], series_idx)) for row in rows]
    )

    return _chart_spec(
        chart_type="grouped_bar",
        x_axis=x_dim["name"],
        y_axis=measure["name"],
        series_column=series_dim["name"],
        series_values=series_values,
        category_order=_ordered_categories(
            dimension_name=x_dim["name"],
            measure_name=measure["name"],
            columns=columns,
            rows=rows,
            sort_strategy=sort_strategy,
        ),
        title=f"{_label_for(measure, semantic_metadata)} nach {_label_for(x_dim, semantic_metadata)} und {_label_for(series_dim, semantic_metadata)}",
        x_label=_label_for(x_dim, semantic_metadata),
        y_label=_label_for(measure, semantic_metadata),
        unit=_unit_for(measure, semantic_metadata),
        reason="Result has two categorical dimensions with one numeric measure.",
        confidence=0.80,
        warnings=[],
        x_type="categorical",
        y_type="quantitative",
        value_axis_starts_at_zero=True,
        display_row_limit=CHART_DISPLAY_ROW_LIMIT,
        truncated=truncated,
        note=note,
        sort_strategy=sort_strategy,
    )


def _build_faceted_bar(
    categorical_dimensions: list[dict[str, Any]],
    numeric_measures: list[dict[str, Any]],
    *,
    columns: list[str],
    rows: list[Any],
    sort_strategy: dict[str, Any],
    semantic_metadata: dict[str, Any],
    truncated: bool,
    note: str,
) -> dict[str, Any]:
    # facet_column = categorical with more distinct values (e.g. Vertriebszentrum)
    # x_axis = categorical with fewer distinct values (e.g. Produkt)
    if categorical_dimensions[0]["distinct_count"] >= categorical_dimensions[1]["distinct_count"]:
        facet_dim, x_dim = categorical_dimensions[0], categorical_dimensions[1]
    else:
        facet_dim, x_dim = categorical_dimensions[1], categorical_dimensions[0]

    y_measure = numeric_measures[0]
    second_measure = numeric_measures[1]

    return _chart_spec(
        chart_type="faceted_bar",
        x_axis=x_dim["name"],
        y_axis=y_measure["name"],
        second_metric=second_measure["name"],
        facet_column=facet_dim["name"],
        category_order=_ordered_categories(
            dimension_name=x_dim["name"],
            measure_name=y_measure["name"],
            columns=columns,
            rows=rows,
            sort_strategy=sort_strategy,
        ),
        title=f"{_label_for(y_measure, semantic_metadata)} und {_label_for(second_measure, semantic_metadata)} je {_label_for(facet_dim, semantic_metadata)}",
        x_label=_label_for(x_dim, semantic_metadata),
        y_label=_label_for(y_measure, semantic_metadata),
        unit=_unit_for(y_measure, semantic_metadata),
        reason="Result has two categorical dimensions and two numeric measures.",
        confidence=0.82,
        warnings=[],
        x_type="categorical",
        y_type="quantitative",
        value_axis_starts_at_zero=True,
        display_row_limit=CHART_DISPLAY_ROW_LIMIT,
        truncated=truncated,
        note=note,
        sort_strategy=sort_strategy,
    )


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


def _profile_column(
    column: str,
    rows: list[Any],
    index: int,
    semantic_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = [_row_value(row, column, index) for row in rows]
    non_null_values = [value for value in values if value is not None]
    distinct_values = {str(value) for value in non_null_values}
    normalized_name = _normalize_name(column)
    semantic_kind = _semantic_kind_for(column, semantic_metadata)

    if not non_null_values:
        kind = "unknown"
    elif len(non_null_values) > 1 and len(distinct_values) == 1:
        # A column with a single repeated value across many rows is a filter constant
        # (e.g. plant="9981" after WHERE plant='9981'). It carries no charting signal and
        # must not be treated as a dimension/measure that blocks better chart choices.
        kind = "unknown"
    elif semantic_kind is not None:
        # 1. The semantic layer is authoritative: it knows that a numeric-looking text
        #    code like plant="9191" is an organizational dimension, not a measure.
        kind = semantic_kind
    elif _is_rank_name(normalized_name):
        # 2. Ranking helper columns (revenue_rank, lieferpositionen_rank) are ordinal
        #    helpers, not measures. Excluded so they don't inflate the measure count.
        kind = "identifier"
    elif _is_measure_name(normalized_name) and _all_numeric_like(non_null_values):
        # 2. Explicit measure names (umsatz, anzahl, anteil, …) on numeric values win
        #    over the dimension-name heuristic for mixed names like "produkt_umsatz".
        kind = "numeric_measure"
    elif _is_dimension_name(normalized_name):
        # 3. German/English business-dimension names → categorical, even if the values
        #    look numeric (Würth encodes Vertriebszentrum/Produkt as numeric codes).
        kind = "categorical_dimension"
    elif _is_date_name(normalized_name) and _mostly_date_like(non_null_values, normalized_name):
        kind = "date_or_time_dimension"
    elif _is_identifier_name(normalized_name):
        kind = "identifier"
    elif _is_code_or_category_name(normalized_name):
        kind = "categorical_dimension"
    elif _all_numeric_like(non_null_values):
        if _mostly_date_like(non_null_values, normalized_name):
            # Numeric values that look like dates (e.g. YYYYMM=202507) → temporal
            kind = "date_or_time_dimension"
        else:
            # Any numeric, non-identifier, non-date column is a measure. We deliberately
            # do NOT require >1 distinct value: a single-row result (e.g. a KPI count)
            # is still a valid measure and should be chartable.
            kind = "numeric_measure"
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


def _semantic_kind_for(column: str, semantic_metadata: dict[str, Any] | None) -> str | None:
    """Return the authoritative chart kind for a column from the semantic layer, if known.

    ``uninterpreted`` columns map to ``unknown`` (excluded). An unrecognised or missing
    semantic_type returns ``None`` so the name/value heuristics take over.
    """
    if not isinstance(semantic_metadata, dict):
        return None
    columns = semantic_metadata.get("columns")
    if not isinstance(columns, dict):
        return None
    meta = columns.get(column)
    if not isinstance(meta, dict):
        return None
    semantic_type = str(meta.get("semantic_type") or "").strip().lower()
    if not semantic_type:
        return None
    return _SEMANTIC_TYPE_TO_KIND.get(semantic_type)


def _is_dimension_name(normalized_name: str) -> bool:
    return bool(_DIMENSION_NAME_PATTERN.search(normalized_name))


def _is_rank_name(normalized_name: str) -> bool:
    return bool(_RANK_NAME_PATTERN.search(normalized_name))


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

    # Exact match: full normalized column name is substring of the text
    exact = [m for m in numeric_measures if m["normalized_name"] and m["normalized_name"] in normalized_text]
    if len(exact) == 1:
        return exact[0]

    # Token match: any individual token of the column name (split by "_") appears in the text
    # E.g. question contains "Anteil" → matches column "anteil_prozent" but not "anzahl_auftraege"
    if not exact:
        text_tokens = set(normalized_text.split("_"))
        token_matches = [
            m for m in numeric_measures
            if m["normalized_name"] and set(m["normalized_name"].split("_")) & text_tokens
        ]
        if len(token_matches) == 1:
            return token_matches[0]

    return None


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
            or _is_yyyymm_int(text)
        )
    if isinstance(value, int) and not isinstance(value, bool):
        return _is_yyyymm_int(str(value)) or _is_year_like(value)
    return _is_year_like(value)


def _is_yyyymm_int(text: str) -> bool:
    """Recognise YYYYMM compact integer format (e.g. 202507 → July 2025)."""
    if not re.fullmatch(r"\d{6}", text):
        return False
    year, month = int(text[:4]), int(text[4:])
    return 1900 <= year <= 2200 and 1 <= month <= 12


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
