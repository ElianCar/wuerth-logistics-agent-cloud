from __future__ import annotations

from pathlib import Path
import os
import re
from typing import Any, Callable

import yaml

from src.agent.id_utils import generate_template_id
from src.agent.memory_index_builder import (
    approved_templates_dir,
    master_index_path,
    scenario_memory_dir,
    write_master_index,
)
from src.agent.memory_store import (
    ACTOR,
    MemoryStoreError,
    append_audit,
    as_bool,
    build_trigger_phrases,
    load_candidates,
    now_iso,
    parse_source_tables,
    save_candidates,
)
from src.agent.memory_template_schema import (
    is_retrievable_template,
    load_and_validate_template,
    validate_template,
)
from src.agent.memory_vector_retriever import retrieve_memory_templates
from src.config.scenarios import SCENARIOS, normalize_scenario_id


class MemoryLifecycleError(RuntimeError):
    pass


IndexWriter = Callable[..., dict[str, Any]]


def _compact(value: object, *, limit: int | None = None) -> str:
    text = " ".join(str(value or "").split()).strip()
    if limit is not None:
        return text[:limit].strip()
    return text


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    mapping: dict[str, str] = {}
    for key, mapped in value.items():
        key_text = str(key).strip()
        value_text = str(mapped).strip()
        if key_text and value_text:
            mapping[key_text] = value_text
    return mapping


def _template_version(value: object) -> int:
    if value in (None, ""):
        return 1
    if isinstance(value, bool):
        raise MemoryLifecycleError("version must be an integer.")
    try:
        version = int(value)
    except (TypeError, ValueError) as error:
        raise MemoryLifecycleError("version must be an integer.") from error
    return version


def _searchable_terms(*values: object) -> list[str]:
    terms: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple)):
            parts = value
        else:
            parts = [value]
        for part in parts:
            for token in re.findall(r"[A-Za-z0-9_äöüÄÖÜß.]+", str(part or "").lower()):
                normalized = token.strip("._")
                if normalized and normalized not in terms:
                    terms.append(normalized)
    return terms[:40]


def _business_rules_from_proposed(proposed_template: dict[str, Any]) -> list[str]:
    rules = _string_list(proposed_template.get("business_rules"))
    notes = _compact(proposed_template.get("notes"))
    if notes:
        rules.append(notes)

    metric_definitions = proposed_template.get("metric_definitions")
    if isinstance(metric_definitions, dict) and metric_definitions:
        rules.append("Use the reviewed metric definitions from the candidate.")

    join_logic = _string_list(proposed_template.get("join_logic"))
    if join_logic:
        rules.extend(join_logic)

    if not rules:
        rules.append("Use this approved template as prompt guidance only.")
    return rules


def _candidate_by_id(candidate_id: str) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    candidates = load_candidates()
    for index, candidate in enumerate(candidates):
        if candidate.get("candidate_id") == candidate_id:
            return candidates, index, candidate
    raise MemoryLifecycleError(f"Candidate not found: {candidate_id}")


