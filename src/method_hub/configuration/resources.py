"""Versioned scientific role resources bundled with the greenfield app."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..json_io import load_json
from .profiles import PROFILE_ROLES, validate_profile_name


@dataclass(frozen=True, slots=True)
class SkillRecommendation:
    skill_id: str
    name: str
    description: str
    source: str
    recommended_version: str


@dataclass(frozen=True, slots=True)
class RoleResource:
    role_id: str
    display_name: str
    profile_version: str
    default_profile: str
    applicable_phases: tuple[str, ...]
    soul_text: str
    soul_sha256: str
    recommended_skills: tuple[SkillRecommendation, ...]


class RoleResourceCatalog:
    def __init__(self, roles: tuple[RoleResource, ...]) -> None:
        self._roles = {item.role_id: item for item in roles}

    @classmethod
    def load(cls, root: str | Path) -> "RoleResourceCatalog":
        base = Path(root).resolve()
        document = load_json(base / "roles.json")
        if type(document) is not dict:
            raise ValueError("Role resource catalog must be a JSON object.")
        skill_items = document.get("skills")
        role_items = document.get("roles")
        if type(skill_items) is not list or type(role_items) is not list:
            raise ValueError("Role resource catalog requires role and skill arrays.")
        skills: dict[str, SkillRecommendation] = {}
        for item in skill_items:
            skill = SkillRecommendation(
                skill_id=str(item["skill_id"]),
                name=str(item["name"]),
                description=str(item["description"]),
                source=str(item["source"]),
                recommended_version=str(item["recommended_version"]),
            )
            if skill.skill_id in skills:
                raise ValueError(f"Duplicate skill {skill.skill_id!r}.")
            skills[skill.skill_id] = skill
        roles: list[RoleResource] = []
        for item in role_items:
            role_id = str(item["role_id"])
            if role_id not in PROFILE_ROLES:
                raise ValueError(f"Unknown role {role_id!r}.")
            profile = validate_profile_name(str(item["default_profile"]))
            relative = Path(str(item["soul_file"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Unsafe soul path for {role_id!r}.")
            soul_path = (base / relative).resolve()
            soul_path.relative_to(base)
            payload = soul_path.read_bytes()
            soul = payload.decode("utf-8", errors="strict")
            if not soul.strip():
                raise ValueError(f"Soul for {role_id!r} is empty.")
            recommendations = tuple(skills[str(value)] for value in item["recommended_skills"])
            roles.append(
                RoleResource(
                    role_id=role_id,
                    display_name=str(item["display_name"]),
                    profile_version=str(item["profile_version"]),
                    default_profile=profile,
                    applicable_phases=tuple(str(value) for value in item["applicable_phases"]),
                    soul_text=soul,
                    soul_sha256=hashlib.sha256(payload).hexdigest(),
                    recommended_skills=recommendations,
                )
            )
        if {item.role_id for item in roles} != set(PROFILE_ROLES):
            raise ValueError("Role resource catalog must define every research role once.")
        return cls(tuple(roles))

    @property
    def roles(self) -> tuple[RoleResource, ...]:
        return tuple(self._roles[role] for role in PROFILE_ROLES)

    def role(self, role_id: str) -> RoleResource:
        try:
            return self._roles[role_id]
        except KeyError as error:
            raise ValueError(f"Unknown research role {role_id!r}.") from error


__all__ = ["RoleResource", "RoleResourceCatalog", "SkillRecommendation"]
