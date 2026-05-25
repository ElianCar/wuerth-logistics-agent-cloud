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
    "CALL",
    "COPY",
    "CREATE",
    "DELETE",
    "DROP",
    "EXEC",
    "EXECUTE",
    "GRANT",
    "INSERT",
    "MERGE",
    "REVOKE",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
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
    "cross",
    "date_trunc",
    "desc",
    "distinct",
    "else",
    "end",
    "from",
    "full",
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
    "using",
    "when",
    "where",
    "with",
    "try_cast",
    "to_date",
    "concat_ws",
    "decimal",
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


def normalize_table_reference(reference: str) -> str:
    parts = [
        part.strip().strip('"').strip("`").lower()
        for part in reference.split(".")
        if part.strip()
    ]
    return ".".join(parts)


def short_table_name(reference: str) -> str:
    return normalize_table_reference(reference).split(".")[-1]


def table_reference_forms(reference: str) -> set[str]:
    normalized = normalize_table_reference(reference)
    parts = normalized.split(".")
    forms = {normalized, parts[-1]}
    if len(parts) == 3:
        forms.add(".".join(parts[1:]))
    return forms


def parse_schema_table_names(schema_context: str) -> list[str]:
    table_names = []
    for raw_line in schema_context.splitlines():
        line = raw_line.strip()
        table_match = re.match(
            r"Table:\s+([`\"]?[a-zA-Z_][a-zA-Z0-9_]*[`\"]?(?:\.[`\"]?[a-zA-Z_][a-zA-Z0-9_]*[`\"]?){0,2})",
            line,
        )
        if table_match:
            table_names.append(normalize_table_reference(table_match.group(1)))
    return table_names


def build_allowed_table_map(schema_context: str) -> dict[str, str]:
    schema_tables = parse_schema_table_names(schema_context)
    if not schema_tables:
        schema_tables = sorted(ALLOWED_TABLES)

    allowed: dict[str, str] = {}
    for table_name in schema_tables:
        for form in table_reference_forms(table_name):
            allowed[form] = table_name
    return allowed


def parse_schema_columns(schema_context: str) -> dict[str, set[str]]:
    schema: dict[str, set[str]] = {}
    current_table = ""

    for raw_line in schema_context.splitlines():
        line = raw_line.strip()
        table_match = re.match(
            r"Table:\s+([`\"]?[a-zA-Z_][a-zA-Z0-9_]*[`\"]?(?:\.[`\"]?[a-zA-Z_][a-zA-Z0-9_]*[`\"]?){0,2})",
            line,
        )
        if table_match:
            current_table = normalize_table_reference(table_match.group(1))
            schema.setdefault(current_table, set())
            schema.setdefault(short_table_name(current_table), set())
            continue

        column_match = re.match(r"-\s+([a-zA-Z_][a-zA-Z0-9_]*):", line)
        if current_table and column_match:
            column_name = column_match.group(1).lower()
            schema[current_table].add(column_name)
            schema[short_table_name(current_table)].add(column_name)

    return schema


def reject_markdown_or_explanation(raw_sql: str) -> str | None:
    stripped = raw_sql.strip()
    if "```" in stripped:
        return "Markdown-Codeblöcke sind nicht erlaubt. Bitte nur SQL ausgeben."
    if "--" in stripped or "/*" in stripped or "*/" in stripped:
        return "SQL-Kommentare oder Erklärungen sind nicht erlaubt. Bitte nur SQL ausgeben."
    forbidden_pattern = r"\b(" + "|".join(sorted(DESTRUCTIVE_KEYWORDS)) + r")\b"
    forbidden_match = re.search(forbidden_pattern, stripped, re.IGNORECASE)
    if forbidden_match:
        return f"Destruktive Operation ist nicht erlaubt: {forbidden_match.group(1).upper()}."
    if not re.match(r"^\s*(select|with)\b", stripped, re.IGNORECASE):
        return "Nur read-only SELECT-Abfragen sind erlaubt."

    semicolon_match = re.search(r";\s*\S+", stripped)
    if semicolon_match:
        return "Erklärungen oder zusätzliche Statements nach dem SQL sind nicht erlaubt."

    explanation_patterns = [
        r"\bhere is\b",
        r"\bexplanation\b",
        r"\bthis query\b",
        r"\bthe sql\b",
    ]
    for pattern in explanation_patterns:
        if re.search(pattern, stripped, re.IGNORECASE):
            return "Erklärender Text ist nicht erlaubt. Bitte nur SQL ausgeben."

    return None


