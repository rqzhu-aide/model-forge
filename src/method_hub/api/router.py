"""FastAPI routes for researcher-facing projections and commands."""

from __future__ import annotations

from collections.abc import AsyncIterator
from hashlib import sha256
from typing import Annotated, TypeVar, cast

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from .errors import CommandRejected, command_schema_error
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
    StartSupervisedRunRequest,
    StrictModel,
    SupervisedRunDetail,
    SupervisedRunSummary,
    SystemSettingsView,
    UpdateProjectBriefRequest,
)
from .ports import (
    ArtifactDelivery,
    CommandFamily,
    RawRequestBody,
    RawRequestReceipt,
    MethodHubApplicationService,
)


API_PREFIX = "/api/v1"
CommandModel = TypeVar("CommandModel", bound=StrictModel)
_INLINE_ARTIFACT_MEDIA_TYPES = frozenset(
    {"application/json", "text/markdown", "text/plain"}
)


def _service_from_request(request: Request) -> MethodHubApplicationService:
    return cast(MethodHubApplicationService, request.app.state.method_hub_service)


Service = Annotated[MethodHubApplicationService, Depends(_service_from_request)]


def _body_contract(model: type[StrictModel]) -> dict[str, object]:
    return {
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": model.model_json_schema()}
            },
        }
    }


def _validation_field_path(exception: ValidationError) -> str | None:
    first = exception.errors()[0] if exception.errors() else None
    if first is None:
        return None
    return ".".join(str(item) for item in first.get("loc", ())) or None


