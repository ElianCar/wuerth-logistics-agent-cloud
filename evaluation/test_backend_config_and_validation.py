from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.agent.sql_validator import validate_generated_sql
from src.backends.config import BackendConfigError, load_backend_settings, load_databricks_config
from src.backends.databricks.databricks_adapter import DatabricksAdapter
from src.backends.config import DatabricksBackendConfig
from src.backends.demo.postgres_adapter import PostgresAdapter
from src.config.scenarios import reset_active_scenario_id


DATABRICKS_SCHEMA_CONTEXT = """Backend: databricks
SQL dialect: Databricks SQL

Databricks SQL schema:
Table: workspace.default.datenabzug_projekt_tum_shipments
  - shipment_id: string
  - created_at: timestamp
Table: workspace.default.datenabzug_projekt_tum_invoices
  - invoice_id: string
  - amount: double

Semantic layer:
(none configured for Databricks backend)
"""


def databricks_env(**overrides: str) -> dict[str, str]:
    env = {
        "DATA_SCENARIO": "databricks",
        "SQL_BACKEND": "databricks",
        "DATABRICKS_AUTH_TYPE": "oauth_u2m",
        "DATABRICKS_SERVER_HOSTNAME": "placeholder-host",
        "DATABRICKS_HTTP_PATH": "placeholder-path",
        "DATABRICKS_CATALOG": "workspace",
        "DATABRICKS_SCHEMA": "default",
        "DATABRICKS_ALLOWED_TABLES": (
            "workspace.default.datenabzug_projekt_tum_shipments,"
            "datenabzug_projekt_tum_invoices"
        ),
    }
    env.update(overrides)
    return env


class FakeCursor:
    description = [("one",)]

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.sql = sql

    def fetchall(self) -> list[tuple[int]]:
        return [(1,)]


class FakeConnection:
    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return FakeCursor()


def raise_connection_error(**_kwargs: object) -> FakeConnection:
    raise ValueError("sensitive-host sensitive-http-path sensitive-token")


class BackendConfigAndValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_active_scenario_id()

    def tearDown(self) -> None:
        reset_active_scenario_id()

    def test_unset_scenario_defaults_to_demo_postgres(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = load_backend_settings()

        self.assertEqual(settings.backend_name, "postgres")

    def test_demo_scenario_selects_postgres_backend(self) -> None:
        with patch.dict(os.environ, {"DATA_SCENARIO": "demo"}, clear=True):
            settings = load_backend_settings()
        self.assertEqual(settings.backend_name, "postgres")

    def test_wuerth_local_scenario_selects_postgres_backend(self) -> None:
        with patch.dict(os.environ, {"DATA_SCENARIO": "wuerth_local"}, clear=True):
            settings = load_backend_settings()
        self.assertEqual(settings.backend_name, "postgres")

    def test_databricks_missing_required_values_returns_safe_error(self) -> None:
        with patch.dict(os.environ, {"DATA_SCENARIO": "databricks"}, clear=True):
            with self.assertRaises(BackendConfigError) as context:
                load_backend_settings()

        message = str(context.exception)
        self.assertIn("Missing Databricks configuration", message)
        self.assertIn("DATABRICKS_SERVER_HOSTNAME", message)
        self.assertNotIn("placeholder-host", message)

    def test_databricks_oauth_u2m_config_does_not_require_pat(self) -> None:
        with patch.dict(os.environ, databricks_env(), clear=True):
            config = load_databricks_config()

        self.assertEqual(config.auth_type, "oauth_u2m")
        self.assertEqual(
            config.allowed_tables,
            (
                "workspace.default.datenabzug_projekt_tum_shipments",
                "workspace.default.datenabzug_projekt_tum_invoices",
            ),
        )
        self.assertEqual(config.access_token, "")

    def test_databricks_oauth_m2m_requires_service_principal_values(self) -> None:
        with patch.dict(os.environ, databricks_env(DATABRICKS_AUTH_TYPE="oauth_m2m"), clear=True):
            with self.assertRaises(BackendConfigError) as context:
                load_databricks_config()

        message = str(context.exception)
        self.assertIn("DATABRICKS_CLIENT_ID", message)
        self.assertIn("DATABRICKS_CLIENT_SECRET", message)

    def test_validator_allows_approved_databricks_table_forms(self) -> None:
        sql_forms = [
            "SELECT shipment_id FROM workspace.default.datenabzug_projekt_tum_shipments LIMIT 50",
            "SELECT s.shipment_id FROM default.datenabzug_projekt_tum_shipments AS s LIMIT 50",
            "SELECT shipment_id FROM datenabzug_projekt_tum_shipments LIMIT 50",
        ]

        for sql in sql_forms:
            with self.subTest(sql=sql):
                result = validate_generated_sql(sql, DATABRICKS_SCHEMA_CONTEXT)
                self.assertTrue(result.is_valid, result.error)

    def test_validator_blocks_non_allowed_databricks_table(self) -> None:
        result = validate_generated_sql(
            "SELECT * FROM workspace.default.some_other_table",
            DATABRICKS_SCHEMA_CONTEXT,
        )

        self.assertFalse(result.is_valid)
        self.assertIn("Unbekannte oder nicht erlaubte Tabellenreferenz", result.error)

    def test_validator_blocks_tpch_tables_in_databricks_context(self) -> None:
        result = validate_generated_sql(
            "SELECT COUNT(*) FROM lineitem",
            DATABRICKS_SCHEMA_CONTEXT,
        )

        self.assertFalse(result.is_valid)
        self.assertIn("Unbekannte oder nicht erlaubte Tabellenreferenz", result.error)

    def test_validator_allows_invoice_aggregation_in_databricks_context(self) -> None:
        result = validate_generated_sql(
            "SELECT SUM(amount) AS total_amount FROM workspace.default.datenabzug_projekt_tum_invoices",
            DATABRICKS_SCHEMA_CONTEXT,
        )

        self.assertTrue(result.is_valid, result.error)

    def test_validator_blocks_destructive_sql(self) -> None:
        result = validate_generated_sql(
            "MERGE INTO workspace.default.datenabzug_projekt_tum_shipments USING source ON 1 = 1",
            DATABRICKS_SCHEMA_CONTEXT,
        )

        self.assertFalse(result.is_valid)

    def test_validator_blocks_unlimited_row_level_query(self) -> None:
        result = validate_generated_sql(
            "SELECT shipment_id FROM workspace.default.datenabzug_projekt_tum_shipments",
            DATABRICKS_SCHEMA_CONTEXT,
        )

        self.assertFalse(result.is_valid)
        self.assertIn("LIMIT 50", result.error)

    def test_validator_allows_literal_limitation_message(self) -> None:
        result = validate_generated_sql(
            "SELECT 'S24 compliance is unsupported because required SLA columns are missing.' AS limitation",
            DATABRICKS_SCHEMA_CONTEXT,
        )

        self.assertTrue(result.is_valid, result.error)
        self.assertEqual(result.used_tables, [])

    def test_postgres_adapter_wraps_existing_backend(self) -> None:
        adapter = PostgresAdapter()

        self.assertEqual(adapter.get_backend_name(), "postgres")
        self.assertEqual(adapter.get_sql_dialect(), "PostgreSQL")

    def test_databricks_adapter_can_execute_with_mocked_connection(self) -> None:
        config = DatabricksBackendConfig(
            auth_type="oauth_u2m",
            server_hostname="placeholder-host",
            http_path="placeholder-path",
            catalog="workspace",
            schema="default",
            allowed_tables=("workspace.default.datenabzug_projekt_tum_shipments",),
        )
        adapter = DatabricksAdapter(
            config=config,
            connect_func=lambda **_kwargs: FakeConnection(),
        )

        result = adapter.execute_sql("SELECT 1")

        self.assertEqual(adapter.get_backend_name(), "databricks")
        self.assertEqual(adapter.get_sql_dialect(), "Databricks SQL")
        self.assertEqual(result["columns"], ["one"])
        self.assertEqual(result["rows"], [(1,)])

    def test_databricks_adapter_sanitizes_connection_errors(self) -> None:
        config = DatabricksBackendConfig(
            auth_type="oauth_u2m",
            server_hostname="placeholder-host",
            http_path="placeholder-path",
            catalog="workspace",
            schema="default",
            allowed_tables=("workspace.default.datenabzug_projekt_tum_shipments",),
        )
        adapter = DatabricksAdapter(config=config, connect_func=raise_connection_error)

        with self.assertRaises(RuntimeError) as context:
            adapter.execute_sql("SELECT 1")

        message = str(context.exception)
        self.assertIn("Databricks SQL execution failed", message)
        self.assertNotIn("sensitive-host", message)
        self.assertNotIn("sensitive-http-path", message)
        self.assertNotIn("sensitive-token", message)


if __name__ == "__main__":
    unittest.main()
