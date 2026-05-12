from datetime import date, datetime
from decimal import Decimal
from numbers import Number

import pandas as pd
import streamlit as st
import yaml

from app.schema import TPC_H_TABLES
from src.agent.langgraph_sql_agent import SQLAgentConfig, run_sql_agent
from src.agent.logging_utils import log_feedback
from src.agent.memory_store import (
    MemoryStoreError,
    approve_candidate,
    audit_candidate_validation,
    create_candidate_from_run,
    disable_template,
    initialize_memory_files,
    load_candidates,
    load_templates,
    mark_candidate_needs_changes,
    parse_source_tables,
    reactivate_template,
    reject_candidate,
    update_candidate_proposed_template,
)
from src.agent.memory_validation import validate_proposed_template
from src.llm.model_adapter import gemini_api_key_is_placeholder


def is_numeric_value(value: object) -> bool:
    return isinstance(value, (Number, Decimal)) and not isinstance(value, bool)


def result_to_dataframe(record: dict) -> pd.DataFrame:
    query_result = record.get("query_result", {})
    return pd.DataFrame(
        query_result.get("rows", []),
        columns=query_result.get("columns", []),
    )


def maybe_show_chart(df: pd.DataFrame) -> None:
    if len(df) <= 1:
        return

    text_or_date_columns = []
    numeric_columns = []

    for column in df.columns:
        values = [value for value in df[column].tolist() if value is not None]
        if not values:
            continue

        first_value = values[0]
        if is_numeric_value(first_value):
            numeric_columns.append(column)
        elif isinstance(first_value, (str, date, datetime)):
            text_or_date_columns.append(column)

    if not text_or_date_columns or not numeric_columns:
        return

    label_column = text_or_date_columns[0]
    value_column = numeric_columns[0]
    chart_df = df[[label_column, value_column]].copy()
    chart_df[value_column] = chart_df[value_column].astype(float)

    st.bar_chart(chart_df.set_index(label_column)[value_column])


def initialize_state() -> None:
    if "history" not in st.session_state:
        st.session_state.history = []
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