def has_multiple_statements(sql: str) -> bool:
    parts = [part.strip() for part in sql.split(";") if part.strip()]
    return len(parts) > 1


def mask_non_table_from_clauses(sql: str) -> str:
    return re.sub(
        r"\bextract\s*\(\s*[a-zA-Z_][a-zA-Z0-9_]*\s+from\s+[a-zA-Z_][a-zA-Z0-9_\.]*\s*\)",
        "extract_value",
        sql,
        flags=re.IGNORECASE,
    )


def extract_referenced_table_refs(sql: str) -> set[str]:
    sql = mask_non_table_from_clauses(sql)
    pattern = re.compile(
        r"\b(?:from|join)\s+([`\"]?[a-zA-Z_][a-zA-Z0-9_]*[`\"]?(?:\.[`\"]?[a-zA-Z_][a-zA-Z0-9_]*[`\"]?){0,2})",
        re.IGNORECASE,
    )
    tables: set[str] = set()

    for match in pattern.finditer(sql):
        reference = normalize_table_reference(match.group(1))
        table_name = short_table_name(reference)
        if table_name not in SQL_KEYWORDS:
            tables.add(reference)

    return tables


def extract_referenced_tables(sql: str) -> set[str]:
    return {short_table_name(reference) for reference in extract_referenced_table_refs(sql)}


def extract_cte_names(sql: str) -> set[str]:
    if not re.match(r"^\s*with\b", sql, re.IGNORECASE):
        return set()

    pattern = re.compile(
        r"(?:\bwith\b|,)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+as\s*\(",
        re.IGNORECASE,
    )
    return {match.group(1).strip('"').lower() for match in pattern.finditer(sql)}


def extract_table_aliases(sql: str, allowed_tables: dict[str, str]) -> dict[str, str]:
    sql = mask_non_table_from_clauses(sql)
    pattern = re.compile(
        r"\b(?:from|join)\s+([`\"]?[a-zA-Z_][a-zA-Z0-9_]*[`\"]?(?:\.[`\"]?[a-zA-Z_][a-zA-Z0-9_]*[`\"]?){0,2})"
        r"(?:\s+(?:as\s+)?([a-zA-Z_][a-zA-Z0-9_]*))?",
        re.IGNORECASE,
    )
    aliases: dict[str, str] = {}

    for match in pattern.finditer(sql):
        reference = normalize_table_reference(match.group(1))
        table_name = short_table_name(reference)
        alias = (match.group(2) or "").strip('"').lower()
        canonical_name = allowed_tables.get(reference) or allowed_tables.get(table_name) or reference

        if table_name in SQL_KEYWORDS:
            continue

        aliases[table_name] = canonical_name
        aliases[canonical_name] = canonical_name
        if alias and alias not in SQL_KEYWORDS:
            aliases[alias] = canonical_name

    return aliases


def extract_used_tables(sql: str, schema_context: str = "") -> list[str]:
    referenced_table_refs = extract_referenced_table_refs(sql)
    cte_names = extract_cte_names(sql)
    allowed_tables = build_allowed_table_map(schema_context)
    used_tables = []

    for reference in sorted(referenced_table_refs):
        if reference in cte_names or short_table_name(reference) in cte_names:
            continue
        canonical_name = allowed_tables.get(reference)
        if canonical_name and canonical_name not in used_tables:
            used_tables.append(canonical_name)

    return used_tables


