from app.db import get_connection


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


def get_schema_text() -> str:
    rows_by_table: dict[str, list[tuple[str, str]]] = {table: [] for table in TPC_H_TABLES}

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = ANY(%s)
                ORDER BY table_name, ordinal_position
                """,
                (TPC_H_TABLES,),
            )

            for table_name, column_name, data_type in cursor.fetchall():
                rows_by_table[table_name].append((column_name, data_type))

    missing_tables = [table for table, columns in rows_by_table.items() if not columns]
    if missing_tables:
        raise RuntimeError(
            "Missing expected PostgreSQL tables: "
            + ", ".join(missing_tables)
            + ". Load the TPC-H schema and CSV data first."
        )

    lines = ["PostgreSQL schema:"]
    for table_name in TPC_H_TABLES:
        lines.append(f"Table: {table_name}")
        for column_name, data_type in rows_by_table[table_name]:
            lines.append(f"  - {column_name}: {data_type}")

    return "\n".join(lines)
