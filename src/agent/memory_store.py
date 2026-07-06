from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import os
import re
import shutil
from typing import Any
from uuid import uuid4

import yaml

from src.agent.access_control import TemplateAction, require_permission
from src.agent.id_utils import (
    generate_audit_id,
    generate_candidate_id,
    generate_template_id,
)
from src.agent.logging_utils import append_csv_row, get_log_dir, read_csv_rows
from src.agent.memory_audit import log_memory_action
from src.agent.profiles import PermissionRole
from src.config.scenarios import get_active_scenario, normalize_scenario_id


ACTOR = "manual_review"

DEFAULT_CANDIDATES = {"candidates": []}
DEFAULT_TEMPLATES = {"templates": []}
DEFAULT_ERRORS = {"errors": []}

AUDIT_COLUMNS = [
    "audit_id",
    "timestamp",
    "actor",
    "action",
    "candidate_id",
    "template_id",
    "old_status",
    "new_status",
    "comment",
]


class MemoryStoreError(RuntimeError):
    pass


def memory_dir() -> Path:
    return get_active_scenario().memory_dir


def solution_templates_path() -> Path:
    return memory_dir() / "solution_templates.yaml"


def error_memory_path() -> Path:
    return memory_dir() / "error_memory.yaml"


def memory_candidates_path() -> Path:
    return memory_dir() / "memory_candidates.yaml"


def memory_audit_log_path() -> Path:
    return memory_dir() / "memory_audit_log.csv"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def backup_suffix() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def initialize_memory_files() -> None:
    active_memory_dir = memory_dir()
    active_memory_dir.mkdir(parents=True, exist_ok=True)
    _create_yaml_if_missing(solution_templates_path(), DEFAULT_TEMPLATES)
    _create_yaml_if_missing(error_memory_path(), DEFAULT_ERRORS)
    _create_yaml_if_missing(memory_candidates_path(), DEFAULT_CANDIDATES)
    audit_path = memory_audit_log_path()
    if not audit_path.exists() or audit_path.stat().st_size == 0:
        audit_path.write_text(",".join(AUDIT_COLUMNS) + "\n", encoding="utf-8")


def _create_yaml_if_missing(path: Path, default_data: dict[str, Any]) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(default_data, sort_keys=False), encoding="utf-8")


def _load_yaml(path: Path, default_data: dict[str, Any]) -> dict[str, Any]:
    initialize_memory_files()
    if not path.exists() or path.stat().st_size == 0:
        return deepcopy(default_data)
    try:
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file)
    except yaml.YAMLError as error:
        raise MemoryStoreError(f"Invalid YAML in {path}: {error}") from error
    if data is None:
        return deepcopy(default_data)
    if not isinstance(data, dict):
        raise MemoryStoreError(f"Expected YAML mapping in {path}.")
    return data


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    initialize_memory_files()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        backup_path = path.with_name(f"{path.name}.bak_{backup_suffix()}_{uuid4().hex[:4]}")
        shutil.copy2(path, backup_path)

    temp_path = path.with_name(f".{path.name}.tmp_{uuid4().hex}")
    with temp_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, sort_keys=False)
    os.replace(temp_path, path)


def _write_yaml_temp(path: Path, data: dict[str, Any]) -> Path:
    temp_path = path.with_name(f".{path.name}.tmp_{uuid4().hex}")
    with temp_path.open("w", encoding="utf-8") as file:
        yaml.safe_dump(data, file, sort_keys=False)
    return temp_path


def _backup_yaml(path: Path) -> Path | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    backup_path = path.with_name(f"{path.name}.bak_{backup_suffix()}_{uuid4().hex[:4]}")
    shutil.copy2(path, backup_path)
    return backup_path


def _restore_backup(path: Path, backup_path: Path | None) -> None:
    if backup_path is not None and backup_path.exists():
        shutil.copy2(backup_path, path)


