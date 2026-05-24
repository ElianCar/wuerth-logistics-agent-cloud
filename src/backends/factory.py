from __future__ import annotations

from src.backends.base import SQLBackend
from src.backends.config import (
    DATABRICKS_BACKEND,
    POSTGRES_BACKEND,
    BackendConfigError,
    get_configured_backend_name,
    load_backend_settings,
)
from src.backends.databricks.databricks_adapter import DatabricksAdapter
from src.backends.demo.postgres_adapter import PostgresAdapter


def get_backend() -> SQLBackend:
    settings = load_backend_settings()
    if settings.backend_name == POSTGRES_BACKEND:
        return PostgresAdapter()
    if settings.backend_name == DATABRICKS_BACKEND and settings.databricks is not None:
        return DatabricksAdapter(settings.databricks)
    raise BackendConfigError(f"Unsupported DB_BACKEND '{settings.backend_name}'.")


def get_backend_metadata() -> dict[str, object]:
    backend_name = get_configured_backend_name()
    if backend_name == POSTGRES_BACKEND:
        return PostgresAdapter().get_safe_metadata()
    if backend_name == DATABRICKS_BACKEND:
        return DatabricksAdapter().get_safe_metadata()
    raise BackendConfigError(f"Unsupported DB_BACKEND '{backend_name}'.")