def _artifact_response(
    delivery: ArtifactDelivery, *, download: bool
) -> Response:
    inline = not download and delivery.media_type in _INLINE_ARTIFACT_MEDIA_TYPES
    disposition = "inline" if inline else "attachment"
    media_type = delivery.media_type if inline else "application/octet-stream"
    return Response(
        content=delivery.content,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "Content-Disposition": f'{disposition}; filename="{delivery.filename}"',
            "ETag": f'"{delivery.content_sha256}"',
            "X-Content-SHA256": delivery.content_sha256,
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _capture_and_parse(
    request: Request,
    service: MethodHubApplicationService,
    model: type[CommandModel],
    *,
    command_family: CommandFamily,
    project_id: str | None,
) -> tuple[CommandModel, RawRequestReceipt]:
    """Preserve exact command bytes before attempting JSON or schema parsing."""

    body = await request.body()
    digest = sha256(body).hexdigest()
    raw_request = RawRequestBody(
        body=body,
        byte_length=len(body),
        media_type=request.headers.get("content-type", "application/octet-stream"),
        content_sha256=digest,
        method=request.method,
        path=request.url.path,
        command_family=command_family,
        project_id=project_id,
        idempotency_key=request.headers.get("idempotency-key"),
    )
    receipt = await service.preserve_raw_request(raw_request)

    try:
        parsed = model.model_validate_json(body, strict=True)
    except ValidationError as exception:
        raise CommandRejected(
            command_schema_error(_validation_field_path(exception))
        ) from exception
    return parsed, receipt


def create_api_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)

    @router.get(
        "/projects",
        response_model=list[ProjectSummary],
        response_model_exclude_none=True,
    )
    async def list_projects(service: Service) -> list[ProjectSummary]:
        return await service.list_projects()

    @router.post(
        "/projects",
        response_model=ProjectSummary,
        response_model_exclude_none=True,
        status_code=status.HTTP_201_CREATED,
        openapi_extra=_body_contract(CreateProjectRequest),
    )
    async def create_project(request: Request, service: Service) -> ProjectSummary:
        command, raw_request = await _capture_and_parse(
            request,
            service,
            CreateProjectRequest,
            command_family="create_project",
            project_id=None,
        )
        return await service.create_project(command, raw_request=raw_request)

    @router.get(
        "/system/settings",
        response_model=SystemSettingsView,
        response_model_exclude_none=True,
    )
    async def get_system_settings(service: Service) -> SystemSettingsView:
        return await service.get_system_settings()

    @router.get(
        "/projects/{project_id}/brief",
        response_model=ProjectBriefView,
        response_model_exclude_none=True,
    )
    async def get_project_brief(
        project_id: str, service: Service
    ) -> ProjectBriefView:
        return await service.get_project_brief(project_id)

    @router.patch(
        "/projects/{project_id}/brief",
        response_model=ProjectBriefView,
        response_model_exclude_none=True,
        openapi_extra=_body_contract(UpdateProjectBriefRequest),
    )
    async def update_project_brief(
        project_id: str,
        request: Request,
        service: Service,
    ) -> ProjectBriefView:
        command, raw_request = await _capture_and_parse(
            request,
            service,
            UpdateProjectBriefRequest,
            command_family="update_project_brief",
            project_id=project_id,
        )
        return await service.update_project_brief(
            project_id, command, raw_request=raw_request
        )

    @router.get(
        "/projects/{project_id}/overview",
        response_model=ProjectOverview,
        response_model_exclude_none=True,
    )
    async def get_project_overview(
        project_id: str, service: Service
    ) -> ProjectOverview:
        return await service.get_project_overview(project_id)

    @router.get(
        "/projects/{project_id}/phases/{phase_id}",
        response_model=PhaseView,
        response_model_exclude_none=True,
    )
    async def get_phase_view(
        project_id: str,
        phase_id: PhaseId,
        service: Service,
        mode: str | None = None,
        method_id: str | None = None,
    ) -> PhaseView:
        return await service.get_phase_view(
            project_id, phase_id, mode=mode, method_id=method_id
        )

    @router.get(
        "/projects/{project_id}/methods",
        response_model=list[MethodRow],
        response_model_exclude_none=True,
    )
    async def list_methods(project_id: str, service: Service) -> list[MethodRow]:
        return await service.list_methods(project_id)

    @router.post(
        "/projects/{project_id}/methods/{method_id}/lifecycle",
        status_code=status.HTTP_204_NO_CONTENT,
        openapi_extra=_body_contract(ReasonedActionRequest),
    )
    async def change_method_lifecycle(
        project_id: str,
        method_id: str,
        request: Request,
        service: Service,
    ) -> Response:
        command, raw_request = await _capture_and_parse(
            request,
            service,
            ReasonedActionRequest,
            command_family="method_lifecycle",
            project_id=project_id,
        )
        await service.change_method_lifecycle(
            project_id, method_id, command, raw_request=raw_request
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/projects/{project_id}/runs",
        response_model=list[RunSummary],
        response_model_exclude_none=True,
    )
    async def list_runs(
        project_id: str,
        service: Service,
        phase: PhaseId | None = None,
    ) -> list[RunSummary]:
        return await service.list_runs(project_id, phase=phase)

    @router.post(
        "/projects/{project_id}/runs",
        response_model=RunDetail,
        response_model_exclude_none=True,
        status_code=status.HTTP_201_CREATED,
        openapi_extra=_body_contract(StartRunRequest),
    )
    async def start_run(
        project_id: str, request: Request, service: Service
    ) -> RunDetail:
        command, raw_request = await _capture_and_parse(
            request,
            service,
            StartRunRequest,
            command_family="start_run",
            project_id=project_id,
        )
        return await service.start_run(
            project_id, command, raw_request=raw_request
        )

    @router.get(
        "/projects/{project_id}/runs/{run_id}",
        response_model=RunDetail,
        response_model_exclude_none=True,
    )
    async def get_run(
        project_id: str, run_id: str, service: Service
    ) -> RunDetail:
        return await service.get_run(project_id, run_id)

    @router.get(
        "/projects/{project_id}/supervised-runs",
        response_model=list[SupervisedRunSummary],
        response_model_exclude_none=True,
    )
    async def list_supervised_runs(
        project_id: str, service: Service
    ) -> list[SupervisedRunSummary]:
        """List sealed supervised invocations (read-only; WP-F0).

        The path ``project_id`` is the free-form project id the
        run-profile assembler seals under — there is deliberately no
        project-existence check against the hub repository, and a
        project without supervised runs returns an empty list.
        """
        return await service.list_supervised_runs(project_id)

    @router.get(
        "/projects/{project_id}/supervised-runs/{invocation_id}",
        response_model=SupervisedRunDetail,
        response_model_exclude_none=True,
    )
    async def get_supervised_run(
        project_id: str, invocation_id: str, service: Service
    ) -> SupervisedRunDetail:
        """Return the durable detail view of one supervised invocation."""
        return await service.get_supervised_run(project_id, invocation_id)

    @router.post(
        "/projects/{project_id}/supervised-runs",
        response_model=SupervisedRunDetail,
        response_model_exclude_none=True,
        status_code=status.HTTP_202_ACCEPTED,
        openapi_extra=_body_contract(StartSupervisedRunRequest),
    )
    async def start_supervised_run(
        project_id: str,
        request: Request,
        service: Service,
        response: Response,
    ) -> SupervisedRunDetail:
        """Seal and schedule one supervised run (explicit command; WP-F1a).

        Returns 202 with the invocation detail once the launch record is
        scheduled (the WP-E0 launch runs in the background and the WP-F0
        read surface shows its progress).  An idempotent replay of an
        existing key returns the existing invocation with 200 and does
        not launch again.  Invalid requests are 400; a held project-role
        state lock or a failing preflight is 409.
        """
        command, raw_request = await _capture_and_parse(
            request,
            service,
            StartSupervisedRunRequest,
            command_family="start_supervised_run",
            project_id=project_id,
        )
        result = await service.start_supervised_run(
            project_id, command, raw_request=raw_request
        )
        if result.replayed:
            response.status_code = status.HTTP_200_OK
        return result.detail

    @router.get("/projects/{project_id}/artifacts/{artifact_id}")
    async def get_artifact(
        project_id: str,
        artifact_id: str,
        service: Service,
        download: bool = False,
    ) -> Response:
        delivery = await service.get_artifact(project_id, artifact_id)
        return _artifact_response(delivery, download=download)

    @router.get(
        "/projects/{project_id}/publications/{receipt_id}",
        response_model=PublicationReceiptDocument,
        response_model_exclude_none=True,
    )
    async def get_publication_receipt(
        project_id: str,
        receipt_id: str,
        service: Service,
        response: Response,
    ) -> PublicationReceiptDocument:
        receipt = await service.get_publication_receipt(project_id, receipt_id)
        response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
        response.headers["ETag"] = f'"{receipt.content_sha256}"'
        response.headers["X-Content-Type-Options"] = "nosniff"
        return receipt

    @router.get(
        "/projects/{project_id}/runs/{run_id}/events",
        response_model=list[RunEvent],
        response_model_exclude_none=True,
    )
    async def list_run_events(
        project_id: str,
        run_id: str,
        service: Service,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
    ) -> list[RunEvent]:
        return await service.list_run_events(
            project_id, run_id, after_sequence=after_sequence
        )

    @router.get("/projects/{project_id}/runs/{run_id}/events/stream")
    async def stream_run_events(
        project_id: str,
        run_id: str,
        request: Request,
        service: Service,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
    ) -> StreamingResponse:
        events = await service.stream_run_events(
            project_id, run_id, after_sequence=after_sequence
        )

        async def encode_events() -> AsyncIterator[str]:
            async for event in events:
                if await request.is_disconnected():
                    break
                payload = event.model_dump_json(exclude_none=True)
                yield f"id: {event.sequence}\ndata: {payload}\n\n"

        return StreamingResponse(
            encode_events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @router.post(
        "/projects/{project_id}/runs/{run_id}/cancel",
        response_model=RunDetail,
        response_model_exclude_none=True,
        openapi_extra=_body_contract(ReasonedActionRequest),
    )
    async def cancel_run(
        project_id: str,
        run_id: str,
        request: Request,
        service: Service,
    ) -> RunDetail:
        command, raw_request = await _capture_and_parse(
            request,
            service,
            ReasonedActionRequest,
            command_family="cancel_run",
            project_id=project_id,
        )
        return await service.cancel_run(
            project_id, run_id, command, raw_request=raw_request
        )

    @router.get(
        "/projects/{project_id}/configuration/profiles",
        response_model=ProfileConfigurationView,
        response_model_exclude_none=True,
    )
    async def get_profiles(
        project_id: str, service: Service
    ) -> ProfileConfigurationView:
        return await service.get_profiles(project_id)

    @router.patch(
        "/projects/{project_id}/configuration/profiles/{role_id}",
        response_model=ProfileConfigurationView,
        response_model_exclude_none=True,
        openapi_extra=_body_contract(SaveProfileRequest),
    )
    async def save_profile(
        project_id: str,
        role_id: str,
        request: Request,
        service: Service,
    ) -> ProfileConfigurationView:
        command, raw_request = await _capture_and_parse(
            request,
            service,
            SaveProfileRequest,
            command_family="save_profile",
            project_id=project_id,
        )
        return await service.save_profile(
            project_id, role_id, command, raw_request=raw_request
        )

    @router.post(
        "/projects/{project_id}/configuration/profiles/{role_id}/skills/{skill_id}/install",
        response_model=ProfileConfigurationView,
        response_model_exclude_none=True,
        openapi_extra=_body_contract(InstallSkillRequest),
    )
    async def install_skill(
        project_id: str,
        role_id: str,
        skill_id: str,
        request: Request,
        service: Service,
    ) -> ProfileConfigurationView:
        command, raw_request = await _capture_and_parse(
            request,
            service,
            InstallSkillRequest,
            command_family="install_skill",
            project_id=project_id,
        )
        return await service.install_skill(
            project_id,
            role_id,
            skill_id,
            command,
            raw_request=raw_request,
        )

    # ------------------------------------------------------------------ #
    # Block 2: role-definition configuration service endpoints           #
    # ------------------------------------------------------------------ #

    @router.get(
        "/configuration/roles",
        response_model=RoleDefinitionCatalogView,
        response_model_exclude_none=True,
    )
    async def get_role_definitions(
        service: Service,
    ) -> RoleDefinitionCatalogView:
        return await service.get_role_definitions()

    @router.get(
        "/configuration/roles/{role_id}",
        response_model=RoleDefinitionView,
        response_model_exclude_none=True,
    )
    async def get_role_definition(
        role_id: str, service: Service
    ) -> RoleDefinitionView:
        return await service.get_role_definition(role_id)

    @router.get(
        "/configuration/health",
        response_model=ConfigurationHealthView,
        response_model_exclude_none=True,
    )
    async def get_configuration_health(
        service: Service,
    ) -> ConfigurationHealthView:
        return await service.get_configuration_health()

    @router.get(
        "/configuration/roles/{role_id}/health",
        response_model=RoleHealthReportView,
        response_model_exclude_none=True,
    )
    async def get_role_health(
        role_id: str, service: Service
    ) -> RoleHealthReportView:
        return await service.get_role_health(role_id)

    @router.post(
        "/configuration/roles/{role_id}/provision",
        response_model=ProvisionResultView,
        response_model_exclude_none=True,
        openapi_extra=_body_contract(ProvisionRoleRequest),
    )
    async def provision_role(
        role_id: str,
        request: Request,
        service: Service,
    ) -> ProvisionResultView:
        command, _ = await _capture_and_parse(
            request,
            service,
            ProvisionRoleRequest,
            command_family="provision_role",
            project_id=None,
        )
        return await service.provision_role(role_id, command)

    return router
