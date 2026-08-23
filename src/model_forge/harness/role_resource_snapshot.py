"""Shared role-resource snapshot for basis sealing.

Both the phase view (at descriptor computation time) and the run coordinator
(at preparation time) need to produce the same role-resource snapshot so that
drift can be detected. This module centralises that computation.

The snapshot seals the exact installed role configuration (WP-H2), not just
bundled recommendations: in addition to the profile/soul/skill records it
carries the memory policy declared by the WP-C base configuration, the
content-addressed digests of the base configuration and library guidance,
the declared custom skills, and explicit nulls for every resource the WP-C
definition does not declare (model, provider, tools, per-role phase
instruction).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from ..configuration.profiles import PROFILE_ROLES, ProfileMapping
from ..configuration.resources import RoleResource, RoleResourceCatalog
from ..json_io import JsonLoadError, loads_json


def _memory_policy(resource: RoleResource) -> str:
    """Return the memory persistence declared by the role's base configuration.

    The WP-C base configuration (``configs/<role>.yaml``) declares
    ``memory.persistence`` (e.g. ``persistent``, ``fresh``). The exact value
    is recorded verbatim; an undeclarable or missing value fails closed
    because an unsealable memory policy cannot be reviewed.
    """
    document = yaml.safe_load(resource.base_configuration.content)
    if type(document) is not dict:
        raise ValueError(
            f"Base configuration for {resource.role_id!r} is not a YAML mapping."
        )
    memory = document.get("memory")
    if type(memory) is not dict:
        raise ValueError(
            f"Base configuration for {resource.role_id!r} declares no memory section."
        )
    persistence = memory.get("persistence")
    if type(persistence) is not str or not persistence:
        raise ValueError(
            f"Base configuration for {resource.role_id!r} declares no "
            "memory persistence."
        )
    return persistence


def role_phase_instructions(
    document: Mapping[str, Any] | None,
    mode: str | None,
    roles: set[str],
) -> dict[str, str | None]:
    """Return per-role phase instruction text declared by the phase contract.

    The machine-readable phase contracts describe role stages with plain role
    id lists and a stage-level ``objective``; they carry no per-role
    instruction text. Every role therefore records an explicit ``None`` --
    never a fabricated instruction. If a future contract declares per-role
    instruction text (a role entry as an object carrying ``role`` and
    ``instruction`` keys), the text is recorded verbatim so the snapshot
    stays exact without code changes.
    """
    instructions: dict[str, str | None] = {role: None for role in roles}
    if document is None or mode is None:
        return instructions
    for stage in document.get("role_stages", ()):
        if type(stage) is not dict or mode not in stage.get("applicable_modes", ()):
            continue
        for role_entry in stage.get("roles", ()):
            if type(role_entry) is not dict:
                continue
            role_id = str(role_entry.get("role"))
            instruction = role_entry.get("instruction")
            if role_id in instructions and type(instruction) is str and instruction:
                instructions[role_id] = instruction
    return instructions


def compute_role_resources(
    *,
    repository,
    settings,
    role_resources: RoleResourceCatalog,
    skill_manifest: Mapping[str, Any],
    roles: set[str],
    project_id: str,
    contract_document: Mapping[str, Any] | None = None,
    mode: str | None = None,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """Compute the role-resource snapshot for the given roles.

    Returns ``(profiles, resources)`` in the same format as
    ``RunCoordinator._freeze_role_resources``. Each role's sealed resources
    carry the exact installed role configuration: the effective profile, the
    WP-C profile version, soul text and digest, skill entries, the memory
    policy parsed from the WP-C base configuration, the content-addressed
    digests of the base configuration and library guidance, the declared
    custom skills, and explicit nulls for model/provider/tools and the
    per-role phase instruction (all undeclared by the current WP-C definition
    and phase contracts).
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
    phase_instructions = role_phase_instructions(contract_document, mode, roles)
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
        base_configuration = resource.base_configuration
        library_guidance = resource.library_guidance
        resources[role] = {
            "profile": profile,
            "profile_version": resource.profile_version,
            "soul_text": resource.soul_text,
            "soul_sha256": resource.soul_sha256,
            "skills": skill_items,
            # WP-H2 exact installed role configuration. model/provider are
            # explicit nulls: the WP-C role definition declares neither.
            "model": None,
            "provider": None,
            "memory_policy": _memory_policy(resource),
            "phase_instruction": phase_instructions[role],
            # tools is an explicit null: the WP-C role definition declares
            # no tool references.
            "tools": None,
            "base_configuration": {
                "file_name": base_configuration.file_name,
                "format": base_configuration.format,
                "sha256": base_configuration.sha256,
            },
            "library_guidance": {
                "file_name": library_guidance.file_name,
                "sha256": library_guidance.sha256,
            },
            "custom_skills": [
                {"skill_id": skill.skill_id, "source": skill.source}
                for skill in resource.custom_skills
            ],
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


__all__ = ["compute_role_resources", "load_skill_manifest", "role_phase_instructions"]
