from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import psycopg
from psycopg import sql


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPORT_DIRS = (
    PROJECT_ROOT / "database" / "exports" / "wuerth",
    PROJECT_ROOT / "database" / "exports" / "Wuerth",
)
NULL_MARKERS = {"", "null", "none", "nan", "na", "n/a"}

FORCED_COLUMN_TYPES = {
    # invoices
    "order_date": "DATE",
    "order_entry_date": "DATE",
    "calendar_day": "TIMESTAMP",
    "turnover_inv": "NUMERIC",
    "freight_cost_inv": "NUMERIC",
    "invoice_quantity_in_sales_unit_inv": "BIGINT",
    # shipments
    "number_delivery_items": "BIGINT",
    "actual_quantity_delivered_in_sales_units": "NUMERIC",
    "freight_costs": "NUMERIC",
    "packing_costs": "NUMERIC",
    "shipment_date": "TIMESTAMP",
    "number_of_packages_per_delivery": "BIGINT",
    "number_of_pick_trays_of_shipment": "BIGINT",
}

REVENUE_COLUMN_CANDIDATES = {
    "revenue",
    "turnover",
    "turnover_inv",
    "invoice_revenue",
    "sales_amount",
    "net_revenue",
    "amount",
}
PACKING_COST_COLUMN_CANDIDATES = {
    "packing_cost",
    "packing_costs",
    "packing_cost_inv",
    "packaging_cost",
    "packaging_costs",
}


@dataclass(frozen=True)
class CsvTableSpec:
    logical_name: str
    table_name: str
    file_candidates: tuple[str, ...]
    expected_key_columns: tuple[str, ...]


@dataclass(frozen=True)
class CsvMetadata:
    path: Path
    original_columns: list[str]
    normalized_columns: list[str]
    column_types: dict[str, str]
    delimiter: str


TABLE_SPECS = (
    CsvTableSpec(
        logical_name="Invoices",
        table_name="invoices",
        file_candidates=(
            "Wuerth_invoices.csv",
            "wuerth_invoices.csv",
            "Invoices.csv",
            "invoices.csv",
            "datenabzug_projekt_tum_invoices.csv",
        ),
        expected_key_columns=("order_number", "customer", "material_price"),
    ),
    CsvTableSpec(
        logical_name="Shipments",
        table_name="shipments",
        file_candidates=(
            "Wuerth_shipments.csv",
            "wuerth_shipments.csv",
            "Shipments.csv",
            "shipments.csv",
            "datenabzug_projekt_tum_shipments.csv",
        ),
        expected_key_columns=("order_number", "shiptoparty", "customer_material"),
    ),
)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def normalize_column_name(raw_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", raw_name.strip().lower()).strip("_")
    if not normalized:
        normalized = "column"
    if normalized[0].isdigit():
        normalized = f"col_{normalized}"
    return normalized


def normalize_columns(raw_columns: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    normalized_columns = []
    for raw_column in raw_columns:
        base_name = normalize_column_name(raw_column)
        counter = seen.get(base_name, 0)
        seen[base_name] = counter + 1
        normalized_columns.append(base_name if counter == 0 else f"{base_name}_{counter + 1}")
    return normalized_columns


def is_nullish(value: str | None) -> bool:
    return value is None or value.strip().lower() in NULL_MARKERS


def detect_delimiter(path: Path) -> str:
    sample = path.read_text(encoding="utf-8-sig", errors="replace")[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def infer_column_types(columns: list[str]) -> dict[str, str]:
    return {column: FORCED_COLUMN_TYPES.get(column, "TEXT") for column in columns}


def find_export_dir(explicit_export_dir: str | None) -> Path | None:
    if explicit_export_dir:
        export_dir = Path(explicit_export_dir).expanduser().resolve()
        return export_dir if export_dir.exists() else None
    for export_dir in DEFAULT_EXPORT_DIRS:
        if export_dir.exists():
            return export_dir
    return None


def find_csv_file(export_dir: Path, spec: CsvTableSpec) -> Path | None:
    for file_name in spec.file_candidates:
        path = export_dir / file_name
        if path.exists():
            return path
    return None


def read_csv_metadata(path: Path) -> CsvMetadata:
    delimiter = detect_delimiter(path)
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.reader(file, delimiter=delimiter)
        try:
            original_columns = next(reader)
        except StopIteration as error:
            raise RuntimeError(f"Würth CSV file is empty: {path}") from error

    normalized_columns = normalize_columns(original_columns)
    column_types = infer_column_types(normalized_columns)
    return CsvMetadata(
        path=path,
        original_columns=original_columns,
        normalized_columns=normalized_columns,
        column_types=column_types,
        delimiter=delimiter,
    )


def postgres_connection() -> psycopg.Connection:
    connection_args = {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "dbname": os.getenv("POSTGRES_DB", "agentic_ai"),
        "user": os.getenv("POSTGRES_USER", "postgres"),
    }
    password = os.getenv("POSTGRES_PASSWORD", "")
    if password:
        connection_args["password"] = password
    return psycopg.connect(**connection_args)


def create_target_table(cursor: psycopg.Cursor, schema_name: str, table_name: str, metadata: CsvMetadata) -> None:
    column_definitions = [
        sql.SQL("{} {}").format(sql.Identifier(column), sql.SQL(metadata.column_types[column]))
        for column in metadata.normalized_columns
    ]
    cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema_name)))
    cursor.execute(
        sql.SQL("DROP TABLE IF EXISTS {}.{}").format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
        )
    )
    cursor.execute(
        sql.SQL("CREATE TABLE {}.{} ({})").format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
            sql.SQL(", ").join(column_definitions),
        )
    )