def has_limit_clause(sql: str) -> bool:
    return bool(re.search(r"\blimit\s+\d+\b", sql, re.IGNORECASE))


def has_aggregation_or_grouping(sql: str) -> bool:
    if re.search(r"\bgroup\s+by\b", sql, re.IGNORECASE):
        return True
    return bool(
        re.search(
            r"\b(count|sum|avg|min|max)\s*\(",
            sql,
            re.IGNORECASE,
        )
    )


def validate_limit_safety(sql: str) -> str | None:
    if has_aggregation_or_grouping(sql) or has_limit_clause(sql):
        return None
    return "Breite Zeilenabfragen ohne Aggregation benötigen LIMIT 50."


def is_literal_limitation_select(sql: str) -> bool:
    return bool(
        re.fullmatch(
            r"\s*select\s+'[^']{1,500}'\s+as\s+limitation\s*",
            sql,
            re.IGNORECASE | re.DOTALL,
        )
    )


def validate_known_columns(
    sql: str,
    schema_columns: dict[str, set[str]],
    allowed_tables: dict[str, str],
) -> str | None:
    if not schema_columns:
        return None

    aliases = extract_table_aliases(sql, allowed_tables)
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
            return f"Unbekannte Spaltenreferenz: {alias}.{column}."

    return None


def validate_generated_sql(raw_sql: str, schema_context: str = "") -> SQLValidationResult:
    format_error = reject_markdown_or_explanation(raw_sql)
    cleaned_sql = strip_trailing_semicolon(raw_sql)

    if format_error:
        return SQLValidationResult(cleaned_sql, False, format_error, [])

    if not cleaned_sql:
        return SQLValidationResult(cleaned_sql, False, "SQL ist leer.", [])

    if has_multiple_statements(cleaned_sql):
        return SQLValidationResult(
            cleaned_sql,
            False,
            "Mehrere SQL-Statements sind nicht erlaubt.",
            [],
        )

    forbidden_pattern = r"\b(" + "|".join(sorted(DESTRUCTIVE_KEYWORDS)) + r")\b"
    forbidden_match = re.search(forbidden_pattern, cleaned_sql, re.IGNORECASE)
    if forbidden_match:
        return SQLValidationResult(
            cleaned_sql,
            False,
            f"Destruktive Operation ist nicht erlaubt: {forbidden_match.group(1).upper()}.",
            [],
        )

    allowed_tables = build_allowed_table_map(schema_context)
    referenced_table_refs = extract_referenced_table_refs(cleaned_sql)
    cte_names = extract_cte_names(cleaned_sql)
    unknown_tables = sorted(
        reference
        for reference in referenced_table_refs
        if reference not in allowed_tables
        and short_table_name(reference) not in cte_names
    )
    if unknown_tables:
        return SQLValidationResult(
            cleaned_sql,
            False,
            "Unbekannte oder nicht erlaubte Tabellenreferenz: " + ", ".join(unknown_tables) + ".",
            [],
        )

    if not referenced_table_refs and is_literal_limitation_select(cleaned_sql):
        return SQLValidationResult(cleaned_sql, True, "", [])

    if not referenced_table_refs:
        return SQLValidationResult(cleaned_sql, False, "Keine Tabellenreferenz im SQL gefunden.", [])

    limit_error = validate_limit_safety(cleaned_sql)
    if limit_error:
        return SQLValidationResult(
            cleaned_sql,
            False,
            limit_error,
            extract_used_tables(cleaned_sql, schema_context),
        )

    schema_columns = parse_schema_columns(schema_context)
    column_error = validate_known_columns(cleaned_sql, schema_columns, allowed_tables)
    if column_error:
        return SQLValidationResult(
            cleaned_sql,
            False,
            column_error,
            extract_used_tables(cleaned_sql, schema_context),
        )

    return SQLValidationResult(
        cleaned_sql,
        True,
        "",
        extract_used_tables(cleaned_sql, schema_context),
    )
