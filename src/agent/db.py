from __future__ import annotations

from typing import Any

from app.db import get_connection
from app.schema import get_schema_text
from app.semantic_layer import get_semantic_layer_text


def load_schema_context() -> str:
    schema_text = get_schema_text()
    semantic_layer_text = get_semantic_layer_text()
    return f"{schema_text}\n\nSemantic layer:\n{semantic_layer_text}"


def execute_read_only_sql(
    sql: str,
    user_question: str,
) -> dict[str, Any]:
    executed_sql = sql.strip().rstrip(";").strip()

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(f"EXPLAIN {executed_sql}")
            cursor.fetchall()
            cursor.execute(executed_sql)
            rows = cursor.fetchall()
            columns = [description.name for description in cursor.description]

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "executed_sql": executed_sql,
        "limit_applied": False,
    }
