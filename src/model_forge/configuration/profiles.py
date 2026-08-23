"""Read-only Hermes profile discovery for run preparation.

The implementation is independent of the archived application. A run freezes
the selected profile name and a later preparation service snapshots the exact
profile resources it is permitted to use.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


AUTHOR_PROFILE_ROLES = (
    "research_lead",
    "theorist",
    "data_analyst",
)
REVIEWER_PROFILE_ROLE = "outside_reviewer"
PROFILE_ROLES = AUTHOR_PROFILE_ROLES + (REVIEWER_PROFILE_ROLE,)
REVIEWER_PROFILE_ISOLATION_MESSAGE = (
    "Hermes assignee profiles retain persistent memory. Phase 5 outside review "
    "uses a closed review packet, so the outside reviewer must use a profile "
    "not assigned to an authoring role."
)
_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_RESERVED = frozenset({"profiles", "skills", ".", ".."})


class ProfileConfigurationError(ValueError):
    pass


def _absolute(path: str | os.PathLike[str]) -> Path:
    value = os.fspath(path)
    if not value or "\x00" in value:
        raise ProfileConfigurationError("Hermes root must be a nonempty path without NUL.")
    return Path(os.path.abspath(os.path.expanduser(value)))


def resolve_hermes_root(
    *,
    environ: Mapping[str, str] | None = None,
    home: str | os.PathLike[str] | None = None,
    platform_name: str | None = None,
) -> Path:
    environment = os.environ if environ is None else environ
    explicit = str(environment.get("MODEL_FORGE_HERMES_ROOT", "")).strip()
    if explicit:
        return _absolute(explicit)
    platform_value = os.name if platform_name is None else platform_name
    home_path = Path.home() if home is None else Path(home)
    if platform_value.casefold() in {"nt", "windows", "win32"}:
        local = str(environment.get("LOCALAPPDATA", "")).strip()
        base = Path(local) if local else home_path / "AppData" / "Local"
        native = _absolute(base / "hermes")
    else:
        native = _absolute(home_path / ".hermes")
    configured = str(environment.get("HERMES_HOME", "")).strip()
    if not configured:
        return native
    candidate = _absolute(configured)
    if candidate.parent.name.casefold() == "profiles" and candidate.name:
        return candidate.parent.parent
    return candidate


def validate_profile_name(name: str) -> str:
    if type(name) is not str or _PROFILE_NAME.fullmatch(name) is None:
        raise ProfileConfigurationError(
            "Profile names must match [a-z0-9][a-z0-9_-]{0,63}."
        )
    if name in _RESERVED:
        raise ProfileConfigurationError(f"Profile name {name!r} is reserved.")
    return name


@dataclass(frozen=True, slots=True)
class ProfileDiscovery:
    name: str
    home: Path
    exists: bool
    is_safe_directory: bool


@dataclass(frozen=True, slots=True)
class ProfileMapping:
    research_lead: str
    theorist: str
    data_analyst: str
    outside_reviewer: str

    def __post_init__(self) -> None:
        for role in PROFILE_ROLES:
            validate_profile_name(getattr(self, role))
        if any(
            self.outside_reviewer == getattr(self, role)
            for role in AUTHOR_PROFILE_ROLES
        ):
            raise ProfileConfigurationError(REVIEWER_PROFILE_ISOLATION_MESSAGE)

    def for_role(self, role: str) -> str:
        if role not in PROFILE_ROLES:
            raise ProfileConfigurationError(f"Unknown research role {role!r}.")
        return getattr(self, role)

    def to_dict(self) -> dict[str, str]:
        return {role: getattr(self, role) for role in PROFILE_ROLES}


def assignment_conflict(
    role: str,
    candidate: str,
    current: ProfileMapping | Mapping[str, str],
) -> bool:
    """Return whether one assignment would cross the reviewer memory boundary."""

    if role not in PROFILE_ROLES:
        raise ProfileConfigurationError(f"Unknown research role {role!r}.")
    validate_profile_name(candidate)
    values = current.to_dict() if isinstance(current, ProfileMapping) else dict(current)
    if set(values) != set(PROFILE_ROLES):
        raise ProfileConfigurationError("Profile mapping must cover all research roles.")
    for current_role in PROFILE_ROLES:
        validate_profile_name(values[current_role])
    if role == REVIEWER_PROFILE_ROLE:
        return any(
            candidate == values[author_role]
            for author_role in AUTHOR_PROFILE_ROLES
        )
    return candidate == values[REVIEWER_PROFILE_ROLE]


def discover_profiles(hermes_root: str | os.PathLike[str]) -> tuple[ProfileDiscovery, ...]:
    root = _absolute(hermes_root)
    result = [
        ProfileDiscovery(
            name="default",
            home=root,
            exists=root.is_dir(),
            is_safe_directory=root.is_dir() and not root.is_symlink(),
        )
    ]
    profiles_root = root / "profiles"
    try:
        children = sorted(profiles_root.iterdir(), key=lambda item: item.name)
    except FileNotFoundError:
        children = []
    except OSError as error:
        raise ProfileConfigurationError(f"Cannot inspect Hermes profiles: {error}.") from error
    for child in children:
        try:
            name = validate_profile_name(child.name)
        except ProfileConfigurationError:
            continue
        result.append(
            ProfileDiscovery(
                name=name,
                home=child,
                exists=child.exists(),
                is_safe_directory=child.is_dir() and not child.is_symlink(),
            )
        )
    return tuple(result)


__all__ = [
    "AUTHOR_PROFILE_ROLES",
    "PROFILE_ROLES",
    "REVIEWER_PROFILE_ISOLATION_MESSAGE",
    "REVIEWER_PROFILE_ROLE",
    "ProfileConfigurationError",
    "ProfileDiscovery",
    "ProfileMapping",
    "assignment_conflict",
    "discover_profiles",
    "resolve_hermes_root",
    "validate_profile_name",
]