def _write_templates_and_candidates(
    templates: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> None:
    initialize_memory_files()
    templates_path = solution_templates_path()
    candidates_path = memory_candidates_path()
    templates_backup = _backup_yaml(templates_path)
    candidates_backup = _backup_yaml(candidates_path)
    templates_temp = _write_yaml_temp(templates_path, {"templates": templates})
    candidates_temp = _write_yaml_temp(candidates_path, {"candidates": candidates})

    try:
        os.replace(templates_temp, templates_path)
        try:
            os.replace(candidates_temp, candidates_path)
        except Exception:
            _restore_backup(templates_path, templates_backup)
            raise
    except Exception:
        _restore_backup(templates_path, templates_backup)
        _restore_backup(candidates_path, candidates_backup)
        raise
    finally:
        for temp_path in (templates_temp, candidates_temp):
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass


def load_candidates_data() -> dict[str, Any]:
    data = _load_yaml(memory_candidates_path(), DEFAULT_CANDIDATES)
    if not isinstance(data.get("candidates", []), list):
        raise MemoryStoreError("memory_candidates.yaml must contain a candidates list.")
    return data


def load_candidates() -> list[dict[str, Any]]:
    candidates = load_candidates_data().get("candidates", [])
    return [candidate for candidate in candidates if isinstance(candidate, dict)]


def save_candidates(candidates: list[dict[str, Any]]) -> None:
    _write_yaml(memory_candidates_path(), {"candidates": candidates})


def load_templates_data() -> dict[str, Any]:
    data = _load_yaml(solution_templates_path(), DEFAULT_TEMPLATES)
    if not isinstance(data.get("templates", []), list):
        raise MemoryStoreError("solution_templates.yaml must contain a templates list.")
    return data


def load_templates() -> list[dict[str, Any]]:
    templates = load_templates_data().get("templates", [])
    return [template for template in templates if isinstance(template, dict)]


def save_templates(templates: list[dict[str, Any]]) -> None:
    _write_yaml(solution_templates_path(), {"templates": templates})


def append_audit(
    *,
    action: str,
    candidate_id: str = "",
    template_id: str = "",
    old_status: str = "",
    new_status: str = "",
    comment: str = "",
    actor: str = ACTOR,
) -> None:
    initialize_memory_files()
    append_csv_row(
        memory_audit_log_path(),
        AUDIT_COLUMNS,
        {
            "audit_id": generate_audit_id(),
            "timestamp": now_iso(),
            "actor": actor,
            "action": action,
            "candidate_id": candidate_id,
            "template_id": template_id,
            "old_status": old_status,
            "new_status": new_status,
            "comment": comment,
        },
    )


def _action_scenario(scenario: str | None = None) -> str:
    active_scenario = get_active_scenario().scenario_id
    scenario_id = normalize_scenario_id(scenario or active_scenario)
    if scenario_id != active_scenario:
        raise MemoryStoreError(
            f"Requested scenario '{scenario_id}' does not match active scenario '{active_scenario}'."
        )
    return scenario_id


def _candidate_scenario(candidate: dict[str, Any], scenario: str | None = None) -> str:
    scenario_id = _action_scenario(scenario)
    candidate_scenario = str(candidate.get("scenario") or "").strip()
    if candidate_scenario and normalize_scenario_id(candidate_scenario) != scenario_id:
        raise MemoryStoreError(
            f"Candidate scenario '{candidate_scenario}' does not match active scenario '{scenario_id}'."
        )
    return scenario_id


def latest_feedback_for_run(run_id: str) -> dict[str, str] | None:
    if not run_id:
        return None
    rows = read_csv_rows(get_log_dir() / "feedback.csv")
    for row in reversed(rows):
        if row.get("run_id") == run_id:
            return row
    return None


def parse_source_tables(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not value:
        return []
    text = str(value)
    if "|" in text:
        parts = text.split("|")
    else:
        parts = text.split(",")
    return [part.strip() for part in parts if part.strip()]


def as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def as_int_or_none(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_intent(question: str) -> str:
    compact = " ".join((question or "").split()).strip(" ?.!:;")
    if not compact:
        return "Reusable SQL solution"
    return compact[:120]


def build_trigger_phrases(question: str) -> list[str]:
    compact = " ".join((question or "").split()).strip()
    simplified = re.sub(r"[^a-zA-Z0-9 ]+", "", compact.lower()).strip()
    variants = [
        compact,
        simplified,
        re.sub(r"^(please|can you|could you)\s+", "", simplified).strip(),
    ]
    unique: list[str] = []
    for variant in variants:
        if variant and variant not in unique:
            unique.append(variant)
    return unique[:3]


def _find_candidate_index(candidates: list[dict[str, Any]], candidate_id: str) -> int:
    for index, candidate in enumerate(candidates):
        if candidate.get("candidate_id") == candidate_id:
            return index
    raise MemoryStoreError(f"Candidate not found: {candidate_id}")


def _find_template_index(templates: list[dict[str, Any]], template_id: str) -> int:
    for index, template in enumerate(templates):
        if template.get("template_id") == template_id:
            return index
    raise MemoryStoreError(f"Template not found: {template_id}")


def _require_successful_candidate_source_run(record: dict[str, Any]) -> None:
    query_result = record.get("query_result") if isinstance(record.get("query_result"), dict) else {}
    generated_sql = str(record.get("generated_sql") or "").strip()
    final_sql = str(record.get("final_sql") or query_result.get("executed_sql") or generated_sql).strip()
    validation_success = as_bool(record.get("validation_success", record.get("sql_valid")))
    execution_success = as_bool(record.get("execution_success"))

    if not validation_success:
        raise MemoryStoreError("Cannot create a candidate unless SQL validation succeeded.")
    if not execution_success:
        raise MemoryStoreError("Cannot create a candidate unless SQL execution succeeded.")
    if not final_sql:
        raise MemoryStoreError("Cannot create a candidate without final SQL from the successful run.")


def create_candidate_from_run(
    record: dict[str, Any],
    *,
    actor_id: str,
    actor_role: PermissionRole | str,
    scenario: str | None = None,
) -> tuple[dict[str, Any], bool, str]:
    require_permission(actor_role, TemplateAction.CREATE_CANDIDATE)
    initialize_memory_files()
    active_scenario = get_active_scenario()
    scenario_id = _action_scenario(scenario)
    candidates = load_candidates()
    run_id = str(record.get("run_id", "")).strip()
    if not run_id:
        raise MemoryStoreError("Cannot create a candidate without run_id.")
    _require_successful_candidate_source_run(record)

    for candidate in candidates:
        if (
            candidate.get("run_id") == run_id
            and candidate.get("candidate_type") == "solution_template"
            and candidate.get("status") != "rejected"
        ):
            return candidate, False, "A candidate for this run already exists."

    feedback = latest_feedback_for_run(run_id) or {}
    question = str(record.get("question") or record.get("user_question") or "")
    answer = str(record.get("answer") or record.get("final_answer") or "")
    generated_sql = str(record.get("generated_sql") or "")
    query_result = record.get("query_result") if isinstance(record.get("query_result"), dict) else {}
    final_sql = str(record.get("final_sql") or query_result.get("executed_sql") or generated_sql)
    source_tables = parse_source_tables(record.get("source_tables"))
    timestamp = now_iso()

    proposed_template = {
        "scenario": scenario_id,
        "dataset_id": active_scenario.dataset_id,
        "intent": build_intent(question),
        "trigger_phrases": build_trigger_phrases(question),
        "required_tables": source_tables,
        "metric_definitions": {},
        "join_logic": [],
        "sql_skeleton": final_sql,
        "notes": "Automatically generated candidate from successful run. Requires manual review.",
    }

    candidate = {
        "candidate_id": generate_candidate_id(),
        "scenario": scenario_id,
        "dataset_id": active_scenario.dataset_id,
        "run_id": run_id,
        "feedback_id": feedback.get("feedback_id") or None,
        "status": "pending_review",
        "is_active": False,
        "candidate_type": "solution_template",
        "created_at": timestamp,
        "updated_at": timestamp,
        "original_question": question,
        "generated_answer": answer,
        "generated_sql": generated_sql,
        "final_sql": final_sql,
        "model_primary": record.get("model_primary") or record.get("primary_model") or "",
        "model_used": record.get("model_used") or record.get("selected_model") or "",
        "fallback_used": as_bool(record.get("fallback_used")),
        "validation_success": as_bool(record.get("validation_success", record.get("sql_valid"))),
        "execution_success": as_bool(record.get("execution_success")),
        "error_type": record.get("error_type") or None,
        "error_message": record.get("error_message") or record.get("sql_error") or None,
        "row_count": as_int_or_none(record.get("row_count") or query_result.get("row_count")),
        "source_tables": source_tables,
        "created_from_positive_feedback": feedback.get("rating") == "thumbs_up",
        "feedback": {
            "rating": feedback.get("rating") or None,
            "comment": feedback.get("comment") or feedback.get("user_comment") or None,
            "corrected_sql": feedback.get("corrected_sql") or None,
            "expected_answer": feedback.get("expected_answer") or None,
        },
        "proposed_template": proposed_template,
        "review": {
            "reviewed_by": None,
            "reviewed_at": None,
            "review_comment": None,
            "rejection_reason": None,
            "approved_template_id": None,
        },
    }

    candidates.append(candidate)
    save_candidates(candidates)
    append_audit(
        action="candidate_created",
        candidate_id=candidate["candidate_id"],
        old_status="",
        new_status="pending_review",
        comment=f"Created from run_id {run_id}",
        actor=actor_id,
    )
    log_memory_action(
        actor_id=actor_id,
        actor_role=actor_role,
        action="candidate_created",
        candidate_id=candidate["candidate_id"],
        previous_status="",
        new_status="pending_review",
        scenario=scenario_id,
        comment=f"Created from run_id {run_id}",
    )
    return candidate, True, "Candidate created."


def update_candidate_proposed_template(
    candidate_id: str,
    proposed_template: dict[str, Any],
    *,
    actor_id: str,
    actor_role: PermissionRole | str,
    scenario: str | None = None,
) -> dict[str, Any]:
    require_permission(actor_role, TemplateAction.EDIT_CANDIDATE)
    candidates = load_candidates()
    index = _find_candidate_index(candidates, candidate_id)
    candidate = candidates[index]
    scenario_id = _candidate_scenario(candidate, scenario)
    old_status = str(candidate.get("status", ""))
    if old_status in {"approved", "rejected"}:
        raise MemoryStoreError("Approved or rejected candidates cannot be edited.")

    candidate["proposed_template"] = proposed_template
    candidate["updated_at"] = now_iso()
    candidates[index] = candidate
    save_candidates(candidates)
    append_audit(
        action="candidate_edited",
        candidate_id=candidate_id,
        old_status=old_status,
        new_status=old_status,
        comment="Edited proposed_template",
        actor=actor_id,
    )
    log_memory_action(
        actor_id=actor_id,
        actor_role=actor_role,
        action="candidate_edited",
        candidate_id=candidate_id,
        previous_status=old_status,
        new_status=old_status,
        scenario=scenario_id,
        comment="Edited proposed_template",
    )
    return candidate


def audit_candidate_validation(candidate_id: str, valid: bool, error_count: int) -> None:
    append_audit(
        action="candidate_validated",
        candidate_id=candidate_id,
        comment=f"{'valid' if valid else 'invalid'}; error_count={error_count}",
    )


def approve_candidate(
    candidate_id: str,
    proposed_template: dict[str, Any],
    *,
    actor_id: str,
    actor_role: PermissionRole | str,
    scenario: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    require_permission(actor_role, TemplateAction.APPROVE_CANDIDATE)
    active_scenario = get_active_scenario()
    scenario_id = _action_scenario(scenario)
    candidates = load_candidates()
    candidate_index = _find_candidate_index(candidates, candidate_id)
    candidate = candidates[candidate_index]
    scenario_id = _candidate_scenario(candidate, scenario_id)
    old_status = str(candidate.get("status", ""))
    review = candidate.setdefault("review", {})

    if old_status == "approved" or review.get("approved_template_id"):
        raise MemoryStoreError("Candidate is already approved.")
    if old_status not in {"pending_review", "needs_changes"}:
        raise MemoryStoreError("Only pending or needs_changes candidates can be approved.")
    if not as_bool(candidate.get("validation_success")) or not as_bool(candidate.get("execution_success")):
        raise MemoryStoreError("Only candidates from successful runs can be approved.")

    from src.agent.memory_validation import validate_proposed_template

    validation_errors = validate_proposed_template(proposed_template)
    if validation_errors:
        raise MemoryStoreError(
            "Cannot approve invalid proposed_template: " + "; ".join(validation_errors)
        )

    templates = load_templates()
    timestamp = now_iso()
    template_id = generate_template_id(str(proposed_template.get("intent") or "solution_template"))
    feedback = candidate.get("feedback") if isinstance(candidate.get("feedback"), dict) else {}

    template = {
        "template_id": template_id,
        "version": 1,
        "scenario": scenario_id,
        "dataset_id": active_scenario.dataset_id,
        "status": "approved",
        "is_active": True,
        "created_from_candidate_id": candidate_id,
        "source_run_id": candidate.get("run_id", ""),
        "created_at": timestamp,
        "approved_at": timestamp,
        "approved_by": actor_id,
        "intent": proposed_template.get("intent", ""),
        "trigger_phrases": proposed_template.get("trigger_phrases", []),
        "required_tables": proposed_template.get("required_tables", []),
        "metric_definitions": proposed_template.get("metric_definitions", {}),
        "join_logic": proposed_template.get("join_logic", []),
        "sql_skeleton": proposed_template.get("sql_skeleton", ""),
        "notes": proposed_template.get("notes", ""),
        "quality": {
            "source_feedback_rating": feedback.get("rating"),
            "validation_success": True,
            "execution_success": True,
            "row_count": candidate.get("row_count"),
            "model_used": candidate.get("model_used", ""),
            "fallback_used": as_bool(candidate.get("fallback_used")),
        },
    }

    candidate["status"] = "approved"
    candidate["is_active"] = False
    candidate["proposed_template"] = proposed_template
    candidate["updated_at"] = timestamp
    review["reviewed_by"] = actor_id
    review["reviewed_at"] = timestamp
    review["approved_template_id"] = template_id
    candidates[candidate_index] = candidate

    templates.append(template)
    _write_templates_and_candidates(templates, candidates)

    append_audit(
        action="candidate_approved",
        candidate_id=candidate_id,
        template_id=template_id,
        old_status=old_status,
        new_status="approved",
        actor=actor_id,
    )
    log_memory_action(
        actor_id=actor_id,
        actor_role=actor_role,
        action="candidate_approved",
        candidate_id=candidate_id,
        template_id=template_id,
        previous_status=old_status,
        new_status="approved",
        scenario=scenario_id,
    )
    return candidate, template


def reject_candidate(
    candidate_id: str,
    rejection_reason: str = "",
    *,
    actor_id: str,
    actor_role: PermissionRole | str,
    scenario: str | None = None,
) -> dict[str, Any]:
    require_permission(actor_role, TemplateAction.REJECT_CANDIDATE)
    if not rejection_reason.strip():
        raise MemoryStoreError("A rejection reason is required.")

    candidates = load_candidates()
    index = _find_candidate_index(candidates, candidate_id)
    candidate = candidates[index]
    scenario_id = _candidate_scenario(candidate, scenario)
    old_status = str(candidate.get("status", ""))
    if old_status not in {"pending_review", "needs_changes"}:
        raise MemoryStoreError("Only pending or needs_changes candidates can be rejected.")

    timestamp = now_iso()
    review = candidate.setdefault("review", {})
    candidate["status"] = "rejected"
    candidate["is_active"] = False
    candidate["updated_at"] = timestamp
    review["reviewed_by"] = actor_id
    review["reviewed_at"] = timestamp
    review["rejection_reason"] = rejection_reason
    candidates[index] = candidate
    save_candidates(candidates)
    append_audit(
        action="candidate_rejected",
        candidate_id=candidate_id,
        old_status=old_status,
        new_status="rejected",
        comment=rejection_reason,
        actor=actor_id,
    )
    log_memory_action(
        actor_id=actor_id,
        actor_role=actor_role,
        action="candidate_rejected",
        candidate_id=candidate_id,
        previous_status=old_status,
        new_status="rejected",
        scenario=scenario_id,
        comment=rejection_reason,
    )
    return candidate


def mark_candidate_needs_changes(
    candidate_id: str,
    review_comment: str = "",
    *,
    actor_id: str,
    actor_role: PermissionRole | str,
    scenario: str | None = None,
) -> dict[str, Any]:
    require_permission(actor_role, TemplateAction.REQUEST_CHANGES)
    candidates = load_candidates()
    index = _find_candidate_index(candidates, candidate_id)
    candidate = candidates[index]
    scenario_id = _candidate_scenario(candidate, scenario)
    old_status = str(candidate.get("status", ""))
    if old_status != "pending_review":
        raise MemoryStoreError("Only pending candidates can be marked as needs_changes.")

    timestamp = now_iso()
    review = candidate.setdefault("review", {})
    candidate["status"] = "needs_changes"
    candidate["is_active"] = False
    candidate["updated_at"] = timestamp
    review["reviewed_by"] = actor_id
    review["reviewed_at"] = timestamp
    review["review_comment"] = review_comment
    candidates[index] = candidate
    save_candidates(candidates)
    append_audit(
        action="candidate_needs_changes",
        candidate_id=candidate_id,
        old_status=old_status,
        new_status="needs_changes",
        comment=review_comment,
        actor=actor_id,
    )
    log_memory_action(
        actor_id=actor_id,
        actor_role=actor_role,
        action="changes_requested",
        candidate_id=candidate_id,
        previous_status=old_status,
        new_status="needs_changes",
        scenario=scenario_id,
        comment=review_comment,
    )
    return candidate


def disable_template(
    template_id: str,
    disabled_reason: str = "",
    *,
    actor_id: str,
    actor_role: PermissionRole | str,
) -> dict[str, Any]:
    require_permission(actor_role, TemplateAction.DEACTIVATE_TEMPLATE)
    if not disabled_reason.strip():
        raise MemoryStoreError("A disabled reason is required.")

    templates = load_templates()
    index = _find_template_index(templates, template_id)
    template = templates[index]
    scenario_id = normalize_scenario_id(template.get("scenario") or get_active_scenario().scenario_id)
    old_status = str(template.get("status", ""))
    if old_status != "approved" or template.get("is_active") is not True:
        raise MemoryStoreError("Only approved active templates can be disabled.")

    template["status"] = "disabled"
    template["is_active"] = False
    template["disabled_at"] = now_iso()
    template["disabled_by"] = actor_id
    template["disabled_reason"] = disabled_reason
    templates[index] = template
    save_templates(templates)
    append_audit(
        action="template_disabled",
        template_id=template_id,
        old_status=old_status,
        new_status="disabled",
        comment=disabled_reason,
        actor=actor_id,
    )
    log_memory_action(
        actor_id=actor_id,
        actor_role=actor_role,
        action="template_deactivated",
        template_id=template_id,
        previous_status=old_status,
        new_status="disabled",
        scenario=scenario_id,
        comment=disabled_reason,
    )
    return template


def reactivate_template(
    template_id: str,
    *,
    actor_id: str,
    actor_role: PermissionRole | str,
) -> dict[str, Any]:
    require_permission(actor_role, TemplateAction.REACTIVATE_TEMPLATE)
    templates = load_templates()
    index = _find_template_index(templates, template_id)
    template = templates[index]
    scenario_id = normalize_scenario_id(template.get("scenario") or get_active_scenario().scenario_id)
    old_status = str(template.get("status", ""))
    if old_status != "disabled":
        raise MemoryStoreError("Only disabled templates can be reactivated.")

    template["status"] = "approved"
    template["is_active"] = True
    template["reactivated_at"] = now_iso()
    template["reactivated_by"] = actor_id
    templates[index] = template
    save_templates(templates)
    append_audit(
        action="template_reactivated",
        template_id=template_id,
        old_status=old_status,
        new_status="approved",
        actor=actor_id,
    )
    log_memory_action(
        actor_id=actor_id,
        actor_role=actor_role,
        action="template_reactivated",
        template_id=template_id,
        previous_status=old_status,
        new_status="approved",
        scenario=scenario_id,
    )
    return template
