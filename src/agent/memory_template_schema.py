from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from pathlib import Path
from typing import Any

import yaml


SCHEMA_VERSION = 1

REQUIRED_FIELDS = (
    "id",
    "scenario",
    "status",
    "is_active",
    "title",
    "intent",
    "trigger_phrases",
    "searchable_summary",
    "searchable_terms",
    "synonyms",
    "required_tables",
    "required_columns",
    "business_rules",
    "sql_pattern",
    "do_not_use_when",
    "validation_checks",
    "source_question",
    "source_sql",
    "approved_by",
    "approved_at",
    "version",
)

RETRIEVAL_FIELDS = (
    "id",
    "scenario",
    "title",
    "intent",
    "trigger_phrases",
    "searchable_summary",
    "searchable_terms",
    "synonyms",
    "required_tables",
    "required_columns",
)

# These fields are prompt guidance only for future integration. In particular,
# source_sql must never be treated as executable instructions by retrieval.
PROMPT_GUIDANCE_FIELDS = (
    "business_rules",
    "sql_pattern",
    "do_not_use_when",
    "validation_checks",
    "source_question",
    "source_sql",
)

LIST_FIELDS = (
    "trigger_phrases",
    "searchable_terms",
    "required_tables",
    "required_columns",
    "business_rules",
    "do_not_use_when",
    "validation_checks",
)

STRING_FIELDS = (
    "id",
    "scenario",
    "status",
    "title",
    "intent",
    "searchable_summary",
    "sql_pattern",
    "source_question",
    "source_sql",
    "approved_by",
    "approved_at",
)

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class TemplateValidationResult:
    template: dict[str, Any]
    errors: list[str]
    unknown_fields: list[str]

    @property
    def is_valid(self) -> bool:
        return not self.errors


def load_template_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Approved template YAML must be a mapping: {path}")
    return data


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_string_list(template: dict[str, Any], field: str, errors: list[str]) -> None:
    value = template.get(field)
    if not isinstance(value, list):
        errors.append(f"{field} must be a list.")
        return
    for index, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"{field}[{index}] must be a string.")


def _approved_at_is_parseable(value: str) -> bool:
    if not value.strip():
        return True
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        datetime.fromisoformat(normalized)
        return True
    except ValueError:
        return False


def validate_template(
    template: dict[str, Any],
    *,
    expected_scenario: str | None = None,
) -> TemplateValidationResult:
    """Validate one approved-template YAML mapping.

    Unknown fields are preserved by callers and intentionally not rejected. They are
    not used for retrieval unless explicitly copied into a known retrieval field.
    """

    errors: list[str] = []

    if not isinstance(template, dict):
        return TemplateValidationResult({}, ["template must be a mapping."], [])

    for field in REQUIRED_FIELDS:
        if field not in template:
            errors.append(f"required field missing: {field}.")

    for field in STRING_FIELDS:
        if field in template and not isinstance(template.get(field), str):
            errors.append(f"{field} must be a string.")

    for field in ("id", "scenario", "title", "intent", "searchable_summary"):
        if field in template and not _is_non_empty_string(template.get(field)):
            errors.append(f"{field} must be a non-empty string.")

    template_id = template.get("id")
    if isinstance(template_id, str) and template_id.strip() and not ID_PATTERN.fullmatch(template_id):
        errors.append("id must contain only letters, numbers, underscores, or hyphens.")

    if expected_scenario is not None and template.get("scenario") != expected_scenario:
        errors.append(
            f"scenario must match the scenario directory '{expected_scenario}'."
        )

    if "is_active" in template and not isinstance(template.get("is_active"), bool):
        errors.append("is_active must be a boolean.")

    for field in LIST_FIELDS:
        if field in template:
            _validate_string_list(template, field, errors)

    if "searchable_terms" in template:
        searchable_terms = template.get("searchable_terms")
        if isinstance(searchable_terms, list) and not searchable_terms:
            errors.append("searchable_terms must contain at least one term.")

    trigger_phrases = template.get("trigger_phrases")
    searchable_terms = template.get("searchable_terms")
    searchable_summary = template.get("searchable_summary")
    if (
        isinstance(trigger_phrases, list)
        and not trigger_phrases
        and isinstance(searchable_terms, list)
        and len(searchable_terms) < 2
        and isinstance(searchable_summary, str)
    ):
        errors.append(
            "trigger_phrases may be empty only when searchable_summary and searchable_terms are sufficiently descriptive."
        )

    synonyms = template.get("synonyms")
    if "synonyms" in template:
        if not isinstance(synonyms, dict):
            errors.append("synonyms must be a mapping.")
        else:
            for key, value in synonyms.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    errors.append("synonyms must map strings to strings.")
                    break

    version = template.get("version")
    if "version" in template:
        if isinstance(version, bool) or not isinstance(version, int):
            errors.append("version must be an integer.")
        elif version < 1:
            errors.append("version must be >= 1.")

    approved_at = template.get("approved_at")
    if isinstance(approved_at, str) and not _approved_at_is_parseable(approved_at):
        errors.append("approved_at must be parseable as an ISO timestamp when present.")

    unknown_fields = sorted(set(template) - set(REQUIRED_FIELDS))
    return TemplateValidationResult(dict(template), errors, unknown_fields)


def load_and_validate_template(
    path: Path,
    *,
    expected_scenario: str | None = None,
) -> TemplateValidationResult:
    return validate_template(load_template_yaml(path), expected_scenario=expected_scenario)


def is_retrievable_template(
    template: dict[str, Any],
    *,
    expected_scenario: str,
) -> bool:
    validation = validate_template(template, expected_scenario=expected_scenario)
    return (
        validation.is_valid
        and template.get("status") == "approved"
        and template.get("is_active") is True
        and template.get("scenario") == expected_scenario
    )
