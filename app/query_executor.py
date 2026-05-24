from app.db import get_connection


def run_explain(sql: str) -> list[str]:
    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"EXPLAIN {sql}")
                return [row[0] for row in cursor.fetchall()]
    except Exception as error:
        raise RuntimeError(str(error)) from error


def execute_sql(sql: str) -> tuple[list[str], list[tuple]]:
    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
                columns = [description.name for description in cursor.description]
                return columns, rows
    except Exception as error:
        raise RuntimeError(str(error)) from error
