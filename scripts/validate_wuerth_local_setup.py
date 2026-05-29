from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import get_connection
from src.agent.db import load_schema_context
from src.config.scenarios import SCENARIOS, load_semantic_layer_text, set_active_scenario_id


CSV_DIR_CANDIDATES = (
    PROJECT_ROOT / "database" / "exports" / "wuerth",
    PROJECT_ROOT / "database" / "exports" / "Wuerth",
)
DEMO_TABLES = ("region", "nation", "supplier", "customer", "part", "partsupp", "orders", "lineitem")
WUERTH_TABLES = ("wuerth.invoices", "wuerth.shipments")


class ValidationError(RuntimeError):
    pass


def read_csv_header(path: Path) -> list[str]:
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.reader(file)
        try:
            return next(reader)
        except StopIteration as error:
            raise ValidationError(f"CSV file is empty: {path}") from error


def find_csv_dir() -> Path:
    for path in CSV_DIR_CANDIDATES:
        if path.exists():
            return path
    raise ValidationError("Würth CSV directory not found under database/exports/wuerth or database/exports/Wuerth.")


def normalize_column(column: str) -> str:
    return column.strip().lower()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def table_columns_from_db(table_reference: str) -> set[str]:
    parts = table_reference.split(".")
    if len(parts) == 1:
        schema_name, table_name = "public", parts[0]
    elif len(parts) == 2:
        schema_name, table_name = parts
    else:
        raise ValidationError(f"Unsupported PostgreSQL table reference: {table_reference}")

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = %s
                ORDER BY ordinal_position
                """,
                (schema_name, table_name),
            )
            return {str(row[0]).lower() for row in cursor.fetchall()}


def table_row_count(table_reference: str) -> int:
    parts = table_reference.split(".")
    if len(parts) == 1:
        qualified_name = f'"{parts[0]}"'
    elif len(parts) == 2:
        qualified_name = f'"{parts[0]}"."{parts[1]}"'
    else:
        raise ValidationError(f"Unsupported PostgreSQL table reference: {table_reference}")

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {qualified_name}")
            return int(cursor.fetchone()[0])


def load_wuerth_semantic_layer() -> dict[str, Any]:
    path = SCENARIOS["wuerth_local"].semantic_layer_path
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    require(isinstance(data, dict), f"Semantic layer must be a mapping: {path}")
    return data


def validate_csv_files() -> tuple[set[str], set[str]]:
    csv_dir = find_csv_dir()
    invoices_path = csv_dir / "Wuerth_invoices.csv"
    shipments_path = csv_dir / "Wuerth_shipments.csv"
    require(invoices_path.exists(), f"Missing invoices CSV: {invoices_path}")
    require(shipments_path.exists(), f"Missing shipments CSV: {shipments_path}")

    invoice_columns = {normalize_column(column) for column in read_csv_header(invoices_path)}
    shipment_columns = {normalize_column(column) for column in read_csv_header(shipments_path)}
    require(invoice_columns, "Invoices CSV has no header columns.")
    require(shipment_columns, "Shipments CSV has no header columns.")
    return invoice_columns, shipment_columns


def validate_scenarios() -> None:
    require(SCENARIOS["demo"].backend_name == "postgres", "Demo scenario must use PostgreSQL.")
    require(SCENARIOS["wuerth_local"].backend_name == "postgres", "Würth local scenario must use PostgreSQL.")
    require(SCENARIOS["demo"].allowed_tables == DEMO_TABLES, "Demo allowed tables changed unexpectedly.")
    require(SCENARIOS["wuerth_local"].allowed_tables == WUERTH_TABLES, "Würth local allowed tables are wrong.")

    set_active_scenario_id("demo")
    demo_semantic = load_semantic_layer_text()
    require("lineitem" in demo_semantic, "Demo semantic layer did not load expected TPC-H content.")

    set_active_scenario_id("wuerth_local")
    wuerth_semantic = load_semantic_layer_text()
    require("wuerth.invoices" in wuerth_semantic, "Würth semantic layer did not load local PostgreSQL table names.")


def validate_semantic_layer(invoice_csv_columns: set[str], shipment_csv_columns: set[str]) -> None:
    semantic = load_wuerth_semantic_layer()
    active_path = SCENARIOS["wuerth_local"].semantic_layer_path.resolve()
    duplicate_paths = [
        path.resolve()
        for path in (PROJECT_ROOT / "semantic_layer").glob("**/*wuerth*semantic_layer*.yaml")
        if path.resolve() != active_path
    ]
    require(not duplicate_paths, f"Unused duplicate Würth semantic layer files found: {duplicate_paths}")

    execution = semantic.get("execution", {})
    require(execution.get("target_platform") == "postgresql", "Würth local semantic layer must target PostgreSQL.")
    require(tuple(execution.get("allowed_tables", [])) == WUERTH_TABLES, "Würth semantic allowed tables are wrong.")

    tables = semantic.get("tables", {})
    require("invoices" in tables, "Semantic layer is missing invoices table.")
    require("shipments" in tables, "Semantic layer is missing shipments table.")

    invoice_semantic_columns = set((tables["invoices"].get("columns") or {}).keys())
    shipment_semantic_columns = set((tables["shipments"].get("columns") or {}).keys())
    require(invoice_semantic_columns <= invoice_csv_columns, f"Invoice semantic layer references missing CSV columns: {sorted(invoice_semantic_columns - invoice_csv_columns)}")
    require(shipment_semantic_columns <= shipment_csv_columns, f"Shipment semantic layer references missing CSV columns: {sorted(shipment_semantic_columns - shipment_csv_columns)}")

    join = (semantic.get("joins") or {}).get("invoices_to_shipments", {})
    conditions = join.get("join_condition", [])
    condition_pairs = {(item.get("left_column"), item.get("right_column")) for item in conditions if isinstance(item, dict)}
    require(("order_number", "order_number") in condition_pairs, "Join mapping for Order Number is missing.")
    require(("customer", "shiptoparty") in condition_pairs, "Join mapping for Customer to Ship to Party is missing.")
    require(("material_price", "customer_material") in condition_pairs, "Join mapping for material key candidate is missing.")

    invoice_kpis = ((semantic.get("kpis") or {}).get("invoice_kpis") or {})
    shipment_kpis = ((semantic.get("kpis") or {}).get("shipment_kpis") or {})
    require(
        invoice_kpis.get("revenue", {}).get("status") == "not_supported_with_current_local_csv",
        "Revenue must be marked unsupported until a real invoice revenue column exists.",
    )
    require(
        shipment_kpis.get("packing_costs", {}).get("status") == "not_supported_with_current_local_csv",
        "Packing costs must be marked unsupported until a real shipment packing cost column exists.",
    )
    require("freight_costs" in shipment_semantic_columns, "Freight cost column must be present in shipment semantic layer.")


def validate_database() -> None:
    for table in DEMO_TABLES:
        row_count = table_row_count(table)
        require(row_count > 0, f"Demo table {table} is empty.")
    for table in WUERTH_TABLES:
        row_count = table_row_count(table)
        require(row_count > 0, f"Würth table {table} is empty.")

    for table in WUERTH_TABLES:
        columns = table_columns_from_db(table)
        require(columns, f"Würth table {table} has no columns.")

    set_active_scenario_id("demo")
    demo_context = load_schema_context()
    require("Table: lineitem" in demo_context, "Demo schema context does not expose lineitem.")
    require("Table: wuerth.invoices" not in demo_context, "Demo schema context leaks Würth tables.")

    set_active_scenario_id("wuerth_local")
    wuerth_context = load_schema_context()
    require("Table: wuerth.invoices" in wuerth_context, "Würth schema context does not expose wuerth.invoices.")
    require("Table: lineitem" not in wuerth_context, "Würth schema context leaks demo tables.")
    require("wuerth.invoices" in wuerth_context, "SQL agent did not load updated Würth semantic layer.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate local Würth PostgreSQL scenario setup.")
    parser.add_argument("--skip-db", action="store_true", help="Skip PostgreSQL table and schema-context checks.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        invoice_columns, shipment_columns = validate_csv_files()
        validate_scenarios()
        validate_semantic_layer(invoice_columns, shipment_columns)
        if not args.skip_db:
            validate_database()
    except ValidationError as error:
        print(f"FAILED: {error}")
        return 1
    except Exception as error:
        print(f"FAILED: {type(error).__name__}: {error}")
        return 1

    print("OK: Würth local scenario validation passed.")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("DATA_SCENARIO", "demo")
    sys.exit(main())
