"""Versioned scientific role resources bundled with the greenfield app."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
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
class BaseConfiguration:
    """Base Hermes profile configuration (YAML or JSON text) for a role."""

    content: str
    sha256: str
    format: str  # "yaml" or "json"
    file_name: str


@dataclass(frozen=True, slots=True)
class CustomSkill:
    """A custom skill defined within the role definition itself."""

    skill_id: str
    name: str
    description: str
    source: str


@dataclass(frozen=True, slots=True)
class LibraryGuidance:
    """Library and reference guidance text for a role."""

    content: str
    sha256: str
    file_name: str


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
    base_configuration: BaseConfiguration
    custom_skills: tuple[CustomSkill, ...]
    library_guidance: LibraryGuidance


def _resolve_child(base: Path, relative_str: str, role_id: str, label: str) -> Path:
    relative = Path(relative_str)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe {label} path for {role_id!r}.")
    resolved = (base / relative).resolve()
    resolved.relative_to(base)
    return resolved


def _read_text_file(path: Path, role_id: str, label: str) -> str:
    payload = path.read_bytes()
    text = payload.decode("utf-8", errors="strict")
    if not text.strip():
        raise ValueError(f"{label.capitalize()} for {role_id!r} is empty.")
    return text


def _load_base_configuration(
    base: Path, item: dict[str, Any], role_id: str
) -> BaseConfiguration:
    config_spec = item.get("base_configuration")
    if type(config_spec) is not dict:
        raise ValueError(f"Role {role_id!r} must include base_configuration.")
    file_name = str(config_spec["file"])
    fmt = str(config_spec.get("format", "yaml"))
    if fmt not in ("yaml", "json"):
        raise ValueError(f"Unsupported configuration format {fmt!r} for {role_id!r}.")
    path = _resolve_child(base, file_name, role_id, "base configuration")
    content = _read_text_file(path, role_id, "base configuration")
    return BaseConfiguration(
        content=content,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        format=fmt,
        file_name=file_name,
    )


def _load_library_guidance(
    base: Path, item: dict[str, Any], role_id: str
) -> LibraryGuidance:
    guidance_spec = item.get("library_guidance")
    if type(guidance_spec) is not dict:
        raise ValueError(f"Role {role_id!r} must include library_guidance.")
    file_name = str(guidance_spec["file"])
    path = _resolve_child(base, file_name, role_id, "library guidance")
    content = _read_text_file(path, role_id, "library guidance")
    return LibraryGuidance(
        content=content,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        file_name=file_name,
    )


def _load_custom_skills(item: dict[str, Any]) -> tuple[CustomSkill, ...]:
    raw = item.get("custom_skills", [])
    if type(raw) is not list:
        raise ValueError("custom_skills must be a list.")
    result: list[CustomSkill] = []
    for entry in raw:
        if type(entry) is not dict:
            raise ValueError("Each custom skill must be an object.")
        skill = CustomSkill(
            skill_id=str(entry["skill_id"]),
            name=str(entry["name"]),
            description=str(entry["description"]),
            source=str(entry["source"]),
        )
        result.append(skill)
    return tuple(result)


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
            soul_path = _resolve_child(base, str(item["soul_file"]), role_id, "soul")
            soul_payload = soul_path.read_bytes()
            soul = soul_payload.decode("utf-8", errors="strict")
            if not soul.strip():
                raise ValueError(f"Soul for {role_id!r} is empty.")
            recommendations = tuple(
                skills[str(value)] for value in item["recommended_skills"]
            )
            base_config = _load_base_configuration(base, item, role_id)
            library_guidance = _load_library_guidance(base, item, role_id)
            custom_skills = _load_custom_skills(item)
            roles.append(
                RoleResource(
                    role_id=role_id,
                    display_name=str(item["display_name"]),
                    profile_version=str(item["profile_version"]),
                    default_profile=profile,
                    applicable_phases=tuple(
                        str(value) for value in item["applicable_phases"]
                    ),
                    soul_text=soul,
                    soul_sha256=hashlib.sha256(soul_payload).hexdigest(),
                    recommended_skills=recommendations,
                    base_configuration=base_config,
                    custom_skills=custom_skills,
                    library_guidance=library_guidance,
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


__all__ = [
    "BaseConfiguration",
    "CustomSkill",
    "LibraryGuidance",
    "RoleResource",
    "RoleResourceCatalog",
    "SkillRecommendation",
]
