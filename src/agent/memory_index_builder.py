from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any

import yaml

from src.agent.memory_template_schema import (
    SCHEMA_VERSION,
    is_retrievable_template,
    load_and_validate_template,
)
from src.config.scenarios import PROJECT_ROOT, SCENARIOS, normalize_scenario_id


MASTER_INDEX_FILENAME = "master_index.yaml"
APPROVED_DIRNAME = "approved"


def scenario_memory_dir(scenario: str, memory_dir: Path | None = None) -> Path:
    if memory_dir is not None:
        return memory_dir
    scenario_id = normalize_scenario_id(scenario)
    return SCENARIOS[scenario_id].memory_dir


def approved_templates_dir(scenario: str, memory_dir: Path | None = None) -> Path:
    return scenario_memory_dir(scenario, memory_dir) / APPROVED_DIRNAME


def master_index_path(scenario: str, memory_dir: Path | None = None) -> Path:
    return scenario_memory_dir(scenario, memory_dir) / MASTER_INDEX_FILENAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _append_string_parts(parts: list[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        parts.append(value.strip())


def _append_list_parts(parts: list[str], value: Any) -> None:
    if isinstance(value, list):
        parts.extend(str(item).strip() for item in value if str(item).strip())


def build_searchable_text(template: dict[str, Any]) -> str:
    parts: list[str] = []
    for field in ("id", "scenario", "title", "intent", "searchable_summary"):
        _append_string_parts(parts, template.get(field))
    for field in ("trigger_phrases", "searchable_terms", "required_tables", "required_columns"):
        _append_list_parts(parts, template.get(field))

    synonyms = template.get("synonyms")
    if isinstance(synonyms, dict):
        for key in sorted(synonyms):
            _append_string_parts(parts, key)
            _append_string_parts(parts, synonyms.get(key))

    return _normalize_whitespace(" ".join(parts))


def checksum_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _path_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _relative_template_path(template_path: Path, memory_dir: Path) -> str:
    resolved_template = template_path.resolve()
    resolved_memory_dir = memory_dir.resolve()
    if _path_inside(resolved_template, PROJECT_ROOT):
        return resolved_template.relative_to(PROJECT_ROOT).as_posix()
    return resolved_template.relative_to(resolved_memory_dir.parent).as_posix()


def _template_index_record(
    *,
    scenario: str,
    template_path: Path,
    template: dict[str, Any],
    memory_dir: Path,
) -> dict[str, Any]:
    searchable_terms = template.get("searchable_terms")
    tags = searchable_terms if isinstance(searchable_terms, list) else []
    return {
        "id": template.get("id", ""),
        "path": _relative_template_path(template_path, memory_dir),
        "status": template.get("status", ""),
        "is_active": template.get("is_active", False),
        "scenario": scenario,
        "intent": template.get("intent", ""),
        "title": template.get("title", ""),
        "searchable_text": build_searchable_text(template),
        "tables": template.get("required_tables", []),
        "columns": template.get("required_columns", []),
        "tags": tags,
        "checksum": checksum_file(template_path),
        "version": template.get("version", 1),
    }


def build_master_index(
    scenario: str,
    *,
    memory_dir: Path | None = None,
    include_inactive: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    # master_index.yaml is generated from approved template files. Candidates,
    # audit logs, and legacy aggregate solution_templates.yaml are never indexed.
    scenario_id = normalize_scenario_id(scenario)
    resolved_memory_dir = scenario_memory_dir(scenario_id, memory_dir)
    approved_dir = approved_templates_dir(scenario_id, resolved_memory_dir)

    records: list[dict[str, Any]] = []
    if approved_dir.exists():
        for template_path in sorted(approved_dir.glob("*.yaml")):
            # Scenario isolation is mandatory: only files physically inside the
            # requested scenario approved directory are eligible.
            if not _path_inside(template_path, approved_dir):
                continue
            validation = load_and_validate_template(
                template_path,
                expected_scenario=scenario_id,
            )
            if not validation.is_valid:
                continue

            template = validation.template
            if include_inactive:
                include = (
                    template.get("status") == "approved"
                    and template.get("scenario") == scenario_id
                )
            else:
                include = is_retrievable_template(template, expected_scenario=scenario_id)

            if not include:
                continue

            records.append(
                _template_index_record(
                    scenario=scenario_id,
                    template_path=template_path,
                    template=template,
                    memory_dir=resolved_memory_dir,
                )
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "scenario": scenario_id,
        "generated_at": generated_at or _now_iso(),
        "template_count": len(records),
        "templates": records,
    }


def write_master_index(
    scenario: str,
    *,
    memory_dir: Path | None = None,
    include_inactive: bool = False,
) -> dict[str, Any]:
    scenario_id = normalize_scenario_id(scenario)
    resolved_memory_dir = scenario_memory_dir(scenario_id, memory_dir)
    index = build_master_index(
        scenario_id,
        memory_dir=resolved_memory_dir,
        include_inactive=include_inactive,
    )
    approved_templates_dir(scenario_id, resolved_memory_dir).mkdir(parents=True, exist_ok=True)
    path = master_index_path(scenario_id, resolved_memory_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(index, file, sort_keys=False, allow_unicode=True)
    return index
