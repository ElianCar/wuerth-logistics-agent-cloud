import io
import uuid
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import yaml

from src.agent.db import get_active_backend_metadata
from src.agent.golden_test_runner import (
    DEFAULT_GOLDEN_RUNTIME_MODE,
    GOLDEN_RUNTIME_MODES,
    GoldenRuntimeMode,
    load_golden_questions,
    run_golden_tests,
)
from src.agent.langgraph_sql_agent import SQLAgentConfig
from src.agent.orchestrator import run_orchestrator
from src.agent.logging_utils import log_feedback
from src.agent.memory_store import (
    MemoryStoreError,
    audit_candidate_validation,
    create_candidate_from_run,
    initialize_memory_files,
    load_candidates,
    load_templates,
    mark_candidate_needs_changes,
    parse_source_tables,
    reject_candidate,
    update_candidate_proposed_template,
)
from src.agent.memory_lifecycle import (
    MemoryLifecycleError,
    approve_candidate_to_vsm,
    load_approved_template_records,
)
from src.agent.memory_validation import validate_proposed_template
from src.agent.presentation_export import (
    PPTX_MIME_TYPE,
    build_presentation_export,
    can_export_presentation,
)
from src.config.scenarios import (
    SCENARIOS,
    get_active_scenario,
    get_active_scenario_id,
    get_scenario_options,
    set_active_scenario_id,
)
from src.llm.model_adapter import (
    DEFAULT_ANTHROPIC_FALLBACK_MODEL,
    DEFAULT_ANTHROPIC_MEDIUM_MODEL,
    DEFAULT_GEMINI_BACKUP_MODEL,
    DEFAULT_GEMINI_PRIMARY_MODEL,
    DEFAULT_OLLAMA_BACKUP_MODEL,
    DEFAULT_OLLAMA_MODEL,
    anthropic_api_key_is_placeholder,
    gemini_api_key_is_placeholder,
    get_provider,
    get_token_usage,
    reset_token_usage,
)


PAGE_CHAT = "Chat"
PAGE_GOLDEN = "Golden-Testmodus"
PAGE_MEMORY = "Memory-Prüfung"
PAGE_TEMPLATES = "Freigegebene Templates"

# --- Würth corporate identity (colors from the PPT template theme) ---
WUERTH_RED = "#CC0000"
WUERTH_TEXT = "#4B4B4B"
WUERTH_BLUE = "#0093DD"
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
WUERTH_LOGO_PATH = _ASSETS_DIR / "wuerth_logo.png"
WUERTH_SHIELD_PATH = _ASSETS_DIR / "wuerth_shield.png"
# Combined TUM + Würth logo for the top-left brand slot (provided by the user).
TUM_WUERTH_LOGO_PATH = _ASSETS_DIR / "tum_wuerth_logo.png"
# Categorical palette for multi-series charts; Würth red first, then theme accents.
WUERTH_PALETTE = ["#CC0000", "#4B4B4B", "#0093DD", "#FDC300", "#008448", "#90112C", "#8B8B8D"]

GOLDEN_RUNTIME_LABELS: dict[GoldenRuntimeMode, str] = {
    "orchestrator": "Real chat path: Orchestrator",
    "direct_sql_agent": "Direct SQL agent: Debug only",
}

GOLDEN_RUNTIME_HELP: dict[GoldenRuntimeMode, str] = {
    "orchestrator": "Nutzt denselben Router-, Modell-, Memory- und SQL-Agent-Pfad wie der normale Chat.",
    "direct_sql_agent": "Debug-Modus: umgeht Router, Modellklassifizierung und VSM Memory Retrieval.",
}

_STEP_LABELS: dict[str, str] = {
    "run_router": "Anfrage analysieren",
    "select_model": "Modell auswählen",
    "terminal_response": "Direkte Antwort erstellen",
    "data_overview": "Datenüberblick erstellen",
    "load_schema": "Datenbankschema laden",
    "generate_sql": "SQL generieren",
    "validate_sql": "SQL validieren",
    "execute_sql": "SQL ausführen",
    "repair_sql": "SQL reparieren",
    "switch_model": "Auf Fallback-Modell wechseln",
    "generate_final_answer": "Antwort formulieren",
}

_STEP_SYMBOLS: dict[str, str] = {
    "run_router": "⊙",
    "select_model": "⚙",
    "terminal_response": "◉",
    "data_overview": "▤",
    "load_schema": "≡",
    "generate_sql": "✎",
    "validate_sql": "✓",
    "execute_sql": "▶",
    "repair_sql": "↺",
    "switch_model": "⇄",
    "generate_final_answer": "◉",
}


def _new_chat_id() -> str:
    return str(uuid.uuid4())


def _make_chat(name: str = "") -> dict:
    return {"name": name, "history": []}


def active_history() -> list[dict]:
    return st.session_state.chats[st.session_state.active_chat_id]["history"]


_PRESENTATION_UNAVAILABLE_REASON_COPY: dict[str, str] = {
    "record_missing": "No analysis record was found.",
    "blocked_request": "This request was blocked for safety.",
    "clarification_needed": "This run needs clarification before export.",
    "sql_execution_failed": "SQL execution did not finish successfully.",
    "sql_validation_failed": "SQL validation did not pass.",
    "missing_query_result": "No query result is available.",
    "missing_query_columns": "The query result has no columns.",
    "missing_query_rows": "The query result has no rows.",
    "zero_row_count": "The query returned zero rows.",
    "presentation_mode_invalid": "The configured PPT export mode is unsupported.",
    "anthropic_api_key_missing": "ANTHROPIC_API_KEY is missing for Claude PPT generation.",
    "anthropic_dependency_missing": "The Anthropic dependency is missing in the app environment.",
    "claude_upload_failed": "Claude could not receive the template or analysis payload.",
    "claude_generation_failed": "Claude PPT generation failed.",
    "claude_generation_incomplete": "Claude PPT generation did not finish before the retry limit.",
    "claude_output_missing": "Claude did not return a PowerPoint file.",
    "claude_output_invalid": "Claude returned a file, but it was not a readable PowerPoint deck.",
}

_PRESENTATION_WARNING_COPY: dict[str, str] = {
    "presentation_planner_fallback": "PPT-Planung nutzt den deterministischen Fallback.",
    "planner_fallback": "PPT-Planung nutzt den deterministischen Fallback.",
    "presentation_table_truncated": "Tabelle wurde fuer die Folie gekuerzt.",
    "table_rows_truncated": "Tabelle wurde fuer die Folie gekuerzt.",
    "table_columns_truncated": "Tabelle wurde fuer die Folie gekuerzt.",
    "presentation_chart_fallback": "Diagramm wurde durch eine lesbare Ersatzdarstellung ersetzt.",
    "chart_fallback": "Diagramm wurde durch eine lesbare Ersatzdarstellung ersetzt.",
    "presentation_label_truncated": "Lange Beschriftungen wurden fuer die Folie gekuerzt.",
    "label_truncated": "Lange Beschriftungen wurden fuer die Folie gekuerzt.",
}


def presentation_export_key(
    record: dict,
    index: int,
    *,
    active_chat_id: str | None = None,
) -> str:
    chat_id = active_chat_id or st.session_state.get("active_chat_id", "chat")
    record_id = record.get("run_id") or index
    return f"ppt_export_{chat_id}_{record_id}"


def presentation_download_key_from_export_key(export_key: str) -> str:
    suffix = str(export_key).removeprefix("ppt_export_")
    return f"download_ppt_{suffix}"


def presentation_exports_state(session_state: dict | None = None) -> dict:
    state = session_state if session_state is not None else st.session_state
    exports = state.setdefault("presentation_exports", {})
    if not isinstance(exports, dict):
        exports = {}
        state["presentation_exports"] = exports
    return exports


def clear_presentation_exports_for_chat(chat_id: str, session_state: dict | None = None) -> None:
    exports = presentation_exports_state(session_state)
    prefix = f"ppt_export_{chat_id}_"
    for key in list(exports):
        if str(key).startswith(prefix):
            del exports[key]


def format_presentation_unavailable_reason(reason: object) -> str:
    return _PRESENTATION_UNAVAILABLE_REASON_COPY.get(
        str(reason or ""),
        "The backend exporter marked this run as unavailable.",
    )


def format_presentation_failure_reason(reason: object) -> str:
    raw_reason = str(reason or "unknown_reason").strip()
    if not raw_reason:
        return "Unknown reason"
    if raw_reason in _PRESENTATION_UNAVAILABLE_REASON_COPY:
        return _PRESENTATION_UNAVAILABLE_REASON_COPY[raw_reason]
    return raw_reason.replace("_", " ").capitalize()


def format_presentation_warning(warning: object) -> str:
    raw_warning = str(warning or "").strip()
    if not raw_warning:
        return ""
    warning_code = raw_warning.split(":", 1)[0].strip()
    return _PRESENTATION_WARNING_COPY.get(
        raw_warning,
        _PRESENTATION_WARNING_COPY.get(warning_code, raw_warning),
    )


_STOP_WORDS = {
    "wie", "was", "wer", "wo", "wann", "warum", "welche", "welcher", "welches",
    "welchen", "welchem", "zeige", "zeig", "gib", "mir", "bitte", "kannst", "du",
    "die", "der", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "eines", "ist", "sind", "gibt", "es", "ich", "all", "alle", "viele", "viel",
    "mal", "bitte", "noch", "schon", "doch", "auch", "nur", "mehr", "weniger",
    "möchte", "möchten", "würde", "würden", "hätte", "hätten", "kann", "können",
}


def _auto_chat_name(question: str) -> str:
    words = question.split()
    kept = [w.strip("?!.,;:") for w in words if w.lower().strip("?!.,;:") not in _STOP_WORDS]
    chosen = kept[:3]
    return " ".join(chosen) if chosen else question[:20]


def _build_chat_context(history: list[dict]) -> str:
    lines = ["Bisheriger Gesprächsverlauf:"]
    for record in history:
        q = record.get("user_question", "").strip()
        sql = (record.get("final_sql") or record.get("generated_sql", "")).strip()
        success = record.get("execution_success", False)
        row_count = record.get("row_count")
        a = record.get("final_answer", "").strip()
        is_clarification = (
            record.get("result_status") == "clarification_needed"
            or record.get("error_type") == "clarification_needed"
        )
        is_overview = record.get("result_status") == "data_overview"

        if q:
            lines.append(f"F: {q}")

        if is_overview:
            # Langen Katalogtext nicht in den Kontext spiegeln.
            lines.append("A: Datenüberblick ausgegeben.")
            lines.append("")
            continue

        if is_clarification:
            # Offene Rückfrage – kein "Fehlgeschlagen". Die nächste Nutzernachricht
            # ist potenziell die Antwort darauf.
            if a:
                lines.append(f"RÜCKFRAGE DES SYSTEMS: {a}")
        else:
            if sql:
                lines.append(f"SQL: {sql}")
            status = "Erfolg" if success else "Fehlgeschlagen"
            if row_count is not None:
                status += f", {row_count} Zeile(n)"
            lines.append(f"Status: {status}")
            if a:
                lines.append(f"A: {a}")
        lines.append("")
    return "\n".join(lines)


