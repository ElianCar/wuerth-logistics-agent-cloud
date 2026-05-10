from datetime import datetime, date
from decimal import Decimal
from numbers import Number

import pandas as pd
import streamlit as st

from app.config import get_config
from app.logging_utils import log_feedback, log_query
from app.llm_client import generate_sql
from app.prompt_builder import build_sql_generation_prompt
from app.query_executor import execute_sql, run_explain
from app.schema import get_schema_text, TPC_H_TABLES
from app.semantic_layer import get_semantic_layer_text
from app.sql_validator import extract_used_tables as extract_sql_used_tables
from app.sql_validator import validate_sql


def is_numeric_value(value: object) -> bool:
    return isinstance(value, (Number, Decimal)) and not isinstance(value, bool)


def summarize_result(columns: list[str], rows: list[tuple]) -> str:
    if not rows:
        return "The query returned no rows."

    if len(rows) == 1 and len(columns) == 1 and is_numeric_value(rows[0][0]):
        return f"The answer is {rows[0][0]}."

    return f"The query returned {len(rows)} rows."


def result_to_dataframe(columns: list[str], rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def extract_used_tables(sql: str) -> list[str]:
    used_tables = extract_sql_used_tables(sql)
    return [table for table in TPC_H_TABLES if table in used_tables]


def current_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def error_message_for_record(record: dict) -> str:
    if record["error"]:
        return record["error"]
    if record["validation_status"] == "failed":
        return record["validation_message"]
    if record["explain_status"] == "failed":
        return record["explain_message"]
    return ""


def write_query_log(record: dict) -> None:
    log_query(
        timestamp=current_timestamp(),
        question=record["question"],
        generated_sql=record["sql"],
        used_tables=record["used_tables"],
        validation_status=record["validation_status"],
        explain_status=record["explain_status"],
        execution_status=record["execution_status"],
        row_count=record["row_count"],
        error_message=error_message_for_record(record),
    )


def write_feedback_log(record: dict, feedback_value: str) -> None:
    log_feedback(
        timestamp=current_timestamp(),
        question=record["question"],
        generated_sql=record["sql"],
        used_tables=record["used_tables"],
        validation_status=record["validation_status"],
        explain_status=record["explain_status"],
        execution_status=record["execution_status"],
        feedback_value=feedback_value,
        error_message=error_message_for_record(record),
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


def run_question(question: str) -> dict:
    record = {
        "question": question,
        "answer": "",
        "columns": [],
        "rows": [],
        "sql": "",
        "used_tables": [],
        "validation_passed": False,
        "validation_status": "failed",
        "validation_message": "",
        "explain_passed": False,
        "explain_status": "not run",
        "explain_message": "",
        "execution_status": "not executed",
        "row_count": 0,
        "error": "",
    }

    try:
        schema_text = get_schema_text()
        semantic_layer_text = get_semantic_layer_text()
    except Exception as error:
        record["error"] = (
            "PostgreSQL cannot be reached or the schema could not be loaded. "
            f"Details: {error}"
        )
        write_query_log(record)
        return record

    prompt = build_sql_generation_prompt(
        question=question,
        schema_text=schema_text,
        semantic_layer_text=semantic_layer_text,
    )

    try:
        raw_sql = generate_sql(prompt)
    except RuntimeError as error:
        error_text = str(error)
        if "Ollama" in error_text:
            record["error"] = "Ollama is not running. Start it with: ollama serve"
        else:
            record["error"] = error_text
        write_query_log(record)
        return record

    validation = validate_sql(raw_sql)
    record["sql"] = validation.sql
    record["used_tables"] = extract_used_tables(validation.sql)
    record["validation_passed"] = validation.is_valid
    record["validation_status"] = "passed" if validation.is_valid else "failed"
    record["validation_message"] = validation.message

    if not validation.is_valid:
        record["execution_status"] = "not executed"
        write_query_log(record)
        return record

    try:
        run_explain(validation.sql)
        record["explain_passed"] = True
        record["explain_status"] = "passed"
        record["explain_message"] = "PostgreSQL EXPLAIN passed."
    except RuntimeError as error:
        record["explain_status"] = "failed"
        record["explain_message"] = str(error)
        record["execution_status"] = "not executed"
        write_query_log(record)
        return record

    try:
        columns, rows = execute_sql(validation.sql)
        record["columns"] = columns
        record["rows"] = rows
        record["row_count"] = len(rows)
        record["answer"] = summarize_result(columns, rows)
        record["execution_status"] = "executed"
    except RuntimeError as error:
        record["execution_status"] = "failed"
        record["error"] = str(error)

    write_query_log(record)
    return record


def render_status(record: dict) -> None:
    if record["validation_passed"]:
        st.success(f"SQL validator passed: {record['validation_message']}")
    else:
        st.error(f"SQL validator failed: {record['validation_message']}")

    if record["explain_status"] == "passed":
        st.success(record["explain_message"])
    elif record["explain_status"] == "failed":
        st.error(f"PostgreSQL EXPLAIN failed: {record['explain_message']}")
    else:
        st.warning("PostgreSQL EXPLAIN was not run.")

    if record["execution_status"] == "executed":
        st.success("Query executed.")
    elif record["execution_status"] == "failed":
        st.error(f"Query execution failed: {record['error']}")
    else:
        st.warning("Query was not executed.")


def render_record(record: dict, index: int) -> None:
    with st.chat_message("user"):
        st.markdown(record["question"])

    with st.chat_message("assistant"):
        if record["error"] and not record["sql"]:
            st.error(record["error"])
            return

        st.subheader("Natural language answer")
        st.write(record["answer"] or "No answer was generated because the query did not execute.")

        if record["columns"]:
            df = result_to_dataframe(record["columns"], record["rows"])
            st.subheader("Result table")
            st.dataframe(df, width="stretch")
            maybe_show_chart(df)

        with st.expander("Generated SQL", expanded=False):
            st.code(record["sql"] or "(no SQL generated)", language="sql")

        st.subheader("Data source trace")
        if record["used_tables"]:
            st.markdown("Used tables:")
            for table in record["used_tables"]:
                st.markdown(f"- `{table}`")
        else:
            st.write("No allowed TPC-H tables were detected in the generated SQL.")

        st.subheader("Validation status")
        render_status(record)

        st.subheader("Feedback")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Thumbs up", key=f"feedback_up_{index}"):
                write_feedback_log(record, "positive")
                st.success("Feedback saved.")
        with col2:
            if st.button("Thumbs down", key=f"feedback_down_{index}"):
                write_feedback_log(record, "negative")
                st.success("Feedback saved.")


def initialize_state() -> None:
    if "history" not in st.session_state:
        st.session_state.history = []


def render_sidebar() -> None:
    config = get_config()

    with st.sidebar:
        st.header("Configuration")
        st.write("Selected database: PostgreSQL")
        st.write(f"Selected LLM model: `{config.ollama_model}`")

        st.header("Allowed tables")
        for table in TPC_H_TABLES:
            st.write(f"- `{table}`")

        st.header("Validation pipeline")
        st.write(
            "The app asks Ollama to generate SQL, validates that it is a safe single "
            "SELECT query over allowed TPC-H tables, runs PostgreSQL EXPLAIN, and "
            "executes the query only after those checks pass."
        )


def main() -> None:
    st.set_page_config(page_title="Agentic AI Data Assistant", layout="wide")
    initialize_state()
    render_sidebar()

    st.title("Agentic AI Data Assistant")
    st.caption("Prototype for natural language questions over local TPC-H data.")

    for index, record in enumerate(st.session_state.history):
        render_record(record, index)

    question = st.chat_input("Ask a question about the TPC-H data")
    if question:
        with st.spinner("Generating SQL and querying PostgreSQL..."):
            record = run_question(question)
        st.session_state.history.append(record)
        st.rerun()


if __name__ == "__main__":
    main()
