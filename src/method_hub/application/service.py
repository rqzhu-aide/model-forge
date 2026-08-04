"""Concrete application service joining API projections to durable state."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from .. import __version__
from ..api.errors import CommandRejected, new_command_error
from ..api.models import (
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
    ConfigurationHealthView,
    RunDetail,
    RunEvent,
    RunSummary,
    SaveProfileRequest,
    StartRunRequest,
    SystemSettingsView,
    UpdateProjectBriefRequest,
)
from ..api.ports import ArtifactDelivery, RawRequestBody, RawRequestReceipt
from ..configuration.profiles import (
    PROFILE_ROLES,
    REVIEWER_PROFILE_ISOLATION_MESSAGE,
    ProfileConfigurationError,
    ProfileMapping,
    discover_profiles,
    resolve_hermes_root,
)
from ..configuration.resources import RoleResourceCatalog
from ..configuration.role_provisioner import (
    CustomizationConflict,
    ProvisioningError,
    discover_profile_home,
    hermes_available,
    provision_role_definition,
)
from ..configuration.skill_installer import (
    SkillConflictError,
    SkillInstallationError,
    install_bundled_skill,
)
from ..contracts import PhaseContractError
from ..digests.jcs import canonicalize
from ..domain.identities import MethodIdentity
from ..domain.runs import RunRequest, isoformat_utc, utc_now
from ..harness.commands import build_run_command
from ..harness.role_resource_snapshot import compute_role_resources, load_skill_manifest
from ..specification import SpecificationPackage
from ..storage.artifacts import ArtifactStore
from ..storage.errors import ArtifactIntegrityError
from ..storage.repository import (
    HubRepository,
    RepositoryConflictError,
    RepositoryNotFoundError,
)
from .method_lifecycle import MethodLifecycleCommandService
from .profile_views import build_profile_configuration_view
from .project_commands import ProjectCommandService
from .repository_views import RepositoryQueries, row_json
from .role_views import (
    build_conflict_detail,
    build_configuration_health_view,
    build_role_definition_catalog_view,
    build_role_definition_view,
    build_role_health_view,
)
from .run_views import CANCELLABLE, run_detail_view, run_event_view, run_summary_view
from .settings import ApplicationSettings
from .view_models import ACTIVE_RUN_STATES, ResearchProjectionService, project_summary


RunLauncher = Callable[[str], Awaitable[None]]
CancellationNotifier = Callable[[str], Awaitable[None]]
RecoveryLauncher = Callable[[], Awaitable[None]]


class MethodHubService:
    """Local researcher service with explicit command and projection boundaries."""

    def __init__(
        self,
        *,
        settings: ApplicationSettings,
        specification: SpecificationPackage,
        repository: HubRepository,
        artifacts: ArtifactStore,
        role_resources: RoleResourceCatalog,
        run_launcher: RunLauncher | None = None,
        cancellation_notifier: CancellationNotifier | None = None,
        recovery_launcher: RecoveryLauncher | None = None,
    ) -> None:
        self.settings = settings
        self.specification = specification
        self.repository = repository
        self.artifacts = artifacts
        self.role_resources = role_resources
        self.skill_bundle_root = (
            Path(__file__).resolve().parents[3] / "resources" / "skills"
        )
        self.queries = RepositoryQueries(repository)
        self.projects = ProjectCommandService(repository, artifacts)
        self.method_lifecycle = MethodLifecycleCommandService(
            repository, artifacts, specification
        )
        self.run_launcher = run_launcher
        self.cancellation_notifier = cancellation_notifier
        self.recovery_launcher = recovery_launcher
        self.projections = ResearchProjectionService(
            repository,
            specification.phases,
            execution_available=run_launcher is not None,
        )
        self._background: set[asyncio.Task[None]] = set()

    async def resume_incomplete(self) -> None:
        if self.recovery_launcher is not None:
            await self.recovery_launcher()
    async def preserve_raw_request(
        self, raw_request: RawRequestBody
    ) -> RawRequestReceipt:
        nonce = raw_request.idempotency_key or str(uuid.uuid4())
        request_id = "request." + hashlib.sha256(
            f"{raw_request.command_family}\x1f{nonce}".encode("utf-8")
        ).hexdigest()
        stored = self.artifacts.put_bytes(
            raw_request.body, expected_sha256=raw_request.content_sha256
        )
        return RawRequestReceipt(
            request_artifact_id=request_id,
            content_sha256=str(stored.sha256),
        )

    async def list_projects(self) -> list[ProjectSummary]:
        results = []
        for row in self.queries.list_projects():
            active = sum(
                item["status"] in ACTIVE_RUN_STATES
                for item in self.queries.list_runs(str(row["project_id"]))
            )
            brief = self.repository.get_current_record(
                str(row["project_id"]), "project.brief.current"
            )
            results.append(
                project_summary(
                    row,
                    active_run_count=active,
                    brief_payload=row_json(brief) if brief is not None else None,
                )
            )
        return results

    async def create_project(
        self,
        command: CreateProjectRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProjectSummary:
        project = self.projects.create(
            command, owner_user_id=self.settings.user_id
        )
        self._attach_raw_request(project["project_id"], raw_request)
        row = self.repository.get_project(project["project_id"])
        brief = self.repository.get_current_record(
            project["project_id"], "project.brief.current"
        )
        return project_summary(
            row,
            active_run_count=0,
            brief_payload=row_json(brief) if brief is not None else None,
        )

    async def get_project_brief(self, project_id: str) -> ProjectBriefView:
        runs = await self.list_runs(project_id, phase=None)
        active_count = sum(item.state in ACTIVE_RUN_STATES for item in runs)
        try:
            return self.projections.project_brief(
                project_id, active_run_count=active_count
            )
        except RepositoryNotFoundError as error:
            raise _not_found(error) from error
        except ValueError as error:
            raise _schema_rejected(str(error)) from error

    async def update_project_brief(
        self,
        project_id: str,
        command: UpdateProjectBriefRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProjectBriefView:
        request_id = self._attach_raw_request(project_id, raw_request)
        existing = self.repository.get_command_by_idempotency(
            project_id, request_id
        )
        if existing is not None:
            receipt = self.queries.publication_receipt_for_command(
                project_id, str(existing["command_id"])
            )
            if receipt is None:
                raise CommandRejected(
                    new_command_error(
                        "PUBLICATION_CONFLICT",
                        object_refs=[project_id, str(existing["command_id"])],
                        researcher_message=(
                            "The earlier project brief command has no committed receipt."
                        ),
                        smallest_correction=(
                            "Inspect repository recovery before submitting another update."
                        ),
                    )
                )
            return await self.get_project_brief(project_id)

        current = await self.get_project_brief(project_id)
        action = next(
            (
                item
                for item in current.actions
                if item.action_type == "update_project_brief"
            ),
            None,
        )
        if action is None or action.descriptor_id != command.action_descriptor_id:
            raise CommandRejected(
                new_command_error(
                    "CONTROL_HEAD_STALE",
                    object_refs=[project_id, current.generation_id],
                    researcher_message="The displayed project brief is no longer current.",
                    smallest_correction="Refresh the project brief and review the update.",
                )
            )
        if not action.enabled:
            raise CommandRejected(
                new_command_error(
                    "INVALID_TRANSITION",
                    object_refs=[project_id],
                    researcher_message=action.researcher_message
                    or "The formal project brief cannot be changed now.",
                    smallest_correction=(
                        "Wait for active runs to finish or cancel them, then refresh."
                    ),
                )
            )
        now = utc_now()
        sealed_payload = {
            "schema_version": "1.0.0",
            "command_type": "project_brief_update",
            "command_id": "command.project_brief."
            + hashlib.sha256(request_id.encode()).hexdigest(),
            "project_id": project_id,
            "expected_generation_id": current.generation_id,
            "expected_authority_root_sha256": (
                current.projection.authority_event_root_sha256
            ),
            "reason": command.reason.strip(),
            "changes": {
                key: value
                for key, value in command.model_dump(mode="json").items()
                if key
                not in {"action_descriptor_id", "reason"}
                and key in command.model_fields_set
            },
            "requested_by": self.settings.user_id,
            "requested_at": isoformat_utc(now),
        }
        command_sha = _content_digest(sealed_payload)
        sealed = self.repository.seal_command(
            str(sealed_payload["command_id"]),
            project_id,
            request_id,
            request_id,
            command_sha,
            sealed_payload,
            sealed_at=now,
        )
        try:
            self.projects.update(
                project_id,
                command,
                command_id=str(sealed.row["command_id"]),
                command_sha256=command_sha,
                requested_by=self.settings.user_id,
                now=now,
            )
        except RepositoryConflictError as error:
            raise CommandRejected(
                new_command_error(
                    "PUBLICATION_CONFLICT",
                    object_refs=[project_id, current.generation_id],
                    researcher_message=(
                        "The formal project basis changed before the brief update committed."
                    ),
                    smallest_correction="Refresh the project and prepare the update again.",
                )
            ) from error
        except ValueError as error:
            code = "NO_STATE_CHANGE" if "does not change" in str(error) else "COMMAND_SCHEMA_INVALID"
            raise CommandRejected(
                new_command_error(
                    code,
                    object_refs=[project_id],
                    researcher_message=str(error),
                    smallest_correction=(
                        "Change at least one scientific framing field and submit again."
                    ),
                )
            ) from error
        return await self.get_project_brief(project_id)

    async def get_system_settings(self) -> SystemSettingsView:
        frontend = self.settings.resolved_frontend_dist()
        return SystemSettingsView(
            service_version=__version__,
            bind_host=self.settings.host,
            port=self.settings.port,
            executor_kind=self.settings.executor_kind,
            execution_available=self.run_launcher is not None,
            development_mode=self.settings.development_mode,
            data_root=str(self.settings.data_root),
            database_path=str(self.repository.database.path),
            artifact_namespace=self.artifacts.namespace,
            architecture_root=str(self.settings.resolved_architecture_root()),
            frontend_dist=str(frontend),
            frontend_available=frontend.is_dir(),
            database_schema_version=self.repository.database.schema_version(),
            project_count=len(self.queries.list_projects()),
            settings_message=(
                "These values describe the active process. Change startup configuration "
                "outside the Web UI and restart the service to apply it."
            ),
        )

    async def get_project_overview(self, project_id: str) -> ProjectOverview:
        runs = await self.list_runs(project_id, phase=None)
        active = [item for item in runs if item.state in ACTIVE_RUN_STATES]
        return self.projections.overview(project_id, active_runs=active)

    async def get_phase_view(
        self,
        project_id: str,
        phase_id: PhaseId,
        *,
        mode: str | None,
        method_id: str | None,
    ) -> PhaseView:
        runs = await self.list_runs(project_id, phase=phase_id)
        active = [item for item in runs if item.state in ACTIVE_RUN_STATES]
        recent = [item for item in runs if item.state not in ACTIVE_RUN_STATES][:10]
        role_resources = self._phase_role_resources(project_id, phase_id, mode)
        try:
            return self.projections.phase_view(
                project_id,
                phase_id,
                mode=mode,
                method_id=method_id,
                active_runs=active,
                recent_runs=recent,
                role_resources=role_resources,
            )
        except RepositoryNotFoundError as error:
            raise _not_found(error) from error
        except ValueError as error:
            raise _schema_rejected(str(error)) from error

    def _phase_role_resources(
        self,
        project_id: str,
        phase_id: str,
        mode: str | None,
    ) -> dict[str, dict[str, Any]] | None:
        """Compute the role-resource snapshot for the phase's roles."""
        identity = self.specification.phases.identity(phase_id)
        try:
            plan = self.specification.resolve_phase(
                identity,
                mode or "",
                {},
                "current_only",
            )
        except Exception:
            return None
        roles = {step.role for stage in plan.stages for step in stage.role_steps}
        if not roles:
            return None
        try:
            manifest = load_skill_manifest(self.skill_bundle_root)
            _, resources = compute_role_resources(
                repository=self.repository,
                settings=self.settings,
                role_resources=self.role_resources,
                skill_manifest=manifest,
                roles=roles,
                project_id=project_id,
            )
        except Exception:
            return None
        return resources

    async def list_methods(self, project_id: str) -> list[MethodRow]:
        try:
            return self.projections.list_methods(project_id)
        except RepositoryNotFoundError as error:
            raise _not_found(error) from error

    async def change_method_lifecycle(
        self,
        project_id: str,
        method_id: str,
        command: ReasonedActionRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> None:
        self.repository.get_project(project_id)
        request_id = self._attach_raw_request(project_id, raw_request)
        existing = self.repository.get_command_by_idempotency(
            project_id, request_id
        )
        if existing is not None:
            receipt = self.queries.publication_receipt_for_command(
                project_id, str(existing["command_id"])
            )
            if receipt is not None:
                return
            raise CommandRejected(
                new_command_error(
                    "PUBLICATION_CONFLICT",
                    object_refs=[project_id, method_id, str(existing["command_id"])],
                    researcher_message=(
                        "The earlier lifecycle command has no committed receipt."
                    ),
                    smallest_correction=(
                        "Inspect repository recovery before submitting another change."
                    ),
                )
            )

        methods = self.projections.list_methods(project_id)
        method = next(
            (item for item in methods if item.identity.stable_id == method_id),
            None,
        )
        if method is None:
            raise _not_found(RepositoryNotFoundError("method", method_id))
        action = next(
            (
                item
                for item in method.actions
                if item.action_type in {"retire_method", "reactivate_method"}
            ),
            None,
        )
        if action is None or action.descriptor_id != command.action_descriptor_id:
            raise CommandRejected(
                new_command_error(
                    "CONTROL_HEAD_STALE",
                    object_refs=[project_id, method_id],
                    researcher_message="The displayed method state is no longer current.",
                    smallest_correction="Refresh the Phase 2 method table and review again.",
                )
            )
        if not action.enabled:
            raise CommandRejected(
                new_command_error(
                    "INVALID_TRANSITION",
                    object_refs=[project_id, method_id],
                    researcher_message=action.researcher_message
                    or "This method lifecycle change is not currently available.",
                    smallest_correction=(
                        "Resolve the displayed lifecycle prerequisite and refresh."
                    ),
                )
            )
        target_state = (
            "retired" if action.action_type == "retire_method" else "active"
        )
        now = utc_now()
        project = self.repository.get_project(project_id)
        method_row = self.repository.get_current_record(
            project_id, f"methods/{method_id}/current"
        )
        catalog_row = self.repository.get_current_record(
            project_id, "p2.method_catalog.current"
        )
        if method_row is None or catalog_row is None:
            raise CommandRejected(
                new_command_error(
                    "DEPENDENCY_CLOSURE_INCOMPLETE",
                    object_refs=[project_id, method_id],
                    researcher_message=(
                        "The current method record and Phase 2 catalog are both required."
                    ),
                    smallest_correction="Run Phase 2 or refresh the method table.",
                )
            )
        sealed_payload = {
            "schema_version": "1.0.0",
            "command_type": "method_lifecycle_change",
            "command_id": "command.method_lifecycle."
            + hashlib.sha256(request_id.encode()).hexdigest(),
            "project_id": project_id,
            "method_id": method_id,
            "expected_method_generation_id": str(method_row["generation_id"]),
            "expected_catalog_generation_id": str(catalog_row["generation_id"]),
            "expected_authority_sequence": int(project["authority_sequence"]),
            "expected_authority_root_sha256": str(
                project["authority_root_sha256"]
            ),
            "target_lifecycle_state": target_state,
            "reason": command.reason.strip(),
            "requested_by": self.settings.user_id,
            "requested_at": isoformat_utc(now),
        }
        command_sha = _content_digest(sealed_payload)
        sealed = self.repository.seal_command(
            str(sealed_payload["command_id"]),
            project_id,
            request_id,
            request_id,
            command_sha,
            sealed_payload,
            sealed_at=now,
        )
        try:
            self.method_lifecycle.change(
                project_id,
                method_id,
                target_state=target_state,
                reason=command.reason,
                command_id=str(sealed.row["command_id"]),
                command_sha256=command_sha,
                requested_by=self.settings.user_id,
                now=now,
            )
        except RepositoryConflictError as error:
            raise CommandRejected(
                new_command_error(
                    "PUBLICATION_CONFLICT",
                    object_refs=[project_id, method_id],
                    researcher_message=(
                        "The method catalog changed before the lifecycle transaction committed."
                    ),
                    smallest_correction=(
                        "Refresh the Phase 2 method table and prepare the change again."
                    ),
                )
            ) from error
        except ValueError as error:
            code = (
                "NO_STATE_CHANGE"
                if "already in the requested" in str(error)
                else "TARGET_STATE_MISMATCH"
            )
            raise CommandRejected(
                new_command_error(
                    code,
                    object_refs=[project_id, method_id],
                    researcher_message=str(error),
                    smallest_correction=(
                        "Refresh the Phase 2 method table and review the exact method state."
                    ),
                )
            ) from error

    async def list_runs(
        self, project_id: str, *, phase: PhaseId | None
    ) -> list[RunSummary]:
        try:
            return [
                run_summary_view(row)
                for row in self.queries.list_runs(project_id, phase=phase)
            ]
        except RepositoryNotFoundError as error:
            raise _not_found(error) from error

    async def start_run(
        self,
        project_id: str,
        command: StartRunRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> RunDetail:
        self.repository.get_project(project_id)
        request_id = self._attach_raw_request(project_id, raw_request)
        existing_command = self.repository.get_command_by_idempotency(
            project_id, request_id
        )
        if existing_command is not None:
            existing_run = self.queries.run_for_command(existing_command["command_id"])
            if existing_run is not None:
                return await self.get_run(project_id, str(existing_run["run_id"]))

        method = _method_choice(command.choice_values)
        method_id = str(method.stable_id) if method is not None else None
        phase_view = await self.get_phase_view(
            project_id,
            command.phase,
            mode=command.mode,
            method_id=method_id,
        )
        action = next(
            (item for item in phase_view.actions if item.action_type == "start_run"),
            None,
        )
        if action is None or action.descriptor_id != command.action_descriptor_id:
            raise CommandRejected(
                new_command_error(
                    "CONTROL_HEAD_STALE",
                    object_refs=[project_id, command.phase],
                    researcher_message="The displayed run action is no longer current.",
                    smallest_correction="Refresh the phase view and review the updated basis.",
                )
            )
        if not action.enabled:
            raise CommandRejected(
                new_command_error(
                    "DEPENDENCY_CLOSURE_INCOMPLETE",
                    object_refs=[project_id, command.phase],
                    researcher_message=action.researcher_message
                    or "The selected run is not currently eligible.",
                    smallest_correction="Resolve the displayed prerequisite before launching.",
                )
            )

        history_key = f"{command.phase.lower()}.selected_history"
        selected_history = command.choice_values.get(history_key, [])
        if type(selected_history) is not list:
            raise _schema_rejected("Selected historical context must be a list.")
        allowed_history = {
            (
                item.artifact_pointer.artifact_id,
                item.artifact_pointer.uri,
                item.artifact_pointer.sha256,
            )
            for item in phase_view.run_configuration.history_options
            if item.artifact_pointer is not None
        }
        unknown_history = []
        for item in selected_history:
            if type(item) is not dict:
                unknown_history.append(item)
                continue
            identity = (
                item.get("artifact_id"),
                item.get("uri"),
                item.get("sha256"),
            )
            if identity not in allowed_history:
                unknown_history.append(item)
        if unknown_history:
            raise CommandRejected(
                new_command_error(
                    "DEPENDENCY_CLOSURE_INCOMPLETE",
                    object_refs=[project_id, command.phase],
                    researcher_message=(
                        "Selected historical context is not an available formal "
                        "generation for this phase and method."
                    ),
                    smallest_correction=(
                        "Refresh the phase view and select history from the displayed list."
                    ),
                )
            )

        current_options = {
            item.option_id: item for item in phase_view.run_configuration.current_inputs
        }
        selected_current = set(command.selected_context_option_ids)
        unknown_current = sorted(selected_current - set(current_options))
        if unknown_current:
            raise _schema_rejected(
                "Selected current context is not available for this phase: "
                + ", ".join(unknown_current)
            )
        missing_required = sorted(
            option_id
            for option_id, option in current_options.items()
            if option.required and option_id not in selected_current
        )
        if missing_required:
            raise CommandRejected(
                new_command_error(
                    "DEPENDENCY_CLOSURE_INCOMPLETE",
                    object_refs=[project_id, *missing_required],
                    researcher_message=(
                        "Required current context was removed from the run: "
                        + ", ".join(missing_required)
                    ),
                    smallest_correction=(
                        "Keep every required current input selected and review the run again."
                    ),
                )
            )

        identity = self.specification.phases.identity(command.phase)
        try:
            plan = self.specification.resolve_phase(
                identity,
                command.mode,
                command.choice_values,
                command.context_policy,
            )
        except PhaseContractError as error:
            raise _schema_rejected(str(error)) from error
        request = RunRequest(
            project_id=project_id,
            phase_contract=identity,
            mode=command.mode,
            choice_values=command.choice_values,
            context_policy=command.context_policy,
            user_id=self.settings.user_id,
            idempotency_key=request_id,
            selected_current_input_ids=tuple(command.selected_context_option_ids),
        )
        sealed = build_run_command(
            request,
            self.specification,
            sealed_basis=phase_view.descriptor_basis,
        )
        sealed_result = self.repository.seal_command(
            str(sealed["command_id"]),
            project_id,
            request_id,
            request_id,
            str(sealed["content_sha256"]),
            sealed,
        )
        command_row = sealed_result.row
        existing_run = self.queries.run_for_command(str(command_row["command_id"]))
        if existing_run is not None:
            return await self.get_run(project_id, str(existing_run["run_id"]))

        run_id = _run_id(command.phase, command.mode)
        now = utc_now()
        instruction_key = next(
            key for key in command.choice_values if key.endswith(".instructions")
        )
        payload: dict[str, Any] = {
            "run_id": run_id,
            "project_id": project_id,
            "phase": command.phase,
            "mode": command.mode,
            "method_identity": method.to_dict() if method is not None else None,
            "requested_at": isoformat_utc(now),
            "requested_by": self.settings.user_id,
            "instructions": str(command.choice_values[instruction_key]),
            "choice_values": command.choice_values,
            "context_policy": command.context_policy,
            "selected_current_input_ids": list(command.selected_context_option_ids),
            "phase_contract_version": str(identity.contract_version),
            "phase_contract_sha256": str(identity.phase_contract_sha256),
            "command_sha256": str(sealed["content_sha256"]),
            "frozen_basis": [],
            "stage_plan": [
                {
                    "sequence": stage.sequence,
                    "stage_id": stage.stage_id,
                    "label": stage.objective,
                    "roles": list(stage.roles),
                    "execution": stage.execution,
                }
                for stage in plan.stages
            ],
            "stage_states": {},
        }
        event = {
            "event_type": "run.created",
            "message": "Run command accepted. Preparation has not started yet.",
            "occurred_at": isoformat_utc(now),
        }
        event_id = _event_id(run_id, 1)
        self.repository.create_run(
            run_id,
            project_id,
            str(command_row["command_id"]),
            "created",
            payload,
            event_id,
            _content_digest(event),
            event,
            recorded_at=now,
        )
        if self.run_launcher is not None:
            task = asyncio.create_task(self.run_launcher(run_id))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        return await self.get_run(project_id, run_id)

    async def get_run(self, project_id: str, run_id: str) -> RunDetail:
        try:
            row = self.repository.get_run(run_id)
        except RepositoryNotFoundError as error:
            raise _not_found(error) from error
        if row["project_id"] != project_id:
            raise _not_found(RepositoryNotFoundError("run", run_id))
        payload = row_json(row)
        receipt = None
        receipt_id = payload.get("publication_receipt_id")
        if type(receipt_id) is str:
            receipt = self.repository.get_publication_receipt(receipt_id)
        return run_detail_view(
            row,
            event_rows=self.repository.list_run_events(run_id),
            manifest_row=self.queries.run_manifest(run_id),
            publication_row=receipt,
        )

    async def get_artifact(
        self, project_id: str, artifact_id: str
    ) -> ArtifactDelivery:
        try:
            self.repository.get_project(project_id)
            row = self.repository.get_artifact(artifact_id)
        except RepositoryNotFoundError as error:
            raise _not_found(error) from error
        if row["project_id"] != project_id:
            raise _not_found(RepositoryNotFoundError("artifact", artifact_id))
        digest = str(row["sha256"])
        content = self.artifacts.read_bytes(digest)
        if len(content) != int(row["size"]):
            raise ArtifactIntegrityError(
                "artifact.size_mismatch",
                "Stored artifact bytes do not match the recorded byte length.",
                sha256=digest,
            )
        media_type = str(row["media_type"])
        return ArtifactDelivery(
            artifact_id=artifact_id,
            content=content,
            media_type=media_type,
            content_sha256=digest,
            filename=_artifact_filename(artifact_id, media_type),
        )

    async def get_publication_receipt(
        self, project_id: str, receipt_id: str
    ) -> PublicationReceiptDocument:
        try:
            self.repository.get_project(project_id)
        except RepositoryNotFoundError as error:
            raise _not_found(error) from error
        row = self.repository.get_publication_receipt(receipt_id)
        if row is None or row["project_id"] != project_id:
            raise _not_found(RepositoryNotFoundError("publication receipt", receipt_id))
        document = PublicationReceiptDocument.model_validate(row_json(row))
        _verify_publication_receipt(row, document)
        return document

    async def list_run_events(
        self, project_id: str, run_id: str, *, after_sequence: int
    ) -> list[RunEvent]:
        await self.get_run(project_id, run_id)
        return [
            run_event_view(row)
            for row in self.repository.list_run_events(run_id)
            if int(row["sequence"]) > after_sequence
        ]

    async def stream_run_events(
        self, project_id: str, run_id: str, *, after_sequence: int
    ) -> AsyncIterator[RunEvent]:
        sequence = after_sequence
        while True:
            events = await self.list_run_events(
                project_id, run_id, after_sequence=sequence
            )
            for event in events:
                sequence = event.sequence
                yield event
            detail = await self.get_run(project_id, run_id)
            if detail.state in {
                "published",
                "failed",
                "rejected",
                "conflicted",
                "cancelled",
            } and sequence >= detail.last_event_sequence:
                return
            await asyncio.sleep(0.5)

    async def cancel_run(
        self,
        project_id: str,
        run_id: str,
        command: ReasonedActionRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> RunDetail:
        detail = await self.get_run(project_id, run_id)
        request_id = self._attach_raw_request(project_id, raw_request)
        existing_command = self.repository.get_command_by_idempotency(
            project_id, request_id
        )
        if existing_command is not None:
            existing_payload = row_json(existing_command)
            if existing_payload.get("run_id") != run_id:
                raise _idempotency_key_reused(project_id, request_id)
            return detail

        action = next(
            (item for item in detail.actions if item.action_type == "cancel_run"), None
        )
        if action is None or action.descriptor_id != command.action_descriptor_id:
            raise CommandRejected(
                new_command_error(
                    "CONTROL_HEAD_STALE",
                    object_refs=[run_id],
                    researcher_message="The displayed cancellation action is no longer current.",
                    smallest_correction="Refresh the run before deciding whether to cancel it.",
                )
            )
        if detail.state not in CANCELLABLE:
            raise CommandRejected(
                new_command_error(
                    "RUN_ALREADY_SUBMITTED",
                    object_refs=[run_id],
                    researcher_message="This run can no longer be cancelled.",
                    smallest_correction="Inspect the submitted or terminal result.",
                )
            )
        cancellation = {
            "schema_version": "1.0.0",
            "command_id": "command.cancel." + hashlib.sha256(request_id.encode()).hexdigest(),
            "project_id": project_id,
            "run_id": run_id,
            "reason": command.reason,
            "requested_by": self.settings.user_id,
            "requested_at": isoformat_utc(utc_now()),
        }
        digest = _content_digest(cancellation)
        sealed = self.repository.seal_command(
            cancellation["command_id"],
            project_id,
            request_id,
            request_id,
            digest,
            cancellation,
        )
        row = self.repository.get_run(run_id)
        payload = row_json(row)
        event = {
            "event_type": "run.cancellation_requested",
            "message": "Cancellation requested. No new role may start.",
            "occurred_at": isoformat_utc(utc_now()),
        }
        result = self.repository.request_cancellation(
            run_id,
            str(sealed.row["command_id"]),
            str(row["status"]),
            int(row["head_sequence"]),
            payload,
            _event_id(run_id, int(row["head_sequence"]) + 1),
            _content_digest(event),
            event,
        )
        if not result.applied and result.reason == "already_submitted":
            raise CommandRejected(
                new_command_error(
                    "RUN_ALREADY_SUBMITTED",
                    object_refs=[run_id],
                    researcher_message="Immutable submission completed before cancellation.",
                    smallest_correction="Inspect validation and publication progress.",
                )
            )
        if self.cancellation_notifier is not None:
            await self.cancellation_notifier(run_id)
        return await self.get_run(project_id, run_id)

    async def get_profiles(self, project_id: str) -> ProfileConfigurationView:
        self.repository.get_project(project_id)
        return self._profile_view(project_id)

    async def save_profile(
        self,
        project_id: str,
        role_id: str,
        command: SaveProfileRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProfileConfigurationView:
        mapping_values, revisions = self._effective_profile_state(project_id)
        current = self._profile_view_from_state(
            project_id,
            mapping_values,
            revisions,
        )
        role = next((item for item in current.profiles if item.role_id == role_id), None)
        option = (
            next(
                (
                    item
                    for item in role.profile_options
                    if item.profile_id == command.profile_id
                ),
                None,
            )
            if role is not None
            else None
        )
        if (
            option is None
            or option.action_descriptor_id != command.action_descriptor_id
        ):
            raise CommandRejected(
                new_command_error(
                    "CONTROL_HEAD_STALE",
                    object_refs=[project_id, role_id, command.profile_id],
                    researcher_message=(
                        "The displayed profile assignment is no longer current."
                    ),
                    smallest_correction=(
                        "Refresh profile configuration and select the target again."
                    ),
                )
            )
        if not option.enabled:
            raise CommandRejected(
                new_command_error(
                    "TARGET_STATE_MISMATCH",
                    object_refs=[project_id, role_id, command.profile_id],
                    researcher_message=(
                        option.researcher_message
                        or REVIEWER_PROFILE_ISOLATION_MESSAGE
                    ),
                    smallest_correction=(
                        "Select a profile that is not shared across the "
                        "outside-reviewer and authoring roles."
                    ),
                )
            )

        candidate_values = dict(mapping_values)
        candidate_values[role_id] = command.profile_id
        try:
            ProfileMapping(**candidate_values)
        except ProfileConfigurationError as error:
            raise CommandRejected(
                new_command_error(
                    "TARGET_STATE_MISMATCH",
                    object_refs=[project_id, role_id, command.profile_id],
                    researcher_message=str(error),
                    smallest_correction=(
                        "Select a profile that preserves reviewer isolation."
                    ),
                )
            ) from error

        self._attach_raw_request(project_id, raw_request)
        try:
            self.repository.compare_and_set_profile_mapping(
                project_id,
                role_id,
                command.profile_id,
                {"source": "user_configuration"},
                expected_profiles=mapping_values,
                expected_revisions=revisions,
            )
        except RepositoryConflictError as error:
            raise CommandRejected(
                new_command_error(
                    "CONTROL_HEAD_STALE",
                    object_refs=[project_id, role_id, command.profile_id],
                    researcher_message=(
                        "The profile mapping changed before this assignment committed."
                    ),
                    smallest_correction=(
                        "Refresh profile configuration and select the target again."
                    ),
                )
            ) from error
        return self._profile_view(project_id)

    async def install_skill(
        self,
        project_id: str,
        role_id: str,
        skill_id: str,
        command: InstallSkillRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> ProfileConfigurationView:
        current = self._profile_view(project_id)
        role = next((item for item in current.profiles if item.role_id == role_id), None)
        skill = (
            next((item for item in role.skills if item.skill_id == skill_id), None)
            if role is not None
            else None
        )
        action = skill.actions[0] if skill and skill.actions else None
        if action is None or action.descriptor_id != command.action_descriptor_id:
            raise CommandRejected(
                new_command_error(
                    "CONTROL_HEAD_STALE",
                    object_refs=[project_id, role_id, skill_id],
                    researcher_message="The displayed skill action is no longer current.",
                    smallest_correction="Refresh profile configuration and review the status.",
                )
            )
        if not action.enabled:
            raise CommandRejected(
                new_command_error(
                    "TARGET_STATE_MISMATCH",
                    object_refs=[project_id, role_id, skill_id],
                    researcher_message=action.researcher_message
                    or "This skill cannot be installed.",
                    smallest_correction="Review the current skill status before trying again.",
                )
            )
        if self._any_active_run():
            raise CommandRejected(
                new_command_error(
                    "INVALID_TRANSITION",
                    object_refs=[role_id, skill_id],
                    researcher_message=(
                        "A research run is active, so shared profile resources are frozen."
                    ),
                    smallest_correction=(
                        "Wait for active runs to finish or cancel them before installing."
                    ),
                )
            )

        latest = self._profile_view(project_id)
        latest_role = next(
            (item for item in latest.profiles if item.role_id == role_id),
            None,
        )
        latest_skill = (
            next(
                (item for item in latest_role.skills if item.skill_id == skill_id),
                None,
            )
            if latest_role is not None
            else None
        )
        latest_action = (
            latest_skill.actions[0]
            if latest_skill is not None and latest_skill.actions
            else None
        )
        if (
            latest_action is None
            or latest_action.descriptor_id != command.action_descriptor_id
        ):
            raise CommandRejected(
                new_command_error(
                    "CONTROL_HEAD_STALE",
                    object_refs=[project_id, role_id, skill_id],
                    researcher_message=(
                        "The profile mapping, skill source, or local skill state changed."
                    ),
                    smallest_correction=(
                        "Refresh profile configuration before installing the skill."
                    ),
                )
            )
        if not latest_action.enabled:
            raise CommandRejected(
                new_command_error(
                    "TARGET_STATE_MISMATCH",
                    object_refs=[project_id, role_id, skill_id],
                    researcher_message=latest_action.researcher_message
                    or "This skill cannot be installed.",
                    smallest_correction="Review the current skill status before trying again.",
                )
            )

        root = self.settings.hermes_root or resolve_hermes_root()
        discovery = next(
            (
                item
                for item in discover_profiles(root)
                if latest_role is not None
                and item.name == latest_role.profile_id
                and item.is_safe_directory
            ),
            None,
        )
        if discovery is None:
            raise CommandRejected(
                new_command_error(
                    "CONTROL_HEAD_STALE",
                    object_refs=[project_id, role_id, skill_id],
                    researcher_message=(
                        "The selected Hermes profile is no longer available."
                    ),
                    smallest_correction=(
                        "Refresh profile configuration before installing the skill."
                    ),
                )
            )

        self._attach_raw_request(project_id, raw_request)
        try:
            install_bundled_skill(
                bundle_root=self.skill_bundle_root,
                profile_home=discovery.home,
                skill_id=skill_id,
            )
        except (SkillConflictError, SkillInstallationError) as error:
            raise CommandRejected(
                new_command_error(
                    "TARGET_STATE_MISMATCH",
                    object_refs=[latest_role.profile_id, skill_id],
                    researcher_message=str(error),
                    smallest_correction=(
                        "Resolve the local skill directory, refresh, and review again."
                    ),
                )
            ) from error
        return self._profile_view(project_id)

    def _effective_profile_state(
        self,
        project_id: str,
    ) -> tuple[dict[str, str], dict[str, int]]:
        values = {
            "research_lead": self.settings.research_lead_profile,
            "theorist": self.settings.theorist_profile,
            "data_analyst": self.settings.data_analyst_profile,
            "outside_reviewer": self.settings.outside_reviewer_profile,
        }
        revisions = {role_id: 0 for role_id in PROFILE_ROLES}
        for role_id in PROFILE_ROLES:
            row = self.repository.get_profile_mapping(project_id, role_id)
            if row is not None:
                values[role_id] = str(row["profile_name"])
                revisions[role_id] = int(row["revision"])
        return values, revisions

    def _profile_view(self, project_id: str) -> ProfileConfigurationView:
        values, revisions = self._effective_profile_state(project_id)
        return self._profile_view_from_state(project_id, values, revisions)

    def _profile_view_from_state(
        self,
        project_id: str,
        values: dict[str, str],
        revisions: dict[str, int],
    ) -> ProfileConfigurationView:
        root = self.settings.hermes_root or resolve_hermes_root()
        return build_profile_configuration_view(
            project_id=project_id,
            catalog=self.role_resources,
            mapping=values,
            mapping_revisions=revisions,
            discoveries=discover_profiles(root),
            bundle_root=self.skill_bundle_root,
            skill_mutation_locked=self._any_active_run(),
        )

    def _any_active_run(self) -> bool:
        for project in self.queries.list_projects():
            if any(
                row["status"] in ACTIVE_RUN_STATES
                for row in self.queries.list_runs(str(project["project_id"]))
            ):
                return True
        return False

    # ------------------------------------------------------------------ #
    # Block 2: role-definition configuration service                     #
    # ------------------------------------------------------------------ #

    def _resolved_hermes_root(self) -> Path:
        return Path(self.settings.hermes_root or resolve_hermes_root())

    async def get_role_definitions(self) -> RoleDefinitionCatalogView:
        """Return all four configuration-managed role definitions."""
        return build_role_definition_catalog_view(self.role_resources)

    async def get_role_definition(self, role_id: str) -> RoleDefinitionView:
        """Return one role definition by role_id."""
        try:
            return build_role_definition_view(self.role_resources, role_id)
        except ValueError as error:
            raise _not_found(RepositoryNotFoundError("role", role_id)) from error

    async def get_configuration_health(self) -> ConfigurationHealthView:
        """Return aggregate health of all role definitions."""
        root = self._resolved_hermes_root()
        # Use global effective profiles (settings defaults, no project override).
        effective = {
            role: self.settings.profile_for(role) for role in PROFILE_ROLES
        }
        return build_configuration_health_view(
            self.role_resources,
            root,
            self.skill_bundle_root,
            effective,
        )

    async def get_role_health(self, role_id: str) -> RoleHealthReportView:
        """Return the health of one role definition."""
        try:
            self.role_resources.role(role_id)
        except ValueError as error:
            raise _not_found(RepositoryNotFoundError("role", role_id)) from error
        root = self._resolved_hermes_root()
        effective = {
            role: self.settings.profile_for(role) for role in PROFILE_ROLES
        }
        return build_role_health_view(
            self.role_resources,
            role_id,
            root,
            self.skill_bundle_root,
            effective,
        )

    async def provision_role(
        self,
        role_id: str,
        command: ProvisionRoleRequest,
    ) -> ProvisionResultView:
        """Provision a role definition into its Hermes profile, atomically."""
        try:
            resource = self.role_resources.role(role_id)
        except ValueError as error:
            raise _not_found(RepositoryNotFoundError("role", role_id)) from error

        root = self._resolved_hermes_root()
        if not hermes_available(root):
            raise CommandRejected(
                new_command_error(
                    "DEPENDENCY_CLOSURE_INCOMPLETE",
                    object_refs=[role_id, str(root)],
                    researcher_message=(
                        "The Hermes root directory is not available. "
                        "Install Hermes and configure the correct root path."
                    ),
                    smallest_correction=(
                        "Install Hermes or set METHOD_HUB_HERMES_ROOT and try again."
                    ),
                )
            )

        effective_profile = self.settings.profile_for(role_id)
        profile_home = discover_profile_home(root, effective_profile)
        if profile_home is None:
            raise CommandRejected(
                new_command_error(
                    "TARGET_NOT_FOUND",
                    object_refs=[role_id, effective_profile],
                    researcher_message=(
                        f"Hermes profile {effective_profile!r} for role "
                        f"{role_id!r} does not exist or is not a safe directory."
                    ),
                    smallest_correction=(
                        f"Create the Hermes profile {effective_profile!r} before "
                        "provisioning this role."
                    ),
                )
            )

        try:
            result = provision_role_definition(
                resource=resource,
                profile_home=profile_home,
                bundle_root=self.skill_bundle_root,
                install_skills=command.install_skills,
                force_overwrite_assets=command.force_overwrite_assets,
                force_overwrite_skills=command.force_overwrite_skills,
            )
        except CustomizationConflict as error:
            conflict_detail = build_conflict_detail(error)
            raise CommandRejected(
                new_command_error(
                    "CUSTOMIZATION_CONFLICT",
                    object_refs=[
                        error.role_id,
                        error.asset_type,
                        error.path.name,
                    ],
                    researcher_message=(
                        f"The {conflict_detail.asset_type} file "
                        f"{conflict_detail.file_name!r} in profile "
                        f"{effective_profile!r} has been customized and differs "
                        f"from the configuration-managed reference. "
                        f"Choose to keep the custom version or overwrite it with "
                        f"the reference."
                    ),
                    smallest_correction=(
                        "Resolve the conflict explicitly: keep the customized "
                        "file or force-overwrite it with the reference, then "
                        "provision again."
                    ),
                )
            ) from error
        except ProvisioningError as error:
            raise CommandRejected(
                new_command_error(
                    "ROLE_PROVISIONING_FAILED",
                    object_refs=[role_id, str(profile_home)],
                    researcher_message=str(error),
                    smallest_correction=(
                        "All partial changes were rolled back. Inspect the "
                        "profile directory and try again."
                    ),
                )
            ) from error

        return ProvisionResultView(
            role_id=role_id,
            profile_name=effective_profile,
            assets_written=list(result.assets_written),
            skills_installed=[s.skill_id for s in result.skills_installed],
            rolled_back=result.rolled_back,
        )

    def _attach_raw_request(
        self, project_id: str, receipt: RawRequestReceipt
    ) -> str:
        stored = self.artifacts.verify(receipt.content_sha256)
        try:
            self.repository.record_artifact(
                receipt.request_artifact_id,
                project_id,
                receipt.content_sha256,
                stored.size,
                "application/octet-stream",
                f"artifact://sha256/{receipt.content_sha256}",
                {
                    "relative_path": stored.relative_path,
                    "purpose": "exact raw command request",
                },
            )
            self.repository.record_raw_command(
                receipt.request_artifact_id,
                project_id,
                receipt.content_sha256,
                {
                    "artifact_id": receipt.request_artifact_id,
                    "uri": f"artifact://sha256/{receipt.content_sha256}",
                    "sha256": receipt.content_sha256,
                    "byte_length": stored.size,
                },
            )
        except RepositoryConflictError as error:
            raise CommandRejected(
                new_command_error(
                    "IDEMPOTENCY_KEY_REUSED",
                    object_refs=[project_id, receipt.request_artifact_id],
                    researcher_message="This idempotency key is bound to another command body.",
                    smallest_correction="Submit the new action with a new idempotency key.",
                )
            ) from error
        return receipt.request_artifact_id


def _idempotency_key_reused(project_id: str, request_id: str) -> CommandRejected:
    return CommandRejected(
        new_command_error(
            "IDEMPOTENCY_KEY_REUSED",
            object_refs=[project_id, request_id],
            researcher_message="This idempotency key is bound to another operation.",
            smallest_correction="Submit the action with a new idempotency key.",
        )
    )


def _method_choice(values: dict[str, Any]) -> MethodIdentity | None:
    for key, value in values.items():
        if key.endswith(".selected_method") and type(value) is dict:
            return MethodIdentity.from_dict(value)
    return None


def _run_id(phase: str, mode: str) -> str:
    suffix = uuid.uuid4().hex
    safe_mode = mode.replace("_", "-").replace(".", "-")
    return f"run.{phase.lower()}.{safe_mode}.{suffix}"


def _event_id(run_id: str, sequence: int) -> str:
    return "event." + hashlib.sha256(f"{run_id}:{sequence}".encode()).hexdigest()


def _content_digest(value: Any) -> str:
    return hashlib.sha256(canonicalize(value)).hexdigest()


def _artifact_filename(artifact_id: str, media_type: str) -> str:
    safe = "".join(
        character
        if character.isascii() and (character.isalnum() or character in "._-")
        else "_"
        for character in artifact_id
    ).strip(".")
    safe = safe[:100] or "artifact"
    extension = {
        "application/json": ".json",
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "text/markdown": ".md",
        "text/plain": ".txt",
    }.get(media_type, ".bin")
    return safe if safe.lower().endswith(extension) else safe + extension


def _verify_publication_receipt(
    row: Any, document: PublicationReceiptDocument
) -> None:
    expected = {
        "receipt_id": document.receipt_id,
        "project_id": document.project_id,
        "run_id": document.run_id,
        "command_id": document.command_id,
        "prior_authority_sequence": document.prior_authority_sequence,
        "new_authority_sequence": document.new_authority_sequence,
        "prior_authority_root_sha256": document.prior_authority_root_sha256,
        "new_authority_root_sha256": document.new_authority_root_sha256,
        "prior_current_revision": document.prior_current_revision,
        "new_current_revision": document.new_current_revision,
        "receipt_sha256": document.content_sha256,
        "committed_at": document.published_at,
    }
    if any(row[field] != value for field, value in expected.items()):
        raise ValueError("Publication receipt metadata does not match its index row.")
    unsigned = document.model_dump(mode="json")
    digest = str(unsigned.pop("content_sha256"))
    if _content_digest(unsigned) != digest:
        raise ValueError("Publication receipt content does not match its SHA-256 digest.")


def _not_found(error: RepositoryNotFoundError) -> CommandRejected:
    return CommandRejected(
        new_command_error(
            "TARGET_NOT_FOUND",
            object_refs=[error.identity],
            researcher_message=f"The requested {error.entity} was not found.",
            smallest_correction="Refresh the project and select an available item.",
        )
    )


def _schema_rejected(message: str) -> CommandRejected:
    return CommandRejected(
        new_command_error(
            "COMMAND_SCHEMA_INVALID",
            researcher_message=message,
            smallest_correction="Correct the selection and submit a new command.",
        )
    )


__all__ = ["MethodHubService"]
