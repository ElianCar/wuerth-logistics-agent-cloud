from dataclasses import dataclass
import re


ALLOWED_TABLES = {
    "region",
    "nation",
    "supplier",
    "customer",
    "part",
    "partsupp",
    "orders",
    "lineitem",
}
FORBIDDEN_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "CREATE",
    "MERGE",
    "TRUNCATE",
    "COPY",
    "GRANT",
    "REVOKE",
}
SQL_KEYWORDS_ALLOWED_AFTER_FROM_OR_JOIN = {
    "select",
    "where",
    "group",
    "order",
    "limit",
    "having",
    "on",
    "using",
    "inner",
    "left",
    "right",
    "full",
    "outer",
    "cross",
}


@dataclass(frozen=True)
class ValidationResult:
    sql: str
    is_valid: bool
    message: str


def strip_markdown_code_fences(sql: str) -> str:
    cleaned = sql.strip()

    fenced_match = re.search(r"```(?:sql|postgresql)?\s*(.*?)\s*```", cleaned, re.IGNORECASE | re.DOTALL)
    if fenced_match:
        cleaned = fenced_match.group(1).strip()

    return cleaned


def strip_sql_comments(sql: str) -> str:
    without_block_comments = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--.*?$", " ", without_block_comments, flags=re.MULTILINE)


def has_multiple_statements(sql: str) -> bool:
    without_comments = strip_sql_comments(sql)
    parts = [part.strip() for part in without_comments.split(";") if part.strip()]
    return len(parts) > 1


def extract_referenced_tables(sql: str) -> set[str]:
    without_comments = strip_sql_comments(sql)
    pattern = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)", re.IGNORECASE)
    tables: set[str] = set()

    for match in pattern.finditer(without_comments):
        table_reference = match.group(1).strip('"').lower()
        table_name = table_reference.split(".")[-1].strip('"')

        if table_name not in SQL_KEYWORDS_ALLOWED_AFTER_FROM_OR_JOIN:
            tables.add(table_name)

    return tables


def extract_used_tables(sql: str) -> list[str]:
    without_comments = strip_sql_comments(sql).lower()
    return [
        table
        for table in sorted(ALLOWED_TABLES)
        if re.search(rf"\b{re.escape(table)}\b", without_comments)
    ]


def validate_sql(raw_sql: str) -> ValidationResult:
    cleaned_sql = strip_markdown_code_fences(raw_sql).strip()

    if cleaned_sql.endswith(";"):
        cleaned_sql = cleaned_sql[:-1].strip()

    if not cleaned_sql:
        return ValidationResult(cleaned_sql, False, "SQL is empty.")

    if has_multiple_statements(cleaned_sql):
        return ValidationResult(cleaned_sql, False, "Multiple SQL statements are not allowed.")

    without_comments = strip_sql_comments(cleaned_sql)

    if not re.match(r"^\s*select\b", without_comments, re.IGNORECASE):
        return ValidationResult(cleaned_sql, False, "Only SELECT queries are allowed.")

    forbidden_pattern = r"\b(" + "|".join(sorted(FORBIDDEN_KEYWORDS)) + r")\b"
    forbidden_match = re.search(forbidden_pattern, without_comments, re.IGNORECASE)
    if forbidden_match:
        return ValidationResult(
            cleaned_sql,
            False,
            f"Forbidden keyword found: {forbidden_match.group(1).upper()}.",
        )

    referenced_tables = extract_referenced_tables(cleaned_sql)
    unknown_tables = sorted(referenced_tables - ALLOWED_TABLES)
    if unknown_tables:
        return ValidationResult(
            cleaned_sql,
            False,
            "Query references tables outside the allowed TPC-H tables: "
            + ", ".join(unknown_tables)
            + ".",
        )

    if not referenced_tables:
        return ValidationResult(cleaned_sql, False, "No table reference found in SQL.")

    return ValidationResult(cleaned_sql, True, "SQL passed local validation.")
