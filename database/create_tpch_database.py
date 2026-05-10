from pathlib import Path

import duckdb


DATABASE_PATH = Path(__file__).resolve().parent / "tpch.duckdb"
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
SCALE_FACTORS_TO_TRY = [0.01, 0.1, 1.0]


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def create_database() -> None:
    if DATABASE_PATH.exists():
        DATABASE_PATH.unlink()

    print(f"Creating fresh DuckDB database: {DATABASE_PATH}")

    with duckdb.connect(str(DATABASE_PATH)) as connection:
        print("Installing and loading DuckDB TPC-H extension...")
        connection.execute("INSTALL tpch")
        connection.execute("LOAD tpch")

        last_error: Exception | None = None
        selected_scale_factor: float | None = None

        for scale_factor in SCALE_FACTORS_TO_TRY:
            try:
                print(f"Generating TPC-H tables with scale factor {scale_factor}...")
                connection.execute(f"CALL dbgen(sf={scale_factor})")
                selected_scale_factor = scale_factor
                break
            except Exception as error:
                last_error = error
                print(f"Scale factor {scale_factor} failed: {error}")

                for table_name in TPC_H_TABLES:
                    connection.execute(f"DROP TABLE IF EXISTS {quote_identifier(table_name)}")

        if selected_scale_factor is None:
            raise RuntimeError("Could not generate TPC-H data with any configured scale factor.") from last_error

        print(f"Generated TPC-H data with scale factor {selected_scale_factor}.")
        print()
        print("Row counts:")

        for table_name in TPC_H_TABLES:
            row_count = connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table_name)}"
            ).fetchone()[0]
            print(f"  {table_name}: {row_count:,}")

    print()
    print("Done.")


if __name__ == "__main__":
    create_database()
