from __future__ import annotations

from dataclasses import dataclass, field
import os
import re

from src.config.scenarios import get_active_scenario


POSTGRES_BACKEND = "postgres"
DATABRICKS_BACKEND = "databricks"
SUPPORTED_BACKENDS = {POSTGRES_BACKEND, DATABRICKS_BACKEND}
SUPPORTED_DATABRICKS_AUTH_TYPES = {"oauth_u2m", "oauth_m2m", "pat"}
AUTH_TYPE_ALIASES = {
    "oauth": "oauth_u2m",
    "databricks-oauth": "oauth_u2m",
}
DEFAULT_DATABRICKS_ALLOWED_TABLES = (
    "workspace.default.datenabzug_projekt_tum_invoices",
    "workspace.default.datenabzug_projekt_tum_shipments",
)


class BackendConfigError(ValueError):
    """Raised when backend configuration is missing or unsupported."""


@dataclass(frozen=True)
class DatabricksBackendConfig:
    auth_type: str
    server_hostname: str = field(repr=False)
    http_path: str = field(repr=False)
    catalog: str
    schema: str
    allowed_tables: tuple[str, ...]
    access_token: str = field(default="", repr=False)
    host: str = field(default="", repr=False)
    client_id: str = field(default="", repr=False)
    client_secret: str = field(default="", repr=False)

    @property
    def short_allowed_tables(self) -> tuple[str, ...]:
        return tuple(table.split(".")[-1] for table in self.allowed_tables)

    @property
    def safe_allowed_tables(self) -> tuple[str, ...]:
        return self.allowed_tables


@dataclass(frozen=True)
class BackendSettings:
    backend_name: str
    databricks: DatabricksBackendConfig | None = None


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def get_configured_backend_name() -> str:
    return get_active_scenario().backend_name


def _missing(required_names: list[str]) -> list[str]:
    return [name for name in required_names if not _env(name)]


def _validate_identifier(value: str, env_name: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise BackendConfigError(f"{env_name} must be a simple SQL identifier.")


def _normalize_allowed_table(raw_table: str, catalog: str, schema: str) -> str:
    cleaned = raw_table.strip().strip("`").strip('"').lower()
    parts = [part.strip().strip("`").strip('"') for part in cleaned.split(".") if part.strip()]

    if len(parts) == 1:
        parts = [catalog.lower(), schema.lower(), parts[0]]
    elif len(parts) == 2:
        parts = [catalog.lower(), parts[0], parts[1]]
    elif len(parts) != 3:
        raise BackendConfigError(
            "DATABRICKS_ALLOWED_TABLES entries must use table, schema.table, or catalog.schema.table."
        )

    for part in parts:
        _validate_identifier(part, "DATABRICKS_ALLOWED_TABLES")

    return ".".join(parts)


def _parse_allowed_tables(catalog: str, schema: str) -> tuple[str, ...]:
    raw_value = _env("DATABRICKS_ALLOWED_TABLES")
    raw_tables = [table for table in raw_value.split(",") if table.strip()]
    if not raw_tables:
        raw_tables = list(DEFAULT_DATABRICKS_ALLOWED_TABLES)

    normalized = []
    for raw_table in raw_tables:
        table_name = _normalize_allowed_table(raw_table, catalog, schema)
        if table_name not in normalized:
            normalized.append(table_name)

    if not normalized:
        raise BackendConfigError("DATABRICKS_ALLOWED_TABLES must contain at least one table.")

    return tuple(normalized)


def load_databricks_config() -> DatabricksBackendConfig:
    auth_type = (_env("DATABRICKS_AUTH_TYPE") or "oauth_u2m").lower()
    auth_type = AUTH_TYPE_ALIASES.get(auth_type, auth_type)
    if auth_type not in SUPPORTED_DATABRICKS_AUTH_TYPES:
        supported = ", ".join(["oauth", *sorted(SUPPORTED_DATABRICKS_AUTH_TYPES)])
        raise BackendConfigError(f"Unsupported DATABRICKS_AUTH_TYPE. Use one of: {supported}.")

    required = [
        "DATABRICKS_SERVER_HOSTNAME",
        "DATABRICKS_HTTP_PATH",
        "DATABRICKS_CATALOG",
        "DATABRICKS_SCHEMA",
    ]
    missing = _missing(required)
    if auth_type == "pat" and not (_env("DATABRICKS_ACCESS_TOKEN") or _env("DATABRICKS_TOKEN")):
        missing.append("DATABRICKS_ACCESS_TOKEN or DATABRICKS_TOKEN")
    if auth_type == "oauth_m2m":
        missing.extend(_missing(["DATABRICKS_HOST", "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"]))

    if missing:
        raise BackendConfigError(
            "Missing Databricks configuration: " + ", ".join(dict.fromkeys(missing)) + "."
        )

    catalog = _env("DATABRICKS_CATALOG")
    schema = _env("DATABRICKS_SCHEMA")
    _validate_identifier(catalog, "DATABRICKS_CATALOG")
    _validate_identifier(schema, "DATABRICKS_SCHEMA")

    allowed_tables = _parse_allowed_tables(catalog, schema)
    scenario_allowed_tables = set(get_active_scenario().allowed_tables)
    disallowed_tables = [table for table in allowed_tables if table not in scenario_allowed_tables]
    if disallowed_tables:
        raise BackendConfigError(
            "DATABRICKS_ALLOWED_TABLES contains tables outside the active scenario allowlist: "
            + ", ".join(disallowed_tables)
            + "."
        )

    return DatabricksBackendConfig(
        auth_type=auth_type,
        server_hostname=_env("DATABRICKS_SERVER_HOSTNAME"),
        http_path=_env("DATABRICKS_HTTP_PATH"),
        catalog=catalog.lower(),
        schema=schema.lower(),
        allowed_tables=allowed_tables,
        access_token=_env("DATABRICKS_ACCESS_TOKEN") or _env("DATABRICKS_TOKEN"),
        host=_env("DATABRICKS_HOST"),
        client_id=_env("DATABRICKS_CLIENT_ID"),
        client_secret=_env("DATABRICKS_CLIENT_SECRET"),
    )


def load_backend_settings() -> BackendSettings:
    backend_name = get_configured_backend_name()
    if backend_name not in SUPPORTED_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_BACKENDS))
        raise BackendConfigError(f"Unsupported data scenario backend '{backend_name}'. Use one of: {supported}.")

    if backend_name == DATABRICKS_BACKEND:
        return BackendSettings(
            backend_name=backend_name,
            databricks=load_databricks_config(),
        )

    return BackendSettings(backend_name=POSTGRES_BACKEND)


def get_safe_backend_metadata() -> dict[str, object]:
    backend_name = get_configured_backend_name()
    scenario = get_active_scenario()
    metadata: dict[str, object] = {
        "backend_name": backend_name,
        "backend_display_name": scenario.backend_display_name,
        "scenario_id": scenario.scenario_id,
        "scenario_label": scenario.label,
        "semantic_layer": scenario.semantic_layer_filename,
        "dataset_id": scenario.dataset_id,
        "sql_dialect": scenario.sql_dialect,
        "auth_type": "",
        "allowed_tables": list(scenario.allowed_tables),
    }

    if backend_name == DATABRICKS_BACKEND:
        config = load_databricks_config()
        metadata["auth_type"] = config.auth_type
        metadata["allowed_tables"] = list(config.safe_allowed_tables)

    return metadata