def apply_app_styles() -> None:
    st.markdown(
        """
        <style>
        p code,
        li code {
            white-space: nowrap;
            word-break: keep-all;
            overflow-wrap: normal;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> str:
    config = SQLAgentConfig.from_env()

    with st.sidebar:
        st.header("Navigation")
        page = st.radio(
            "View",
            ["Chat", "Memory Review", "Approved Templates"],
            label_visibility="collapsed",
        )

        st.header("Configuration")
        st.write("Selected database: PostgreSQL")
        st.write(f"LLM provider: `{config.llm_provider}`")
        st.write(f"Primary model: `{config.primary_model}`")
        st.write(f"Fallback model: `{config.fallback_model}`")
        st.write(f"Max primary attempts: `{config.max_primary_attempts}`")
        if config.llm_provider == "gemini":
            if gemini_api_key_is_placeholder():
                st.warning(
                    "GEMINI_API_KEY is still set to `key`. Replace it in `.env` "
                    "with a real Gemini API key before asking questions."
                )
        else:
            st.write(f"Ollama host: `{config.ollama_host}`")

        st.header("Allowed tables")
        for table in TPC_H_TABLES:
            st.write(f"- `{table}`")

    return page


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


def retry_with_comment(record: dict, index: int, comment: str) -> None:
    if not comment.strip():
        st.warning("Add a short correction first.")
        return

    write_feedback(record, "neutral", f"retry_with_comment: {comment}")
    with st.spinner("Retrying with your correction..."):
        corrected_record = run_sql_agent(
            record.get("user_question", ""),
            previous_failed_sql=record.get("generated_sql", ""),
            previous_final_answer=record.get("final_answer", ""),
            previous_sql_error="User said the previous answer did not match their intent.",
            user_correction=comment.strip(),
        )
    st.session_state.history[index] = corrected_record
    st.rerun()


def rerun_with_fallback(record: dict, index: int, comment: str = "") -> None:
    write_feedback(record, "neutral", f"fallback_requested: {comment}")
    with st.spinner("Retrying with fallback model..."):
        fallback_record = run_sql_agent(
            record.get("user_question", ""),
            force_fallback=True,
            previous_failed_sql=record.get("generated_sql", ""),
            previous_final_answer=record.get("final_answer", ""),
            previous_sql_error="User requested the fallback model.",
            user_correction=comment.strip(),
        )
    st.session_state.history[index] = fallback_record
    st.rerun()


def render_metadata(record: dict) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Model", record.get("model_used") or record.get("selected_model", ""))
    col2.metric("Attempts", int(record.get("total_attempts", 0)))
    col3.metric("Fallback", "yes" if record.get("fallback_used") else "no")
    col4.metric("Status", record.get("result_status", ""))


def can_create_template_candidate(record: dict) -> bool:
    return (
        bool(record.get("validation_success", record.get("sql_valid")))
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
    col3.write(f"status: `{candidate.get('status', '')}`")
    col4.write(f"type: `{candidate.get('candidate_type', '')}`")
    st.write(f"created_at: `{candidate.get('created_at', '')}`")
    st.write(f"updated_at: `{candidate.get('updated_at', '')}`")

    st.subheader("Originalfrage")
    st.write(candidate.get("original_question", ""))

    st.subheader("Antwort")
    st.write(candidate.get("generated_answer", ""))

    sql_col1, sql_col2 = st.columns(2)
    with sql_col1:
        st.subheader("Generated SQL")
        st.code(candidate.get("generated_sql", "") or "(empty)", language="sql")
    with sql_col2:
        st.subheader("Final SQL")
        st.code(candidate.get("final_sql", "") or "(empty)", language="sql")

    st.subheader("Metadaten")
    metadata = {
        "source_tables": candidate.get("source_tables", []),
        "model_primary": candidate.get("model_primary"),
        "model_used": candidate.get("model_used"),
        "fallback_used": candidate.get("fallback_used"),
        "validation_success": candidate.get("validation_success"),
        "execution_success": candidate.get("execution_success"),
        "error_type": candidate.get("error_type"),
        "error_message": candidate.get("error_message"),
        "row_count": candidate.get("row_count"),
    }
    st.json(metadata, expanded=False)

    feedback = candidate.get("feedback", {})
    st.subheader("Feedback")
    st.write(f"rating: `{feedback.get('rating') if isinstance(feedback, dict) else ''}`")
    st.write(feedback.get("comment") if isinstance(feedback, dict) else "")


def render_memory_review_view() -> None:
    st.title("Memory Review")
    render_flash()

    try:
        candidates = load_candidates()
    except MemoryStoreError as error:
        st.error(str(error))
        return

    if not candidates:
        st.info("Keine Memory-Vorschläge vorhanden.")
        return

    statuses = ["all", "pending_review", "needs_changes", "rejected", "approved"]
    candidate_types = ["all", *sorted({str(candidate.get("candidate_type", "")) for candidate in candidates if candidate.get("candidate_type")})]
    source_tables = sorted({table for candidate in candidates for table in parse_source_tables(candidate.get("source_tables"))})

    filter_col1, filter_col2, filter_col3, filter_col4 = st.columns(4)
    with filter_col1:
        status_filter = st.selectbox("Status", statuses, key="candidate_status_filter")
    with filter_col2:
        type_filter = st.selectbox("Typ", candidate_types, key="candidate_type_filter")
    with filter_col3:
        table_filter = st.selectbox("Source table", ["all", *source_tables], key="candidate_table_filter")
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
                "status": candidate.get("status", ""),
                "candidate_type": candidate.get("candidate_type", ""),
                "intent": proposed_template.get("intent", "") if isinstance(proposed_template, dict) else "",
                "source_tables": ", ".join(parse_source_tables(candidate.get("source_tables"))),
                "created_at": candidate.get("created_at", ""),
                "updated_at": candidate.get("updated_at", ""),
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

    st.subheader("Proposed Template YAML")
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
                        _candidate, template = approve_candidate(candidate_id, parsed)
                    except MemoryStoreError as error:
                        st.warning(str(error))
                    else:
                        set_flash("success", f"Template `{template.get('template_id')}` wurde freigegeben.")
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
    st.title("Approved Templates")
    render_flash()

    try:
        templates = load_templates()
    except MemoryStoreError as error:
        st.error(str(error))
        return

    if not templates:
        st.info("Keine freigegebenen Templates vorhanden.")
        return

    table_rows = [
        {
            "template_id": template.get("template_id", ""),
            "version": template.get("version", ""),
            "status": template.get("status", ""),
            "is_active": template.get("is_active", False),
            "intent": template.get("intent", ""),
            "required_tables": ", ".join(parse_source_tables(template.get("required_tables"))),
            "created_from_candidate_id": template.get("created_from_candidate_id", ""),
            "source_run_id": template.get("source_run_id", ""),
            "approved_at": template.get("approved_at", ""),
            "approved_by": template.get("approved_by", ""),
        }
        for template in templates
    ]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    template_by_id = {template.get("template_id"): template for template in templates}
    if st.session_state.get("selected_template_id") not in template_by_id:
        st.session_state.pop("selected_template_id", None)
    selected_template_id = st.selectbox(
        "Template auswählen",
        list(template_by_id.keys()),
        key="selected_template_id",
    )
    template = template_by_id[selected_template_id]

    st.subheader("Details")
    st.write(f"template_id: `{template.get('template_id', '')}`")
    st.write(f"status: `{template.get('status', '')}`")
    st.write(f"is_active: `{template.get('is_active', False)}`")
    st.write(f"intent: {template.get('intent', '')}")
    st.write("trigger_phrases")
    st.json(template.get("trigger_phrases", []), expanded=False)
    st.write("metric_definitions")
    st.json(template.get("metric_definitions", {}), expanded=False)
    st.write("join_logic")
    st.json(template.get("join_logic", []), expanded=False)
    st.write("quality")
    st.json(template.get("quality", {}), expanded=False)
    st.subheader("SQL Skeleton")
    st.code(template.get("sql_skeleton", "") or "(empty)", language="sql")

    disabled_reason = st.text_area(
        "Deaktivierungsgrund",
        key=f"disabled_reason_{selected_template_id}",
    )

    if template.get("status") == "approved" and template.get("is_active") is True:
        if st.button("Template deaktivieren", key=f"disable_{selected_template_id}"):
            if not disabled_reason.strip():
                st.warning("Bitte Deaktivierungsgrund angeben.")
            else:
                try:
                    disable_template(str(selected_template_id), disabled_reason)
                except MemoryStoreError as error:
                    st.error(str(error))
                else:
                    set_flash("success", "Template wurde deaktiviert.")
                    st.rerun()

    if template.get("status") == "disabled":
        if st.button("Template reaktivieren", key=f"reactivate_{selected_template_id}"):
            try:
                reactivate_template(str(selected_template_id))
            except MemoryStoreError as error:
                st.error(str(error))
            else:
                set_flash("success", "Template wurde reaktiviert.")
                st.rerun()


def render_record(record: dict, index: int) -> None:
    with st.chat_message("user"):
        st.caption("Question")
        st.markdown(record.get("user_question", ""))

    with st.chat_message("assistant"):
        render_metadata(record)

        st.subheader("Answer")
        st.write(record.get("final_answer") or "No answer was generated.")

        query_result = record.get("query_result", {})
        rows = query_result.get("rows", [])
        columns = query_result.get("columns", [])
        if rows and columns:
            st.subheader("Query result preview")
            df = result_to_dataframe(record)
            st.dataframe(df, use_container_width=True)
            maybe_show_chart(df)

        st.subheader("SQL statement")
        st.code(record.get("final_sql") or record.get("generated_sql", "") or "(no SQL generated)", language="sql")

        source_tables = record.get("source_tables", [])
        st.subheader("Source tables")
        if source_tables:
            for table in source_tables:
                st.markdown(f"- `{table}`")
        else:
            st.write("No source tables were extracted.")

        if record.get("sql_error"):
            st.subheader("SQL error")
            st.error(record["sql_error"])

        with st.expander("Trace steps", expanded=False):
            for step in record.get("trace_steps", []):
                st.markdown(f"- {step}")

        if record.get("user_correction"):
            st.subheader("User correction")
            st.write(record["user_correction"])

        st.subheader("Feedback")
        comment = st.text_area("Optional comment", key=f"feedback_comment_{index}")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("Good answer", key=f"feedback_good_{index}"):
                write_feedback(record, "thumbs_up", comment)
                st.success("Feedback saved.")
        with col2:
            if st.button("Bad answer", key=f"feedback_bad_{index}"):
                write_feedback(record, "thumbs_down", comment)
                st.warning("Feedback saved.")
        with col3:
            if st.button("Retry with comment", key=f"feedback_retry_{index}"):
                retry_with_comment(record, index, comment)
        with col4:
            if st.button("Use fallback model", key=f"feedback_fallback_{index}"):
                rerun_with_fallback(record, index, comment)

        render_candidate_creation(record, index)


def main() -> None:
    st.set_page_config(page_title="Agentic AI Data Assistant", layout="wide")
    apply_app_styles()
    initialize_state()
    page = render_sidebar()

    if page == "Memory Review":
        render_memory_review_view()
        return

    if page == "Approved Templates":
        render_approved_templates_view()
        return

    st.title("Agentic AI Data Assistant")
    st.caption("LangGraph SQL workflow over local TPC-H data with Gemini fallback models.")
    render_flash()

    for index, record in enumerate(st.session_state.history):
        render_record(record, index)

    question = st.chat_input("Ask a question about the TPC-H data")
    if question:
        with st.spinner("Running LangGraph SQL workflow..."):
            record = run_sql_agent(question)
        st.session_state.history.append(record)
        st.rerun()


if __name__ == "__main__":
    main()
