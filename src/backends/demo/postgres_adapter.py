from __future__ import annotations

from typing import Any

from app.db import get_connection
from app.schema import get_schema_text_for_tables
from src.config.scenarios import get_active_scenario, load_semantic_layer_text


class PostgresAdapter:
    def get_backend_name(self) -> str:
        return "postgres"

    def get_sql_dialect(self) -> str:
        return "PostgreSQL"

    def load_schema_context(self) -> str:
        scenario = get_active_scenario()
        schema_text = get_schema_text_for_tables(scenario.allowed_tables)
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
        scenario = get_active_scenario()
        return {
            "backend_name": self.get_backend_name(),
            "backend_display_name": scenario.backend_display_name,
            "scenario_id": scenario.scenario_id,
            "scenario_label": scenario.label,
            "sql_dialect": self.get_sql_dialect(),
            "auth_type": "",
            "semantic_layer": scenario.semantic_layer_filename,
            "dataset_id": scenario.dataset_id,
            "allowed_tables": list(scenario.allowed_tables),
        }