def build_approved_template_from_candidate(
    candidate: dict[str, Any],
    proposed_template: dict[str, Any],
    *,
    scenario: str | None = None,
    template_id: str | None = None,
    approved_by: str = ACTOR,
    approved_at: str | None = None,
) -> dict[str, Any]:
    """Convert a manually reviewed candidate into the approved VSM schema."""

    if not isinstance(proposed_template, dict):
        raise MemoryLifecycleError("proposed_template must be a YAML mapping.")

    scenario_id = normalize_scenario_id(scenario or candidate.get("scenario"))
    candidate_scenario = str(candidate.get("scenario") or "").strip()
    if not candidate_scenario:
        raise MemoryLifecycleError(
            "Legacy candidate has no scenario. Select an explicit migration flow instead."
        )
    if normalize_scenario_id(candidate_scenario) != scenario_id:
        raise MemoryLifecycleError(
            f"Candidate scenario '{candidate_scenario}' does not match active scenario '{scenario_id}'."
        )

    original_question = _compact(candidate.get("original_question"))
    source_tables = parse_source_tables(candidate.get("source_tables"))
    required_tables = _string_list(proposed_template.get("required_tables")) or source_tables
    trigger_phrases = (
        _string_list(proposed_template.get("trigger_phrases"))
        or build_trigger_phrases(original_question)
    )
    intent = _compact(proposed_template.get("intent") or original_question, limit=120)
    title = _compact(proposed_template.get("title") or intent or original_question, limit=120)
    source_sql = _compact(
        proposed_template.get("source_sql")
        or candidate.get("final_sql")
        or proposed_template.get("sql_skeleton")
        or candidate.get("generated_sql")
    )
    sql_pattern = _compact(
        proposed_template.get("sql_pattern")
        or proposed_template.get("notes")
        or "Use the reviewed source SQL as prompt guidance only; adapt it to the current question."
    )
    searchable_summary = _compact(
        proposed_template.get("searchable_summary")
        or f"{title}. Source question: {original_question}. Required tables: {', '.join(required_tables)}."
    )
    searchable_terms = (
        _string_list(proposed_template.get("searchable_terms"))
        or _searchable_terms(title, intent, original_question, trigger_phrases, required_tables)
    )

    approved_template = {
        "id": _compact(
            template_id
            or proposed_template.get("id")
            or proposed_template.get("template_id")
            or generate_template_id(intent)
        ),
        "scenario": scenario_id,
        "status": "approved",
        "is_active": True,
        "title": title,
        "intent": intent,
        "trigger_phrases": trigger_phrases,
        "searchable_summary": searchable_summary,
        "searchable_terms": searchable_terms,
        "synonyms": _string_mapping(proposed_template.get("synonyms")),
        "required_tables": required_tables,
        "required_columns": _string_list(proposed_template.get("required_columns")),
        "business_rules": _business_rules_from_proposed(proposed_template),
        "sql_pattern": sql_pattern,
        "do_not_use_when": _string_list(proposed_template.get("do_not_use_when"))
        or ["The current question asks for different tables, metrics, filters, or scenario data."],
        "validation_checks": _string_list(proposed_template.get("validation_checks"))
        or [
            "Final SQL must be read-only SELECT/WITH.",
            "Final SQL must use only known schema tables and columns.",
            "Final SQL must still pass validation before execution.",
        ],
        "source_question": _compact(proposed_template.get("source_question") or original_question),
        "source_sql": source_sql,
        "approved_by": approved_by,
        "approved_at": approved_at or now_iso(),
        "version": _template_version(proposed_template.get("version")),
        "created_from_candidate_id": candidate.get("candidate_id", ""),
        "source_run_id": candidate.get("run_id", ""),
        "dataset_id": candidate.get("dataset_id", SCENARIOS[scenario_id].dataset_id),
    }

    validation = validate_template(approved_template, expected_scenario=scenario_id)
    if not validation.is_valid:
        raise MemoryLifecycleError(
            "Approved template schema validation failed: " + "; ".join(validation.errors)
        )
    return approved_template


def write_approved_template(
    template: dict[str, Any],
    *,
    memory_dir: Path | None = None,
    overwrite: bool = False,
) -> Path:
    scenario_id = normalize_scenario_id(str(template.get("scenario", "")))
    validation = validate_template(template, expected_scenario=scenario_id)
    if not validation.is_valid:
        raise MemoryLifecycleError(
            "Approved template schema validation failed: " + "; ".join(validation.errors)
        )

    approved_dir = approved_templates_dir(scenario_id, memory_dir)
    approved_dir.mkdir(parents=True, exist_ok=True)
    path = approved_dir / f"{template['id']}.yaml"
    if path.exists() and not overwrite:
        raise MemoryLifecycleError(f"Approved template already exists: {path}")

    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(template, file, sort_keys=False, allow_unicode=True)
    os.replace(temp_path, path)
    return path


def rebuild_scenario_master_index(
    scenario: str,
    *,
    memory_dir: Path | None = None,
    index_writer: IndexWriter = write_master_index,
) -> dict[str, Any]:
    scenario_id = normalize_scenario_id(scenario)
    return index_writer(scenario_id, memory_dir=memory_dir)


def run_retrieval_smoke_test(
    scenario: str,
    query: str,
    *,
    template_id: str | None = None,
    memory_dir: Path | None = None,
) -> dict[str, Any]:
    scenario_id = normalize_scenario_id(scenario)
    index_path = master_index_path(scenario_id, memory_dir)
    result = retrieve_memory_templates(
        scenario_id,
        query,
        memory_dir=memory_dir,
        index_path=index_path,
    )["memory_retrieval"]
    candidates = list(result.get("candidates", []) or [])
    candidate_ids = [str(candidate.get("template_id", "")) for candidate in candidates]
    indexed_template_count = 0
    if index_path.exists():
        with index_path.open("r", encoding="utf-8") as file:
            index = yaml.safe_load(file) or {}
        if isinstance(index, dict):
            indexed_template_count = int(index.get("template_count") or 0)

    return {
        "scenario": scenario_id,
        "query": query,
        "index_path": str(index_path),
        "indexed_template_count": indexed_template_count,
        "template_id": template_id or "",
        "top_matches": candidates,
        "no_match_reason": result.get("no_match_reason", ""),
        "ambiguous": bool(result.get("ambiguous", False)),
        "enabled": bool(result.get("enabled", False)),
        "method": result.get("method", ""),
        "would_inject_prompt_guidance": bool(template_id and template_id in candidate_ids),
    }


