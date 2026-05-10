from __future__ import annotations

import re
from typing import Any

from app.db import get_connection
from app.schema import get_schema_text
from app.semantic_layer import get_semantic_layer_text


MAX_RESULT_ROWS = 50


def load_schema_context() -> str:
    schema_text = get_schema_text()
    semantic_layer_text = get_semantic_layer_text()
    return f"{schema_text}\n\nSemantic layer:\n{semantic_layer_text}"


def should_skip_limit(sql: str, user_question: str) -> bool:
    if re.search(r"\blimit\s+\d+\b", sql, re.IGNORECASE):
        return True

    has_aggregate = bool(re.search(r"\b(sum|count|avg|min|max)\s*\(", sql, re.IGNORECASE))
    has_group_by = bool(re.search(r"\bgroup\s+by\b", sql, re.IGNORECASE))
    if has_aggregate and not has_group_by:
        return True

    single_value_phrases = (
        "total",
        "single value",
        "how many",
        "count of",
        "average",
        "minimum",
        "maximum",
    )
    question = user_question.lower()
    return has_aggregate and any(phrase in question for phrase in single_value_phrases)


def apply_limit_if_needed(sql: str, user_question: str, max_rows: int = MAX_RESULT_ROWS) -> tuple[str, bool]:
    cleaned_sql = sql.strip().rstrip(";").strip()
    if should_skip_limit(cleaned_sql, user_question):
        return cleaned_sql, False
    return f"SELECT * FROM ({cleaned_sql}) AS langgraph_generated_query LIMIT {max_rows}", True


def execute_read_only_sql(
    sql: str,
    user_question: str,
    max_rows: int = MAX_RESULT_ROWS,
) -> dict[str, Any]:
    executed_sql, limit_applied = apply_limit_if_needed(sql, user_question, max_rows)

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(f"EXPLAIN {executed_sql}")
            cursor.fetchall()
            cursor.execute(executed_sql)
            rows = cursor.fetchmany(max_rows)
            columns = [description.name for description in cursor.description]

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "executed_sql": executed_sql,
        "limit_applied": limit_applied,
    }
