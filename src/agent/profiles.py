from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionRole(str, Enum):
    VIEWER = "viewer"
    CONTRIBUTOR = "contributor"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class ResponseProfile(str, Enum):
    MANAGEMENT = "management"
    ANALYST = "analyst"
    TECHNICAL = "technical"


@dataclass(frozen=True)
class UserProfile:
    profile_id: str
    display_name: str
    permission_role: PermissionRole
    response_profile: ResponseProfile
    avatar: str
    description: str


DEMO_PROFILES: dict[str, UserProfile] = {
    "management_user": UserProfile(
        profile_id="management_user",
        display_name="Management User",
        permission_role=PermissionRole.VIEWER,
        response_profile=ResponseProfile.MANAGEMENT,
        avatar="👔",
        description="Views top-down business answers without memory-template governance actions.",
    ),
    "business_analyst": UserProfile(
        profile_id="business_analyst",
        display_name="Business Analyst",
        permission_role=PermissionRole.CONTRIBUTOR,
        response_profile=ResponseProfile.ANALYST,
        avatar="📊",
        description="Creates reviewed memory-template candidates from successful validated SQL runs.",
    ),
    "template_reviewer": UserProfile(
        profile_id="template_reviewer",
        display_name="Template Reviewer",
        permission_role=PermissionRole.REVIEWER,
        response_profile=ResponseProfile.ANALYST,
        avatar="✅",
        description="Reviews, edits, approves, rejects, and requests changes for candidates.",
    ),
    "admin_developer": UserProfile(
        profile_id="admin_developer",
        display_name="Admin / Developer",
        permission_role=PermissionRole.ADMIN,
        response_profile=ResponseProfile.TECHNICAL,
        avatar="🛠️",
        description="Performs all demo governance actions and can inspect technical details.",
    ),
}

DEFAULT_PROFILE_ID = "management_user"


def coerce_permission_role(role: PermissionRole | str) -> PermissionRole:
    if isinstance(role, PermissionRole):
        return role
    return PermissionRole(str(role))


def coerce_response_profile(profile: ResponseProfile | str) -> ResponseProfile:
    if isinstance(profile, ResponseProfile):
        return profile
    return ResponseProfile(str(profile))


def get_demo_profile(profile_id: str | None) -> UserProfile:
    return DEMO_PROFILES.get(str(profile_id or ""), DEMO_PROFILES[DEFAULT_PROFILE_ID])
