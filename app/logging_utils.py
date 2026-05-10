from pathlib import Path
import csv


LOG_DIR = Path("logs")
QUERY_LOG_PATH = LOG_DIR / "query_log.csv"
FEEDBACK_LOG_PATH = LOG_DIR / "feedback.csv"

QUERY_LOG_FIELDS = [
    "timestamp",
    "question",
    "generated_sql",
    "used_tables",
    "validation_status",
    "explain_status",
    "execution_status",
    "row_count",
    "error_message",
]

FEEDBACK_LOG_FIELDS = [
    "timestamp",
    "question",
    "generated_sql",
    "used_tables",
    "validation_status",
    "explain_status",
    "execution_status",
    "feedback_value",
    "error_message",
]


def _stringify(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value)
    return str(value)


def _append_row(path: Path, fieldnames: list[str], row: dict) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        should_write_header = not path.exists() or path.stat().st_size == 0

        with path.open("a", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if should_write_header:
                writer.writeheader()

            writer.writerow({field: _stringify(row.get(field, "")) for field in fieldnames})
    except Exception as error:
        print(f"Logging failed for {path}: {error}")


def log_query(
    timestamp: str = "",
    question: str = "",
    generated_sql: str = "",
    used_tables: list[str] | None = None,
    validation_status: str = "",
    explain_status: str = "",
    execution_status: str = "",
    row_count: int | str = "",
    error_message: str = "",
) -> None:
    _append_row(
        QUERY_LOG_PATH,
        QUERY_LOG_FIELDS,
        {
            "timestamp": timestamp,
            "question": question,
            "generated_sql": generated_sql,
            "used_tables": used_tables or [],
            "validation_status": validation_status,
            "explain_status": explain_status,
            "execution_status": execution_status,
            "row_count": row_count,
            "error_message": error_message,
        },
    )


def log_feedback(
    timestamp: str = "",
    question: str = "",
    generated_sql: str = "",
    used_tables: list[str] | None = None,
    validation_status: str = "",
    explain_status: str = "",
    execution_status: str = "",
    feedback_value: str = "",
    error_message: str = "",
) -> None:
    _append_row(
        FEEDBACK_LOG_PATH,
        FEEDBACK_LOG_FIELDS,
        {
            "timestamp": timestamp,
            "question": question,
            "generated_sql": generated_sql,
            "used_tables": used_tables or [],
            "validation_status": validation_status,
            "explain_status": explain_status,
            "execution_status": execution_status,
            "feedback_value": feedback_value,
            "error_message": error_message,
        },
    )
