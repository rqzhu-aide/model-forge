"""Researcher-facing profile and recommended-skill projections."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from ..api.models import (
    ActionDescriptor,
    ProfileConfigurationView,
    ProfileOption,
    ProjectionStamp,
    RoleProfileView,
    SkillStatus,
)
from ..configuration.profiles import (
    PROFILE_ROLES,
    REVIEWER_PROFILE_ISOLATION_MESSAGE,
    REVIEWER_PROFILE_ROLE,
    ProfileDiscovery,
    ProfileMapping,
    assignment_conflict,
)
from ..configuration.resources import RoleResourceCatalog
from ..configuration.skill_installer import SkillInstallationError, directory_sha256


def _action_id(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return "action." + digest


def _mapping_values(
    mapping: ProfileMapping | Mapping[str, str],
) -> dict[str, str]:
    values = mapping.to_dict() if isinstance(mapping, ProfileMapping) else dict(mapping)
    if set(values) != set(PROFILE_ROLES):
        raise ValueError("Effective profile mapping must cover all research roles.")
    return {role: str(values[role]) for role in PROFILE_ROLES}


def _mapping_state_token(
    mapping: Mapping[str, str],
    mapping_revisions: Mapping[str, int],
) -> str:
    if set(mapping_revisions) != set(PROFILE_ROLES):
        raise ValueError("Profile mapping revisions must cover all research roles.")
    parts = ["profile_mapping_state"]
    for role in PROFILE_ROLES:
        revision = mapping_revisions[role]
        if type(revision) is not int or revision < 0:
            raise ValueError("Profile mapping revisions must be nonnegative integers.")
        parts.extend((role, mapping[role], str(revision)))
    return _action_id(*parts)


def build_profile_configuration_view(
    *,
    project_id: str,
    catalog: RoleResourceCatalog,
    mapping: ProfileMapping | Mapping[str, str],
    mapping_revisions: Mapping[str, int],
    discoveries: tuple[ProfileDiscovery, ...],
    bundle_root: Path | None = None,
    skill_mutation_locked: bool = False,
) -> ProfileConfigurationView:
    """Project role mappings and locally observed skill installation state."""

    mapping_values = _mapping_values(mapping)
    mapping_state = _mapping_state_token(mapping_values, mapping_revisions)
    safe_profiles = tuple(item for item in discoveries if item.is_safe_directory)
    by_name = {item.name: item for item in discoveries}
    profiles: list[RoleProfileView] = []
    for resource in catalog.roles:
        selected_name = mapping_values[resource.role_id]
        selected = by_name.get(selected_name)
        usable = selected is not None and selected.is_safe_directory
        current_conflict = assignment_conflict(
            resource.role_id,
            selected_name,
            mapping_values,
        )
        options = []
        for item in safe_profiles:
            conflict = assignment_conflict(
                resource.role_id,
                item.name,
                mapping_values,
            )
            already_selected = item.name == selected_name
            enabled = not conflict and not already_selected
            option_message = (
                REVIEWER_PROFILE_ISOLATION_MESSAGE
                if conflict
                else (
                    "This profile is already assigned."
                    if already_selected
                    else None
                )
            )
            options.append(
                ProfileOption(
                    profile_id=item.name,
                    label=item.name,
                    version="local",
                    enabled=enabled,
                    researcher_message=option_message,
                    action_descriptor_id=_action_id(
                        project_id,
                        resource.role_id,
                        "save_profile",
                        mapping_state,
                        selected_name,
                        item.name,
                        str(enabled).lower(),
                    ),
                )
            )

        skills: list[SkillStatus] = []
        for skill in resource.recommended_skills:
            bundle_digest = _bundle_digest(bundle_root, skill.skill_id)
            status = _skill_state(
                selected.home if usable and selected is not None else None,
                bundle_root,
                skill.skill_id,
                bundle_digest,
            )
            installed = status == "installed"
            action_enabled = (
                status == "missing"
                and not current_conflict
                and not skill_mutation_locked
            )
            if current_conflict:
                reason_code = "profile.reviewer_memory_conflict"
                action_message = REVIEWER_PROFILE_ISOLATION_MESSAGE
                status_detail = (
                    "Repair the reviewer and author profile assignment before "
                    "installing role resources."
                )
            elif status == "missing" and skill_mutation_locked:
                reason_code = "control.active_run"
                action_message = (
                    "A research run is active, so shared Hermes profile skills "
                    "cannot be changed."
                )
                status_detail = (
                    "Wait for active research runs to finish or cancel them "
                    "before installing this skill."
                )
            elif action_enabled:
                reason_code = None
                action_message = None
                status_detail = "Install the pinned skill bundle in the selected profile."
            elif installed:
                reason_code = "skill.already_installed"
                action_message = "This exact pinned skill is already installed."
                status_detail = (
                    "The selected profile contains the exact pinned skill bundle."
                )
            elif status == "update_available":
                reason_code = "skill.local_copy_differs"
                action_message = (
                    "A different local copy exists and cannot be overwritten."
                )
                status_detail = (
                    "A different local copy exists and will not be overwritten."
                )
            else:
                reason_code = "profile.unavailable"
                action_message = (
                    "The selected profile or bundled skill is unavailable."
                )
                status_detail = (
                    "Select an available profile with a bundled skill source."
                )
            skills.append(
                SkillStatus(
                    skill_id=skill.skill_id,
                    name=skill.name,
                    description=skill.description,
                    required=False,
                    status=status,
                    installed_version="local" if installed else None,
                    recommended_version=skill.recommended_version,
                    source_revision=skill.source,
                    status_detail=status_detail,
                    actions=[
                        ActionDescriptor(
                            descriptor_id=_action_id(
                                project_id,
                                resource.role_id,
                                skill.skill_id,
                                "install_skill",
                                mapping_state,
                                selected_name,
                                bundle_digest or "unavailable",
                                status,
                                str(action_enabled).lower(),
                            ),
                            action_type="install_skill",
                            execution_kind="configuration",
                            enabled=action_enabled,
                            reason_code=reason_code,
                            researcher_message=action_message,
                            consequence_summary=(
                                "Install this recommended skill only in the selected "
                                "Hermes profile. Existing run manifests remain unchanged."
                            ),
                            target_id=skill.skill_id,
                        )
                    ],
                )
            )

        if current_conflict:
            memory_summary = (
                REVIEWER_PROFILE_ISOLATION_MESSAGE
                + " Repair this current assignment before preparing another run."
            )
        elif resource.role_id == REVIEWER_PROFILE_ROLE:
            memory_summary = (
                "The harness supplies only the declared Phase 5 review packet, "
                "and the distinct profile prevents direct sharing of author-role "
                "memory. Current Hermes integration cannot attest that persistent "
                "reviewer-profile memory is empty."
            )
        else:
            memory_summary = (
                "Role and phase resources are frozen for each run. The outside "
                "reviewer uses a distinct persistent-memory profile."
            )
        profiles.append(
            RoleProfileView(
                role_id=resource.role_id,
                display_name=resource.display_name,
                role_summary=_first_paragraph(resource.soul_text),
                profile_id=selected_name,
                profile_version=resource.profile_version,
                profile_options=options,
                scientific_stance_summary=_first_paragraph(resource.soul_text),
                model_summary=(
                    "Model and provider settings are read from the selected Hermes profile."
                ),
                memory_policy_summary=memory_summary,
                applicable_phases=list(resource.applicable_phases),
                skills=skills,
                actions=[],
            )
        )
    return ProfileConfigurationView(
        profiles=profiles,
        projection=ProjectionStamp(
            view_revision=max(mapping_revisions.values(), default=0)
        ),
    )


def _bundle_digest(bundle_root: Path | None, skill_id: str) -> str | None:
    if bundle_root is None:
        return None
    source = bundle_root / skill_id
    if not source.is_dir() or source.is_symlink():
        return None
    try:
        return directory_sha256(source)
    except (OSError, SkillInstallationError):
        return None


def _skill_state(
    profile_home: Path | None,
    bundle_root: Path | None,
    skill_id: str,
    bundle_digest: str | None,
) -> str:
    if profile_home is None or bundle_root is None or bundle_digest is None:
        return "unavailable"
    destination = profile_home / "skills" / skill_id
    try:
        if not destination.exists():
            return "missing"
        if not destination.is_dir() or destination.is_symlink():
            return "update_available"
        return (
            "installed"
            if bundle_digest == directory_sha256(destination)
            else "update_available"
        )
    except (OSError, SkillInstallationError):
        return "unavailable"


def _first_paragraph(text: str) -> str:
    paragraphs = [item.strip() for item in text.split("\n\n") if item.strip()]
    for paragraph in paragraphs:
        if not paragraph.startswith("#"):
            return " ".join(line.strip() for line in paragraph.splitlines())
    return "Scientific role instructions are available in the bundled profile resource."


__all__ = ["build_profile_configuration_view"]
