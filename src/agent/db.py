from __future__ import annotations

from typing import Any

from src.backends.factory import get_backend, get_backend_metadata


def load_schema_context() -> str:
    return get_backend().load_schema_context()


def execute_read_only_sql(
    sql: str,
    user_question: str,
) -> dict[str, Any]:
    return get_backend().execute_sql(sql, user_question)


def get_active_backend_metadata() -> dict[str, object]:
    return get_backend_metadata()
