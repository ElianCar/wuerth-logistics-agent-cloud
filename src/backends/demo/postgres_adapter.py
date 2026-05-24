from __future__ import annotations

from typing import Any

from app.db import get_connection
from app.schema import TPC_H_TABLES, get_schema_text
from app.semantic_layer import get_semantic_layer_text


class PostgresAdapter:
    def get_backend_name(self) -> str:
        return "postgres"

    def get_sql_dialect(self) -> str:
        return "PostgreSQL"

    def load_schema_context(self) -> str:
        schema_text = get_schema_text()
        semantic_layer_text = get_semantic_layer_text()
        return (
            "Backend: postgres\n"
            "SQL dialect: PostgreSQL\n\n"
            f"{schema_text}\n\n"
            f"Semantic layer:\n{semantic_layer_text}"
        )

    def execute_sql(self, sql: str, user_question: str = "") -> dict[str, Any]:
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

    def test_connection(self) -> dict[str, Any]:
        with get_connection():
            return {
                "ok": True,
                "backend_name": self.get_backend_name(),
                "sql_dialect": self.get_sql_dialect(),
            }

    def get_safe_metadata(self) -> dict[str, object]:
        return {
            "backend_name": self.get_backend_name(),
            "sql_dialect": self.get_sql_dialect(),
            "auth_type": "",
            "allowed_tables": list(TPC_H_TABLES),
        }

