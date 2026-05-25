from __future__ import annotations

from typing import Any

from app.db import get_connection
from app.schema import TPC_H_TABLES, get_schema_text
from src.config.scenarios import SCENARIOS, load_semantic_layer_text


class PostgresAdapter:
    def get_backend_name(self) -> str:
        return "postgres"

    def get_sql_dialect(self) -> str:
        return "PostgreSQL"

    def load_schema_context(self) -> str:
        scenario = SCENARIOS["demo"]
        schema_text = get_schema_text()
        semantic_layer_text = load_semantic_layer_text(scenario)
        return (
            f"Scenario: {scenario.scenario_id}\n"
            f"Dataset ID: {scenario.dataset_id}\n"
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
            "backend_display_name": "PostgreSQL demo database",
            "scenario_id": "demo",
            "scenario_label": "Demo data",
            "sql_dialect": self.get_sql_dialect(),
            "auth_type": "",
            "semantic_layer": SCENARIOS["demo"].semantic_layer_filename,
            "dataset_id": SCENARIOS["demo"].dataset_id,
            "allowed_tables": list(TPC_H_TABLES),
        }
