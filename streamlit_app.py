from datetime import date, datetime
from decimal import Decimal
from numbers import Number

import pandas as pd
import streamlit as st

from app.schema import TPC_H_TABLES
from src.agent.langgraph_sql_agent import SQLAgentConfig, run_sql_agent
from src.agent.logging_utils import log_feedback


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


def render_sidebar() -> None:
    config = SQLAgentConfig.from_env()

    with st.sidebar:
        st.header("Configuration")
        st.write("Selected database: PostgreSQL")
        st.write(f"Primary model: `{config.primary_model}`")
        st.write(f"Fallback model: `{config.fallback_model}`")
        st.write(f"Max primary attempts: `{config.max_primary_attempts}`")
        st.write(f"Ollama host: `{config.ollama_host}`")

        st.header("Allowed tables")
        for table in TPC_H_TABLES:
            st.write(f"- `{table}`")


def write_feedback(record: dict, rating: str, comment: str) -> None:
    log_feedback(
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

    write_feedback(record, "retry_with_comment", comment)
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
    write_feedback(record, "fallback_requested", comment)
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
    col1.metric("Model", record.get("selected_model", ""))
    col2.metric("Attempts", int(record.get("total_attempts", 0)))
    col3.metric("Fallback", "yes" if record.get("fallback_used") else "no")
    col4.metric("Status", record.get("result_status", ""))


def render_record(record: dict, index: int) -> None:
    with st.chat_message("user"):
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

        with st.expander("Generated SQL", expanded=False):
            st.code(record.get("generated_sql", "") or "(no SQL generated)", language="sql")

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
                write_feedback(record, "good", comment)
                st.success("Feedback saved.")
        with col2:
            if st.button("Bad answer", key=f"feedback_bad_{index}"):
                write_feedback(record, "bad", comment)
                st.warning("Feedback saved.")
        with col3:
            if st.button("Retry with comment", key=f"feedback_retry_{index}"):
                retry_with_comment(record, index, comment)
        with col4:
            if st.button("Use fallback model", key=f"feedback_fallback_{index}"):
                rerun_with_fallback(record, index, comment)


def main() -> None:
    st.set_page_config(page_title="Agentic AI Data Assistant", layout="wide")
    initialize_state()
    render_sidebar()

    st.title("Agentic AI Data Assistant")
    st.caption("LangGraph SQL workflow over local TPC-H data with Ollama models.")

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
