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


def split_table_reference(table_reference: str) -> tuple[str, str]:
    parts = [part.strip().strip('"').lower() for part in table_reference.split(".") if part.strip()]
    if len(parts) == 1:
        return "public", parts[0]
    if len(parts) == 2:
        return parts[0], parts[1]
    raise ValueError(f"Unsupported PostgreSQL table reference: {table_reference}")


def get_schema_text_for_tables(table_references: list[str] | tuple[str, ...]) -> str:
    table_pairs = [split_table_reference(table_reference) for table_reference in table_references]
    rows_by_table: dict[str, list[tuple[str, str]]] = {
        table_reference: [] for table_reference in table_references
    }
    pair_to_reference = {
        (schema_name, table_name): table_reference
        for table_reference, (schema_name, table_name) in zip(table_references, table_pairs)
    }

    with get_connection() as connection:
        with connection.cursor() as cursor:
            where_clause = " OR ".join(["(table_schema = %s AND table_name = %s)"] * len(table_pairs))
            params = [value for pair in table_pairs for value in pair]
            cursor.execute(
                f"""
                SELECT table_schema, table_name, column_name, data_type
                FROM information_schema.columns
                WHERE {where_clause}
                ORDER BY table_schema, table_name, ordinal_position
                """,
                params,
            )

            for schema_name, table_name, column_name, data_type in cursor.fetchall():
                table_reference = pair_to_reference.get((schema_name, table_name))
                if table_reference:
                    rows_by_table[table_reference].append((column_name, data_type))

    missing_tables = [table for table, columns in rows_by_table.items() if not columns]
    if missing_tables:
        raise RuntimeError(
            "Erwartete PostgreSQL-Tabellen fehlen: "
            + ", ".join(missing_tables)
            + ". Lade zuerst die passenden CSV-Daten für das aktive Szenario."
        )

    lines = ["PostgreSQL schema:"]
    for table_reference in table_references:
        lines.append(f"Table: {table_reference}")
        for column_name, data_type in rows_by_table[table_reference]:
            lines.append(f"  - {column_name}: {data_type}")

    return "\n".join(lines)


def get_schema_text() -> str:
    return get_schema_text_for_tables(TPC_H_TABLES)
