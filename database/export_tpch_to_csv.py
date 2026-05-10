from pathlib import Path

import duckdb


DATABASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = DATABASE_DIR / "tpch.duckdb"
EXPORT_DIR = DATABASE_DIR / "exports"
TPC_H_TABLES = [
    "region",
    "nation",
    "supplier",
    "customer",
    "part",
    "partsupp",
    "orders",
    "lineitem",
]


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def export_tables() -> None:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database file not found: {DATABASE_PATH}. "
            "Run database/create_tpch_database.py first."
        )

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(DATABASE_PATH), read_only=True) as connection:
        row_counts: dict[str, int] = {}

        for table_name in TPC_H_TABLES:
            csv_path = EXPORT_DIR / f"{table_name}.csv"

            if csv_path.exists():
                csv_path.unlink()

            connection.execute(
                f"""
                COPY (SELECT * FROM {quote_identifier(table_name)})
                TO {quote_literal(str(csv_path))}
                WITH (FORMAT CSV, HEADER TRUE)
                """
            )

            row_count = connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table_name)}"
            ).fetchone()[0]
            row_counts[table_name] = row_count

    print(f"Exported TPC-H CSV files to: {EXPORT_DIR}")
    print()
    print("Row counts:")

    for table_name in TPC_H_TABLES:
        print(f"  {table_name}: {row_counts[table_name]:,}")


if __name__ == "__main__":
    export_tables()
