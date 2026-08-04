"""Application-service port consumed by the FastAPI transport."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from .models import (
    ConfigurationHealthView,
    CreateProjectRequest,
    InstallSkillRequest,
    MethodRow,
    PhaseId,
    PhaseView,
    ProfileConfigurationView,
    ProvisionResultView,
    ProvisionRoleRequest,
    PublicationReceiptDocument,
    ProjectBriefView,
    ProjectOverview,
    ProjectSummary,
    ReasonedActionRequest,
    RoleDefinitionCatalogView,
    RoleDefinitionView,
    RoleHealthReportView,
    RunDetail,
    RunEvent,
    RunSummary,
    SaveProfileRequest,
    StartRunRequest,
    SystemSettingsView,
    UpdateProjectBriefRequest,
)


CommandFamily = Literal[
    "create_project",
    "update_project_brief",
    "start_run",
    "cancel_run",
    "method_lifecycle",
    "save_profile",
    "install_skill",
    "provision_role",
]


@dataclass(frozen=True, slots=True)
class RawRequestBody:
    """Exact command bytes and transport metadata captured before parsing."""

    body: bytes
    byte_length: int
    media_type: str
    content_sha256: str
    method: str
    path: str
    command_family: CommandFamily
    project_id: str | None
    idempotency_key: str | None


@dataclass(frozen=True, slots=True)
class RawRequestReceipt:
    """Opaque durable identity returned by the application service."""

    request_artifact_id: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ArtifactDelivery:
    """Verified bytes and presentation metadata for one immutable artifact."""

    artifact_id: str
    content: bytes
    media_type: str
    content_sha256: str
    filename: str


class MethodHubApplicationService(Protocol):
    """Operations required by the Web and remote-compatible HTTP API."""

    async def preserve_raw_request(
        self, raw_request: RawRequestBody
    ) -> RawRequestReceipt: ...

    async def list_projects(self) -> list[ProjectSummary]: ...

    async def create_project(
        self,
        command: CreateProjectRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProjectSummary: ...

    async def get_project_brief(self, project_id: str) -> ProjectBriefView: ...

    async def update_project_brief(
        self,
        project_id: str,
        command: UpdateProjectBriefRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProjectBriefView: ...

    async def get_system_settings(self) -> SystemSettingsView: ...

    async def get_project_overview(self, project_id: str) -> ProjectOverview: ...

    async def get_phase_view(
        self,
        project_id: str,
        phase_id: PhaseId,
        *,
        mode: str | None,
        method_id: str | None,
    ) -> PhaseView: ...

    async def list_methods(self, project_id: str) -> list[MethodRow]: ...

    async def change_method_lifecycle(
        self,
        project_id: str,
        method_id: str,
        command: ReasonedActionRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> None: ...

    async def list_runs(
        self, project_id: str, *, phase: PhaseId | None
    ) -> list[RunSummary]: ...

    async def start_run(
        self,
        project_id: str,
        command: StartRunRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> RunDetail: ...

    async def get_run(self, project_id: str, run_id: str) -> RunDetail: ...

    async def get_artifact(
        self, project_id: str, artifact_id: str
    ) -> ArtifactDelivery: ...

    async def get_publication_receipt(
        self, project_id: str, receipt_id: str
    ) -> PublicationReceiptDocument: ...

    async def list_run_events(
        self, project_id: str, run_id: str, *, after_sequence: int
    ) -> list[RunEvent]: ...

    async def stream_run_events(
        self, project_id: str, run_id: str, *, after_sequence: int
    ) -> AsyncIterator[RunEvent]: ...

    async def cancel_run(
        self,
        project_id: str,
        run_id: str,
        command: ReasonedActionRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> RunDetail: ...

    async def get_profiles(self, project_id: str) -> ProfileConfigurationView: ...

    async def save_profile(
        self,
        project_id: str,
        role_id: str,
        command: SaveProfileRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProfileConfigurationView: ...

    async def install_skill(
        self,
        project_id: str,
        role_id: str,
        skill_id: str,
        command: InstallSkillRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProfileConfigurationView: ...

    async def get_role_definitions(self) -> RoleDefinitionCatalogView: ...

    async def get_role_definition(self, role_id: str) -> RoleDefinitionView: ...

    async def get_configuration_health(self) -> ConfigurationHealthView: ...

    async def get_role_health(self, role_id: str) -> RoleHealthReportView: ...

    async def provision_role(
        self,
        role_id: str,
        command: ProvisionRoleRequest,
    ) -> ProvisionResultView: ...
