from __future__ import annotations

from typing import Any, Protocol


class SQLBackend(Protocol):
    def execute_sql(self, sql: str, user_question: str = "") -> dict[str, Any]:
        """Execute a validated read-only SQL statement."""

    def load_schema_context(self) -> str:
        """Return schema and semantic context for prompt construction and validation."""

    def test_connection(self) -> dict[str, Any]:
        """Open a backend connection and return safe status metadata."""

    def get_backend_name(self) -> str:
        """Return a stable backend identifier, such as postgres or databricks."""

    def get_sql_dialect(self) -> str:
        """Return the SQL dialect name to show in prompts and UI."""

