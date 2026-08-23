"""Researcher-facing role-definition projections for the configuration service."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from ..api.models import (
    AssetStatusView,
    BaseConfigurationView,
    ConfigurationHealthView,
    ConflictDetailView,
    CustomSkillView,
    LibraryGuidanceView,
    RoleDefinitionCatalogView,
    RoleDefinitionView,
    RoleHealthReportView,
    SkillRecommendationView,
)
from ..configuration.profiles import PROFILE_ROLES
from ..configuration.resources import RoleResourceCatalog
from ..configuration.role_provisioner import (
    AssetStatus,
    CustomizationConflict,
    RoleHealthReport,
    assess_role_health,
    discover_profile_home,
    hermes_available,
)
from collections.abc import Mapping

_AssetType = Literal["soul", "base_configuration", "library_guidance", "skill"]
_AssetStatusLiteral = Literal["present", "missing", "customized", "unavailable"]
_HealthConditionLiteral = Literal[
    "hermes_missing", "profile_missing", "soul_customized", "soul_missing",
    "config_customized", "config_missing", "skill_mismatch", "skill_missing",
    "skill_unavailable", "bundle_missing", "healthy",
]


def build_role_definition_view(
    resource_catalog: RoleResourceCatalog,
    role_id: str,
) -> RoleDefinitionView:
    """Build the complete role-definition view for one role."""
    resource = resource_catalog.role(role_id)
    return _role_definition_from_resource(resource)


def build_role_definition_catalog_view(
    resource_catalog: RoleResourceCatalog,
) -> RoleDefinitionCatalogView:
    """Build the complete role-definition catalog for all four roles."""
    roles = [_role_definition_from_resource(r) for r in resource_catalog.roles]
    return RoleDefinitionCatalogView(roles=roles)


def _role_definition_from_resource(resource) -> RoleDefinitionView:
    return RoleDefinitionView(
        role_id=resource.role_id,
        display_name=resource.display_name,
        profile_version=resource.profile_version,
        default_profile=resource.default_profile,
        applicable_phases=list(resource.applicable_phases),
        soul_text=resource.soul_text,
        soul_sha256=resource.soul_sha256,
        base_configuration=BaseConfigurationView(
            file_name=resource.base_configuration.file_name,
            format=resource.base_configuration.format,
            content_sha256=resource.base_configuration.sha256,
        ),
        recommended_skills=[
            SkillRecommendationView(
                skill_id=s.skill_id,
                name=s.name,
                description=s.description,
                source=s.source,
                recommended_version=s.recommended_version,
            )
            for s in resource.recommended_skills
        ],
        custom_skills=[
            CustomSkillView(
                skill_id=s.skill_id,
                name=s.name,
                description=s.description,
                source=s.source,
            )
            for s in resource.custom_skills
        ],
        library_guidance=LibraryGuidanceView(
            file_name=resource.library_guidance.file_name,
            content_sha256=resource.library_guidance.sha256,
        ),
    )


def build_configuration_health_view(
    resource_catalog: RoleResourceCatalog,
    hermes_root: Path,
    bundle_root: Path | None,
    effective_profiles: Mapping[str, str],
) -> ConfigurationHealthView:
    """Build the aggregate health view across all role definitions."""

    hermes_ok = hermes_available(hermes_root)
    role_reports: list[RoleHealthReportView] = []
    all_conditions: set[str] = set()
    overall_statuses: set[str] = set()

    if not hermes_ok:
        all_conditions.add("hermes_missing")

    for resource in resource_catalog.roles:
        profile_name = effective_profiles.get(resource.role_id) or resource.default_profile
        profile_home: Path | None = None
        if hermes_ok:
            profile_home = discover_profile_home(hermes_root, profile_name)

        report = assess_role_health(resource, profile_home, bundle_root)
        role_view = _health_report_to_view(resource.display_name, report)
        role_reports.append(role_view)
        all_conditions.update(role_view.conditions)
        overall_statuses.add(role_view.overall_status)

    if "unavailable" in overall_statuses or not hermes_ok:
        overall = "unavailable"
    elif "customized" in overall_statuses:
        overall = "customized"
    elif "incomplete" in overall_statuses:
        overall = "incomplete"
    else:
        overall = "healthy"

    if overall == "healthy" and not all_conditions:
        all_conditions_list: list[str] = ["healthy"]
    else:
        all_conditions_list = sorted(all_conditions)

    return ConfigurationHealthView(
        hermes_root=str(hermes_root),
        hermes_available=hermes_ok,
        roles=role_reports,
        overall_status=cast(
            Literal["healthy", "incomplete", "customized", "unavailable"],
            overall,
        ),
        conditions=[
            cast(_HealthConditionLiteral, c) for c in all_conditions_list
        ],
    )


def build_role_health_view(
    resource_catalog: RoleResourceCatalog,
    role_id: str,
    hermes_root: Path,
    bundle_root: Path | None,
    effective_profiles: Mapping[str, str],
) -> RoleHealthReportView:
    """Build the health view for a single role definition."""
    resource = resource_catalog.role(role_id)
    hermes_ok = hermes_available(hermes_root)
    profile_name = effective_profiles.get(role_id) or resource.default_profile
    profile_home: Path | None = None
    if hermes_ok:
        profile_home = discover_profile_home(hermes_root, profile_name)
    report = assess_role_health(resource, profile_home, bundle_root)
    return _health_report_to_view(resource.display_name, report)


def _health_report_to_view(
    display_name: str,
    report: RoleHealthReport,
) -> RoleHealthReportView:
    conditions = _derive_conditions(report)
    return RoleHealthReportView(
        role_id=report.role_id,
        display_name=display_name,
        profile_available=report.profile_available,
        profile_name=report.profile_name,
        overall_status=cast(
            Literal["healthy", "incomplete", "customized", "unavailable"],
            report.overall_status,
        ),
        soul_status=_asset_to_view(report.soul_status),
        configuration_status=_asset_to_view(report.configuration_status),
        guidance_status=_asset_to_view(report.guidance_status),
        skill_statuses=[_asset_to_view(s) for s in report.skill_statuses],
        conditions=[cast(_HealthConditionLiteral, c) for c in conditions],
        detail=report.detail,
    )


def _derive_conditions(report: RoleHealthReport) -> list[str]:
    """Derive the list of health condition codes from a health report."""
    conditions: list[str] = []
    if not report.profile_available:
        conditions.append("profile_missing")
    if report.soul_status.status == "missing":
        conditions.append("soul_missing")
    if report.soul_status.status == "customized":
        conditions.append("soul_customized")
    if report.configuration_status.status == "missing":
        conditions.append("config_missing")
    if report.configuration_status.status == "customized":
        conditions.append("config_customized")
    bundle_missing_reported = False
    for skill in report.skill_statuses:
        if skill.status == "missing":
            conditions.append("skill_missing")
        elif skill.status == "customized":
            conditions.append("skill_mismatch")
        elif skill.status == "unavailable":
            conditions.append("skill_unavailable")
            # The profile exists but the recommended skill's source cannot be
            # reached — the skill bundle (or the skill inside it) is missing.
            if report.profile_available and not bundle_missing_reported:
                conditions.append("bundle_missing")
                bundle_missing_reported = True
    if report.overall_status == "healthy" and not conditions:
        conditions.append("healthy")
    return conditions


def _asset_to_view(status: AssetStatus) -> AssetStatusView:
    return AssetStatusView(
        asset_type=cast(_AssetType, status.asset_type),
        file_name=status.file_name,
        status=cast(_AssetStatusLiteral, status.status),
        expected_sha256=status.expected_sha256,
        actual_sha256=status.actual_sha256,
        source=status.source,
        recommended_version=status.recommended_version,
        detail=status.detail,
    )


def build_conflict_detail(
    conflict: CustomizationConflict,
) -> ConflictDetailView:
    """Build a conflict detail view from a CustomizationConflict."""
    return ConflictDetailView(
        role_id=conflict.role_id,
        asset_type=conflict.asset_type,
        file_name=conflict.path.name,
        expected_sha256=conflict.expected_sha256,
        actual_sha256=conflict.actual_sha256,
        resolution_options=["keep_custom", "overwrite_with_reference"],
    )


__all__ = [
    "build_conflict_detail",
    "build_configuration_health_view",
    "build_role_definition_catalog_view",
    "build_role_definition_view",
    "build_role_health_view",
]