def _render_chat_sidebar_css() -> None:
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"]
            [data-testid="stColumn"]:first-child div[data-testid="stButton"] button {
            font-size: 0.78rem;
            text-align: left;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        section[data-testid="stSidebar"] [data-testid="stHorizontalBlock"]
            [data-testid="stColumn"]:last-child button {
            justify-content: center !important;
            padding: 4px 0 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def result_to_dataframe(record: dict) -> pd.DataFrame:
    query_result = record.get("query_result", {})
    return pd.DataFrame(
        query_result.get("rows", []),
        columns=query_result.get("columns", []),
    )


def render_chart_from_spec(record: dict, df: pd.DataFrame) -> None:
    chart_spec = record.get("chart_spec")
    if not isinstance(chart_spec, dict) or not chart_spec.get("render_allowed"):
        return

    # Chart-only daily refinement: when a monthly time series collapsed to a single
    # point, the orchestrator attaches a finer (daily) result used for the chart only.
    chart_qr = record.get("reporting_result", {}).get("chart_query_result") if isinstance(record.get("reporting_result"), dict) else None
    if isinstance(chart_qr, dict) and chart_qr.get("rows") and chart_qr.get("columns"):
        df = pd.DataFrame(chart_qr.get("rows", []), columns=chart_qr.get("columns", []))

    chart_type = str(chart_spec.get("chart_type", "none"))
    x_axis = chart_spec.get("x_axis")
    y_axis = chart_spec.get("y_axis")
    renderable_types = {"bar", "line", "area", "scatter", "pie", "grouped_bar", "stacked_bar", "faceted_bar", "measure_bar"}
    if chart_type not in renderable_types or not x_axis or not y_axis:
        return
    if x_axis not in df.columns or y_axis not in df.columns:
        st.warning("Die Visualisierung konnte nicht gerendert werden, weil Spalten im Ergebnis fehlen.")
        return

    x_label = str(chart_spec.get("x_label") or x_axis)
    y_label = str(chart_spec.get("y_label") or y_axis)
    unit = str(chart_spec.get("unit") or "")
    display_y_label = f"{y_label} ({unit})" if unit else y_label
    display_row_limit = int(chart_spec.get("display_row_limit") or len(df))

    st.subheader("Visualisierung")
    title = str(chart_spec.get("title") or "")
    if title:
        st.caption(title)
    note = str(chart_spec.get("note") or "")
    if note:
        st.caption(note)

    # --- Scatter: 2 numeric axes, no category mapping needed ---
    if chart_type == "scatter":
        scatter_df = df[[x_axis, y_axis]].head(display_row_limit).copy()
        scatter_df["_chart_x"] = pd.to_numeric(scatter_df[x_axis], errors="coerce")
        scatter_df["_chart_y"] = pd.to_numeric(scatter_df[y_axis], errors="coerce")
        scatter_df = scatter_df.dropna(subset=["_chart_x", "_chart_y"])
        if scatter_df.empty:
            return
        chart = alt.Chart(scatter_df).mark_circle(size=80, color=WUERTH_RED).encode(
            x=alt.X("_chart_x:Q", title=x_label),
            y=alt.Y("_chart_y:Q", title=display_y_label),
            tooltip=[
                alt.Tooltip("_chart_x:Q", title=x_label),
                alt.Tooltip("_chart_y:Q", title=display_y_label),
            ],
        )
        st.altair_chart(chart, use_container_width=True)
        return

    # --- Grouped / Stacked Bar: uses series_column for color grouping ---
    if chart_type in ("grouped_bar", "stacked_bar"):
        series_column = chart_spec.get("series_column")
        if not series_column or series_column not in df.columns:
            return
        cols_needed = [x_axis, y_axis, series_column]
        gb_df = df[cols_needed].head(display_row_limit).copy()
        gb_df["_chart_category"] = gb_df[x_axis].astype(str)
        gb_df["_chart_value"] = pd.to_numeric(gb_df[y_axis], errors="coerce")
        gb_df["_chart_series"] = gb_df[series_column].astype(str)
        gb_df = gb_df.dropna(subset=["_chart_value"])
        if gb_df.empty:
            return
        category_order = [str(v) for v in chart_spec.get("category_order", [])]
        if not category_order:
            category_order = list(dict.fromkeys(gb_df["_chart_category"].tolist()))
        series_label = str(series_column).replace("_", " ").title()
        stack = True if chart_type == "stacked_bar" else None
        chart = alt.Chart(gb_df).mark_bar().encode(
            x=alt.X("_chart_category:N", sort=category_order, title=x_label),
            y=alt.Y("_chart_value:Q", stack=stack, scale=alt.Scale(zero=True), title=display_y_label),
            color=alt.Color("_chart_series:N", title=series_label, scale=alt.Scale(range=WUERTH_PALETTE)),
            tooltip=[
                alt.Tooltip("_chart_category:N", title=x_label),
                alt.Tooltip("_chart_series:N", title=series_label),
                alt.Tooltip("_chart_value:Q", title=display_y_label),
            ],
        )
        st.altair_chart(chart, use_container_width=True)
        return

    # --- Faceted Bar: per facet_column, grouped bars with optional second metric ---
    if chart_type == "faceted_bar":
        facet_column = chart_spec.get("facet_column")
        second_metric = chart_spec.get("second_metric")
        if not facet_column or facet_column not in df.columns:
            return
        cols_needed = [x_axis, y_axis, facet_column]
        if second_metric and second_metric in df.columns:
            cols_needed.append(second_metric)
        fb_df = df[cols_needed].head(display_row_limit).copy()

        if second_metric and second_metric in df.columns:
            # Reshape to long format via pd.melt so both measures appear as color groups
            id_cols = [x_axis, facet_column]
            fb_long = fb_df.melt(id_vars=id_cols, value_vars=[y_axis, second_metric],
                                  var_name="_measure_name", value_name="_measure_value")
            fb_long["_chart_category"] = fb_long[x_axis].astype(str)
            fb_long["_chart_facet"] = fb_long[facet_column].astype(str)
            fb_long["_chart_value"] = pd.to_numeric(fb_long["_measure_value"], errors="coerce")
            fb_long = fb_long.dropna(subset=["_chart_value"])
            if fb_long.empty:
                return
            category_order = [str(v) for v in chart_spec.get("category_order", [])]
            if not category_order:
                category_order = list(dict.fromkeys(fb_long["_chart_category"].tolist()))
            base = alt.Chart(fb_long).mark_bar().encode(
                x=alt.X("_chart_category:N", sort=category_order, title=x_label),
                y=alt.Y("_chart_value:Q", scale=alt.Scale(zero=True), title=display_y_label),
                color=alt.Color("_measure_name:N", title="Kennzahl", scale=alt.Scale(range=WUERTH_PALETTE)),
                tooltip=[
                    alt.Tooltip("_chart_facet:N", title=str(facet_column).replace("_", " ").title()),
                    alt.Tooltip("_chart_category:N", title=x_label),
                    alt.Tooltip("_measure_name:N", title="Kennzahl"),
                    alt.Tooltip("_chart_value:Q", title=display_y_label),
                ],
            )
            chart = base.facet(facet=alt.Facet("_chart_facet:N", title=str(facet_column).replace("_", " ").title()), columns=3)
        else:
            fb_df["_chart_category"] = fb_df[x_axis].astype(str)
            fb_df["_chart_facet"] = fb_df[facet_column].astype(str)
            fb_df["_chart_value"] = pd.to_numeric(fb_df[y_axis], errors="coerce")
            fb_df = fb_df.dropna(subset=["_chart_value"])
            if fb_df.empty:
                return
            category_order = [str(v) for v in chart_spec.get("category_order", [])]
            if not category_order:
                category_order = list(dict.fromkeys(fb_df["_chart_category"].tolist()))
            base = alt.Chart(fb_df).mark_bar().encode(
                x=alt.X("_chart_category:N", sort=category_order, title=x_label),
                y=alt.Y("_chart_value:Q", scale=alt.Scale(zero=True), title=display_y_label),
                color=alt.Color("_chart_category:N", legend=None, scale=alt.Scale(range=WUERTH_PALETTE)),
                tooltip=[
                    alt.Tooltip("_chart_facet:N", title=str(facet_column).replace("_", " ").title()),
                    alt.Tooltip("_chart_category:N", title=x_label),
                    alt.Tooltip("_chart_value:Q", title=display_y_label),
                ],
            )
            chart = base.facet(facet=alt.Facet("_chart_facet:N", title=str(facet_column).replace("_", " ").title()), columns=3)
        st.altair_chart(chart, use_container_width=True)
        return

    # --- Measure bar: dimensionless result, each measure column becomes a bar ---
    if chart_type == "measure_bar":
        measure_columns = [c for c in chart_spec.get("measure_columns", []) if c in df.columns]
        if not measure_columns:
            return
        mb_df = df[measure_columns].head(display_row_limit).copy()
        label_map = {c: str(c).replace("_", " ").title() for c in measure_columns}
        if len(mb_df) <= 1:
            long_df = mb_df.melt(var_name="_measure", value_name="_chart_value")
            long_df["_chart_category"] = long_df["_measure"].map(label_map)
            long_df["_chart_value"] = pd.to_numeric(long_df["_chart_value"], errors="coerce")
            long_df = long_df.dropna(subset=["_chart_value"])
            if long_df.empty:
                return
            chart = alt.Chart(long_df).mark_bar().encode(
                x=alt.X("_chart_category:N", sort=list(label_map.values()), title="Kennzahl"),
                y=alt.Y("_chart_value:Q", scale=alt.Scale(zero=True), title="Wert"),
                color=alt.Color("_chart_category:N", legend=None, scale=alt.Scale(range=WUERTH_PALETTE)),
                tooltip=[
                    alt.Tooltip("_chart_category:N", title="Kennzahl"),
                    alt.Tooltip("_chart_value:Q", title="Wert"),
                ],
            )
        else:
            mb_df["_row"] = range(1, len(mb_df) + 1)
            long_df = mb_df.melt(id_vars="_row", var_name="_measure", value_name="_chart_value")
            long_df["_measure_label"] = long_df["_measure"].map(label_map)
            long_df["_chart_category"] = long_df["_row"].astype(str)
            long_df["_chart_value"] = pd.to_numeric(long_df["_chart_value"], errors="coerce")
            long_df = long_df.dropna(subset=["_chart_value"])
            if long_df.empty:
                return
            chart = alt.Chart(long_df).mark_bar().encode(
                x=alt.X("_chart_category:N", title="Zeile"),
                xOffset=alt.XOffset("_measure_label:N"),
                y=alt.Y("_chart_value:Q", scale=alt.Scale(zero=True), title="Wert"),
                color=alt.Color("_measure_label:N", title="Kennzahl", scale=alt.Scale(range=WUERTH_PALETTE)),
                tooltip=[
                    alt.Tooltip("_chart_category:N", title="Zeile"),
                    alt.Tooltip("_measure_label:N", title="Kennzahl"),
                    alt.Tooltip("_chart_value:Q", title="Wert"),
                ],
            )
        st.altair_chart(chart, use_container_width=True)
        return

    # --- Standard single-axis charts (bar, area, line, pie) ---
    chart_df = df[[x_axis, y_axis]].head(display_row_limit).copy()
    chart_df["_chart_category"] = chart_df[x_axis].astype(str)
    chart_df["_chart_value"] = pd.to_numeric(chart_df[y_axis], errors="coerce")
    chart_df["_row_order"] = range(len(chart_df))
    chart_df = chart_df.dropna(subset=["_chart_value"])
    if chart_df.empty:
        return

    category_order = [str(value) for value in chart_spec.get("category_order", [])]
    if not category_order:
        category_order = list(dict.fromkeys(chart_df["_chart_category"].tolist()))

    tooltip = [
        alt.Tooltip("_chart_category:N", title=x_label),
        alt.Tooltip("_chart_value:Q", title=display_y_label),
    ]
    base_chart = alt.Chart(chart_df)

    if chart_type == "pie":
        chart = base_chart.mark_arc(innerRadius=50 if chart_spec.get("donut") else 0).encode(
            theta=alt.Theta("_chart_value:Q"),
            color=alt.Color("_chart_category:N", sort=category_order, title=x_label, scale=alt.Scale(range=WUERTH_PALETTE)),
            tooltip=tooltip,
        )
        st.altair_chart(chart, use_container_width=True)
    elif chart_type == "bar":
        if str(chart_spec.get("orientation") or "vertical") == "horizontal":
            chart = base_chart.mark_bar(color=WUERTH_RED).encode(
                y=alt.Y("_chart_category:N", sort=category_order, title=x_label),
                x=alt.X("_chart_value:Q", scale=alt.Scale(zero=True), title=display_y_label),
                tooltip=tooltip,
            )
        else:
            chart = base_chart.mark_bar(color=WUERTH_RED).encode(
                x=alt.X("_chart_category:N", sort=category_order, title=x_label),
                y=alt.Y("_chart_value:Q", scale=alt.Scale(zero=True), title=display_y_label),
                tooltip=tooltip,
            )
        st.altair_chart(chart, use_container_width=True)
    elif chart_type in ("area", "line"):
        mark = (
            base_chart.mark_area(point=True, color=WUERTH_RED)
            if chart_type == "area"
            else base_chart.mark_line(point=True, color=WUERTH_RED)
        )
        chart = mark.encode(
            x=alt.X("_chart_category:N", sort=category_order, title=x_label),
            y=alt.Y("_chart_value:Q", title=display_y_label),
            order=alt.Order("_row_order:Q"),
            tooltip=tooltip,
        )
        st.altair_chart(chart, use_container_width=True)


def render_reporting_summary(record: dict) -> None:
    reporting = record.get("reporting_result")
    if not isinstance(reporting, dict):
        return

    summary = str(reporting.get("summary") or "").strip()
    if not summary:
        return

    st.subheader("Management-Zusammenfassung")
    st.markdown(summary)

    kpi_cards = reporting.get("kpi_cards", [])
    if isinstance(kpi_cards, list) and kpi_cards:
        columns = st.columns(min(len(kpi_cards), 4))
        for index, card in enumerate(kpi_cards[:4]):
            if not isinstance(card, dict):
                continue
            columns[index].metric(str(card.get("label", "Kennzahl")), str(card.get("value", "")))


def render_reporting_audit(record: dict) -> None:
    reporting = record.get("reporting_result")
    if not isinstance(reporting, dict):
        return
    audit = reporting.get("audit")
    if not isinstance(audit, dict):
        return
    with st.expander("Reporting-Audit", expanded=False):
        st.json(audit, expanded=False)


def _presentation_export_warnings(export: object) -> list[str]:
    warnings = getattr(export, "warnings", []) or []
    return [str(warning) for warning in warnings if str(warning)]


def render_presentation_export_feedback(export: object, container=st) -> None:
    warnings = _presentation_export_warnings(export)
    slide_count = int(getattr(export, "slide_count", 0) or 0)
    if warnings:
        container.warning("PPT created with warnings.")
        if slide_count:
            container.caption(f"Slides: {slide_count}")
        with container.expander("PPT warnings", expanded=False):
            for warning in warnings:
                st.write(format_presentation_warning(warning))
        return
    container.caption("PPT ready.")
    if slide_count:
        container.caption(f"Slides: {slide_count}")


def render_presentation_export_failure(export: object, container=st) -> None:
    reason = format_presentation_failure_reason(getattr(export, "unavailable_reason", ""))
    container.error(
        f"PPT export failed: {reason}. Fix the template or rerun a valid analysis, then create the deck again."
    )
    warnings = _presentation_export_warnings(export)
    if warnings:
        with container.expander("PPT warnings", expanded=False):
            for warning in warnings:
                st.write(warning)


def _render_ppt_token_caption(export_key: str, slot) -> None:
    usage = st.session_state.get("ppt_token_usage", {}).get(export_key)
    line = _format_token_usage(usage)
    if line:
        slot.caption(f"PPT-Generierung — {line}")


def render_presentation_export_controls(record: dict, index: int, container=st) -> None:
    eligibility = can_export_presentation(record)
    export_key = presentation_export_key(record, index)
    download_key = presentation_download_key_from_export_key(export_key)
    exports = presentation_exports_state()
    export = exports.get(export_key)
    control_slot = container.empty()
    feedback_slot = container.container()

    if getattr(export, "available", False):
        control_slot.download_button(
            "Download PPT",
            data=export.content,
            file_name=export.filename,
            mime=export.mime_type or PPTX_MIME_TYPE,
            key=download_key,
            type="primary",
            use_container_width=True,
        )
        render_presentation_export_feedback(export, feedback_slot)
        _render_ppt_token_caption(export_key, feedback_slot)
        return

    reason = format_presentation_unavailable_reason(getattr(eligibility, "reason", ""))
    if not getattr(eligibility, "can_export", False):
        control_slot.button(
            "Create PPT",
            key=f"create_{export_key}",
            disabled=True,
            use_container_width=True,
        )
        feedback_slot.caption(f"PPT unavailable: {reason}")
        return

    clicked = control_slot.button(
        "Create PPT",
        key=f"create_{export_key}",
        type="primary",
        use_container_width=True,
    )
    if clicked:
        reset_token_usage()
        with st.spinner("Creating PPT..."):
            export = build_presentation_export(record=record, include_closing=False)
        exports[export_key] = export
        st.session_state.setdefault("ppt_token_usage", {})[export_key] = get_token_usage()

    if getattr(export, "available", False):
        control_slot.download_button(
            "Download PPT",
            data=export.content,
            file_name=export.filename,
            mime=export.mime_type or PPTX_MIME_TYPE,
            key=download_key,
            type="primary",
            use_container_width=True,
        )
        render_presentation_export_feedback(export, feedback_slot)
        _render_ppt_token_caption(export_key, feedback_slot)
    elif export is not None:
        render_presentation_export_failure(export, feedback_slot)


def render_presentation_unavailable_compact(record: dict) -> None:
    eligibility = can_export_presentation(record)
    if getattr(eligibility, "can_export", False):
        return
    reason = format_presentation_unavailable_reason(getattr(eligibility, "reason", ""))
    st.caption("PPT unavailable")
    st.caption("Run a successful validated analysis with result rows, then create the deck.")
    st.caption(f"PPT unavailable: {reason}")


def initialize_state() -> None:
    if "data_scenario" in st.session_state:
        set_active_scenario_id(st.session_state.data_scenario)
    if "chats" not in st.session_state:
        first_id = _new_chat_id()
        st.session_state.chats = {first_id: _make_chat()}
        st.session_state.active_chat_id = first_id
    if st.session_state.get("active_chat_id") not in st.session_state.get("chats", {}):
        st.session_state.active_chat_id = next(iter(st.session_state.chats))
    st.session_state.setdefault("editing_chat_id", None)
    st.session_state.setdefault("confirm_delete_chat_id", None)
    st.session_state.setdefault("last_golden_run_id", "")
    st.session_state.setdefault("last_selected_question_ids", [])
    st.session_state.setdefault("last_failed_question_ids", [])
    st.session_state.setdefault("last_errored_question_ids", [])
    st.session_state.setdefault("last_golden_result_summary", {})
    st.session_state.setdefault("last_golden_results", [])
    presentation_exports_state()
    initialize_memory_files()


def set_flash(level: str, message: str) -> None:
    st.session_state.memory_flash = (level, message)


def render_flash() -> None:
    flash = st.session_state.pop("memory_flash", None)
    if not flash:
        return
    level, message = flash
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    elif level == "error":
        st.error(message)
    else:
        st.info(message)


def build_streamlit_llm_config() -> SQLAgentConfig:
    env_config = SQLAgentConfig.from_env()
    ollama_config = SQLAgentConfig.from_provider("ollama")

    st.session_state.setdefault(
        "use_local_ollama",
        env_config.llm_provider == "ollama",
    )

    use_local_ollama = st.toggle(
        "Lokales Ollama verwenden",
        key="use_local_ollama",
        help="Wenn aktiv, nutzt der Workflow lokale Ollama-Modelle für Primary und Fallback. Sonst wird der konfigurierte LLM-Anbieter genutzt.",
    )

    if use_local_ollama:
        return SQLAgentConfig(
            primary_model=DEFAULT_OLLAMA_MODEL,
            fallback_model=DEFAULT_OLLAMA_BACKUP_MODEL,
            max_primary_attempts=ollama_config.max_primary_attempts,
            llm_provider="ollama",
            ollama_host=ollama_config.ollama_host,
        )

    return env_config


def _img_data_uri(path: Path) -> str:
    """Return a base64 data URI for a local PNG (empty string if missing)."""
    import base64

    if not path.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def apply_app_styles() -> None:
    logo_uri = _img_data_uri(WUERTH_LOGO_PATH)
    st.markdown(
        f"""
        <style>
        p code,
        li code {{
            white-space: nowrap;
            word-break: keep-all;
            overflow-wrap: normal;
        }}

        /* --- Würth branding --- */
        /* Remove the chat pictograms (avatars) next to question and model/answer. */
        [data-testid^="stChatMessageAvatar"],
        [data-testid^="chatAvatarIcon-"] {{
            display: none !important;
        }}
        /* Headings and titles in Würth anthracite, with a red accent for the main title. */
        h1, h2, h3 {{
            color: {WUERTH_TEXT};
        }}
        /* Active tab underline / labels in Würth red. */
        .stTabs [aria-selected="true"] {{
            color: {WUERTH_RED} !important;
        }}
        .stTabs [data-baseweb="tab-highlight"] {{
            background-color: {WUERTH_RED} !important;
        }}
        /* Links in Würth red. */
        a, a:visited {{
            color: {WUERTH_RED};
        }}
        /* Metric values (e.g. "Modell", "Status") in Würth red. */
        [data-testid="stMetricValue"] {{
            color: {WUERTH_RED};
        }}
        /* Expander headers (Ablaufschritte, SQL-Anweisung) get a subtle red accent. */
        [data-testid="stExpander"] summary:hover {{
            color: {WUERTH_RED};
        }}
        /* Primary buttons in Würth red. */
        .stButton > button[kind="primary"],
        .stDownloadButton > button[kind="primary"] {{
            background-color: {WUERTH_RED};
            border-color: {WUERTH_RED};
            color: #FFFFFF;
        }}

        /* --- Würth-branded chat input bar (bottom) --- */
        /* No red bar: keep the default background, just make room on the left for the
           Würth logo card shown next to the input. */
        /* Reserve space on the left of the input bar for the Würth logo card. */
        [data-testid="stBottomBlockContainer"] {{
            padding-left: 150px;
        }}
        /* The actual input box: white with a neutral light border (only the send
           button is red). */
        [data-testid="stChatInput"] {{
            position: relative;
            overflow: visible;
            border: 1px solid #D0D0D0;
            border-radius: 12px;
            background-color: #FFFFFF;
        }}
        /* Würth logo card, anchored to and vertically centred on the input bar itself
           so it sits exactly at the same height as the chat input. */
        [data-testid="stChatInput"]::before {{
            content: "";
            position: absolute;
            left: -134px;
            top: 50%;
            transform: translateY(-50%);
            width: 116px;
            height: 46px;
            background: #FFFFFF url("{logo_uri}") no-repeat center;
            background-size: 96px auto;
            border: 1px solid #D9D9D9;
            border-radius: 8px;
        }}
        [data-testid="stChatInput"] textarea {{
            color: {WUERTH_TEXT};
        }}
        /* Solid red send button with a white arrow. */
        [data-testid="stChatInputSubmitButton"] {{
            background-color: {WUERTH_RED};
            border-radius: 8px;
        }}
        [data-testid="stChatInputSubmitButton"] svg {{
            fill: #FFFFFF;
        }}
        [data-testid="stChatInputSubmitButton"]:hover {{
            background-color: #A30000;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> tuple[str, SQLAgentConfig]:
    with st.sidebar:
        st.header("Navigation")
        page = st.radio(
            "Ansicht",
            [PAGE_CHAT, PAGE_GOLDEN, PAGE_MEMORY, PAGE_TEMPLATES],
            label_visibility="collapsed",
        )

        _render_chat_sidebar_css()
        st.header("Chats")
        if st.button("+ Neuer Chat", use_container_width=True):
            new_id = _new_chat_id()
            st.session_state.chats[new_id] = _make_chat()
            st.session_state.active_chat_id = new_id
            st.rerun()
        for chat_id, chat in list(st.session_state.chats.items()):
            is_editing = st.session_state.editing_chat_id == chat_id
            confirming = st.session_state.confirm_delete_chat_id == chat_id

            if is_editing:
                new_name = st.text_input(
                    "Name",
                    value=chat["name"],
                    key=f"rename_input_{chat_id}",
                    label_visibility="collapsed",
                )
                c1, c2 = st.columns(2)
                if c1.button("Speichern", key=f"confirm_{chat_id}", use_container_width=True):
                    chat["name"] = new_name.strip() or chat["name"]
                    st.session_state.editing_chat_id = None
                    st.rerun()
                if c2.button("Abbrechen", key=f"cancel_{chat_id}", use_container_width=True):
                    st.session_state.editing_chat_id = None
                    st.rerun()
            elif confirming:
                st.warning(f"„{chat['name'] or 'Neuer Chat'}\" löschen?")
                c1, c2 = st.columns(2)
                if c1.button("Ja, löschen", key=f"confirm_del_{chat_id}", type="primary", use_container_width=True):
                    clear_presentation_exports_for_chat(chat_id)
                    del st.session_state.chats[chat_id]
                    if st.session_state.active_chat_id == chat_id:
                        st.session_state.active_chat_id = next(iter(st.session_state.chats))
                    st.session_state.confirm_delete_chat_id = None
                    st.session_state.editing_chat_id = None
                    st.rerun()
                if c2.button("Abbrechen", key=f"cancel_del_{chat_id}", use_container_width=True):
                    st.session_state.confirm_delete_chat_id = None
                    st.rerun()
            else:
                label = chat["name"] or "Neuer Chat"
                cols = st.columns([5, 1])
                if cols[0].button(label, key=f"select_{chat_id}", use_container_width=True):
                    st.session_state.active_chat_id = chat_id
                    st.rerun()
                with cols[1].popover(" ", use_container_width=True):
                    if st.button("Umbenennen", key=f"edit_{chat_id}", use_container_width=True):
                        st.session_state.editing_chat_id = chat_id
                        st.rerun()
                    if len(st.session_state.chats) > 1:
                        if st.button("Löschen", key=f"del_{chat_id}", use_container_width=True):
                            st.session_state.confirm_delete_chat_id = chat_id
                            st.rerun()

        st.header("Konfiguration")
        scenario_ids = [scenario.scenario_id for scenario in get_scenario_options()]
        default_scenario_id = st.session_state.get("data_scenario", get_active_scenario_id())
        default_index = scenario_ids.index(default_scenario_id) if default_scenario_id in scenario_ids else 0
        selected_scenario_id = st.selectbox(
            "Data scenario",
            scenario_ids,
            index=default_index,
            key="data_scenario_selector",
            format_func=lambda scenario_id: SCENARIOS[scenario_id].label,
        )
        previous_scenario_id = st.session_state.get("data_scenario")
        st.session_state.data_scenario = selected_scenario_id
        if previous_scenario_id and previous_scenario_id != selected_scenario_id:
            first_id = _new_chat_id()
            st.session_state.chats = {first_id: _make_chat()}
            st.session_state.active_chat_id = first_id
            st.session_state.confirm_delete_chat_id = None
            st.session_state.editing_chat_id = None
            st.session_state.last_golden_run_id = ""
            st.session_state.last_selected_question_ids = []
            st.session_state.last_failed_question_ids = []
            st.session_state.last_errored_question_ids = []
            st.session_state.last_golden_result_summary = {}
            st.session_state.last_golden_results = []
            st.session_state.presentation_exports = {}
        set_active_scenario_id(selected_scenario_id)
        initialize_memory_files()
        scenario = get_active_scenario()

        config = build_streamlit_llm_config()
        try:
            backend_metadata = get_active_backend_metadata()
        except Exception as error:
            backend_metadata = {
                **scenario.safe_metadata,
                "auth_type": "",
            }
            st.error(f"Datenbank-Backend ist nicht korrekt konfiguriert: {error}")

        st.write(f"Active data scenario: `{backend_metadata.get('scenario_label', scenario.label)}`")
        st.write(f"Backend: `{backend_metadata.get('backend_display_name', backend_metadata.get('backend_name', ''))}`")
        st.write(f"SQL-Dialekt: `{backend_metadata.get('sql_dialect', '')}`")
        st.write(f"Semantic layer: `{backend_metadata.get('semantic_layer', scenario.semantic_layer_filename)}`")
        if backend_metadata.get("auth_type"):
            st.write(f"Databricks-Auth-Modus: `{backend_metadata.get('auth_type', '')}`")
        st.write(f"LLM-Anbieter: `{config.llm_provider}`")
        st.write(f"Primäres Modell: `{config.primary_model}`")
        st.write(f"Fallback-Modell: `{config.fallback_model}`")
        st.write(f"Max. primäre Versuche: `{config.max_primary_attempts}`")
        if config.llm_provider == "anthropic":
            if anthropic_api_key_is_placeholder():
                st.warning(
                    "ANTHROPIC_API_KEY ist nicht gesetzt. Trage deinen Key in `.env` ein, "
                    "bevor Fragen gestellt werden."
                )
        elif config.llm_provider == "gemini":
            if gemini_api_key_is_placeholder():
                st.warning(
                    "GEMINI_API_KEY ist noch auf `key` gesetzt. Ersetze den Wert in `.env` "
                    "durch einen echten Gemini API Key, bevor Fragen gestellt werden."
                )
        else:
            st.write(f"Ollama-Host: `{config.ollama_host}`")

        st.header("Erlaubte Tabellen")
        allowed_tables = backend_metadata.get("allowed_tables") or list(scenario.allowed_tables)
        for table in allowed_tables:
            st.write(f"- `{table}`")

    return page, config


def write_feedback(record: dict, rating: str, comment: str) -> str:
    return log_feedback(
        run_id=record.get("run_id", ""),
        rating=rating,
        comment=comment,
        user_question=record.get("user_question", ""),
        final_answer=record.get("final_answer", ""),
        generated_sql=record.get("generated_sql", ""),
        selected_model=record.get("selected_model", ""),
        fallback_used=bool(record.get("fallback_used", False)),
        user_rating=rating,
        user_comment=comment,
    )


def retry_with_comment(record: dict, index: int, comment: str, config: SQLAgentConfig) -> None:
    if not comment.strip():
        st.warning("Bitte zuerst eine kurze Korrektur eingeben.")
        return

    _steps_log: list[dict] = []
    write_feedback(record, "neutral", f"retry_with_comment: {comment}")
    with st.status("Wiederhole den Lauf mit deiner Korrektur...", expanded=True) as _retry_status:
        def _retry_on_step(node: str, duration: float, metadata: dict) -> None:
            symbol = _STEP_SYMBOLS.get(node, "·")
            label = _STEP_LABELS.get(node, node)
            _retry_status.write(f"{symbol} {label}   {duration:.1f}s")
            if node == "run_router":
                intent = metadata.get("intent", "")
                tier = metadata.get("complexity_tier", "")
                reason = metadata.get("complexity_reason", "")
                if intent:
                    _retry_status.write(f"  Intent: {intent}")
                if tier or reason:
                    _retry_status.write(f"  Complexity: {tier} – {reason}")
            _steps_log.append({"node": node, "label": label, "symbol": symbol,
                                "duration": duration, "metadata": metadata})

        corrected_record = run_orchestrator(
            record.get("user_question", ""),
            config=config,
            previous_failed_sql=record.get("generated_sql", ""),
            previous_sql_error=record.get("sql_error", ""),
            previous_final_answer=record.get("final_answer", ""),
            user_correction=comment.strip(),
            step_callback=_retry_on_step,
        )
        _retry_status.update(label="Fertig ✓", state="complete", expanded=False)
    corrected_record["agent_step_log"] = _steps_log
    active_history()[index] = corrected_record
    st.rerun()


def rerun_with_fallback(
    record: dict,
    index: int,
    config: SQLAgentConfig,
    comment: str = "",
) -> None:
    _steps_log: list[dict] = []
    write_feedback(record, "neutral", f"fallback_requested: {comment}")
    with st.status("Wiederhole den Lauf mit dem Fallback-Modell...", expanded=True) as _fb_status:
        def _fb_on_step(node: str, duration: float, metadata: dict) -> None:
            symbol = _STEP_SYMBOLS.get(node, "·")
            label = _STEP_LABELS.get(node, node)
            _fb_status.write(f"{symbol} {label}   {duration:.1f}s")
            _steps_log.append({"node": node, "label": label, "symbol": symbol,
                                "duration": duration, "metadata": metadata})

        fallback_record = run_orchestrator(
            record.get("user_question", ""),
            config=config,
            force_fallback=True,
            previous_failed_sql=record.get("generated_sql", ""),
            previous_sql_error=record.get("sql_error", ""),
            previous_final_answer=record.get("final_answer", ""),
            user_correction=comment.strip(),
            step_callback=_fb_on_step,
        )
        _fb_status.update(label="Fertig ✓", state="complete", expanded=False)
    fallback_record["agent_step_log"] = _steps_log
    active_history()[index] = fallback_record
    st.rerun()


def render_metadata(record: dict) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Modell", record.get("model_used") or record.get("selected_model", ""))
    col2.metric("Versuche", int(record.get("total_attempts", 0)))
    col3.metric("Fallback", "ja" if record.get("fallback_used") else "nein")
    col4.metric("Status", format_status(record.get("result_status", "")))


def can_create_template_candidate(record: dict) -> bool:
    return (
        record.get("run_context", "chat") == "chat"
        and bool(record.get("enable_memory_candidate_generation", True))
        and bool(record.get("validation_success", record.get("sql_valid")))
        and bool(record.get("execution_success"))
        and bool(record.get("final_sql") or record.get("generated_sql"))
        and bool(record.get("question") or record.get("user_question"))
    )


def render_candidate_creation(record: dict, index: int) -> None:
    if not can_create_template_candidate(record):
        return

    st.subheader("Memory")
    if st.button("YAML Template Vorschlag erstellen", key=f"create_candidate_{index}"):
        try:
            _candidate, created, message = create_candidate_from_run(record)
        except MemoryStoreError as error:
            st.error(str(error))
            return

        if created:
            st.success("YAML Template Vorschlag wurde erstellt.")
        else:
            st.info(message)


def format_filter_value(value: object) -> str:
    mapping = {
        "all": "alle",
        "pending_review": "wartet auf Prüfung",
        "needs_changes": "Überarbeitung nötig",
        "rejected": "verworfen",
        "approved": "freigegeben",
        "disabled": "deaktiviert",
        "solution_template": "Lösungstemplate",
    }
    return mapping.get(str(value), str(value))


def dump_yaml(data: object) -> str:
    return yaml.safe_dump(data or {}, sort_keys=False)


def parse_yaml_editor(text: str) -> dict | None:
    try:
        parsed = yaml.safe_load(text) or {}
    except yaml.YAMLError as error:
        st.error(f"YAML ist ungültig: {error}")
        return None
    if not isinstance(parsed, dict):
        st.error("YAML muss ein Mapping sein.")
        return None
    return parsed


def candidate_editor_is_stale(candidate_id: str, candidate: dict) -> bool:
    loaded_key = f"candidate_loaded_updated_at_{candidate_id}"
    loaded_updated_at = st.session_state.get(loaded_key)
    current_updated_at = candidate.get("updated_at", "")
    return bool(loaded_updated_at and loaded_updated_at != current_updated_at)


def show_validation_result(errors: list[str]) -> None:
    if not errors:
        st.success("YAML ist gültig.")
        return
    st.error("YAML ist ungültig.")
    for error in errors:
        st.write(f"- {error}")


def candidate_matches_filters(
    candidate: dict,
    *,
    status_filter: str,
    type_filter: str,
    table_filter: str,
    search_text: str,
) -> bool:
    if status_filter != "all" and candidate.get("status") != status_filter:
        return False
    if type_filter != "all" and candidate.get("candidate_type") != type_filter:
        return False
    if table_filter != "all" and table_filter not in parse_source_tables(candidate.get("source_tables")):
        return False

    if search_text:
        proposed_template = candidate.get("proposed_template", {})
        searchable = " ".join(
            [
                str(candidate.get("candidate_id", "")),
                str(candidate.get("run_id", "")),
                str(candidate.get("original_question", "")),
                str(proposed_template.get("intent", "")) if isinstance(proposed_template, dict) else "",
            ]
        ).lower()
        if search_text.lower() not in searchable:
            return False

    return True


def render_candidate_details(candidate: dict) -> None:
    st.subheader("Vorschlag")
    col1, col2, col3, col4 = st.columns(4)
    col1.write(f"candidate_id: `{candidate.get('candidate_id', '')}`")
    col2.write(f"run_id: `{candidate.get('run_id', '')}`")
    col3.write(f"Status: `{format_filter_value(candidate.get('status', ''))}`")
    col4.write(f"Typ: `{format_filter_value(candidate.get('candidate_type', ''))}`")
    st.write(f"Szenario: `{candidate.get('scenario', '')}`")
    st.write(f"Dataset: `{candidate.get('dataset_id', '')}`")
    st.write(f"Erstellt am: `{candidate.get('created_at', '')}`")
    st.write(f"Aktualisiert am: `{candidate.get('updated_at', '')}`")

    st.subheader("Originalfrage")
    st.write(candidate.get("original_question", ""))

    st.subheader("Antwort")
    st.write(candidate.get("generated_answer", ""))

    sql_col1, sql_col2 = st.columns(2)
    with sql_col1:
        st.subheader("Generiertes SQL")
        st.code(candidate.get("generated_sql", "") or "(leer)", language="sql")
    with sql_col2:
        st.subheader("Finales SQL")
        st.code(candidate.get("final_sql", "") or "(leer)", language="sql")

    st.subheader("Metadaten")
    metadata = {
        "Quelltabellen": candidate.get("source_tables", []),
        "Primäres Modell": candidate.get("model_primary"),
        "Verwendetes Modell": candidate.get("model_used"),
        "Fallback verwendet": candidate.get("fallback_used"),
        "Validierung erfolgreich": candidate.get("validation_success"),
        "Ausführung erfolgreich": candidate.get("execution_success"),
        "Fehlertyp": candidate.get("error_type"),
        "Fehlermeldung": candidate.get("error_message"),
        "Zeilenanzahl": candidate.get("row_count"),
    }
    st.json(metadata, expanded=False)

    feedback = candidate.get("feedback", {})
    st.subheader("Rückmeldung")
    st.write(f"Bewertung: `{feedback.get('rating') if isinstance(feedback, dict) else ''}`")
    st.write(feedback.get("comment") if isinstance(feedback, dict) else "")


def render_memory_approval_result(result: dict) -> None:
    if not result:
        return

    template = result.get("template", {}) if isinstance(result.get("template"), dict) else {}
    smoke_test = result.get("smoke_test", {}) if isinstance(result.get("smoke_test"), dict) else {}
    st.subheader("Letzter VSM-Freigabecheck")
    meta1, meta2, meta3, meta4 = st.columns(4)
    meta1.write(f"Template: `{template.get('id', '')}`")
    meta2.write(f"Szenario: `{template.get('scenario', smoke_test.get('scenario', ''))}`")
    meta3.write(f"Index-Templates: `{smoke_test.get('indexed_template_count', 0)}`")
    meta4.write(f"Prompt-Guidance: `{format_yes_no(smoke_test.get('would_inject_prompt_guidance', False))}`")
    st.write(f"Approved YAML: `{result.get('template_path', '')}`")
    st.write(f"Master Index: `{smoke_test.get('index_path', result.get('index_path', ''))}`")
    st.write(
        "Retrieval: "
        f"`enabled={smoke_test.get('enabled', False)}` "
        f"`method={smoke_test.get('method', '')}` "
        f"`no_match_reason={smoke_test.get('no_match_reason', '') or '-'}` "
        f"`ambiguous={smoke_test.get('ambiguous', False)}`"
    )

    matches = smoke_test.get("top_matches", [])
    if matches:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "template_id": match.get("template_id", ""),
                        "score": match.get("score", ""),
                        "matched_terms": ", ".join(match.get("matched_terms", []) or []),
                        "threshold": format_yes_no(match.get("passed_threshold", False)),
                    }
                    for match in matches
                    if isinstance(match, dict)
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Der Smoke-Test hat keinen Treffer oberhalb des Schwellenwerts gefunden.")


def render_memory_review_view() -> None:
    st.title("Memory-Prüfung")
    render_flash()
    active_scenario = get_active_scenario()
    st.caption(
        f"Aktives Szenario: `{active_scenario.scenario_id}`. "
        "Produktives Ziel: scenario-scoped `approved/*.yaml` plus `master_index.yaml`."
    )

    last_result = st.session_state.get("last_memory_approval_result")
    if isinstance(last_result, dict):
        smoke = last_result.get("smoke_test", {}) if isinstance(last_result.get("smoke_test"), dict) else {}
        if smoke.get("scenario") == active_scenario.scenario_id:
            render_memory_approval_result(last_result)

    try:
        all_candidates = load_candidates()
    except MemoryStoreError as error:
        st.error(str(error))
        return

    missing_scenario_count = sum(1 for candidate in all_candidates if not candidate.get("scenario"))
    other_scenario_count = sum(
        1
        for candidate in all_candidates
        if candidate.get("scenario") and candidate.get("scenario") != active_scenario.scenario_id
    )
    if missing_scenario_count:
        st.warning(
            f"{missing_scenario_count} Legacy-Kandidat(en) ohne Szenario werden nicht angezeigt. "
            "Bitte nur über eine explizite Migration einem Szenario zuordnen."
        )
    if other_scenario_count:
        st.info(
            f"{other_scenario_count} Kandidat(en) aus anderen Szenarien sind für dieses Szenario ausgeblendet."
        )

    candidates = [
        candidate
        for candidate in all_candidates
        if candidate.get("scenario") == active_scenario.scenario_id
    ]

    if not candidates:
        st.info("Keine Memory-Vorschläge für das aktive Szenario vorhanden.")
        return

    statuses = ["all", "pending_review", "needs_changes", "rejected", "approved"]
    candidate_types = ["all", *sorted({str(candidate.get("candidate_type", "")) for candidate in candidates if candidate.get("candidate_type")})]
    source_tables = sorted({table for candidate in candidates for table in parse_source_tables(candidate.get("source_tables"))})

    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        status_filter = st.selectbox(
            "Status",
            statuses,
            key="candidate_status_filter",
            format_func=format_filter_value,
        )
    with filter_col2:
        type_filter = st.selectbox(
            "Typ",
            candidate_types,
            key="candidate_type_filter",
            format_func=format_filter_value,
        )
    with filter_col3:
        table_filter = st.selectbox(
            "Quelltabelle",
            ["all", *source_tables],
            key="candidate_table_filter",
            format_func=format_filter_value,
        )
    with filter_col4:
        search_text = st.text_input("Suche", key="candidate_search")

    filtered_candidates = [
        candidate
        for candidate in candidates
        if candidate_matches_filters(
            candidate,
            status_filter=status_filter,
            type_filter=type_filter,
            table_filter=table_filter,
            search_text=search_text,
        )
    ]

    if not filtered_candidates:
        st.info("Keine Vorschläge für diese Filter.")
        return

    table_rows = []
    for candidate in filtered_candidates:
        proposed_template = candidate.get("proposed_template", {})
        table_rows.append(
            {
                "candidate_id": candidate.get("candidate_id", ""),
                "run_id": candidate.get("run_id", ""),
                "Szenario": candidate.get("scenario", ""),
                "Status": format_filter_value(candidate.get("status", "")),
                "Typ": format_filter_value(candidate.get("candidate_type", "")),
                "Intent": proposed_template.get("intent", "") if isinstance(proposed_template, dict) else "",
                "Quelltabellen": ", ".join(parse_source_tables(candidate.get("source_tables"))),
                "Erstellt am": candidate.get("created_at", ""),
                "Aktualisiert am": candidate.get("updated_at", ""),
            }
        )
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    candidate_by_id = {candidate.get("candidate_id"): candidate for candidate in filtered_candidates}
    if st.session_state.get("selected_candidate_id") not in candidate_by_id:
        st.session_state.pop("selected_candidate_id", None)
    selected_candidate_id = st.selectbox(
        "Vorschlag auswählen",
        list(candidate_by_id.keys()),
        key="selected_candidate_id",
    )
    candidate = candidate_by_id[selected_candidate_id]
    candidate_id = str(candidate.get("candidate_id", ""))
    status = str(candidate.get("status", ""))
    editing_disabled = status in {"approved", "rejected"}

    render_candidate_details(candidate)

    st.subheader("Vorgeschlagenes Template-YAML")
    yaml_key = f"candidate_yaml_{candidate_id}"
    loaded_key = f"candidate_loaded_updated_at_{candidate_id}"
    if yaml_key not in st.session_state:
        st.session_state[yaml_key] = dump_yaml(candidate.get("proposed_template", {}))
        st.session_state[loaded_key] = candidate.get("updated_at", "")

    if st.button("Neu laden", key=f"reload_{candidate_id}"):
        st.session_state[yaml_key] = dump_yaml(candidate.get("proposed_template", {}))
        st.session_state[loaded_key] = candidate.get("updated_at", "")
        st.rerun()

    edited_yaml = st.text_area(
        "proposed_template",
        key=yaml_key,
        height=360,
        disabled=editing_disabled,
        label_visibility="collapsed",
    )
    st.caption(
        "Bei Freigabe wird daraus ein VSM-Template mit `status=approved` und "
        "`is_active=true` unter dem aktiven Szenario erzeugt. `source_sql` bleibt Prompt-Guidance."
    )

    review_comment = st.text_area("Review-Kommentar", key=f"review_comment_{candidate_id}")
    rejection_reason = st.text_area("Ablehnungsgrund", key=f"rejection_reason_{candidate_id}")

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        if st.button(
            "Änderungen speichern",
            key=f"save_{candidate_id}",
            disabled=editing_disabled,
        ):
            if candidate_editor_is_stale(candidate_id, candidate):
                st.warning("Dieser Vorschlag wurde seit dem Laden geändert. Bitte zuerst neu laden.")
                parsed = None
            else:
                parsed = parse_yaml_editor(edited_yaml)
            if parsed is not None:
                try:
                    update_candidate_proposed_template(candidate_id, parsed)
                except MemoryStoreError as error:
                    st.error(str(error))
                else:
                    st.session_state[loaded_key] = ""
                    set_flash("success", "Änderungen wurden gespeichert.")
                    st.rerun()

    with col2:
        if st.button("YAML prüfen", key=f"validate_{candidate_id}"):
            parsed = parse_yaml_editor(edited_yaml)
            if parsed is not None:
                errors = validate_proposed_template(parsed)
                audit_candidate_validation(candidate_id, valid=not errors, error_count=len(errors))
                show_validation_result(errors)

    with col3:
        can_approve = status in {"pending_review", "needs_changes"}
        if st.button("Template freigeben", key=f"approve_{candidate_id}", disabled=not can_approve):
            if candidate_editor_is_stale(candidate_id, candidate):
                st.warning("Dieser Vorschlag wurde seit dem Laden geändert. Bitte zuerst neu laden.")
                parsed = None
            else:
                parsed = parse_yaml_editor(edited_yaml)
            if parsed is not None:
                errors = validate_proposed_template(parsed)
                if errors:
                    show_validation_result(errors)
                else:
                    try:
                        result = approve_candidate_to_vsm(
                            candidate_id,
                            parsed,
                            scenario=active_scenario.scenario_id,
                        )
                    except (MemoryStoreError, MemoryLifecycleError) as error:
                        st.warning(str(error))
                    else:
                        st.session_state["last_memory_approval_result"] = result
                        template = result.get("template", {}) if isinstance(result.get("template"), dict) else {}
                        set_flash(
                            "success",
                            f"Template `{template.get('id', '')}` wurde als VSM-Memory freigegeben und indexiert.",
                        )
                        st.rerun()

    with col4:
        can_reject = status in {"pending_review", "needs_changes"}
        if st.button("Vorschlag verwerfen", key=f"reject_{candidate_id}", disabled=not can_reject):
            if not rejection_reason.strip():
                st.warning("Bitte Ablehnungsgrund angeben.")
            else:
                try:
                    reject_candidate(candidate_id, rejection_reason)
                except MemoryStoreError as error:
                    st.error(str(error))
                else:
                    set_flash("success", "Vorschlag wurde verworfen.")
                    st.rerun()

    with col5:
        can_mark_needs_changes = status == "pending_review"
        if st.button(
            "Überarbeitung nötig",
            key=f"needs_changes_{candidate_id}",
            disabled=not can_mark_needs_changes,
        ):
            try:
                mark_candidate_needs_changes(candidate_id, review_comment)
            except MemoryStoreError as error:
                st.error(str(error))
            else:
                set_flash("success", "Vorschlag wurde als Überarbeitung nötig markiert.")
                st.rerun()


def render_approved_templates_view() -> None:
    st.title("Freigegebene Templates")
    render_flash()
    active_scenario = get_active_scenario()
    st.caption(
        f"Aktives Szenario: `{active_scenario.scenario_id}`. "
        "Diese Ansicht zeigt die runtime-aktive VSM-Quelle `memory/<scenario>/approved/*.yaml`."
    )

    try:
        records = load_approved_template_records(active_scenario.scenario_id)
    except (MemoryStoreError, MemoryLifecycleError) as error:
        st.error(str(error))
        return

    try:
        legacy_templates = load_templates()
    except MemoryStoreError:
        legacy_templates = []
    if legacy_templates:
        st.info(
            f"Legacy `solution_templates.yaml` enthält {len(legacy_templates)} Template(s). "
            "Diese Datei ist nicht mehr die produktive VSM-Runtime-Quelle."
        )

    if not records:
        st.info("Keine freigegebenen VSM-Templates für das aktive Szenario vorhanden.")
        return

    table_rows = [
        {
            "template_id": record["template"].get("id", ""),
            "Runtime-retrievable": format_yes_no(record.get("is_runtime_retrievable", False)),
            "Schema gültig": format_yes_no(record.get("is_valid", False)),
            "Status": format_filter_value(record["template"].get("status", "")),
            "Aktiv": format_yes_no(record["template"].get("is_active", False)),
            "Titel": record["template"].get("title", ""),
            "Intent": record["template"].get("intent", ""),
            "Benötigte Tabellen": ", ".join(parse_source_tables(record["template"].get("required_tables"))),
            "Datei": record.get("path", ""),
            "Freigegeben am": record["template"].get("approved_at", ""),
            "Freigegeben von": record["template"].get("approved_by", ""),
        }
        for record in records
    ]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    template_by_id = {
        record["template"].get("id"): record
        for record in records
        if isinstance(record.get("template"), dict)
    }
    if st.session_state.get("selected_template_id") not in template_by_id:
        st.session_state.pop("selected_template_id", None)
    selected_template_id = st.selectbox(
        "Template auswählen",
        list(template_by_id.keys()),
        key="selected_template_id",
    )
    selected_record = template_by_id[selected_template_id]
    template = selected_record["template"]

    st.subheader("Details")
    st.write(f"template_id: `{template.get('id', '')}`")
    st.write(f"Szenario: `{template.get('scenario', '')}`")
    st.write(f"Datei: `{selected_record.get('path', '')}`")
    st.write(f"Status: `{format_filter_value(template.get('status', ''))}`")
    st.write(f"Aktiv: `{format_yes_no(template.get('is_active', False))}`")
    st.write(f"Runtime-retrievable: `{format_yes_no(selected_record.get('is_runtime_retrievable', False))}`")
    if not selected_record.get("is_valid", False):
        st.error("Dieses Template erfüllt die approved-template-Schema-Validierung nicht.")
        st.json(selected_record.get("validation_errors", []), expanded=False)
    st.write(f"Intent: {template.get('intent', '')}")
    st.write("Auslösephrasen")
    st.json(template.get("trigger_phrases", []), expanded=False)
    st.write("Searchable Terms")
    st.json(template.get("searchable_terms", []), expanded=False)
    st.write("Synonyme")
    st.json(template.get("synonyms", {}), expanded=False)
    st.write("Benötigte Spalten")
    st.json(template.get("required_columns", []), expanded=False)
    st.write("Business Rules")
    st.json(template.get("business_rules", []), expanded=False)
    st.write("Do not use when")
    st.json(template.get("do_not_use_when", []), expanded=False)
    st.write("Validation Checks")
    st.json(template.get("validation_checks", []), expanded=False)
    st.subheader("SQL Pattern")
    st.write(template.get("sql_pattern", "") or "(leer)")
    st.subheader("Source SQL")
    st.caption("Nur Prompt-Guidance; wird nicht ausgeführt und ersetzt keine SQL-Validierung.")
    st.code(template.get("source_sql", "") or "(leer)", language="sql")


def golden_checkbox_key(question_id: str) -> str:
    return f"golden_select_{question_id}"


def initialize_golden_question_state(questions: list[dict]) -> None:
    for question in questions:
        st.session_state.setdefault(golden_checkbox_key(question["question_id"]), False)


def selected_golden_question_ids(questions: list[dict]) -> list[str]:
    return [
        question["question_id"]
        for question in questions
        if st.session_state.get(golden_checkbox_key(question["question_id"]), False)
    ]


def ordered_subset(question_ids: list[str], questions: list[dict]) -> list[str]:
    requested = set(question_ids)
    return [question["question_id"] for question in questions if question["question_id"] in requested]


def run_golden_question_ids(
    question_ids: list[str],
    *,
    use_approved_memory: bool,
    runtime_mode: GoldenRuntimeMode,
    config: SQLAgentConfig,
) -> None:
    if not question_ids:
        st.warning("Bitte zuerst mindestens eine Golden-Testfrage auswählen.")
        return

    with st.spinner(f"Golden Tests werden gegen {get_active_scenario().label} ausgeführt..."):
        batch_run_id, results, summary = run_golden_tests(
            question_ids,
            use_approved_memory=use_approved_memory,
            runtime_mode=runtime_mode,
            config=config,
        )

    st.session_state.last_golden_run_id = batch_run_id
    st.session_state.last_selected_question_ids = question_ids
    st.session_state.last_failed_question_ids = [
        result["question_id"] for result in results if result.get("status") == "failed"
    ]
    st.session_state.last_errored_question_ids = [
        result["question_id"] for result in results if result.get("status") == "error"
    ]
    st.session_state.last_golden_result_summary = summary
    st.session_state.last_golden_results = results


def preview_to_dataframe(preview: dict) -> pd.DataFrame:
    return pd.DataFrame(preview.get("rows", []), columns=preview.get("columns", []))


def format_status(value: object) -> str:
    mapping = {
        "passed": "bestanden",
        "failed": "fehlgeschlagen",
        "error": "Fehler",
        "first attempt success": "im ersten Versuch erfolgreich",
        "repaired success": "nach Reparatur erfolgreich",
        "fallback success": "mit Fallback erfolgreich",
    }
    return mapping.get(str(value), str(value))


def format_yes_no(value: object) -> str:
    return "ja" if bool(value) else "nein"


def format_failure_reason(value: object) -> str:
    mapping = {
        "output_mismatch": "Ausgabe weicht ab",
        "sql_validation": "SQL-Validierung fehlgeschlagen",
        "execution_error": "Ausführungsfehler",
        "reference_sql_validation_error": "Referenz-SQL ist ungültig",
        "reference_sql_execution_error": "Referenz-SQL konnte nicht ausgeführt werden",
        "agent_error": "Agentenfehler",
        "unexpected_error": "Unerwarteter Fehler",
        "shape mismatch": "Form der Ausgabe weicht ab",
        "column count mismatch": "Spaltenanzahl weicht ab",
        "row count mismatch": "Zeilenanzahl weicht ab",
        "column name mismatch": "Spaltennamen weichen ab",
        "row values differ ignoring order": "Zeilenwerte weichen ab",
        "row values differ with order enforced": "Zeilenwerte oder Sortierung weichen ab",
        "duplicate row count mismatch": "Anzahl doppelter Zeilen weicht ab",
        "numeric value outside tolerance": "Numerischer Wert außerhalb der Toleranz",
        "null mismatch": "NULL-Wert weicht ab",
        "missing rows": "fehlende Zeilen",
        "unexpected rows": "unerwartete Zeilen",
        "value mismatch": "Wertabweichung",
        "column mismatch": "Spaltenabweichung",
        "order mismatch": "Sortierung weicht ab",
    }
    text = str(value or "")
    for english, german in mapping.items():
        text = text.replace(english, german)
    return text


def localize_diff_summary(diff_summary: dict) -> dict:
    if not isinstance(diff_summary, dict):
        return {}
    localized = {
        "bestanden": diff_summary.get("passed", False),
        "Probleme": [
            format_failure_reason(issue)
            for issue in diff_summary.get("issues", [])
        ],
    }
    for source_key, target_key in [
        ("shape_mismatch", "Formabweichung"),
        ("column_count_mismatch", "Spaltenanzahlabweichung"),
        ("row_count_mismatch", "Zeilenanzahlabweichung"),
        ("column_name_mismatch", "Spaltennamenabweichung"),
        ("column_mismatch", "Spaltenabweichung"),
        ("value_mismatch", "Wertabweichung"),
        ("missing_rows", "fehlende Zeilen"),
        ("unexpected_rows", "unerwartete Zeilen"),
    ]:
        if source_key in diff_summary:
            localized[target_key] = diff_summary[source_key]
    localized["reihenfolge_sensitiv"] = diff_summary.get("order_sensitive", False)
    localized["spaltennamen_vergleichen"] = diff_summary.get("compare_column_names", True)
    return localized


def render_golden_summary(summary: dict) -> None:
    if not summary:
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tests insgesamt", int(summary.get("total_tests_run", 0)))
    col2.metric("Bestanden", int(summary.get("passed", 0)))
    col3.metric("Bestehensquote", f"{float(summary.get('pass_rate', 0.0)) * 100:.1f}%")
    col4.metric("Ø Laufzeit", f"{float(summary.get('average_runtime', 0.0)):.2f}s")

    col5, col6, col7 = st.columns(3)
    col5.metric("Ausgabeabweichung", int(summary.get("failed_output_mismatch", 0)))
    col6.metric("SQL-Validierung", int(summary.get("failed_sql_validation", 0)))
    col7.metric("Ausführungsfehler", int(summary.get("failed_execution_error", 0)))


def render_golden_results(results: list[dict]) -> None:
    if not results:
        return

    st.subheader("Ergebnisse")
    table_rows = [
        {
            "Frage": result.get("question_id", ""),
            "Titel": result.get("title", ""),
            "Status": format_status(result.get("status", "")),
            "Runtime": result.get("runtime_mode", ""),
            "Route": result.get("route_status", ""),
            "Komplexität": result.get("complexity_tier", ""),
            "Bestanden": format_yes_no(result.get("passed", False)),
            "Laufzeit": f"{float(result.get('runtime_seconds', 0.0)):.2f}s",
            "Erwartete Zeilen": result.get("expected_row_count", 0),
            "Tatsächliche Zeilen": result.get("actual_row_count", 0),
            "Fehlergrund": format_failure_reason(result.get("failure_reason", "")),
        }
        for result in results
    ]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    for result in results:
        label = (
            f"{result.get('question_id', '')} - {result.get('title', '')} "
            f"({format_status(result.get('status', ''))})"
        )
        with st.expander(label, expanded=not result.get("passed", False)):
            meta1, meta2, meta3, meta4 = st.columns(4)
            meta1.write(f"Zeitpunkt: `{result.get('timestamp', '')}`")
            meta2.write(f"Modell: `{result.get('model_used', '')}`")
            meta3.write(f"Backend: `{result.get('backend', '')}`")
            meta4.write(f"Memory/Templates: `{format_yes_no(result.get('memory_templates_enabled', False))}`")
            runtime_meta1, runtime_meta2, runtime_meta3, runtime_meta4 = st.columns(4)
            runtime_meta1.write(f"Runtime: `{result.get('runtime_mode', '')}`")
            runtime_meta2.write(f"Szenario: `{result.get('active_scenario', '')}`")
            runtime_meta3.write(f"Route: `{result.get('route_status', '')}`")
            runtime_meta4.write(f"Komplexität: `{result.get('complexity_tier', '')}`")
            model_meta1, model_meta2, model_meta3 = st.columns(3)
            model_meta1.write(f"Ausgewählt: `{result.get('selected_model', '')}`")
            model_meta2.write(f"Fallback: `{result.get('fallback_model', '')}`")
            model_meta3.write(f"Fallback genutzt: `{format_yes_no(result.get('fallback_used', False))}`")
            memory_meta1, memory_meta2, memory_meta3, memory_meta4 = st.columns(4)
            memory_meta1.write(f"VSM Memory: `{format_yes_no(result.get('memory_retrieval_enabled', False))}`")
            memory_meta2.write(f"Methode: `{result.get('memory_retrieval_method', '')}`")
            memory_meta3.write(f"Memory-Szenario: `{result.get('memory_retrieval_scenario', '')}`")
            memory_meta4.write(f"Ambiguous: `{format_yes_no(result.get('memory_retrieval_ambiguous', False))}`")
            if result.get("memory_candidate_ids") or result.get("memory_retrieval_no_match_reason"):
                st.caption(
                    "Memory: "
                    f"candidates=`{result.get('memory_candidate_ids', '') or '-'}` "
                    f"scores=`{result.get('memory_candidate_scores', '') or '-'}` "
                    f"reason=`{result.get('memory_retrieval_no_match_reason', '') or '-'}`"
                )

            st.subheader("Frage")
            st.write(result.get("question", ""))

            sql_col1, sql_col2 = st.columns(2)
            with sql_col1:
                st.subheader("Generiertes Agenten-SQL")
                st.code(result.get("generated_agent_sql", "") or "(leer)", language="sql")
            with sql_col2:
                st.subheader("Referenz-SQL")
                st.code(result.get("reference_sql", "") or "(leer)", language="sql")

            out_col1, out_col2 = st.columns(2)
            with out_col1:
                st.subheader("Tatsächliche Ausgabevorschau")
                st.dataframe(
                    preview_to_dataframe(result.get("actual_output_preview", {})),
                    use_container_width=True,
                )
            with out_col2:
                st.subheader("Erwartete Ausgabevorschau")
                st.dataframe(
                    preview_to_dataframe(result.get("expected_output_preview", {})),
                    use_container_width=True,
                )

            st.subheader("Abweichungsübersicht")
            st.json(localize_diff_summary(result.get("diff_summary", {})), expanded=False)

            if result.get("validation_errors"):
                st.subheader("Validierungsfehler")
                st.json(result.get("validation_errors", []), expanded=False)

            if result.get("execution_errors"):
                st.subheader("Ausführungsfehler")
                execution_errors = result.get("execution_errors", {})
                if isinstance(execution_errors, dict):
                    execution_errors = {
                        format_failure_reason(key): value
                        for key, value in execution_errors.items()
                    }
                st.json(execution_errors, expanded=False)

            if result.get("agent_trace_steps"):
                st.subheader("Ablaufschritte")
                for step in result.get("agent_trace_steps", []):
                    st.markdown(f"- {step}")


def render_golden_test_mode_view(config: SQLAgentConfig) -> None:
    st.title("Golden-Testmodus")
    scenario = get_active_scenario()
    st.caption(
        f"Reiner Evaluationsmodus für {scenario.label}. Ergebnisse werden unter "
        f"{scenario.evaluation_dir.name}/golden_results.jsonl geschrieben."
    )
    render_flash()

    try:
        questions = load_golden_questions()
    except Exception as error:
        st.error(f"Golden-Testfragen konnten nicht geladen werden: {error}")
        return

    initialize_golden_question_state(questions)
    all_question_ids = [question["question_id"] for question in questions]
    use_approved_memory = st.toggle(
        "Freigegebene Memory/Templates verwenden",
        value=True,
        key="golden_use_approved_memory",
    )
    runtime_mode = st.radio(
        "Golden Runtime",
        GOLDEN_RUNTIME_MODES,
        index=GOLDEN_RUNTIME_MODES.index(DEFAULT_GOLDEN_RUNTIME_MODE),
        format_func=lambda mode: GOLDEN_RUNTIME_LABELS[mode],
        key="golden_runtime_mode",
        help=(
            "Standard ist der echte Chat-Pfad. Der direkte SQL-Agent-Modus ist nur "
            "für isoliertes Debugging und testet nicht den vollständigen Runtime-Pfad."
        ),
        horizontal=True,
    )
    st.caption(GOLDEN_RUNTIME_HELP[runtime_mode])

    if not st.session_state.last_golden_run_id:
        st.info("Es gibt noch keinen vorherigen Golden-Testlauf. Wiederholen-Buttons sind deaktiviert, bis ein Lauf abgeschlossen wurde.")

    control_cols = st.columns(6)
    with control_cols[0]:
        if st.button("Alle auswählen"):
            for question_id in all_question_ids:
                st.session_state[golden_checkbox_key(question_id)] = True
            st.rerun()
    with control_cols[1]:
        if st.button("Alle abwählen"):
            for question_id in all_question_ids:
                st.session_state[golden_checkbox_key(question_id)] = False
            st.rerun()
    with control_cols[2]:
        if st.button("Ausgewählte Golden Tests ausführen"):
            run_golden_question_ids(
                selected_golden_question_ids(questions),
                use_approved_memory=use_approved_memory,
                runtime_mode=runtime_mode,
                config=config,
            )
    with control_cols[3]:
        if st.button("Alle Golden Tests ausführen"):
            run_golden_question_ids(
                all_question_ids,
                use_approved_memory=use_approved_memory,
                runtime_mode=runtime_mode,
                config=config,
            )
    with control_cols[4]:
        if st.button(
            "Letzten Lauf wiederholen",
            disabled=not bool(st.session_state.last_selected_question_ids),
        ):
            run_golden_question_ids(
                ordered_subset(st.session_state.last_selected_question_ids, questions),
                use_approved_memory=use_approved_memory,
                runtime_mode=runtime_mode,
                config=config,
            )
    with control_cols[5]:
        failed_or_errored = ordered_subset(
            [
                *st.session_state.last_failed_question_ids,
                *st.session_state.last_errored_question_ids,
            ],
            questions,
        )
        if st.button("Nur fehlgeschlagene Tests wiederholen", disabled=not bool(failed_or_errored)):
            run_golden_question_ids(
                failed_or_errored,
                use_approved_memory=use_approved_memory,
                runtime_mode=runtime_mode,
                config=config,
            )

    selected_ids = selected_golden_question_ids(questions)
    st.write(f"Ausgewählte Fragen: `{len(selected_ids)}` von `{len(questions)}`")

    st.subheader("Fragen")
    for question in questions:
        st.checkbox(
            f"{question['question_id']} - {question.get('title', '')}",
            key=golden_checkbox_key(question["question_id"]),
        )
        st.caption(question.get("question", ""))

    render_golden_summary(st.session_state.last_golden_result_summary)
    render_golden_results(st.session_state.last_golden_results)


def _format_token_usage(token_usage: dict | None) -> str:
    if not token_usage:
        return ""
    total = int(token_usage.get("total_tokens", 0))
    input_tokens = int(token_usage.get("input_tokens", 0))
    output_tokens = int(token_usage.get("output_tokens", 0))
    if total <= 0:
        return ""
    return f"Σ Tokens: {total:,} (Input: {input_tokens:,} · Output: {output_tokens:,})".replace(",", ".")


def render_step_log(record: dict) -> None:
    step_log = record.get("agent_step_log", [])
    if not step_log:
        trace = record.get("trace_steps", [])
        if trace:
            with st.expander("Ablaufschritte", expanded=False):
                for step in trace:
                    st.markdown(f"- {step}")
                token_line = _format_token_usage(record.get("token_usage"))
                if token_line:
                    st.markdown(f"- {token_line}")
        return

    with st.expander("Ablaufschritte", expanded=False):
        for step in step_log:
            symbol = step.get("symbol", "·")
            label = step.get("label", step.get("node", ""))
            duration = step.get("duration", 0.0)
            st.markdown(
                f"{symbol}&nbsp; {label} &nbsp;&nbsp; `{duration:.1f}s`",
                unsafe_allow_html=True,
            )
            meta = step.get("metadata", {})
            if step.get("node") == "run_router":
                intent = meta.get("intent", "")
                tier = meta.get("complexity_tier", "")
                reason = meta.get("complexity_reason", "")
                if intent:
                    st.caption(f"Intent: {intent}")
                if tier or reason:
                    st.caption(f"Complexity: {tier} – {reason}")
            if step.get("node") == "select_model":
                primary = meta.get("primary", "")
                tier = meta.get("tier", "")
                if primary:
                    suffix = f" ({tier})" if tier else ""
                    st.caption(f"Modell: {primary}{suffix}")

        token_line = _format_token_usage(record.get("token_usage"))
        if token_line:
            st.markdown("---")
            st.markdown(f"**{token_line}**")


def render_record(record: dict, index: int, config: SQLAgentConfig) -> None:
    with st.chat_message("user"):
        st.caption("Frage")
        st.markdown(record.get("user_question", ""))

    with st.chat_message("assistant"):
        render_metadata(record)

        st.subheader("Antwort")
        st.write(record.get("final_answer") or "Es wurde keine Antwort erzeugt.")
        render_reporting_summary(record)

        query_result = record.get("query_result", {})
        rows = query_result.get("rows", [])
        columns = query_result.get("columns", [])
        if rows and columns:
            st.subheader("Ergebnisvorschau")
            df = result_to_dataframe(record)
            st.dataframe(df, use_container_width=True)
            render_chart_from_spec(record, df)

            col_csv, col_xlsx, col_ppt = st.columns(3)
            csv_data = df.to_csv(index=False).encode("utf-8")
            col_csv.download_button(
                "Als CSV exportieren",
                data=csv_data,
                file_name=f"ergebnis_{record.get('run_id', index)}.csv",
                mime="text/csv",
                key=f"export_csv_{index}",
                use_container_width=True,
            )
            xlsx_buffer = io.BytesIO()
            xlsx_df = df.copy()
            for col in xlsx_df.select_dtypes(include=["datetimetz"]).columns:
                xlsx_df[col] = xlsx_df[col].dt.tz_localize(None)
            xlsx_df.to_excel(xlsx_buffer, index=False)
            col_xlsx.download_button(
                "Als Excel exportieren",
                data=xlsx_buffer.getvalue(),
                file_name=f"ergebnis_{record.get('run_id', index)}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"export_xlsx_{index}",
                use_container_width=True,
            )
            render_presentation_export_controls(record, index, col_ppt)
        else:
            render_presentation_unavailable_compact(record)

        with st.expander("SQL-Anweisung", expanded=False):
            st.code(record.get("final_sql") or record.get("generated_sql", "") or "(kein SQL erzeugt)", language="sql")

        source_tables = record.get("source_tables", [])
        st.subheader("Quelltabellen")
        if source_tables:
            for table in source_tables:
                st.markdown(f"- `{table}`")
        else:
            st.write("Es wurden keine Quelltabellen erkannt.")

        if record.get("sql_error"):
            st.subheader("SQL-Fehler")
            st.error(record["sql_error"])

        render_step_log(record)

        render_reporting_audit(record)

        if record.get("user_correction"):
            st.subheader("Nutzerkorrektur")
            st.write(record["user_correction"])

        st.subheader("Rückmeldung")
        comment = st.text_area("Optionaler Kommentar", key=f"feedback_comment_{index}")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("Gute Antwort", key=f"feedback_good_{index}"):
                write_feedback(record, "thumbs_up", comment)
                st.success("Rückmeldung gespeichert.")
        with col2:
            if st.button("Schlechte Antwort", key=f"feedback_bad_{index}"):
                write_feedback(record, "thumbs_down", comment)
                st.warning("Rückmeldung gespeichert.")
        with col3:
            if st.button("Mit Kommentar wiederholen", key=f"feedback_retry_{index}"):
                retry_with_comment(record, index, comment, config)
        with col4:
            if st.button("Fallback-Modell verwenden", key=f"feedback_fallback_{index}"):
                rerun_with_fallback(record, index, config, comment)

        render_candidate_creation(record, index)


def main() -> None:
    # Top-left brand slot: prefer the combined TUM + Würth logo, fall back to Würth.
    _corner_logo = (
        str(TUM_WUERTH_LOGO_PATH) if TUM_WUERTH_LOGO_PATH.exists()
        else str(WUERTH_LOGO_PATH) if WUERTH_LOGO_PATH.exists()
        else None
    )
    _page_icon = str(WUERTH_SHIELD_PATH) if WUERTH_SHIELD_PATH.exists() else "📊"
    st.set_page_config(
        page_title="Würth Datenassistent",
        page_icon=_page_icon,
        layout="wide",
    )
    if _corner_logo:
        try:  # st.logo requires Streamlit >= 1.35; degrade gracefully otherwise.
            st.logo(_corner_logo)
        except Exception:
            pass
    apply_app_styles()
    initialize_state()
    page, config = render_sidebar()

    if page == PAGE_MEMORY:
        render_memory_review_view()
        return

    if page == PAGE_GOLDEN:
        render_golden_test_mode_view(config)
        return

    if page == PAGE_TEMPLATES:
        render_approved_templates_view()
        return

    _shield_uri = _img_data_uri(WUERTH_SHIELD_PATH)
    if _shield_uri:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:18px;margin:0 0 4px 0;">'
            f'<img src="{_shield_uri}" alt="Würth" style="height:64px;width:auto;"/>'
            f'<h1 style="margin:0;color:{WUERTH_TEXT};font-weight:700;">Würth Datenassistent</h1>'
            f"</div>",
            unsafe_allow_html=True,
        )
    else:
        st.title("Würth Datenassistent")
    scenario = get_active_scenario()
    st.caption(
        f"LangGraph-SQL-Workflow für {scenario.label} mit konfigurierbaren Primary- und Fallback-Modellen."
    )
    render_flash()

    history = active_history()
    for index, record in enumerate(history):
        render_record(record, index, config)

    context_key = f"send_context_{st.session_state.active_chat_id}"
    if history:
        st.checkbox(
            "Chatkontext mitsenden",
            key=context_key,
            help="Sendet den bisherigen Gesprächsverlauf als Kontext mit — nützlich für Folgefragen.",
        )

    question = st.chat_input(f"Stelle eine Frage zu {scenario.label}")
    if question:
        chat_context = ""
        if st.session_state.get(context_key) and history:
            chat_context = _build_chat_context(history)
        _steps_log: list[dict] = []
        with st.status("LangGraph-SQL-Workflow wird ausgeführt...", expanded=True) as status:
            def _on_step(node_name: str, duration: float, metadata: dict) -> None:
                symbol = _STEP_SYMBOLS.get(node_name, "·")
                label = _STEP_LABELS.get(node_name, node_name)
                status.write(f"{symbol} {label}   {duration:.1f}s")
                if node_name == "run_router":
                    intent = metadata.get("intent", "")
                    tier = metadata.get("complexity_tier", "")
                    reason = metadata.get("complexity_reason", "")
                    if intent:
                        status.write(f"  Intent: {intent}")
                    if tier or reason:
                        status.write(f"  Complexity: {tier} – {reason}")
                if node_name == "select_model":
                    primary = metadata.get("primary", "")
                    tier = metadata.get("tier", "")
                    if primary:
                        suffix = f" ({tier})" if tier else ""
                        status.write(f"  Modell: {primary}{suffix}")
                _steps_log.append({
                    "node": node_name,
                    "label": label,
                    "symbol": symbol,
                    "duration": duration,
                    "metadata": metadata,
                })

            record = run_orchestrator(question, config=config, chat_context=chat_context, step_callback=_on_step)
            token_line = _format_token_usage(record.get("token_usage"))
            if token_line:
                status.write(token_line)
            status.update(label="Fertig ✓", state="complete", expanded=False)
        record["agent_step_log"] = _steps_log
        record["user_question"] = question
        active_history().append(record)
        chat = st.session_state.chats[st.session_state.active_chat_id]
        if len(active_history()) == 1:
            chat["name"] = _auto_chat_name(question)
        st.rerun()


if __name__ == "__main__":
    main()