def mark_candidate_approved_for_vsm(
    candidate_id: str,
    proposed_template: dict[str, Any],
    *,
    template_id: str,
) -> dict[str, Any]:
    candidates, index, candidate = _candidate_by_id(candidate_id)
    old_status = str(candidate.get("status", ""))
    if old_status == "approved" or candidate.get("review", {}).get("approved_template_id"):
        raise MemoryLifecycleError("Candidate is already approved.")
    if old_status not in {"pending_review", "needs_changes"}:
        raise MemoryLifecycleError("Only pending or needs_changes candidates can be approved.")

    timestamp = now_iso()
    review = candidate.setdefault("review", {})
    candidate["status"] = "approved"
    candidate["is_active"] = False
    candidate["proposed_template"] = proposed_template
    candidate["updated_at"] = timestamp
    review["reviewed_by"] = ACTOR
    review["reviewed_at"] = timestamp
    review["approved_template_id"] = template_id
    review["runtime_memory_target"] = "approved_yaml"
    candidates[index] = candidate
    save_candidates(candidates)
    append_audit(
        action="candidate_approved_vsm",
        candidate_id=candidate_id,
        template_id=template_id,
        old_status=old_status,
        new_status="approved",
        comment="Approved to scenario scoped approved YAML and rebuilt VSM index.",
    )
    return candidate


def approve_candidate_to_vsm(
    candidate_id: str,
    proposed_template: dict[str, Any],
    *,
    scenario: str | None = None,
    memory_dir: Path | None = None,
    index_writer: IndexWriter = write_master_index,
) -> dict[str, Any]:
    candidates, index, candidate = _candidate_by_id(candidate_id)
    _ = (candidates, index)
    old_status = str(candidate.get("status", ""))
    if old_status == "approved" or candidate.get("review", {}).get("approved_template_id"):
        raise MemoryLifecycleError("Candidate is already approved.")
    if old_status not in {"pending_review", "needs_changes"}:
        raise MemoryLifecycleError("Only pending or needs_changes candidates can be approved.")
    if not as_bool(candidate.get("validation_success")) or not as_bool(candidate.get("execution_success")):
        raise MemoryLifecycleError("Only candidates from successful runs can be approved.")

    scenario_id = normalize_scenario_id(scenario or candidate.get("scenario"))
    resolved_memory_dir = scenario_memory_dir(scenario_id, memory_dir)
    template = build_approved_template_from_candidate(
        candidate,
        proposed_template,
        scenario=scenario_id,
    )
    template_path: Path | None = None
    try:
        template_path = write_approved_template(template, memory_dir=resolved_memory_dir)
        index_data = rebuild_scenario_master_index(
            scenario_id,
            memory_dir=resolved_memory_dir,
            index_writer=index_writer,
        )
    except Exception as error:
        if template_path is not None and template_path.exists():
            template_path.unlink()
        raise MemoryLifecycleError(f"Approval target was not activated: {error}") from error

    smoke_test = run_retrieval_smoke_test(
        scenario_id,
        str(candidate.get("original_question") or template.get("source_question") or ""),
        template_id=str(template.get("id", "")),
        memory_dir=resolved_memory_dir,
    )
    approved_candidate = mark_candidate_approved_for_vsm(
        candidate_id,
        proposed_template,
        template_id=str(template.get("id", "")),
    )
    return {
        "candidate": approved_candidate,
        "template": template,
        "template_path": str(template_path),
        "index": index_data,
        "index_path": str(master_index_path(scenario_id, resolved_memory_dir)),
        "smoke_test": smoke_test,
    }


def load_approved_template_records(
    scenario: str,
    *,
    memory_dir: Path | None = None,
) -> list[dict[str, Any]]:
    scenario_id = normalize_scenario_id(scenario)
    approved_dir = approved_templates_dir(scenario_id, memory_dir)
    records: list[dict[str, Any]] = []
    if not approved_dir.exists():
        return records

    for path in sorted(approved_dir.glob("*.yaml")):
        validation = load_and_validate_template(path, expected_scenario=scenario_id)
        template = validation.template
        records.append(
            {
                "template": template,
                "path": str(path),
                "is_valid": validation.is_valid,
                "validation_errors": validation.errors,
                "unknown_fields": validation.unknown_fields,
                "is_runtime_retrievable": is_retrievable_template(
                    template,
                    expected_scenario=scenario_id,
                ),
            }
        )
    return records
