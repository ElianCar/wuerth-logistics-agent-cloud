from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import os
import shutil
from uuid import uuid4


QUERY_LOG_REQUIRED_FIELDS = [
    "log_type",
    "run_id",
    "timestamp",
    "question",
    "generated_sql",
    "final_sql",
    "model_primary",
    "model_used",
    "fallback_used",
    "validation_success",
    "execution_success",
    "error_type",
    "error_message",
    "source_tables",
    "row_count",
    "latency_seconds",
    "answer_preview",
]

QUERY_LOG_LEGACY_FIELDS = [
    "primary_model",
    "backup_model",
    "sql_candidate",
    "success",
    "user_question",
    "selected_model",
    "attempt_number",
    "sql_valid",
    "sql_error",
]

QUERY_LOG_FIELDS = [
    *QUERY_LOG_REQUIRED_FIELDS,
    *[field for field in QUERY_LOG_LEGACY_FIELDS if field not in QUERY_LOG_REQUIRED_FIELDS],
]

FEEDBACK_LOG_REQUIRED_FIELDS = [
    "feedback_id",
    "run_id",
    "timestamp",
    "rating",
    "comment",
    "corrected_sql",
    "expected_answer",
    "created_by",
]

FEEDBACK_LOG_LEGACY_FIELDS = [
    "user_question",
    "final_answer",
    "generated_sql",
    "selected_model",
    "fallback_used",
    "user_rating",
    "user_comment",
]

FEEDBACK_LOG_FIELDS = [
    *FEEDBACK_LOG_REQUIRED_FIELDS,
    *[field for field in FEEDBACK_LOG_LEGACY_FIELDS if field not in FEEDBACK_LOG_REQUIRED_FIELDS],
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


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def append_csv_row(path: Path, fieldnames: list[str], row: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        current_fieldnames = ensure_csv_columns(path, fieldnames)
        should_write_header = not path.exists() or path.stat().st_size == 0

        with path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=current_fieldnames)
            if should_write_header:
                writer.writeheader()
            writer.writerow({field: stringify(row.get(field, "")) for field in current_fieldnames})
    except Exception as error:
        print(f"Logging failed for {path}: {error}")


def ensure_csv_columns(path: Path, fieldnames: list[str]) -> list[str]:
    if not path.exists() or path.stat().st_size == 0:
        return fieldnames

    with path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        existing_fieldnames = reader.fieldnames or []
        missing_fields = [field for field in fieldnames if field not in existing_fieldnames]
        if not missing_fields:
            return existing_fieldnames
        rows = list(reader)

    migrated_fieldnames = [*existing_fieldnames, *missing_fields]
    backup_path = path.with_name(
        f"{path.name}.bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:4]}"
    )
    temp_path = path.with_name(f".{path.name}.tmp_{uuid4().hex}")

    shutil.copy2(path, backup_path)
    with temp_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=migrated_fieldnames)
        writer.writeheader()
        for existing_row in rows:
            writer.writerow(
                {field: stringify(existing_row.get(field, "")) for field in migrated_fieldnames}
            )
    os.replace(temp_path, path)
    return migrated_fieldnames


def format_source_tables(source_tables: list[str] | str | None) -> str:
    if source_tables is None:
        return ""
    if isinstance(source_tables, str):
        return source_tables
    return "|".join(str(table) for table in source_tables if table)


