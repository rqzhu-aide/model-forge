"""Application configuration and external Hermes profile discovery."""

from .profiles import (
    AUTHOR_PROFILE_ROLES,
    PROFILE_ROLES,
    REVIEWER_PROFILE_ISOLATION_MESSAGE,
    REVIEWER_PROFILE_ROLE,
    ProfileDiscovery,
    ProfileMapping,
    assignment_conflict,
    discover_profiles,
    resolve_hermes_root,
    validate_profile_name,
)

__all__ = [
    "AUTHOR_PROFILE_ROLES",
    "PROFILE_ROLES",
    "REVIEWER_PROFILE_ISOLATION_MESSAGE",
    "REVIEWER_PROFILE_ROLE",
    "ProfileDiscovery",
    "ProfileMapping",
    "assignment_conflict",
    "discover_profiles",
    "resolve_hermes_root",
    "validate_profile_name",
]
