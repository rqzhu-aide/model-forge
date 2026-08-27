"""Per-phase skill assignment matrix for team roles.

The matrix lives at ``resources/team/skill-assignments.json`` and maps
``(role, phase) -> skill ids``.  A pair without an entry falls back to the
role's catalog default (recommended skills plus bundled custom skills), so
the zero-configuration state reproduces the historical behavior.  An entry
REPLACES the default for that pair - it never extends it silently - and an
empty skill list is legal: the role runs that phase with no skills.

Every listed skill id must exist in the bundled skill manifest with
content.  Unknown ids fail catalog load, not the run seal.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..json_io import load_json
from .profiles import PROFILE_ROLES
from .resources import RoleResource, RoleResourceCatalog

_FILE_NAME = "skill-assignments.json"
_SCHEMA_VERSION = "1.0.0"
_PHASE_RE = re.compile(r"^P[1-5]$")


@dataclass(frozen=True, slots=True)
class SkillAssignment:
    role: str
    phase: str
    skills: tuple[str, ...]


class SkillAssignmentMatrix:
    """Immutable (role, phase) -> skill ids assignment matrix."""

    def __init__(self, assignments: tuple[SkillAssignment, ...]) -> None:
        self._by_pair: dict[tuple[str, str], tuple[str, ...]] = {
            (item.role, item.phase): item.skills for item in assignments
        }

    @classmethod
    def empty(cls) -> "SkillAssignmentMatrix":
        return cls(())

    @classmethod
    def load(
        cls,
        team_root: str | Path,
        catalog: RoleResourceCatalog,
        manifest: Mapping[str, Any],
    ) -> "SkillAssignmentMatrix":
        """Load and validate the matrix from the team resources root.

        A missing file means the zero-configuration state (defaults
        everywhere).  ``manifest`` is the bundled skill manifest document;
        every assigned skill id must name a bundled skill entry.
        """
        path = Path(team_root).resolve() / _FILE_NAME
        if not path.exists():
            return cls.empty()
        document = load_json(path)
        if type(document) is not dict:
            raise ValueError("Skill assignment matrix must be a JSON object.")
        if str(document.get("schema_version")) != _SCHEMA_VERSION:
            raise ValueError(
                f"Skill assignment matrix schema_version must be {_SCHEMA_VERSION!r}."
            )
        raw = document.get("assignments")
        if type(raw) is not list:
            raise ValueError("Skill assignment matrix requires an assignments array.")
        bundled = manifest.get("skills")
        if type(bundled) is not dict:
            raise ValueError("Bundled skill manifest is invalid.")
        assignments: list[SkillAssignment] = []
        seen: set[tuple[str, str]] = set()
        for entry in raw:
            if type(entry) is not dict:
                raise ValueError("Each skill assignment must be an object.")
            role = str(entry.get("role"))
            phase = str(entry.get("phase"))
            if role not in PROFILE_ROLES:
                raise ValueError(f"Skill assignment names unknown role {role!r}.")
            if not _PHASE_RE.fullmatch(phase):
                raise ValueError(f"Skill assignment names unknown phase {phase!r}.")
            if phase not in catalog.role(role).applicable_phases:
                raise ValueError(
                    f"Role {role!r} is not applicable to phase {phase!r}."
                )
            pair = (role, phase)
            if pair in seen:
                raise ValueError(
                    f"Duplicate skill assignment for {role!r} in {phase!r}."
                )
            seen.add(pair)
            raw_skills = entry.get("skills")
            if type(raw_skills) is not list:
                raise ValueError(
                    f"Skill assignment for {role!r} in {phase!r} requires a skills array."
                )
            skills: list[str] = []
            for value in raw_skills:
                skill_id = str(value)
                if type(bundled.get(skill_id)) is not dict:
                    raise ValueError(
                        f"Skill assignment names unknown bundled skill {skill_id!r}."
                    )
                if skill_id in skills:
                    raise ValueError(
                        f"Skill assignment for {role!r} in {phase!r} repeats {skill_id!r}."
                    )
                skills.append(skill_id)
            assignments.append(
                SkillAssignment(role=role, phase=phase, skills=tuple(skills))
            )
        return cls(tuple(assignments))

    @property
    def assignments(self) -> tuple[SkillAssignment, ...]:
        return tuple(
            SkillAssignment(role=role, phase=phase, skills=skills)
            for (role, phase), skills in sorted(self._by_pair.items())
        )

    def assigned(self, role: str, phase: str) -> tuple[str, ...] | None:
        """Return the assigned skills for the pair, or None when unset."""
        return self._by_pair.get((role, phase))

    def default_skills(self, resource: RoleResource) -> tuple[str, ...]:
        """The role's catalog default: recommended plus bundled custom."""
        return tuple(skill.skill_id for skill in resource.recommended_skills) + tuple(
            skill.skill_id
            for skill in resource.custom_skills
            if skill.source == "model-forge/bundled"
        )

    def effective_skills(self, resource: RoleResource, phase: str) -> tuple[str, ...]:
        """Resolve the skill ids the role carries into the phase."""
        assigned = self.assigned(resource.role_id, phase)
        if assigned is not None:
            return assigned
        return self.default_skills(resource)

    def with_assignment(
        self, role: str, phase: str, skills: tuple[str, ...] | None
    ) -> "SkillAssignmentMatrix":
        """Return a new matrix with the pair set (or cleared with None)."""
        updated = dict(self._by_pair)
        if skills is None:
            updated.pop((role, phase), None)
        else:
            updated[(role, phase)] = tuple(skills)
        return SkillAssignmentMatrix(
            tuple(
                SkillAssignment(role=r, phase=p, skills=s)
                for (r, p), s in sorted(updated.items())
            )
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "assignments": [
                {"role": role, "phase": phase, "skills": list(skills)}
                for (role, phase), skills in sorted(self._by_pair.items())
            ],
        }

    def save(self, team_root: str | Path) -> str:
        """Atomically write the matrix file; return its sha256."""
        path = Path(team_root).resolve() / _FILE_NAME
        payload = (
            json.dumps(self.to_document(), indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        temporary = path.with_suffix(".json.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)
        return hashlib.sha256(payload).hexdigest()


__all__ = ["SkillAssignment", "SkillAssignmentMatrix"]
