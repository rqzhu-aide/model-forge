"""Concrete application service joining API projections to durable state."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
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
    StartSupervisedRunRequest,
    SupervisedRunDetail,
    SupervisedRunSummary,
    SystemSettingsView,
    UpdateProjectBriefRequest,
)
from ..api.ports import (
    ArtifactDelivery,
    RawRequestBody,
    RawRequestReceipt,
    SupervisedRunStartResult,
)
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
from ..executors.local_hermes import LocalHermesExecutorSettings
from ..harness.commands import build_run_command, require_complete_sealed_basis
from ..harness.role_resource_snapshot import compute_role_resources, load_skill_manifest
from ..specification import SpecificationPackage
from ..storage.artifacts import ArtifactStore
from ..storage.database import Database
from ..storage.errors import ArtifactIntegrityError
from ..storage.migrations import HUB_MIGRATIONS
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
from .run_launcher import launch_sealed_run
from .run_preflight import DEFAULT_MIN_FREE_BYTES, run_preflight
from .run_profile_assembler import (
    RunProfileAssembler,
    RunSealError,
    RunSealStore,
    SealedRun,
    StateLockHeld,
)
from .run_views import CANCELLABLE, run_detail_view, run_event_view, run_summary_view
from .settings import ApplicationSettings
from .supervised_run_views import supervised_run_detail, supervised_run_summary
from .view_models import ACTIVE_RUN_STATES, ResearchProjectionService, project_summary


RunLauncher = Callable[[str], Awaitable[None]]
CancellationNotifier = Callable[[str], Awaitable[None]]
RecoveryLauncher = Callable[[], Awaitable[None]]

logger = logging.getLogger(__name__)

#: Provider credential environment variables the supervised-start path
#: may pass to the Hermes process.  Keys come ONLY from the server
#: process environment through this allowlist — never from the request
#: body (the strict request model forbids them), never logged, never
#: persisted (the E0 executor redaction covers captured streams).
PROVIDER_SECRET_ENV_ALLOWLIST: tuple[str, ...] = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
)


def _provider_secret_env() -> dict[str, str]:
    """Collect present provider keys from the process environment."""
    return {
        name: os.environ[name]
        for name in PROVIDER_SECRET_ENV_ALLOWLIST
        if name in os.environ
    }


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
        supervised_executor_settings: LocalHermesExecutorSettings | None = None,
        supervised_min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
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
        self._run_seal_store: RunSealStore | None = None
        self._run_seal_database: Database | None = None
        self._run_assembler: RunProfileAssembler | None = None
        self._supervised_executor_settings = supervised_executor_settings
        self._supervised_min_free_bytes = supervised_min_free_bytes
        self._background: set[asyncio.Task[None]] = set()

    @property
    def run_seal_store(self) -> RunSealStore:
        """Lazily open the run-seal store over this service's data root.

        The supervised-run machinery keeps its own Database at
        ``<data_root>/hub.sqlite3`` (the pilot-script layout), separate
        from the hub repository's ``method-hub.sqlite3``.  It is opened
        and migrated on first use so a fresh installation with no
        supervised runs ever still serves empty read results instead of
        errors.  The same Database instance backs the run-profile
        assembler, so a launch recorded by a background thread is visible
        to the WP-F0 read surface immediately.
        """
        if self._run_seal_store is None:
            database = Database(
                self.settings.data_root / "hub.sqlite3",
                migrations=HUB_MIGRATIONS,
            )
            database.initialize()
            self._run_seal_database = database
            self._run_seal_store = RunSealStore(database)
        return self._run_seal_store

    @property
    def run_profile_assembler(self) -> RunProfileAssembler:
        """Lazily build the run-profile assembler (WP-D1) over the seal store.

        The assembler is wired to this service's data root, the WP-C role
        catalog, the repository's skill bundle root, the SAME
        ``hub.sqlite3`` database the lazy run-seal store reads, and the
        Hermes root/binary from settings.  It is built once and reused
        for every supervised start.
        """
        if self._run_assembler is None:
            self.run_seal_store  # ensure the shared database exists
            assert self._run_seal_database is not None
            self._run_assembler = RunProfileAssembler(
                data_root=self.settings.data_root,
                role_resources=self.role_resources,
                database=self._run_seal_database,
                bundle_root=self.skill_bundle_root,
                hermes_root=self.settings.resolved_hermes_root(),
                hermes_binary=self.settings.hermes_executable,
            )
        return self._run_assembler

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
        """Compute the role-resource snapshot for the phase's roles.

        Roles are derived from the phase contract's role stages filtered by
        the selected mode (the same filter ``resolve_phase`` applies), NOT
        from a ``resolve_phase`` call with empty choice values: every mode
        declares required choices, so that resolution always raises and the
        basis would silently omit all role resources -- including for
        method-bound modes, which is exactly the empty-choices omission gap.
        """
        if mode is None:
            return None
        document = self.specification.phases.contract_document(phase_id)
        roles = {
            str(role)
            for stage in document["role_stages"]
            if mode in stage.get("applicable_modes", ())
            for role in stage.get("roles", ())
        }
        if not roles:
            return None
        try:
            manifest = load_skill_manifest(self.skill_bundle_root.parent)
            _, resources = compute_role_resources(
                repository=self.repository,
                settings=self.settings,
                role_resources=self.role_resources,
                skill_manifest=manifest,
                roles=roles,
                project_id=project_id,
                contract_document=document,
                mode=mode,
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

        # NEW-command acceptance gate (C2/C6): the schema keeps sealed_basis
        # optional so stored pre-upgrade commands still revalidate during
        # restart recovery, but a command accepted from this point on must
        # seal a complete reviewed basis. The descriptor match above already
        # proves the basis is live-true; this gate proves it is complete.
        # The idempotent-replay path returns before this point, so replays
        # never re-resolve or re-gate (reviewed-basis test case 7).
        try:
            require_complete_sealed_basis(
                sealed_basis=phase_view.descriptor_basis,
                phase_roles={
                    step.role
                    for stage in plan.stages
                    for step in stage.role_steps
                },
                required_input_ids={
                    str(item["input_id"])
                    for item in self.specification.phases.contract_document(
                        command.phase
                    )["required_inputs"]
                    if str(item["presence"]) in {"always", "required_in_modes"}
                    and not (
                        str(item["presence"]) == "required_in_modes"
                        and plan.mode_id not in item.get("required_in_modes", ())
                    )
                    and (
                        item.get("applicable_modes") is None
                        or plan.mode_id in item.get("applicable_modes")
                    )
                },
                selected_input_ids=set(command.selected_context_option_ids),
                expected_method=method,
            )
        except ValueError as error:
            raise CommandRejected(
                new_command_error(
                    "STALE_BASIS",
                    object_refs=[project_id, command.phase],
                    researcher_message=str(error),
                    smallest_correction=(
                        "Refresh the phase view and review the updated basis "
                        "before starting the run."
                    ),
                )
            ) from error

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

    async def list_supervised_runs(
        self, project_id: str
    ) -> list[SupervisedRunSummary]:
        """List sealed supervised invocations for a project (WP-F0, read-only).

        ``project_id`` here is the free-form project identifier the
        run-profile assembler seals under — NOT a hub-repository project.
        No project-existence check is performed against the hub
        repository, and a project with no supervised runs (or no seal
        store at all) yields an empty list rather than an error.
        """
        store = self.run_seal_store
        return [
            supervised_run_summary(record, store)
            for record in store.list_seals(project_id=project_id, limit=1000)
        ]

    async def get_supervised_run(
        self, project_id: str, invocation_id: str
    ) -> SupervisedRunDetail:
        """Return the durable detail view of one supervised invocation.

        As with :meth:`list_supervised_runs`, ``project_id`` is the
        assembler's free-form seal identifier and is matched against the
        seal's stored project id; an invocation sealed under another
        project id is reported as not found here.
        """
        store = self.run_seal_store
        record = store.find_by_invocation_id(invocation_id)
        if record is None or record["project_id"] != project_id:
            raise _not_found(
                RepositoryNotFoundError("supervised run", invocation_id)
            )
        return supervised_run_detail(record, store)

    async def start_supervised_run(
        self,
        project_id: str,
        command: StartSupervisedRunRequest,
        *,
        raw_request: RawRequestReceipt,
    ) -> SupervisedRunStartResult:
        """Seal, preflight, and schedule one supervised run (WP-F1a).

        This is an explicit user command: nothing here starts a run
        automatically.  The flow is:

        1. **Transport validation** — the brief must be non-empty and
           every expected-output path must be relative (the full output
           contract is re-checked by the WP-D2b preflight, so deep
           validation is not duplicated here).
        2. **Seal** — the WP-D1 assembler seals the invocation under the
           project-role state lock.  A replay of an existing idempotency
           key returns the existing seal WITHOUT relaunching (HTTP 200
           instead of 202).  A second start for the same project-role
           while a launch holds the state lock is rejected with 409.
        3. **Brief materialization** — the brief text is written under
           the run's ``briefs/`` area; the launcher copies it into the
           workspace as ``task.md`` and records its digest.
        4. **Synchronous preflight** — the WP-D2b preflight must pass
           before the request returns; a failure is a 409 carrying the
           preflight detail.
        5. **Background launch** — ``launch_sealed_run`` (which can run
           for many minutes) is dispatched through ``asyncio.to_thread``
           and held by this service, so the endpoint returns immediately
           and the WP-F0 read surface shows the launch record as
           ``running`` and then the terminal status.  Thread exceptions
           are captured onto the launch record (``failed``) by the
           launcher and logged here — never swallowed, never crashing the
           server.

        Provider keys are read from the server process environment via
        :data:`PROVIDER_SECRET_ENV_ALLOWLIST` and injected only through
        the executor's ``secret_env`` mechanism — never from the request
        body, never logged, never persisted.
        """
        brief_text = command.brief_text.strip()
        if not brief_text:
            raise CommandRejected(
                new_command_error(
                    "SUPERVISED_RUN_INVALID",
                    field_path="brief_text",
                    object_refs=[project_id],
                    researcher_message="The task brief must not be empty.",
                    smallest_correction=(
                        "Provide the brief text for the run and submit again."
                    ),
                )
            )
        for index, entry in enumerate(command.expected_outputs):
            path_value = entry.path
            if path_value.startswith(("/", "\\")) or Path(path_value).is_absolute():
                raise CommandRejected(
                    new_command_error(
                        "SUPERVISED_RUN_INVALID",
                        field_path=f"expected_outputs.{index}.path",
                        object_refs=[project_id],
                        researcher_message=(
                            f"Expected output path {path_value!r} must be "
                            "relative to the run's outputs directory."
                        ),
                        smallest_correction=(
                            "Declare the path relative to the run outputs "
                            "area (for example 'results/summary.json') and "
                            "submit again."
                        ),
                    )
                )
        try:
            self.role_resources.role(command.role)
        except ValueError as error:
            raise CommandRejected(
                new_command_error(
                    "SUPERVISED_RUN_INVALID",
                    field_path="role",
                    object_refs=[project_id, command.role],
                    researcher_message=str(error),
                    smallest_correction=(
                        "Select one of the configured research roles and "
                        "submit again."
                    ),
                )
            ) from error

        assembler = self.run_profile_assembler
        store = self.run_seal_store

        # Idempotency: a replayed key returns the existing seal without
        # touching the filesystem or launching anything.
        existing = store.find_by_idempotency_key(command.idempotency_key)
        if existing is not None:
            if existing["project_id"] != project_id:
                raise CommandRejected(
                    new_command_error(
                        "SUPERVISED_RUN_INVALID",
                        field_path="idempotency_key",
                        object_refs=[project_id, command.idempotency_key],
                        researcher_message=(
                            "This idempotency key is already bound to a "
                            "supervised run of another project."
                        ),
                        smallest_correction=(
                            "Submit the run with a new idempotency key."
                        ),
                    )
                )
            return SupervisedRunStartResult(
                detail=supervised_run_detail(existing, store),
                replayed=True,
            )

        user_choices: dict[str, Any] = {
            "mode": "headless",
            "task_brief": "briefs/task.md",
        }
        for key, value in (
            ("model", command.model),
            ("provider", command.provider),
            ("timeout_seconds", command.timeout_seconds),
        ):
            if value is not None:
                user_choices[key] = value

        try:
            sealed = assembler.seal_invocation(
                invocation_id=command.invocation_id,
                idempotency_key=command.idempotency_key,
                project_id=project_id,
                role=command.role,
                phase=command.phase,
                method_identity=command.method_identity,
                user_choices=user_choices,
                expected_outputs=[
                    entry.model_dump(mode="json", exclude_none=True)
                    for entry in command.expected_outputs
                ],
                memory_policy=command.memory_policy,
            )
        except StateLockHeld as error:
            raise CommandRejected(
                new_command_error(
                    "SUPERVISED_RUN_LOCKED",
                    object_refs=[
                        project_id,
                        command.role,
                        error.holder_invocation_id,
                    ],
                    researcher_message=str(error),
                    smallest_correction=(
                        "Wait for the active run of this project-role to "
                        "finish before starting another."
                    ),
                )
            ) from error
        except RunSealError as error:
            raise CommandRejected(
                new_command_error(
                    "SUPERVISED_RUN_INVALID",
                    object_refs=[project_id, command.role],
                    researcher_message=str(error),
                    smallest_correction=(
                        "Correct the run request and submit again with a "
                        "new invocation id."
                    ),
                )
            ) from error

        # A concurrent same-key seal may have won the
        # UNIQUE(idempotency_key) race after our pre-check; its surviving
        # record wins and this attempt is a replay (the loser's run
        # directory was already rolled back by the assembler).
        surviving = store.find_by_idempotency_key(command.idempotency_key)
        if surviving is not None and surviving["run_dir"] != str(sealed.run_dir):
            return SupervisedRunStartResult(
                detail=supervised_run_detail(surviving, store),
                replayed=True,
            )

        brief_path = sealed.run_dir / "briefs" / "task.md"
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        brief_path.write_text(command.brief_text, encoding="utf-8")

        report = run_preflight(
            assembler,
            sealed,
            min_free_bytes=self._supervised_min_free_bytes,
        )
        if not report.passed:
            raise CommandRejected(
                new_command_error(
                    "SUPERVISED_RUN_PREFLIGHT_FAILED",
                    object_refs=[project_id, sealed.invocation_id],
                    researcher_message=(
                        "Preflight failed for this run; no process was "
                        "launched: "
                        + ", ".join(report.to_dict()["failed_checks"])
                    ),
                    smallest_correction=(
                        "Resolve the preflight failures and replay the same "
                        "idempotency key to retry the launch."
                    ),
                    detail=report.to_dict(),
                )
            )

        launch_task = asyncio.create_task(
            asyncio.to_thread(
                self._launch_supervised_in_background, sealed, brief_path
            )
        )
        self._background.add(launch_task)
        launch_task.add_done_callback(self._background.discard)

        record = store.find_by_invocation_id(sealed.invocation_id)
        assert record is not None
        return SupervisedRunStartResult(
            detail=supervised_run_detail(record, store),
            replayed=False,
        )

    def _launch_supervised_in_background(
        self, sealed: SealedRun, brief_path: Path
    ) -> None:
        """Run the WP-E0 supervised launch off the event loop.

        Executes in a worker thread via ``asyncio.to_thread`` so a
        multi-minute Hermes run never blocks the HTTP request.  The
        launcher closes its launch record as ``failed`` on every abort
        and re-raises; this wrapper logs the exception so the failure is
        never silent, and never lets it crash the server.
        """
        try:
            launch_sealed_run(
                assembler=self.run_profile_assembler,
                seal_or_invocation_id=sealed,
                task_brief=brief_path,
                executor_settings=self._supervised_executor_settings,
                secret_env=_provider_secret_env(),
                min_free_bytes=self._supervised_min_free_bytes,
            )
        except Exception:
            logger.exception(
                "Supervised launch failed for invocation %s "
                "(project %s, role %s); the launch record is closed as failed.",
                sealed.invocation_id,
                sealed.project_id,
                sealed.role,
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
            if effective_profile == "default":
                raise ProvisioningError(
                    f"Profile name {effective_profile!r} is reserved: it "
                    f"resolves to the Hermes root directory itself. Refusing "
                    f"to provision role {role_id!r} into it; assign a "
                    f"dedicated profile for this role."
                )
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
        except (SkillConflictError, SkillInstallationError) as error:
            raise CommandRejected(
                new_command_error(
                    "CUSTOMIZATION_CONFLICT",
                    object_refs=[role_id, effective_profile],
                    researcher_message=(
                        f"A recommended skill for role {role_id!r} conflicts "
                        f"with a customized local skill directory: {error}"
                    ),
                    smallest_correction=(
                        "Resolve the local skill directory, refresh, and "
                        "provision again, or force-overwrite the skill."
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
