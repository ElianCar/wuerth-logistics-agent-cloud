from __future__ import annotations

from enum import Enum

from src.agent.profiles import PermissionRole, coerce_permission_role


class TemplateAction(str, Enum):
    CREATE_CANDIDATE = "create_candidate"
    EDIT_CANDIDATE = "edit_candidate"
    APPROVE_CANDIDATE = "approve_candidate"
    REJECT_CANDIDATE = "reject_candidate"
    REQUEST_CHANGES = "request_changes"
    DEACTIVATE_TEMPLATE = "deactivate_template"
    REACTIVATE_TEMPLATE = "reactivate_template"
    MANAGE_ROLES = "manage_roles"


ROLE_PERMISSIONS: dict[PermissionRole, frozenset[TemplateAction]] = {
    PermissionRole.VIEWER: frozenset(),
    PermissionRole.CONTRIBUTOR: frozenset({TemplateAction.CREATE_CANDIDATE}),
    PermissionRole.REVIEWER: frozenset(
        {
            TemplateAction.EDIT_CANDIDATE,
            TemplateAction.APPROVE_CANDIDATE,
            TemplateAction.REJECT_CANDIDATE,
            TemplateAction.REQUEST_CHANGES,
        }
    ),
    PermissionRole.ADMIN: frozenset(
        {
            TemplateAction.CREATE_CANDIDATE,
            TemplateAction.EDIT_CANDIDATE,
            TemplateAction.APPROVE_CANDIDATE,
            TemplateAction.REJECT_CANDIDATE,
            TemplateAction.REQUEST_CHANGES,
            TemplateAction.DEACTIVATE_TEMPLATE,
            TemplateAction.REACTIVATE_TEMPLATE,
            TemplateAction.MANAGE_ROLES,
        }
    ),
}


def can(role: PermissionRole | str, action: TemplateAction | str) -> bool:
    permission_role = coerce_permission_role(role)
    template_action = action if isinstance(action, TemplateAction) else TemplateAction(str(action))
    return template_action in ROLE_PERMISSIONS[permission_role]


def require_permission(role: PermissionRole | str, action: TemplateAction | str) -> None:
    if can(role, action):
        return
    permission_role = coerce_permission_role(role)
    template_action = action if isinstance(action, TemplateAction) else TemplateAction(str(action))
    raise PermissionError(
        f"Permission role '{permission_role.value}' may not perform '{template_action.value}'."
    )
