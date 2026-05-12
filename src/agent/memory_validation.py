from __future__ import annotations

import re
from typing import Any

from src.agent.db import load_schema_context
from src.agent.sql_validator import validate_generated_sql


REQUIRED_TEMPLATE_FIELDS = [
    "intent",
    "trigger_phrases",
    "required_tables",
    "metric_definitions",
    "join_logic",
    "sql_skeleton",
]

FORBIDDEN_SQL_KEYWORDS = {
    "ALTER",
    "CALL",
    "COPY",
    "CREATE",
    "DELETE",
    "DROP",
    "EXEC",
    "GRANT",
    "INSERT",
    "MERGE",
    "REVOKE",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
}


def validate_sql_skeleton(sql: str, schema_context: str | None = None) -> list[str]:
    errors: list[str] = []
    cleaned_sql = (sql or "").strip()

    if not cleaned_sql:
        return ["sql_skeleton must be a non-empty string."]

    forbidden_pattern = r"\b(" + "|".join(sorted(FORBIDDEN_SQL_KEYWORDS)) + r")\b"
    forbidden_match = re.search(forbidden_pattern, cleaned_sql, re.IGNORECASE)
    if forbidden_match:
        errors.append(
            f"sql_skeleton contains a forbidden keyword: {forbidden_match.group(1).upper()}."
        )

    if not re.match(r"^\s*select\b", cleaned_sql, re.IGNORECASE):
        errors.append("sql_skeleton must start with SELECT.")

    if schema_context is None:
        try:
            schema_context = load_schema_context()
        except Exception:
            schema_context = ""

    validation = validate_generated_sql(cleaned_sql, schema_context or "")
    if not validation.is_valid:
        errors.append(validation.error)

    return errors


def validate_proposed_template(
    proposed_template: dict[str, Any] | None,
    *,
    validate_sql: bool = True,
    schema_context: str | None = None,
) -> list[str]:
    errors: list[str] = []

    if not isinstance(proposed_template, dict):
        return ["proposed_template must be a YAML mapping."]

    for field in REQUIRED_TEMPLATE_FIELDS:
        if field not in proposed_template:
            errors.append(f"Missing required field: {field}.")

    intent = proposed_template.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        errors.append("intent must be a non-empty string.")

    trigger_phrases = proposed_template.get("trigger_phrases")
    if not isinstance(trigger_phrases, list):
        errors.append("trigger_phrases must be a list.")

    required_tables = proposed_template.get("required_tables")
    if not isinstance(required_tables, list):
        errors.append("required_tables must be a list.")

    metric_definitions = proposed_template.get("metric_definitions")
    if not isinstance(metric_definitions, dict):
        errors.append("metric_definitions must be a dict.")

    join_logic = proposed_template.get("join_logic")
    if not isinstance(join_logic, list):
        errors.append("join_logic must be a list.")

    sql_skeleton = proposed_template.get("sql_skeleton")
    if not isinstance(sql_skeleton, str) or not sql_skeleton.strip():
        errors.append("sql_skeleton must be a non-empty string.")
    elif validate_sql:
        errors.extend(validate_sql_skeleton(sql_skeleton, schema_context=schema_context))

    return errors
