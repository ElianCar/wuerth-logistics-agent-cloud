from __future__ import annotations

from typing import Any, Callable

from src.backends.config import DatabricksBackendConfig, load_databricks_config
from src.config.scenarios import get_active_scenario, load_semantic_layer_text


ConnectFunc = Callable[..., Any]


class DatabricksAdapter:
    def __init__(
        self,
        config: DatabricksBackendConfig | None = None,
        connect_func: ConnectFunc | None = None,
    ) -> None:
        self.config = config or load_databricks_config()
        self._connect_func = connect_func

    def get_backend_name(self) -> str:
        return "databricks"

    def get_sql_dialect(self) -> str:
        return "Databricks SQL"

    def _default_connect_func(self) -> ConnectFunc:
        try:
            from databricks import sql
        except ImportError as error:
            raise RuntimeError(
                "Databricks SQL connector is not installed. "
                "Install project requirements before using DATA_SCENARIO=databricks."
            ) from error
        return sql.connect

    def _connect(self) -> Any:
        connect_func = self._connect_func or self._default_connect_func()
        config = self.config
        kwargs: dict[str, Any] = {
            "server_hostname": config.server_hostname,
            "http_path": config.http_path,
        }

        if config.auth_type == "oauth_u2m":
            kwargs["auth_type"] = "databricks-oauth"
        elif config.auth_type == "pat":
            kwargs["access_token"] = config.access_token
        elif config.auth_type == "oauth_m2m":
            try:
                from databricks.sdk.core import Config, oauth_service_principal
            except ImportError as error:
                raise RuntimeError(
                    "Databricks SDK is not installed. "
                    "Install project requirements before using OAuth M2M authentication."
                ) from error

            sdk_config = Config(
                host=config.host,
                client_id=config.client_id,
                client_secret=config.client_secret,
            )
            kwargs["credentials_provider"] = oauth_service_principal(sdk_config)
        else:
            raise RuntimeError("Unsupported Databricks authentication mode.")

        return connect_func(**kwargs)

    def test_connection(self) -> dict[str, Any]:
        try:
            with self._connect():
                return {
                    "ok": True,
                    "backend_name": self.get_backend_name(),
                    "sql_dialect": self.get_sql_dialect(),
                    "auth_type": self.config.auth_type,
                }
        except RuntimeError:
            raise
        except Exception as error:
            raise _safe_databricks_error("Databricks connection test failed.", error) from error

    def load_schema_context(self) -> str:
        rows_by_table: dict[str, list[tuple[str, str]]] = {
            table_name: [] for table_name in self.config.allowed_tables
        }
        short_to_full = {
            table_name.split(".")[-1]: table_name for table_name in self.config.allowed_tables
        }

        catalog = _quote_identifier(self.config.catalog)
        schema_literal = _quote_literal(self.config.schema)
        table_literals = ", ".join(
            _quote_literal(table_name) for table_name in self.config.short_allowed_tables
        )
        query = f"""
        SELECT table_name, column_name, data_type
        FROM {catalog}.information_schema.columns
        WHERE table_schema = {schema_literal}
          AND table_name IN ({table_literals})
        ORDER BY table_name, ordinal_position
        """

        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(query)
                    for table_name, column_name, data_type in cursor.fetchall():
                        normalized_table = str(table_name).lower()
                        full_table_name = short_to_full.get(normalized_table)
                        if full_table_name:
                            rows_by_table[full_table_name].append((str(column_name), str(data_type)))
        except RuntimeError:
            raise
        except Exception as error:
            raise _safe_databricks_error("Databricks schema loading failed.", error) from error

        missing_tables = [table for table, columns in rows_by_table.items() if not columns]
        if missing_tables:
            raise RuntimeError(
                "Configured Databricks tables are missing or not visible to the current user: "
                + ", ".join(missing_tables)
                + "."
            )

        scenario = get_active_scenario()
        semantic_layer_text = load_semantic_layer_text(scenario)
        lines = [
            f"Scenario: {scenario.scenario_id}",
            f"Dataset ID: {scenario.dataset_id}",
            "Backend: databricks",
            "SQL dialect: Databricks SQL",
            "",
            "Databricks SQL schema:",
        ]
        for table_name in self.config.allowed_tables:
            lines.append(f"Table: {table_name}")
            for column_name, data_type in rows_by_table[table_name]:
                lines.append(f"  - {column_name}: {data_type}")

        lines.extend(["", "Semantic layer:", semantic_layer_text])
        return "\n".join(lines)

    def execute_sql(self, sql: str, user_question: str = "") -> dict[str, Any]:
        executed_sql = sql.strip().rstrip(";").strip()
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(executed_sql)
                    rows = cursor.fetchall()
                    columns = _column_names(cursor.description)
        except RuntimeError:
            raise
        except Exception as error:
            raise _safe_databricks_error("Databricks SQL execution failed.", error) from error

        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "executed_sql": executed_sql,
            "limit_applied": False,
        }

    def get_safe_metadata(self) -> dict[str, object]:
        return {
            "backend_name": self.get_backend_name(),
            "backend_display_name": "Databricks SQL Warehouse",
            "scenario_id": "databricks",
            "scenario_label": "Würth Databricks",
            "sql_dialect": self.get_sql_dialect(),
            "auth_type": self.config.auth_type,
            "semantic_layer": get_active_scenario().semantic_layer_filename,
            "dataset_id": get_active_scenario().dataset_id,
            "allowed_tables": list(self.config.safe_allowed_tables),
        }


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace("`", "``")
    return f"`{escaped}`"


def _quote_literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _column_names(description: Any) -> list[str]:
    if not description:
        return []

    columns = []
    for column in description:
        name = getattr(column, "name", None)
        if name is None and isinstance(column, (tuple, list)) and column:
            name = column[0]
        columns.append(str(name))
    return columns


def _safe_databricks_error(message: str, error: Exception) -> RuntimeError:
    return RuntimeError(
        f"{message} Check credentials, warehouse state, and allowed tables. "
        f"Connector error type: {type(error).__name__}."
    )
