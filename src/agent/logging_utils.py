from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import os


QUERY_LOG_FIELDS = [
    "timestamp",
    "user_question",
    "selected_model",
    "attempt_number",
    "fallback_used",
    "generated_sql",
    "sql_valid",
    "sql_error",
    "execution_success",
    "row_count",
]

FEEDBACK_LOG_FIELDS = [
    "timestamp",
    "user_question",
    "final_answer",
    "generated_sql",
    "selected_model",
    "fallback_used",
    "user_rating",
    "user_comment",
]


def current_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_log_dir() -> Path:
    return Path(os.getenv("LOG_DIR", "logs"))


def stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value)


def append_csv_row(path: Path, fieldnames: list[str], row: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        should_write_header = not path.exists() or path.stat().st_size == 0

        with path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if should_write_header:
                writer.writeheader()
            writer.writerow({field: stringify(row.get(field, "")) for field in fieldnames})
    except Exception as error:
        print(f"Logging failed for {path}: {error}")


def log_query_attempt(
    *,
    user_question: str,
    selected_model: str,
    attempt_number: int,
    fallback_used: bool,
    generated_sql: str,
    sql_valid: bool,
    sql_error: str,
    execution_success: bool,
    row_count: int,
) -> None:
    append_csv_row(
        get_log_dir() / "query_log.csv",
        QUERY_LOG_FIELDS,
        {
            "timestamp": current_timestamp(),
            "user_question": user_question,
            "selected_model": selected_model,
            "attempt_number": attempt_number,
            "fallback_used": fallback_used,
            "generated_sql": generated_sql,
            "sql_valid": sql_valid,
            "sql_error": sql_error,
            "execution_success": execution_success,
            "row_count": row_count,
        },
    )


def log_feedback(
    *,
    user_question: str,
    final_answer: str,
    generated_sql: str,
    selected_model: str,
    fallback_used: bool,
    user_rating: str,
    user_comment: str = "",
) -> None:
    append_csv_row(
        get_log_dir() / "feedback.csv",
        FEEDBACK_LOG_FIELDS,
        {
            "timestamp": current_timestamp(),
            "user_question": user_question,
            "final_answer": final_answer,
            "generated_sql": generated_sql,
            "selected_model": selected_model,
            "fallback_used": fallback_used,
            "user_rating": user_rating,
            "user_comment": user_comment,
        },
    )