def normalized_row(row: list[str]) -> list[str | None]:
    return [None if is_nullish(value) else value.strip() for value in row]


def load_csv_rows(
    cursor: psycopg.Cursor,
    schema_name: str,
    table_name: str,
    metadata: CsvMetadata,
) -> int:
    copy_sql = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(schema_name),
        sql.Identifier(table_name),
        sql.SQL(", ").join(sql.Identifier(column) for column in metadata.normalized_columns),
    )
    row_count = 0
    with metadata.path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.reader(file, delimiter=metadata.delimiter)
        next(reader, None)
        with cursor.copy(copy_sql) as copy:
            for row in reader:
                if len(row) != len(metadata.normalized_columns):
                    raise RuntimeError(
                        f"{metadata.path} row {row_count + 2} has {len(row)} fields, "
                        f"expected {len(metadata.normalized_columns)}."
                    )
                copy.write_row(normalized_row(row))
                row_count += 1
    return row_count


def create_indexes(cursor: psycopg.Cursor, schema_name: str) -> None:
    cursor.execute(
        sql.SQL(
            "CREATE INDEX IF NOT EXISTS invoices_join_idx "
            "ON {}.{} (order_number, customer, material_price)"
        ).format(sql.Identifier(schema_name), sql.Identifier("invoices"))
    )
    cursor.execute(
        sql.SQL(
            "CREATE INDEX IF NOT EXISTS shipments_join_idx "
            "ON {}.{} (order_number, shiptoparty, customer_material)"
        ).format(sql.Identifier(schema_name), sql.Identifier("shipments"))
    )
    cursor.execute(
        sql.SQL("CREATE INDEX IF NOT EXISTS shipments_soldtoparty_idx ON {}.{} (soldtoparty)").format(
            sql.Identifier(schema_name),
            sql.Identifier("shipments"),
        )
    )


def log_metadata(spec: CsvTableSpec, metadata: CsvMetadata) -> None:
    logging.info("Detected %s CSV: %s", spec.logical_name, metadata.path)
    logging.info("Detected columns for %s: %s", spec.logical_name, ", ".join(metadata.normalized_columns))
    logging.info(
        "Detected PostgreSQL types for %s: %s",
        spec.logical_name,
        ", ".join(f"{column}={metadata.column_types[column]}" for column in metadata.normalized_columns),
    )
    missing_keys = [column for column in spec.expected_key_columns if column not in metadata.normalized_columns]
    if missing_keys:
        logging.warning("Missing expected %s key columns: %s", spec.logical_name, ", ".join(missing_keys))
    else:
        logging.info("Detected key columns for %s: %s", spec.logical_name, ", ".join(spec.expected_key_columns))

    if spec.table_name == "invoices" and not (set(metadata.normalized_columns) & REVENUE_COLUMN_CANDIDATES):
        logging.warning("No revenue or turnover column detected in invoices CSV.")
    if spec.table_name == "shipments" and not (set(metadata.normalized_columns) & PACKING_COST_COLUMN_CANDIDATES):
        logging.warning("No packing cost column detected in shipments CSV.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load local Würth CSV exports into PostgreSQL.")
    parser.add_argument("--export-dir", help="Directory containing the local Wuerth invoice and shipment CSV exports.")
    parser.add_argument("--schema", default="wuerth", help="Target PostgreSQL schema. Defaults to wuerth.")
    parser.add_argument(
        "--if-present",
        action="store_true",
        help="Exit successfully when the Würth export directory or CSV files are not present.",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()
    export_dir = find_export_dir(args.export_dir)
    if export_dir is None:
        message = "Würth export directory not found. Expected database/exports/wuerth or database/exports/Wuerth."
        if args.if_present:
            logging.warning(message)
            return 0
        logging.error(message)
        return 1

    metadata_by_table: dict[str, CsvMetadata] = {}
    for spec in TABLE_SPECS:
        csv_path = find_csv_file(export_dir, spec)
        if csv_path is None:
            message = f"{spec.logical_name} CSV not found in {export_dir}."
            if args.if_present:
                logging.warning(message)
                return 0
            logging.error(message)
            return 1
        metadata = read_csv_metadata(csv_path)
        metadata_by_table[spec.table_name] = metadata
        log_metadata(spec, metadata)

    with postgres_connection() as connection:
        with connection.cursor() as cursor:
            for spec in TABLE_SPECS:
                metadata = metadata_by_table[spec.table_name]
                create_target_table(cursor, args.schema, spec.table_name, metadata)
                row_count = load_csv_rows(cursor, args.schema, spec.table_name, metadata)
                logging.info("Loaded %s rows into %s.%s", row_count, args.schema, spec.table_name)
            create_indexes(cursor, args.schema)
        connection.commit()

    logging.info("Würth CSV ingestion completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
