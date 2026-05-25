"""Run this only after manually starting the Databricks SQL Warehouse."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backends.databricks.databricks_adapter import DatabricksAdapter


def run_query(adapter: DatabricksAdapter, sql: str, label: str) -> None:
    result = adapter.execute_sql(sql)
    print(f"{label}: succeeded with {result['row_count']} row(s).")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    os.environ["DATA_SCENARIO"] = "databricks"
    os.environ["SQL_BACKEND"] = "databricks"

    adapter = DatabricksAdapter()
    adapter.test_connection()
    print("Databricks connection opened successfully.")

    run_query(adapter, "SELECT 1", "SELECT 1")
    run_query(
        adapter,
        "SELECT COUNT(*) FROM workspace.default.datenabzug_projekt_tum_invoices",
        "Invoices reachability",
    )
    run_query(
        adapter,
        "SELECT COUNT(*) FROM workspace.default.datenabzug_projekt_tum_shipments",
        "Shipments reachability",
    )


if __name__ == "__main__":
    main()
