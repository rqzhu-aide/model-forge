"""Shared role-resource snapshot for basis sealing.

Both the phase view (at descriptor computation time) and the run coordinator
(at preparation time) need to produce the same role-resource snapshot so that
drift can be detected. This module centralises that computation.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..configuration.profiles import PROFILE_ROLES, ProfileMapping
from ..configuration.resources import RoleResourceCatalog
from ..json_io import JsonLoadError, loads_json
from pathlib import Path


def compute_role_resources(
    *,
    repository,
    settings,
    role_resources: RoleResourceCatalog,
    skill_manifest: Mapping[str, Any],
    roles: set[str],
    project_id: str,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Compute the role-resource snapshot for the given roles.

    Returns ``(profiles, resources)`` in the same format as
    ``RunCoordinator._freeze_role_resources``.
    """
    effective_values = {
        role: settings.profile_for(role) for role in PROFILE_ROLES
    }
    for role in PROFILE_ROLES:
        row = repository.get_profile_mapping(project_id, role)
        if row is not None:
            effective_values[role] = str(row["profile_name"])
    effective_mapping = ProfileMapping(**effective_values)

    if type(skill_manifest) is not dict or type(skill_manifest.get("skills")) is not dict:
        raise ValueError("Bundled skill manifest is invalid.")
    source = skill_manifest.get("source", {})
    profiles: dict[str, str] = {}
    resources: dict[str, dict[str, Any]] = {}
    for role in sorted(roles):
        resource = role_resources.role(role)
        profile = effective_mapping.for_role(role)
        profiles[role] = profile
        skill_items = []
        for recommendation in resource.recommended_skills:
            bundled = skill_manifest["skills"].get(recommendation.skill_id)
            if type(bundled) is not dict:
                raise ValueError(
                    f"Bundled skill {recommendation.skill_id!r} is unavailable."
                )
            skill_items.append(
                {
                    "skill_id": recommendation.skill_id,
                    "source": recommendation.source,
                    "source_revision": str(source.get("revision", "unknown")),
                    "bundle_sha256": str(bundled["content_sha256"]),
                }
            )
        resources[role] = {
            "profile": profile,
            "profile_version": resource.profile_version,
            "soul_text": resource.soul_text,
            "soul_sha256": resource.soul_sha256,
            "skills": skill_items,
        }
    return profiles, resources


def load_skill_manifest(resource_root: Path) -> dict[str, Any]:
    """Load the bundled skill manifest."""
    manifest_path = resource_root / "skills" / "manifest.json"
    payload = manifest_path.read_bytes()
    document = loads_json(payload, source=str(manifest_path))
    if type(document) is not dict:
        raise JsonLoadError(
            "json.invalid",
            "Skill manifest is not a JSON object.",
            source=str(manifest_path),
        )
    return document


__all__ = ["compute_role_resources", "load_skill_manifest"]
