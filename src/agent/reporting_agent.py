from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any

import pandas as pd

from src.agent.visualization_spec import build_visualization_spec


_IDENTIFIER_NAME_PATTERN = re.compile(
    r"(^|_)(id|key)$|"
    r"(^|_)[a-z0-9]+key$|"
    r"(^|_)(order|customer|shipment|article|invoice|supplier|product|line_item|delivery|material|nation|region)"
    r"_(id|key|number)$|"
    r"(^|_)(order|invoice|shipment|material|customer)_number$",
    re.IGNORECASE,
)


def build_reporting_result(
    *,
    user_question: str,
    router_state: dict[str, Any] | None = None,
    sql: str = "",
    query_result: dict[str, Any] | None = None,
    result_dataframe: pd.DataFrame | None = None,
    row_count: int | None = None,
    source_tables: list[str] | None = None,
    execution_success: bool = False,
    validation_success: bool = False,
    language: str = "de",
    chart_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic post-SQL reporting output.

    The reporting layer does not generate SQL, modify SQL, call a database, or
    call an LLM. It only inspects the already returned SQL result and metadata.
    """

    router_state = router_state or {}
    query_result = query_result or {}
    source_tables = source_tables or []
    df = result_dataframe.copy(deep=True) if result_dataframe is not None else _dataframe_from_query_result(query_result)
    effective_row_count = int(row_count if row_count is not None else len(df.index))

    if chart_plan is None:
        chart_plan = build_visualization_spec(
            user_question=user_question,
            router_context=router_state,
            output_mode=str(router_state.get("output_mode", "")),
            query_result=query_result,
            execution_success=execution_success,
            validation_success=validation_success,
            row_count=effective_row_count,
            final_sql=sql,
            source_tables=source_tables,
        )

    metadata = _derive_metadata(df, sql, chart_plan)
    audit = _build_audit(
        chart_plan=chart_plan,
        df=df,
        row_count=effective_row_count,
        source_tables=source_tables,
        execution_success=execution_success,
        validation_success=validation_success,
        metadata=metadata,
        language=language or str(router_state.get("language") or "de"),
    )
    display_notes = _display_notes(chart_plan, audit)
    summary_parts = _build_german_summary(
        df=df,
        chart_plan=chart_plan,
        source_tables=source_tables,
        execution_success=execution_success,
        validation_success=validation_success,
        metadata=metadata,
        audit=audit,
    )
    caveats = summary_parts["caveats"]
    audit["display_notes"] = display_notes
    audit["summary_generated"] = bool(summary_parts["summary"])
    audit["warnings"] = [*audit.get("warnings", []), *chart_plan.get("warnings", [])]

    return {
        "summary": summary_parts["summary"],
        "interpretation": summary_parts["interpretation"],
        "caveats": caveats,
        "chart_plan": chart_plan,
        "table_plan": {
            "render_allowed": bool(not df.empty),
            "row_count": effective_row_count,
            "columns": [str(column) for column in df.columns],
            "preserve_sql_order": True,
        },
        "kpi_cards": _build_kpi_cards(df, metadata),
        "display_notes": display_notes,
        "audit": audit,
    }


def _dataframe_from_query_result(query_result: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(query_result.get("rows", []) or [], columns=query_result.get("columns", []) or [])


def _derive_metadata(df: pd.DataFrame, sql: str, chart_plan: dict[str, Any]) -> dict[str, Any]:
    columns = [str(column) for column in df.columns]
    metric_columns = _metric_columns(df)
    grouping_columns = _grouping_columns(df, metric_columns)

    chart_metric = chart_plan.get("y_axis") if chart_plan.get("render_allowed") else None
    chart_grouping = chart_plan.get("x_axis") if chart_plan.get("render_allowed") else None
    if chart_metric and str(chart_metric) not in metric_columns:
        metric_columns.insert(0, str(chart_metric))
    if chart_grouping and str(chart_grouping) not in grouping_columns:
        grouping_columns.insert(0, str(chart_grouping))

    return {
        "columns": columns,
        "metric_columns": metric_columns,
        "grouping_columns": grouping_columns,
        "applied_filters": _extract_where_clause(sql),
        "sort_order": _extract_order_by_clause(sql),
        "limit": _extract_limit(sql),
        "unit": str(chart_plan.get("unit") or ""),
    }


def _build_audit(
    *,
    chart_plan: dict[str, Any],
    df: pd.DataFrame,
    row_count: int,
    source_tables: list[str],
    execution_success: bool,
    validation_success: bool,
    metadata: dict[str, Any],
    language: str,
) -> dict[str, Any]:
    chart_type = str(chart_plan.get("chart_type", "none"))
    render_allowed = bool(chart_plan.get("render_allowed"))
    explicit_sort = bool((chart_plan.get("sort") or {}).get("explicit"))
    chart_order = "not_applicable"
    if render_allowed:
        chart_order = "explicit_user_sort" if explicit_sort else "sql_result_order"

    missing = []
    for key in ("applied_filters", "sort_order", "limit", "unit"):
        if not metadata.get(key):
            missing.append(key)
    if not metadata.get("grouping_columns"):
        missing.append("grouping_columns")
    if not metadata.get("metric_columns"):
        missing.append("metric_columns")

    chart_cap = int(chart_plan.get("display_row_limit") or 50)
    return {
        "sql_success": bool(execution_success and validation_success),
        "row_count": row_count,
        "rows_visualized": min(row_count, chart_cap) if render_allowed else 0,
        "chart_type": chart_type,
        "category_column": chart_plan.get("x_axis") if render_allowed else None,
        "metric_column": chart_plan.get("y_axis") if render_allowed else None,
        "chart_order": chart_order,
        "chart_truncated": bool(chart_plan.get("truncated", False)),
        "chart_cap": chart_cap,
        "explicit_sort_applied": explicit_sort,
        "source_tables": source_tables,
        "grouping_columns": metadata.get("grouping_columns", []),
        "metric_columns": metadata.get("metric_columns", []),
        "applied_filters": metadata.get("applied_filters", ""),
        "sort_order": metadata.get("sort_order", ""),
        "limit": metadata.get("limit"),
        "display_notes": [],
        "summary_generated": False,
        "summary_language": "de",
        "warnings": [],
        "missing_metadata_fields": missing,
        "table_order_preserved": True,
    }


def _display_notes(chart_plan: dict[str, Any], audit: dict[str, Any]) -> list[str]:
    notes = []
    note = str(chart_plan.get("note") or "")
    if note:
        notes.append(note)
    if audit.get("explicit_sort_applied"):
        notes.append("Die Visualisierung verwendet eine explizit angeforderte Sortierung.")
    return notes


def _build_german_summary(
    *,
    df: pd.DataFrame,
    chart_plan: dict[str, Any],
    source_tables: list[str],
    execution_success: bool,
    validation_success: bool,
    metadata: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    caveats = _base_caveats(metadata, chart_plan)
    if not execution_success or not validation_success:
        summary = (
            "Kurzantwort: Es liegt kein erfolgreiches SQL Ergebnis vor.\n\n"
            "Berechnungslogik: Es wurde keine belastbare Auswertung erstellt, weil SQL Validierung oder Ausführung nicht erfolgreich war.\n\n"
            "Auffälligkeit: Ohne erfolgreiches Ergebnis ist keine fachliche Interpretation möglich.\n\n"
            f"Einschränkungen: {' '.join(caveats)}"
        )
        return {"summary": summary, "interpretation": "Keine Interpretation ohne erfolgreiches SQL Ergebnis.", "caveats": caveats}

    if df.empty:
        summary = (
            "Kurzantwort: Die Abfrage hat keine Ergebniszeilen zurückgegeben.\n\n"
            f"Berechnungslogik: Ausgewertet wurde das SQL Ergebnis aus {_source_text(source_tables)}.\n\n"
            "Auffälligkeit: Ohne Ergebniszeilen ist keine Mustererkennung möglich.\n\n"
            f"Einschränkungen: {' '.join(caveats)}"
        )
        return {"summary": summary, "interpretation": "Keine sichtbare Auffälligkeit, da keine Zeilen zurückgegeben wurden.", "caveats": caveats}

    metric = _first(metadata.get("metric_columns", []))
    grouping = _first(metadata.get("grouping_columns", []))
    metric_label = _label(metric)
    grouping_label = _label(grouping)
    logic = _calculation_logic(metric_label, grouping_label, metadata, source_tables, audit)
    interpretation = _interpretation(df, metric, grouping, chart_plan, audit)

    if metric and grouping:
        short_answer = (
            f"Die Analyse zeigt {metric_label} nach {grouping_label}. "
            "Tabelle und Visualisierung verwenden standardmäßig dieselbe Reihenfolge wie das SQL Ergebnis."
        )
    elif metric:
        short_answer = f"Die Analyse zeigt den Kennwert {metric_label} im zurückgegebenen SQL Ergebnis."
    else:
        short_answer = "Die Analyse zeigt die vom SQL Agenten zurückgegebenen Ergebniszeilen."

    summary = (
        f"Kurzantwort: {short_answer}\n\n"
        f"Berechnungslogik: {logic}\n\n"
        f"Auffälligkeit: {interpretation}\n\n"
        f"Einschränkungen: {' '.join(caveats)}"
    )
    return {"summary": summary, "interpretation": interpretation, "caveats": caveats}


def _calculation_logic(
    metric_label: str,
    grouping_label: str,
    metadata: dict[str, Any],
    source_tables: list[str],
    audit: dict[str, Any],
) -> str:
    parts = []
    if metric_label and grouping_label:
        parts.append(f"Gruppiert wurde nach {grouping_label}, ausgewertet wurde {metric_label}.")
    elif metric_label:
        parts.append(f"Ausgewertet wurde {metric_label}.")
    else:
        parts.append("Ausgewertet wurden die zurückgegebenen Ergebniszeilen.")
    parts.append(f"Die Daten stammen aus {_source_text(source_tables)}.")
    if metadata.get("applied_filters"):
        parts.append("Berücksichtigt wurden die im SQL enthaltenen Filter.")
    if metadata.get("sort_order"):
        parts.append("Die Sortierung stammt aus der SQL Abfrage.")
    else:
        parts.append("Die Darstellung folgt der Reihenfolge der Ergebnistabelle.")
    if metadata.get("limit") is not None:
        parts.append(f"Das SQL Ergebnis enthält ein LIMIT von {metadata['limit']}.")
    if audit.get("explicit_sort_applied"):
        parts.append("Für die Visualisierung wurde eine explizit angeforderte Sortierung angewendet.")
    return " ".join(parts)


def _interpretation(
    df: pd.DataFrame,
    metric: str,
    grouping: str,
    chart_plan: dict[str, Any],
    audit: dict[str, Any],
) -> str:
    if len(df.index) == 1 and len(df.columns) == 1:
        value = _format_value(df.iloc[0, 0])
        return f"Der zurückgegebene Einzelwert beträgt {value}. Ein Vergleich oder Trend ist daraus nicht ableitbar."

    time_column = _time_column(df)
    if metric and metric in df.columns and time_column:
        numeric = pd.to_numeric(df[metric], errors="coerce")
        visible = df.loc[numeric.notna(), [time_column, metric]].copy()
        if len(visible.index) >= 2:
            visible_numeric = pd.to_numeric(visible[metric], errors="coerce")
            first_value = visible_numeric.iloc[0]
            last_value = visible_numeric.iloc[-1]
            first_period = str(visible[time_column].iloc[0])
            last_period = str(visible[time_column].iloc[-1])
            direction = "steigt" if last_value > first_value else "sinkt" if last_value < first_value else "bleibt stabil"
            return (
                f"Der sichtbare Verlauf {direction} von {first_period} ({_format_value(first_value)}) "
                f"bis {last_period} ({_format_value(last_value)}). "
                "Ursachen werden daraus nicht abgeleitet."
            )

    if metric and metric in df.columns and grouping and grouping in df.columns:
        numeric = pd.to_numeric(df[metric], errors="coerce")
        visible = df.loc[numeric.notna(), [grouping, metric]].copy()
        if visible.empty:
            return "In den zurückgegebenen Zeilen ist kein belastbarer numerischer Vergleich erkennbar."
        numeric = pd.to_numeric(visible[metric], errors="coerce")
        high_idx = numeric.idxmax()
        low_idx = numeric.idxmin()
        high_group = str(visible.loc[high_idx, grouping])
        low_group = str(visible.loc[low_idx, grouping])
        high_value = _format_value(visible.loc[high_idx, metric])
        low_value = _format_value(visible.loc[low_idx, metric])
        scope = "in den visualisierten ersten 50 Zeilen" if chart_plan.get("truncated") else "in den angezeigten Ergebnissen"
        return (
            f"{scope} liegt der höchste sichtbare Wert bei {high_group} mit {high_value}; "
            f"der niedrigste sichtbare Wert liegt bei {low_group} mit {low_value}. "
            "Eine fachliche Ursache ist aus diesem SQL Ergebnis allein nicht ableitbar."
        )

    time_column = _time_column(df)
    if metric and metric in df.columns and time_column:
        numeric = pd.to_numeric(df[metric], errors="coerce")
        if numeric.notna().sum() >= 2:
            first = numeric.dropna().iloc[0]
            last = numeric.dropna().iloc[-1]
            direction = "steigt" if last > first else "sinkt" if last < first else "bleibt stabil"
            return f"Der sichtbare Verlauf {direction} zwischen erstem und letztem zurückgegebenem Zeitpunkt. Ursachen werden daraus nicht abgeleitet."

    return "Die zurückgegebenen Zeilen liefern eine deskriptive Übersicht; weitergehende Ursachen oder nicht sichtbare Segmente sind daraus nicht ableitbar."


def _base_caveats(metadata: dict[str, Any], chart_plan: dict[str, Any]) -> list[str]:
    caveats = [
        "Die Aussage basiert nur auf den zurückgegebenen Zeilen und den im SQL enthaltenen Filtern.",
        "Aus deskriptiven Aggregaten wird keine Ursache abgeleitet.",
    ]
    if not metadata.get("unit"):
        caveats.append("Einheiten werden nicht automatisch abgeleitet, wenn sie nicht im Ergebnis oder in der Semantik verfügbar sind.")
    if chart_plan.get("truncated"):
        caveats.append("Die Visualisierung zeigt nur die ersten 50 Zeilen; die Tabelle bleibt vollständig.")
    return caveats


def _build_kpi_cards(df: pd.DataFrame, metadata: dict[str, Any]) -> list[dict[str, str]]:
    if len(df.index) == 1 and len(df.columns) == 1:
        column = str(df.columns[0])
        if _is_identifier_column(column):
            return []
        return [{"label": _label(column), "value": _format_value(df.iloc[0, 0])}]
    if len(df.index) == 1 and metadata.get("metric_columns"):
        cards = []
        for column in metadata["metric_columns"]:
            if column in df.columns:
                cards.append({"label": _label(column), "value": _format_value(df.iloc[0][column])})
        return cards
    return []


def _metric_columns(df: pd.DataFrame) -> list[str]:
    metrics = []
    for column in df.columns:
        values = [value for value in df[column].tolist() if value is not None]
        if values and not _is_identifier_column(str(column)) and all(_is_numeric_like(value) for value in values):
            metrics.append(str(column))
    return metrics


def _grouping_columns(df: pd.DataFrame, metric_columns: list[str]) -> list[str]:
    return [str(column) for column in df.columns if str(column) not in metric_columns]


def _extract_where_clause(sql: str) -> str:
    match = re.search(r"\bwhere\b(.+?)(\border\s+by\b|\bgroup\s+by\b|\blimit\b|$)", sql, flags=re.IGNORECASE | re.DOTALL)
    return _clean_sql_fragment(match.group(1)) if match else ""


def _extract_order_by_clause(sql: str) -> str:
    match = re.search(r"\border\s+by\b(.+?)(\blimit\b|$)", sql, flags=re.IGNORECASE | re.DOTALL)
    return _clean_sql_fragment(match.group(1)) if match else ""


def _extract_limit(sql: str) -> int | None:
    match = re.search(r"\blimit\s+(\d+)\b", sql, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _clean_sql_fragment(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ;\n\t")


def _time_column(df: pd.DataFrame) -> str:
    for column in df.columns:
        name = str(column).lower()
        if any(token in name for token in ("date", "datum", "day", "tag", "week", "woche", "month", "monat", "year", "jahr", "time", "zeit")):
            return str(column)
    return ""


def _source_text(source_tables: list[str]) -> str:
    return ", ".join(f"`{table}`" for table in source_tables) if source_tables else "den vom SQL Agenten verwendeten Quelltabellen"


def _first(values: list[str]) -> str:
    return str(values[0]) if values else ""


def _label(column: str) -> str:
    return re.sub(r"_+", " ", str(column)).strip().title() if column else ""


def _is_identifier_column(column: str) -> bool:
    return bool(_IDENTIFIER_NAME_PATTERN.search(re.sub(r"[^a-z0-9]+", "_", str(column).lower()).strip("_")))


def _format_value(value: Any) -> str:
    if _is_numeric_like(value):
        number = Decimal(str(value))
        if number == number.to_integral_value():
            return f"{int(number):,}".replace(",", ".")
        return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(value)


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
