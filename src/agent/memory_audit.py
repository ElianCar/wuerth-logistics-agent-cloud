from __future__ import annotations

from src.agent.logging_utils import append_csv_row, current_timestamp, get_log_dir
from src.agent.profiles import PermissionRole, coerce_permission_role


MEMORY_AUDIT_FIELDS = [
    "timestamp",
    "actor_id",
    "actor_role",
    "action",
    "candidate_id",
    "template_id",
    "previous_status",
    "new_status",
    "scenario",
    "comment",
]


def log_memory_action(
    *,
    actor_id: str,
    actor_role: PermissionRole | str,
    action: str,
    scenario: str,
    candidate_id: str = "",
    template_id: str = "",
    previous_status: str = "",
    new_status: str = "",
    comment: str = "",
) -> None:
    role = coerce_permission_role(actor_role)
    append_csv_row(
        get_log_dir() / "memory_audit_log.csv",
        MEMORY_AUDIT_FIELDS,
        {
            "timestamp": current_timestamp(),
            "actor_id": actor_id,
            "actor_role": role.value,
            "action": action,
            "candidate_id": candidate_id,
            "template_id": template_id,
            "previous_status": previous_status,
            "new_status": new_status,
            "scenario": scenario,
            "comment": comment,
        },
    )
