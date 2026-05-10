from app.db import get_connection


MAX_RESULT_ROWS = 50


def run_explain(sql: str) -> list[str]:
    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"EXPLAIN {sql}")
                return [row[0] for row in cursor.fetchall()]
    except Exception as error:
        raise RuntimeError(str(error)) from error


def execute_sql(sql: str, max_rows: int = MAX_RESULT_ROWS) -> tuple[list[str], list[tuple]]:
    limited_sql = sql
    if "limit" not in sql.lower():
        limited_sql = f"SELECT * FROM ({sql}) AS generated_query LIMIT {max_rows}"

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(limited_sql)
                rows = cursor.fetchmany(max_rows)
                columns = [description.name for description in cursor.description]
                return columns, rows
    except Exception as error:
        raise RuntimeError(str(error)) from error
