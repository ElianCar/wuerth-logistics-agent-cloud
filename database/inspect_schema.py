from pathlib import Path

import duckdb


DATABASE_PATH = Path(__file__).resolve().parent / "tpch.duckdb"


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def get_table_names(connection: duckdb.DuckDBPyConnection) -> list[str]:
    rows = connection.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    ).fetchall()
    return [row[0] for row in rows]


def inspect_schema() -> None:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database file not found: {DATABASE_PATH}. "
            "Run create_tpch_database.py first."
        )

    with duckdb.connect(str(DATABASE_PATH), read_only=True) as connection:
        table_names = get_table_names(connection)

        print(f"Database: {DATABASE_PATH}")
        print()
        print("Tables:")

        for table_name in table_names:
            row_count = connection.execute(
                f"SELECT COUNT(*) FROM {quote_identifier(table_name)}"
            ).fetchone()[0]
            print(f"- {table_name} ({row_count:,} rows)")

        print()
        print("Schema:")

        for table_name in table_names:
            columns = connection.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'main'
                  AND table_name = ?
                ORDER BY ordinal_position
                """,
                [table_name],
            ).fetchall()

            print()
            print(table_name)
            for column_name, data_type in columns:
                print(f"  {column_name}: {data_type}")


if __name__ == "__main__":
    inspect_schema()