def preview_text(value: object, limit: int = 500) -> str:
    text = stringify(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def normalize_rating(rating: str) -> str:
    normalized = (rating or "").strip().lower()
    rating_map = {
        "good": "thumbs_up",
        "positive": "thumbs_up",
        "thumbs up": "thumbs_up",
        "thumbs_up": "thumbs_up",
        "bad": "thumbs_down",
        "negative": "thumbs_down",
        "thumbs down": "thumbs_down",
        "thumbs_down": "thumbs_down",
        "neutral": "neutral",
        "retry_with_comment": "neutral",
        "fallback_requested": "neutral",
    }
    return rating_map.get(normalized, "neutral")


def infer_error_type(
    *,
    validation_success: bool,
    execution_success: bool,
    error_message: str = "",
) -> str:
    if not error_message:
        return ""
    if not validation_success:
        return "validation_error"
    if not execution_success:
        return "execution_error"
    return "runtime_error"


def log_query_attempt(
    *,
    run_id: str = "",
    user_question: str = "",
    primary_model: str = "",
    backup_model: str = "",
    model_used: str = "",
    selected_model: str = "",
    attempt_number: int = 0,
    fallback_used: bool = False,
    sql_candidate: str = "",
    generated_sql: str = "",
    sql_valid: bool = False,
    success: bool | None = None,
    error_message: str = "",
    sql_error: str = "",
    execution_success: bool = False,
    row_count: int = 0,
    source_tables: list[str] | None = None,
) -> None:
    validation_success = bool(sql_valid)
    effective_error = error_message or sql_error
    append_csv_row(
        get_log_dir() / "query_log.csv",
        QUERY_LOG_FIELDS,
        {
            "log_type": "attempt",
            "run_id": run_id,
            "timestamp": current_timestamp(),
            "question": user_question,
            "generated_sql": generated_sql,
            "final_sql": generated_sql if execution_success else "",
            "model_primary": primary_model,
            "model_used": model_used or selected_model,
            "fallback_used": fallback_used,
            "validation_success": validation_success,
            "execution_success": execution_success,
            "error_type": infer_error_type(
                validation_success=validation_success,
                execution_success=execution_success,
                error_message=effective_error,
            ),
            "error_message": effective_error,
            "source_tables": format_source_tables(source_tables),
            "row_count": row_count,
            "latency_seconds": "",
            "answer_preview": "",
            "primary_model": primary_model,
            "backup_model": backup_model,
            "model_used": model_used or selected_model,
            "sql_candidate": sql_candidate or generated_sql,
            "success": execution_success if success is None else success,
            "user_question": user_question,
            "selected_model": selected_model,
            "attempt_number": attempt_number,
            "sql_valid": sql_valid,
            "sql_error": sql_error,
        },
    )


def log_query_run(
    *,
    run_id: str,
    question: str,
    generated_sql: str,
    final_sql: str,
    model_primary: str,
    model_used: str,
    fallback_used: bool,
    validation_success: bool,
    execution_success: bool,
    error_type: str,
    error_message: str,
    source_tables: list[str] | None,
    row_count: int,
    latency_seconds: float,
    answer: str = "",
) -> None:
    append_csv_row(
        get_log_dir() / "query_log.csv",
        QUERY_LOG_FIELDS,
        {
            "log_type": "run_final",
            "run_id": run_id,
            "timestamp": current_timestamp(),
            "question": question,
            "generated_sql": generated_sql,
            "final_sql": final_sql,
            "model_primary": model_primary,
            "model_used": model_used,
            "fallback_used": fallback_used,
            "validation_success": validation_success,
            "execution_success": execution_success,
            "error_type": error_type,
            "error_message": error_message,
            "source_tables": format_source_tables(source_tables),
            "row_count": row_count,
            "latency_seconds": f"{latency_seconds:.3f}",
            "answer_preview": preview_text(answer),
            "primary_model": model_primary,
            "selected_model": model_used,
            "success": execution_success,
            "sql_valid": validation_success,
            "sql_error": error_message,
        },
    )


def log_feedback(
    *,
    run_id: str = "",
    rating: str | None = None,
    comment: str | None = None,
    corrected_sql: str = "",
    expected_answer: str = "",
    created_by: str = "manual_review",
    user_question: str,
    final_answer: str,
    generated_sql: str,
    selected_model: str,
    fallback_used: bool,
    user_rating: str,
    user_comment: str = "",
    feedback_id: str = "",
) -> str:
    from src.agent.id_utils import generate_feedback_id

    effective_feedback_id = feedback_id or generate_feedback_id()
    effective_rating = normalize_rating(rating or user_rating)
    effective_comment = user_comment if comment is None else comment
    append_csv_row(
        get_log_dir() / "feedback.csv",
        FEEDBACK_LOG_FIELDS,
        {
            "feedback_id": effective_feedback_id,
            "run_id": run_id,
            "timestamp": current_timestamp(),
            "rating": effective_rating,
            "comment": effective_comment,
            "corrected_sql": corrected_sql,
            "expected_answer": expected_answer,
            "created_by": created_by,
            "user_question": user_question,
            "final_answer": final_answer,
            "generated_sql": generated_sql,
            "selected_model": selected_model,
            "fallback_used": fallback_used,
            "user_rating": effective_rating,
            "user_comment": effective_comment,
        },
    )
    return effective_feedback_id
