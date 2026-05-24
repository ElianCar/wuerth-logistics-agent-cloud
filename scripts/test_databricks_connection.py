"""Run this only after manually starting the Databricks SQL Warehouse."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backends.databricks.databricks_adapter import DatabricksAdapter


def run_query(adapter: DatabricksAdapter, sql: str, label: str) -> None:
    result = adapter.execute_sql(sql)
    print(f"{label}: succeeded with {result['row_count']} row(s).")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    os.environ["DB_BACKEND"] = "databricks"

    adapter = DatabricksAdapter()
    adapter.test_connection()
    print("Databricks connection opened successfully.")

    run_query(adapter, "SELECT 1", "SELECT 1")
    run_query(
        adapter,
        "SELECT * FROM workspace.default.datenabzug_projekt_tum_shipments LIMIT 5",
        "Shipments sample",
    )
    run_query(
        adapter,
        "SELECT * FROM workspace.default.datenabzug_projekt_tum_invoices LIMIT 5",
        "Invoices sample",
    )


if __name__ == "__main__":
    main()

