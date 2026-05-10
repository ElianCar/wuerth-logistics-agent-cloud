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

DESTRUCTIVE_KEYWORDS = {
    "ALTER",
    "COPY",
    "CREATE",
    "DELETE",
    "DROP",
    "GRANT",
    "INSERT",
    "REVOKE",
    "TRUNCATE",
    "UPDATE",
}

SQL_KEYWORDS = {
    "and",
    "as",
    "asc",
    "avg",
    "between",
    "by",
    "case",
    "cast",
    "count",
    "date_trunc",
    "desc",
    "distinct",
    "else",
    "end",
    "from",
    "group",
    "having",
    "in",
    "inner",
    "is",
    "join",
    "left",
    "limit",
    "max",
    "min",
    "not",
    "null",
    "on",
    "or",
    "order",
    "outer",
    "right",
    "round",
    "select",
    "sum",
    "then",
    "when",
    "where",
}


@dataclass(frozen=True)
class SQLValidationResult:
    sql: str
    is_valid: bool
    error: str
    used_tables: list[str]


def strip_trailing_semicolon(sql: str) -> str:
    cleaned = sql.strip()
    if cleaned.endswith(";"):
        return cleaned[:-1].strip()
    return cleaned


def parse_schema_columns(schema_context: str) -> dict[str, set[str]]:
    schema: dict[str, set[str]] = {}
    current_table = ""

    for raw_line in schema_context.splitlines():
        line = raw_line.strip()
        table_match = re.match(r"Table:\s+([a-zA-Z_][a-zA-Z0-9_]*)", line)
        if table_match:
            current_table = table_match.group(1).lower()
            schema.setdefault(current_table, set())
            continue

        column_match = re.match(r"-\s+([a-zA-Z_][a-zA-Z0-9_]*):", line)
        if current_table and column_match:
            schema[current_table].add(column_match.group(1).lower())

    return schema


def reject_markdown_or_explanation(raw_sql: str) -> str | None:
    stripped = raw_sql.strip()
    if "```" in stripped:
        return "Markdown fenced code is not allowed. Return SQL only."
    if "--" in stripped or "/*" in stripped or "*/" in stripped:
        return "SQL comments or explanations are not allowed. Return SQL only."
    forbidden_pattern = r"\b(" + "|".join(sorted(DESTRUCTIVE_KEYWORDS)) + r")\b"
    forbidden_match = re.search(forbidden_pattern, stripped, re.IGNORECASE)
    if forbidden_match:
        return f"Destructive operation is not allowed: {forbidden_match.group(1).upper()}."
    if not re.match(r"^\s*select\b", stripped, re.IGNORECASE):
        return "Only SQL starting with SELECT is allowed."

    semicolon_match = re.search(r";\s*\S+", stripped)
    if semicolon_match:
        return "Explanations or additional statements after SQL are not allowed."

    explanation_patterns = [
        r"\bhere is\b",
        r"\bexplanation\b",
        r"\bthis query\b",
        r"\bthe sql\b",
    ]
    for pattern in explanation_patterns:
        if re.search(pattern, stripped, re.IGNORECASE):
            return "Explanatory text is not allowed. Return SQL only."

    return None


def has_multiple_statements(sql: str) -> bool:
    parts = [part.strip() for part in sql.split(";") if part.strip()]
    return len(parts) > 1


def extract_referenced_tables(sql: str) -> set[str]:
    pattern = re.compile(
        r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)",
        re.IGNORECASE,
    )
    tables: set[str] = set()

    for match in pattern.finditer(sql):
        reference = match.group(1).strip('"').lower()
        table_name = reference.split(".")[-1].strip('"')
        if table_name not in SQL_KEYWORDS:
            tables.add(table_name)

    return tables


def extract_table_aliases(sql: str) -> dict[str, str]:
    pattern = re.compile(
        r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)"
        r"(?:\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?",
        re.IGNORECASE,
    )
    aliases: dict[str, str] = {}

    for match in pattern.finditer(sql):
        reference = match.group(1).strip('"').lower()
        table_name = reference.split(".")[-1].strip('"')
        alias = (match.group(2) or "").strip('"').lower()

        if table_name in SQL_KEYWORDS:
            continue

        aliases[table_name] = table_name
        if alias and alias not in SQL_KEYWORDS:
            aliases[alias] = table_name

    return aliases


def extract_used_tables(sql: str) -> list[str]:
    referenced_tables = extract_referenced_tables(sql)
    return [table for table in sorted(ALLOWED_TABLES) if table in referenced_tables]


def validate_known_columns(sql: str, schema_columns: dict[str, set[str]]) -> str | None:
    if not schema_columns:
        return None

    aliases = extract_table_aliases(sql)
    qualified_pattern = re.compile(
        r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b"
    )

    for alias, column in qualified_pattern.findall(sql):
        alias_name = alias.lower()
        column_name = column.lower()
        table_name = aliases.get(alias_name)

        if not table_name:
            continue

        known_columns = schema_columns.get(table_name, set())
        if known_columns and column_name not in known_columns:
            return f"Unknown column reference: {alias}.{column}."

    return None


def validate_generated_sql(raw_sql: str, schema_context: str = "") -> SQLValidationResult:
    format_error = reject_markdown_or_explanation(raw_sql)
    cleaned_sql = strip_trailing_semicolon(raw_sql)

    if format_error:
        return SQLValidationResult(cleaned_sql, False, format_error, [])

    if not cleaned_sql:
        return SQLValidationResult(cleaned_sql, False, "SQL is empty.", [])

    if has_multiple_statements(cleaned_sql):
        return SQLValidationResult(
            cleaned_sql,
            False,
            "Multiple SQL statements are not allowed.",
            [],
        )

    forbidden_pattern = r"\b(" + "|".join(sorted(DESTRUCTIVE_KEYWORDS)) + r")\b"
    forbidden_match = re.search(forbidden_pattern, cleaned_sql, re.IGNORECASE)
    if forbidden_match:
        return SQLValidationResult(
            cleaned_sql,
            False,
            f"Destructive operation is not allowed: {forbidden_match.group(1).upper()}.",
            [],
        )

    referenced_tables = extract_referenced_tables(cleaned_sql)
    unknown_tables = sorted(referenced_tables - ALLOWED_TABLES)
    if unknown_tables:
        return SQLValidationResult(
            cleaned_sql,
            False,
            "Unknown or disallowed table reference: " + ", ".join(unknown_tables) + ".",
            [],
        )

    if not referenced_tables:
        return SQLValidationResult(cleaned_sql, False, "No table reference found in SQL.", [])

    schema_columns = parse_schema_columns(schema_context)
    column_error = validate_known_columns(cleaned_sql, schema_columns)
    if column_error:
        return SQLValidationResult(
            cleaned_sql,
            False,
            column_error,
            extract_used_tables(cleaned_sql),
        )

    return SQLValidationResult(
        cleaned_sql,
        True,
        "",
        extract_used_tables(cleaned_sql),
    )
