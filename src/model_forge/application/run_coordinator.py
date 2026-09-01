"""Recovery-safe coordinator for one manually authorized research run."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..configuration.resources import RoleResourceCatalog
from ..configuration.skill_assignments import SkillAssignmentMatrix, SkillDefaults
from ..contracts.runtime import RuntimePhaseContract, resolve_runtime_contract
from ..digests.jcs import canonicalize
from ..domain.identities import (
    PHASE_IDS,
    ArtifactPointer,
    MethodIdentity,
    Sha256Digest,
    StableId,
)
from ..domain.runs import RunStatus, isoformat_utc, utc_now
from ..domain.validation import ValidationFinding, finding_from_dict
from ..executors import RoleExecutor
from ..harness.execution_context import RunExecutionContext
from ..harness.execution_records import (
    RoleExecutionInfrastructureError,
    RoleExecutionPending,
)
from ..harness.index_reducers import prepare_index_transforms
from ..harness.inputs import CurrentRecordReference, resolve_run_inputs
from ..harness.outputs import build_output_plan
from ..harness.preparation import PreparedRunRecipe, build_prepared_run_recipe
from ..harness.publication import ContractPublicationService, PublicationError
from ..harness.publication_basis import (
    capture_publication_basis,
    recover_publication_head,
)
from ..harness.stage_execution import HarnessExecutionServices
from ..harness.invocation_fencing import FencingError, InvocationFencer
from ..harness.submission_validation import (
    SubmissionValidationResult,
    validate_submission,
)
from ..json_io import load_json, loads_json
from ..orchestration import (
    ContractSequentialOrchestrator,
    OrchestrationBinding,
    OrchestrationStatus,
    OrchestratorRegistry,
)
from ..storage import ArtifactStore
from ..storage.repository import HubRepository, RepositoryConflictError
from ..specification import SpecificationPackage
from .orchestration_progress import ProgressReportingServices
from .repository_views import RepositoryQueries
from .run_lifecycle import RunLifecycle
from .settings import ApplicationSettings

logger = logging.getLogger(__name__)


_TERMINAL = frozenset(
    {"published", "failed", "rejected", "conflicted", "cancelled",
     "correction_exhausted"}
)


class RunCoordinator:
    """Advance or recover one run without choosing another user action."""

    def __init__(
        self,
        *,
        settings: ApplicationSettings,
        specification: SpecificationPackage,
        repository: HubRepository,
        artifacts: ArtifactStore,
        role_resources: RoleResourceCatalog,
        executor: RoleExecutor,
    ) -> None:
        self.settings = settings
        self.specification = specification
        self.repository = repository
        self.artifacts = artifacts
        self.workspace = artifacts.workspace
        self.role_resources = role_resources
        self.executor = executor
        self.lifecycle = RunLifecycle(repository)
        self.queries = RepositoryQueries(repository)
        self.orchestrator = ContractSequentialOrchestrator()
        self.orchestrators = OrchestratorRegistry((self.orchestrator,))
        self.publisher = ContractPublicationService(repository)
        self._fencer = InvocationFencer(repository)
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        resource_root = Path(__file__).resolve().parents[3] / "resources"
        self._skill_manifest = load_json(resource_root / "skills" / "manifest.json")
        team_root = resource_root / "team"
        self._skill_assignments = SkillAssignmentMatrix.load(
            team_root, role_resources, self._skill_manifest
        )
        self._skill_defaults = SkillDefaults.load(
            team_root, role_resources, self._skill_manifest
        )

    async def run(self, run_id: str) -> None:
        """Advance the selected run until terminal or externally pending."""

        lock = self._locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            holder = f"coordinator:{run_id}"
            self._fencer.acquire_lease(run_id, holder)
            try:
                for _ in range(24):
                    row = self.repository.get_run(run_id)
                    status = str(row["status"])
                    if status in _TERMINAL:
                        return
                    try:
                        if status == "created":
                            self.lifecycle.transition(
                                run_id,
                                RunStatus.PREPARING,
                                "Freezing the exact inputs, roles, resources, and publication basis.",
                            )
                        elif status == "preparing":
                            self._prepare(run_id)
                        elif status == "prepared":
                            self.lifecycle.transition(
                                run_id,
                                RunStatus.RUNNING,
                                "The frozen role plan is starting.",
                            )
                        elif status == "running":
                            pending = await self._execute(run_id)
                            if pending:
                                return
                        elif status == "cancellation_requested":
                            pending = await self._settle_cancellation(run_id)
                            if pending:
                                return
                        elif status == "submitted":
                            self.lifecycle.transition(
                                run_id,
                                RunStatus.VALIDATING,
                                "The immutable submission is being checked against the frozen contract.",
                                payload_updates={
                                    "validation_report": {
                                        "status": "pending",
                                        "summary": "Submission validation is in progress.",
                                    }
                                },
                            )
                        elif status == "validating":
                            self._validate(run_id)
                        elif status == "promoting":
                            self._promote(run_id)
                        elif status in ("correction_authorized", "correcting"):
                            # HV-5.8: Never auto-advance correction states.
                            # These require explicit user authorization and
                            # must not be relanched on restart.
                            return
                        else:
                            raise RuntimeError(f"Unsupported active run status {status!r}.")
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        if self._handle_error(run_id, error):
                            return
                        raise
            finally:
                self._fencer.release_lease(run_id)

    async def resume_incomplete(self) -> None:
        """Schedule every durable nonterminal run after application startup."""

        for row in self.repository.list_incomplete_runs():
            self._schedule(str(row["run_id"]))

    async def notify_cancellation(self, run_id: str) -> None:
        """Wake settlement without making the notification authoritative."""

        self._schedule(run_id)
        await asyncio.sleep(0)

    def _schedule(self, run_id: str) -> None:
        task = asyncio.create_task(self.run(run_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _prepare(self, run_id: str) -> None:
        manifest_row = self.repository.get_manifest(run_id)
        if manifest_row is not None:
            recipe = self._load_recipe(run_id)
            self._backfill_manifest_contract(recipe.document)
            self._mark_prepared(run_id, recipe)
            return

        run = self.repository.get_run(run_id)
        command_row = self.repository.get_sealed_command(str(run["command_id"]))
        command = loads_json(
            command_row["payload_json"], source=f"command {command_row['command_id']}"
        )
        if type(command) is not dict:
            raise ValueError("Sealed run command must be a JSON object.")
        self.specification.schemas.require_valid("run-command.schema.json", command)
        self.specification.digests.require_match("run_command.content", command)
        identity = self.specification.phases.identity(str(command["phase"]))
        if (
            str(identity.contract_version) != str(command["phase_contract_version"])
            or str(identity.phase_contract_sha256)
            != str(command["phase_contract_sha256"])
        ):
            raise ValueError("Sealed command references an unavailable phase contract.")
        plan = self.specification.resolve_phase(
            identity,
            str(command["mode"]),
            dict(command["choice_values"]),
            str(command["context_policy"]),
        )
        runtime = resolve_runtime_contract(self.specification.phases, plan)
        selected = command.get("selected_current_input_ids")
        seed_records = self._prepare_seed_records(
            command=command,
            contract=runtime,
        )
        inputs = resolve_run_inputs(
            project_id=str(run["project_id"]),
            contract=runtime,
            lookup=self.queries,
            selected_context_option_ids=(
                tuple(str(value) for value in selected)
                if type(selected) is list
                else None
            ),
            seed_records=seed_records,
        )
        if not inputs.passed:
            message = "; ".join(item.message for item in inputs.findings)
            raise ValueError(message or "Required current inputs could not be frozen.")
        self._preserve_frozen_contract(
            str(run["project_id"]), str(command["phase"])
        )
        output_plan = build_output_plan(plan)
        roles = {
            step.role for stage in plan.stages for step in stage.role_steps
        }
        profiles, resources = self._freeze_role_resources(
            str(run["project_id"]),
            roles,
            contract_document=self.specification.phases.contract_document(
                str(command["phase"])
            ),
            mode=plan.mode_id,
        )
        method = _selected_method(plan.choice_values)
        publication_basis = capture_publication_basis(
            repository=self.repository,
            project_id=str(run["project_id"]),
            plan=plan,
            method=method,
        )
        binding = self.orchestrator.binding_for(plan.identity)
        recipe = build_prepared_run_recipe(
            run_id=run_id,
            command=command,
            contract=runtime,
            inputs=inputs,
            output_plan=output_plan,
            profiles=profiles,
            binding=binding,
            publication_basis=publication_basis,
            role_resources=resources,
        )
        self._verify_frozen_inputs(recipe)
        self._verify_sealed_basis(command, recipe, runtime=runtime)
        self.repository.freeze_manifest(run_id, recipe.sha256, recipe.document)
        self._mark_prepared(run_id, recipe)

    def _mark_prepared(self, run_id: str, recipe: PreparedRunRecipe) -> None:
        frozen_basis = [
            {
                "label": str(item["record_type"]).replace("_", " ").title(),
                "identity": str(item["generation_id"]),
                "digest": str(item["artifact"]["sha256"]),
                "origin": str(item.get("origin", "current_record")),
            }
            for item in recipe.document.get("frozen_inputs", ())
        ]
        self.lifecycle.transition(
            run_id,
            RunStatus.PREPARED,
            "The exact run manifest is sealed. No phase choice can change inside this run.",
            payload_updates={
                "manifest_sha256": recipe.sha256,
                "frozen_basis": frozen_basis,
            },
        )

    async def _execute(self, run_id: str) -> bool:
        recipe, plan, context, services = self._execution_components(run_id)
        binding = OrchestrationBinding.from_dict(
            recipe.document["orchestration_binding"]
        )
        orchestrator = self.orchestrators.resolve(binding)
        try:
            result = await orchestrator.execute(
                run_id=context.run_id,
                manifest_sha256=context.manifest_sha256,
                binding=binding,
                plan=plan,
                services=ProgressReportingServices(services, self.lifecycle),
            )
        except (RoleExecutionPending, RoleExecutionInfrastructureError):
            # Restart-safe recovery: an acknowledged execution is still in
            # flight, or harness bookkeeping hit a transient failure. Leave
            # the run `running`; the next resume/notify pass reconciles.
            return True
        if result.status is OrchestrationStatus.SUBMITTED:
            return False
        if result.status is OrchestrationStatus.CANCELLED:
            row = self.repository.get_run(run_id)
            if row["status"] == "cancellation_requested":
                return await self._settle_cancellation(run_id)
            self._fail(
                run_id,
                "executor.unrequested_cancellation",
                "A role stopped as cancelled without a durable user cancellation request.",
            )
            return False
        failure_code = (
            result.stage_outcomes[-1].failure_code
            if result.stage_outcomes
            else "orchestration.failed"
        )
        self._fail(
            run_id,
            failure_code or "orchestration.failed",
            "A declared role group failed. No scientific role was retried.",
            findings=self._failed_closure_findings(run_id),
        )
        return False

    async def _settle_cancellation(self, run_id: str) -> bool:
        manifest = self.repository.get_manifest(run_id)
        if manifest is not None:
            _, plan, _, services = self._execution_components(run_id)
            for stage in plan.stages:
                for step in stage.role_steps:
                    settled = await services.roles.settle_cancellation(
                        stage=stage, role=step.role
                    )
                    if not settled:
                        return True
            if self.repository.list_unclosed_acknowledged_executions(run_id):
                return True
        self.lifecycle.transition(
            run_id,
            RunStatus.CANCELLED,
            "Cancellation settled. No role process remains active and formal records were unchanged.",
            payload_updates={
                "terminal_reason": {
                    "code": "run.cancelled_by_user",
                    "message": "The researcher cancelled this run before submission.",
                },
                "current_stage_label": None,
            },
        )
        return False

    def _validate(self, run_id: str) -> None:
        try:
            validation, _, _, _, _ = self._publication_plan(run_id)
        except (PublicationError, ValueError) as error:
            self._reject(run_id, "submission.validation_failed", str(error))
            return
        if not validation.passed:
            summary = "; ".join(item.message for item in validation.findings[:4])
            self._reject(
                run_id,
                "submission.validation_failed",
                summary or "Submission validation failed.",
                findings=validation.findings,
            )
            return
        prepared_at = isoformat_utc(utc_now())
        self.lifecycle.transition(
            run_id,
            RunStatus.PROMOTING,
            "Validation passed. The complete declared publication is ready for one atomic commit.",
            payload_updates={
                "validation_report": {
                    "status": "passed",
                    "summary": "All structural, provenance, identity, and publication-plan checks passed.",
                },
                "publication_prepared_at": prepared_at,
            },
        )

    def _promote(self, run_id: str) -> None:
        prior = self.repository.get_publication_receipt_for_run(run_id)
        if prior is not None:
            self._mark_published(run_id, str(prior["receipt_id"]))
            return
        validation, plan, recipe, transforms, head = self._publication_plan(run_id)
        if not validation.passed:
            raise ValueError("Validated submission changed before publication.")
        run = self.repository.get_run(run_id)
        payload = json.loads(run["payload_json"])
        published_at = _parse_time(str(payload["publication_prepared_at"]))
        publication_outputs = _publication_outputs(plan, validation)
        basis = recipe.document["publication_basis"]
        try:
            result = self.publisher.publish(
                project_id=str(run["project_id"]),
                run_id=run_id,
                command_id=str(run["command_id"]),
                bindings=plan,
                outputs=publication_outputs,
                expected_head=head,
                published_at=published_at,
                slot_scope_prefix=basis.get("slot_scope_prefix"),
                prepared_transforms=transforms,
            )
        except RepositoryConflictError:
            prior = self.repository.get_publication_receipt_for_run(run_id)
            if prior is not None:
                self._mark_published(run_id, str(prior["receipt_id"]))
                return
            self.lifecycle.transition(
                run_id,
                RunStatus.CONFLICTED,
                "Formal state changed after preparation, so this submission was not published.",
                payload_updates={
                    "terminal_reason": {
                        "code": "publication.basis_changed",
                        "message": "The frozen formal head no longer matches the project.",
                        "smallest_correction": "Review the new current records and launch a new run if needed.",
                    }
                },
            )
            return
        self._mark_published(run_id, result.receipt_id)

    def _publication_plan(
        self, run_id: str
    ) -> tuple[
        SubmissionValidationResult,
        Any,
        PreparedRunRecipe,
        dict[str, Any],
        Any,
    ]:
        recipe = self._load_recipe(run_id)
        plan = self._plan_from_recipe(recipe)
        output_plan = build_output_plan(plan)
        method = _selected_method(plan.choice_values)
        run = self.repository.get_run(run_id)
        validation = validate_submission(
            repository=self.repository,
            artifacts=self.artifacts,
            schemas=self.specification.schemas,
            project_id=str(run["project_id"]),
            run_id=run_id,
            plan=plan,
            output_plan=output_plan,
            selected_method=method,
        )
        if not validation.passed:
            return validation, plan, recipe, {}, None
        publication_outputs = _publication_outputs(plan, validation)
        transforms = prepare_index_transforms(
            repository=self.repository,
            artifacts=self.artifacts,
            project_id=str(run["project_id"]),
            run_id=run_id,
            recipe=recipe,
            plan=plan,
            outputs=publication_outputs,
        )
        self._verify_transform_inputs(recipe, plan, transforms)
        basis = recipe.document.get("publication_basis")
        if type(basis) is not dict:
            raise ValueError("Prepared run lacks a frozen publication basis.")
        head = recover_publication_head(
            basis, plan=plan, outputs=publication_outputs
        )
        self.publisher.validate_materialization(
            project_id=str(run["project_id"]),
            run_id=run_id,
            command_id=str(run["command_id"]),
            bindings=plan,
            outputs=publication_outputs,
            expected_head=head,
            slot_scope_prefix=basis.get("slot_scope_prefix"),
            prepared_transforms=transforms,
        )
        return validation, plan, recipe, transforms, head

    def _execution_components(
        self, run_id: str
    ) -> tuple[
        PreparedRunRecipe,
        Any,
        RunExecutionContext,
        HarnessExecutionServices,
    ]:
        recipe = self._load_recipe(run_id)
        plan = self._plan_from_recipe(recipe)
        output_plan = build_output_plan(plan)
        resources = recipe.document.get("role_resources")
        if type(resources) is not dict:
            raise ValueError("Prepared run lacks frozen role resources.")
        souls: dict[str, str] = {}
        skills: dict[str, tuple[str, ...]] = {}
        for role, value in resources.items():
            if type(value) is not dict:
                raise ValueError(f"Frozen resource for {role!r} is invalid.")
            soul = str(value["soul_text"])
            if hashlib.sha256(soul.encode("utf-8")).hexdigest() != value["soul_sha256"]:
                raise ValueError(f"Frozen soul digest for {role!r} is invalid.")
            souls[str(role)] = soul
            skills[str(role)] = tuple(
                str(item["skill_id"]) for item in value.get("skills", ())
            )
        instruction = next(
            str(value)
            for key, value in plan.choice_values.items()
            if key.endswith(".instructions")
        )

        # Resolve separate mode and stage-role instruction layers. The
        # frozen choice remains untouched. When it differs from the
        # rendered mode default, it is researcher-authored direction and
        # is carried verbatim as the highest scientific-priority layer
        # inside the immutable mode and method scope.
        mode_instruction = instruction
        researcher_instruction = ""
        role_instructions: dict[str, str] = {}
        try:
            from .default_instructions import (
                load_mode_instruction,
                load_stage_instruction,
                stage_template_exists,
            )
            from .repository_views import row_json

            mode = plan.mode_id
            # Fetch the brief once for all roles
            brief_row = self.repository.get_current_record(
                str(recipe.document["project_id"]),
                "project.brief.current",
            )
            brief_payload = row_json(brief_row) if brief_row is not None else None

            if brief_payload is not None:
                mode_instruction = load_mode_instruction(mode, brief_payload)
                if instruction != mode_instruction:
                    researcher_instruction = instruction
                for stage in plan.stages:
                    for step in stage.role_steps:
                        role = step.role
                        stage_id = stage.stage_id
                        if stage_template_exists(mode, role, stage_id):
                            key = f"{stage_id}.{role}"
                            role_instructions[key] = load_stage_instruction(
                                mode,
                                brief_payload,
                                role=role,
                                stage_id=stage_id,
                            )
        except Exception:
            logger.exception(
                "Failed to resolve stage+role instructions for run %s; "
                "falling back to phase-level instruction only.",
                run_id,
            )

        # Append open LITERATURE_GAP items to P1 role instructions.
        # Stage templates shadow the phase instruction, so we must enrich
        # the role-level instructions here too, not just in service.py.
        if plan.mode_id.startswith("p1.") and role_instructions:
            _append_gaps_to_role_instructions(
                self.repository,
                self.queries,
                str(recipe.document["project_id"]),
                role_instructions,
            )

        # Extract researcher-provided method spec for researcher_proposal mode.
        researcher_method_spec = str(
            plan.choice_values.get("p2.researcher_method_spec", "")
        )

        context = RunExecutionContext(
            run_id=run_id,
            project_id=str(recipe.document["project_id"]),
            manifest_sha256=recipe.sha256,
            recipe=recipe,
            plan=plan,
            output_plan=output_plan,
            phase_instruction=instruction,
            role_souls=souls,
            preloaded_skills=skills,
            mode_instruction=mode_instruction,
            researcher_instruction=researcher_instruction,
            role_instructions=role_instructions,
            researcher_method_spec=researcher_method_spec,
        )
        services = HarnessExecutionServices(
            context=context,
            repository=self.repository,
            executor=self.executor,
            schemas=self.specification.schemas,
            artifacts=self.artifacts,
            workspace=self.workspace,
        )
        return recipe, plan, context, services

    def correction_services(
        self,
        run_id: str,
        *,
        correction_command_id: str,
        correction_type: str,
    ) -> HarnessExecutionServices:
        """Build harness services for one authorized output correction.

        Reuses the frozen execution components; only the submission
        provenance and correction identity change (K-1a5 Lane A).
        """

        _, _, context, _ = self._execution_components(run_id)
        correction_context = dataclasses.replace(
            context,
            submission_from_status="correcting",
            correction_command_id=correction_command_id,
            correction_type=correction_type,
        )
        return HarnessExecutionServices(
            context=correction_context,
            repository=self.repository,
            executor=self.executor,
            schemas=self.specification.schemas,
            artifacts=self.artifacts,
            workspace=self.workspace,
        )

    def _load_recipe(self, run_id: str) -> PreparedRunRecipe:
        row = self.repository.get_manifest(run_id)
        if row is None:
            raise ValueError("Run manifest is unavailable.")
        document = loads_json(row["payload_json"], source=f"manifest {run_id}")
        if type(document) is not dict:
            raise ValueError("Run manifest must be an object.")
        return PreparedRunRecipe.load(document, str(row["manifest_sha256"]))

    def _plan_from_recipe(self, recipe: PreparedRunRecipe):
        identity = self.specification.phases.identity(str(recipe.document["phase"]))
        if (
            str(identity.contract_version)
            != str(recipe.document["phase_contract_version"])
            or str(identity.phase_contract_sha256)
            != str(recipe.document["phase_contract_sha256"])
        ):
            # The run was sealed under a superseded contract version; resolve
            # the plan from the frozen contract bytes preserved at seal time.
            document = self._recover_frozen_contract(recipe)
            if document is None:
                raise ValueError("Frozen phase contract is unavailable.")
            request = recipe.document["user_request"]
            return self.specification.resolve_phase_frozen(
                document,
                str(recipe.document["mode"]),
                dict(request["choice_values"]),
                str(request["context_policy"]),
            )
        request = recipe.document["user_request"]
        return self.specification.resolve_phase(
            identity,
            str(recipe.document["mode"]),
            dict(request["choice_values"]),
            str(request["context_policy"]),
        )

    def _backfill_manifest_contract(self, document: Mapping[str, Any]) -> bool:
        """Preserve frozen contract bytes for one sealed manifest if possible.

        Only manifests whose pinned digest still matches the loaded registry
        can be backfilled; older pins are unrecoverable by construction and
        left untouched. Idempotent: an already-preserved pin is skipped.
        """
        project_id = str(document.get("project_id", ""))
        phase = str(document.get("phase", ""))
        pinned = str(document.get("phase_contract_sha256", ""))
        if not project_id or not phase or not pinned:
            return False
        try:
            identity = self.specification.phases.identity(phase)
        except Exception:
            return False
        if str(identity.phase_contract_sha256) != pinned:
            return False
        for row in self.repository.find_artifacts_by_purpose(
            project_id, "phase_contract_frozen"
        ):
            metadata = loads_json(
                str(row["payload_json"]),
                source=f"artifact {row['artifact_id']}",
            )
            if type(metadata) is dict and str(
                metadata.get("phase_contract_sha256", "")
            ) == pinned:
                return False
        self._preserve_frozen_contract(project_id, phase)
        return True

    def backfill_frozen_contracts(self) -> int:
        """Preserve frozen contract bytes for every recoverable manifest.

        Covers manifests sealed before the preservation feature and the
        manifest-exists re-prepare path; returns the count preserved.
        """
        preserved = 0
        for row in self.repository.list_manifests():
            document = loads_json(
                str(row["payload_json"]), source=f"manifest {row['run_id']}"
            )
            if type(document) is dict and self._backfill_manifest_contract(
                document
            ):
                preserved += 1
        return preserved

    def _preserve_frozen_contract(self, project_id: str, phase: str) -> None:
        """Content-address the exact contract bytes at seal time.

        A contract version bump must never orphan corrections, submissions,
        or execution of runs sealed under the older version: the bytes are
        stored under their digest and findable by purpose.
        """
        document = self.specification.phases.contract_document(phase)
        identity = self.specification.phases.identity(phase)
        pinned = str(identity.phase_contract_sha256)
        payload = canonicalize(document)
        stored = self.artifacts.put_bytes(payload)
        artifact_id = "artifact.phase_contract." + hashlib.sha256(
            f"{project_id}:{phase}:{pinned}".encode()
        ).hexdigest()[:24]
        self.repository.record_artifact(
            artifact_id,
            project_id,
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "relative_path": stored.relative_path,
                "purpose": "phase_contract_frozen",
                "phase_id": phase,
                "contract_version": str(identity.contract_version),
                "phase_contract_sha256": pinned,
            },
        )

    def _recover_frozen_contract(
        self, recipe: PreparedRunRecipe
    ) -> dict[str, Any] | None:
        project_id = str(recipe.document.get("project_id", ""))
        pinned = str(recipe.document["phase_contract_sha256"])
        for row in self.repository.find_artifacts_by_purpose(
            project_id, "phase_contract_frozen"
        ):
            document = loads_json(
                self.artifacts.read_bytes(str(row["sha256"])),
                source=f"artifact {row['artifact_id']}",
            )
            if type(document) is not dict:
                continue
            digest = self.specification.digests.compute(
                "phase_contract.content", document
            )
            if str(digest) == pinned:
                return document
        return None

    def _prepare_seed_records(
        self,
        *,
        command: Mapping[str, Any],
        contract: RuntimePhaseContract,
    ) -> dict[str, CurrentRecordReference]:
        """Content-address the run command's seed inputs (SD-1, ADR-019).

        Each seed's bytes are stored immutably and wrapped in a synthetic
        record reference frozen with ``researcher_seed`` provenance.  Seeds
        are additive only: they fill the contract's declared supplementary
        material slots and can never replace a required published input.
        The run's selected method identity attaches so method-scoped inputs
        keep their lineage checks.  Unknown or disallowed input ids are
        passed through; ``resolve_run_inputs`` rejects them with precise
        findings.
        """
        raw = command.get("seed_inputs")
        if type(raw) is not dict or not raw:
            return {}
        record_types = {
            str(item["input_id"]): str(item["record_type"])
            for item in contract.required_inputs
        }
        record_types.update(
            {
                str(item["input_id"]): str(item["record_type"])
                for item in contract.supplementary_inputs
            }
        )
        method = _selected_method(contract.plan.choice_values)
        records: dict[str, CurrentRecordReference] = {}
        for input_id, seed in raw.items():
            content = str(seed.get("content", "")).encode("utf-8")
            stored = self.artifacts.put_bytes(content)
            sha = str(stored.sha256)
            records[str(input_id)] = CurrentRecordReference(
                record_id=f"seed.{input_id}.{sha[:12]}",
                generation_id="seed",
                generation_number=0,
                record_type=record_types.get(str(input_id), "unknown"),
                artifact=ArtifactPointer(
                    artifact_id=StableId(f"artifact.{sha}"),
                    uri=f"artifact://sha256/{sha}",
                    sha256=Sha256Digest(sha),
                    media_type=str(seed.get("media_type", "text/markdown")),
                ),
                method_identity=method,
                size_bytes=len(content),
            )
        return records

    def _freeze_role_resources(
        self,
        project_id: str,
        roles: set[str],
        *,
        contract_document: dict[str, Any] | None = None,
        mode: str | None = None,
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        from ..harness.role_resource_snapshot import compute_role_resources

        return compute_role_resources(
            repository=self.repository,
            settings=self.settings,
            role_resources=self.role_resources,
            skill_manifest=self._skill_manifest,
            roles=roles,
            project_id=project_id,
            contract_document=contract_document,
            mode=mode,
            skill_assignments=self._skill_assignments,
            skill_defaults=self._skill_defaults,
        )

    def _verify_frozen_inputs(self, recipe: PreparedRunRecipe) -> None:
        basis = recipe.document["publication_basis"]
        project = self.repository.get_project(str(recipe.document["project_id"]))
        if (
            int(project["authority_sequence"]) != int(basis["authority_sequence"])
            or str(project["authority_root_sha256"])
            != str(basis["authority_root_sha256"])
            or int(project["current_revision"]) != int(basis["current_revision"])
        ):
            raise RepositoryConflictError(
                "repository.preparation_basis_changed",
                "Formal state changed while the run basis was being frozen.",
            )
        for item in recipe.document.get("frozen_inputs", ()):
            slot = item.get("logical_slot")
            if slot is None:
                continue
            current = self.repository.get_current_record(
                str(recipe.document["project_id"]), str(slot)
            )
            if current is None or current["generation_id"] != item["generation_id"]:
                raise RepositoryConflictError(
                    "repository.preparation_basis_changed",
                    "A selected current input changed during preparation.",
                )

    def _verify_sealed_basis(
        self,
        command: dict[str, Any],
        recipe: PreparedRunRecipe,
        *,
        runtime: RuntimePhaseContract,
    ) -> None:
        """Verify the sealed basis captured at view time against the freshly
        prepared run recipe.

        If the sealed basis in the command does not match the prepared state,
        the run is rejected with ``STALE_BASIS`` — the researcher must refresh
        and re-review. A stored pre-upgrade command without ``sealed_basis``
        (C6) passes through unchanged.
        """
        sealed = command.get("sealed_basis")
        if sealed is None:
            return
        project_id = str(command["project_id"])

        # 1. Authority head
        project = self.repository.get_project(project_id)
        live_head = {
            "authority_sequence": int(project["authority_sequence"]),
            "authority_root_sha256": str(project["authority_root_sha256"]),
            "current_revision": int(project["current_revision"]),
        }
        for key, expected in live_head.items():
            actual = sealed.get("authority_head", {}).get(key)
            if actual is not None and str(actual) != str(expected):
                raise RepositoryConflictError(
                    "stale_basis.authority_head_drifted",
                    "The formal authority head changed between review and preparation.",
                )

        # 2. Reviewed current inputs — generation_id drift, and rejection of a
        #    sealed entry that matches no frozen contract input (the reviewed
        #    input is no longer part of the prepared basis).  An optional input
        #    that the user deselected is intentionally absent from the frozen
        #    set (``resolve_run_inputs`` skips it); such entries are skipped
        #    here rather than treated as drift.
        frozen = recipe.document.get("frozen_inputs", ())
        frozen_ids = {
            str(item.get("contract_input_id", "")) for item in frozen
        }
        for sealed_input in sealed.get("reviewed_current_inputs", ()):
            option_id = sealed_input.get("option_id")
            if option_id is None:
                continue
            sealed_gen = sealed_input.get("generation_id")
            if sealed_gen is None:
                continue
            if str(option_id) not in frozen_ids:
                # The reviewed basis seals every current input option,
                # including optional ones the user may have deselected.
                # resolve_run_inputs intentionally omits unselected
                # optional inputs from the frozen set — that is not
                # drift, just a user selection.  Only reject when the
                # sealed entry was required (required inputs are always
                # frozen when present).
                if sealed_input.get("required"):
                    raise RepositoryConflictError(
                        "stale_basis.input_generation_drifted",
                        f"Reviewed current input {option_id!r} is not part of the prepared basis.",
                    )
                continue
            for item in frozen:
                if str(item.get("contract_input_id", "")) == str(option_id):
                    if str(item["generation_id"]) != str(sealed_gen):
                        raise RepositoryConflictError(
                            "stale_basis.input_generation_drifted",
                            "A reviewed current input was republished before the run froze.",
                        )
                    break

        # 3. Method identity: the run must execute exactly the reviewed method.
        #    The live method comes from the resolved runtime contract's choices;
        #    either side missing while the other names a method is drift too.
        sealed_method = sealed.get("method_identity")
        live_method = _selected_method(runtime.plan.choice_values)
        if live_method is None:
            if sealed_method is not None:
                raise RepositoryConflictError(
                    "stale_basis.method_drifted",
                    "The reviewed basis names a method but the prepared run is not method-bound.",
                )
        else:
            if type(sealed_method) is not dict:
                raise RepositoryConflictError(
                    "stale_basis.method_drifted",
                    "The reviewed basis does not name the method the prepared run will execute.",
                )
            expected = live_method.to_dict()
            for key in ("stable_id", "version", "definition_sha256"):
                if sealed_method.get(key) != expected[key]:
                    raise RepositoryConflictError(
                        "stale_basis.method_drifted",
                        "The method the run will execute changed between review and preparation.",
                    )

        # 4. Role resources. The frozen recipe is the live reference at
        #    preparation time: a role absent from the live catalog is absent
        #    from the recipe's role_resources.
        sealed_resources = sealed.get("role_resources", {})
        if sealed_resources:
            live_resources = recipe.document.get("role_resources", {})
            for role, sealed_role in sealed_resources.items():
                live_role = live_resources.get(role)
                if live_role is None:
                    raise RepositoryConflictError(
                        "stale_basis.role_resource_drifted",
                        f"Role {role!r} is no longer part of the prepared run.",
                    )
                for field in ("profile", "profile_version", "soul_sha256"):
                    if str(sealed_role.get(field, "")) != str(
                        live_role.get(field, "")
                    ):
                        raise RepositoryConflictError(
                            "stale_basis.role_resource_drifted",
                            f"Role resource for {role!r} changed between review and preparation.",
                        )
                sealed_skills = {
                    s.get("skill_id"): s.get("bundle_sha256")
                    for s in sealed_role.get("skills", ())
                }
                live_skills = {
                    s.get("skill_id"): s.get("bundle_sha256")
                    for s in live_role.get("skills", ())
                }
                if sealed_skills != live_skills:
                    raise RepositoryConflictError(
                        "stale_basis.role_resource_drifted",
                        f"Skill bundles for role {role!r} changed between review and preparation.",
                    )
                # Every further field present in BOTH snapshots must match:
                # soul text, per-skill source revisions, and the WP-H2 exact
                # configuration fields (memory policy, model/provider,
                # phase instruction, base configuration and library guidance
                # digests, custom skills). A field the sealed basis does not
                # record at all (a pre-WP-H2 stored command) passes through
                # unchanged (C6); a recorded field that differs from the
                # freshly frozen snapshot is drift.
                for field in sorted(set(sealed_role) & set(live_role)):
                    if field in (
                        "profile",
                        "profile_version",
                        "soul_sha256",
                        "skills",
                    ):
                        continue
                    if sealed_role[field] != live_role[field]:
                        raise RepositoryConflictError(
                            "stale_basis.role_resource_drifted",
                            f"Role resource for {role!r} changed between review and preparation.",
                        )
                sealed_skill_entries = [
                    dict(s)
                    for s in sealed_role.get("skills", ())
                    if type(s) is dict
                ]
                live_skill_entries = [
                    dict(s)
                    for s in live_role.get("skills", ())
                    if type(s) is dict
                ]
                if sealed_skill_entries != live_skill_entries:
                    raise RepositoryConflictError(
                        "stale_basis.role_resource_drifted",
                        f"Skill entries for role {role!r} changed between review and preparation.",
                    )

    @staticmethod
    def _verify_transform_inputs(recipe, plan, transforms) -> None:
        frozen = {
            str(item["contract_input_id"]): str(item["artifact"]["sha256"])
            for item in recipe.document.get("frozen_inputs", ())
        }
        for binding in plan.publication_bindings:
            if binding["publisher_transform"] != "deterministic_index":
                continue
            binding_id = str(binding["binding_id"])
            expected = {
                str(input_id): frozen[str(input_id)]
                for input_id in binding.get("source_input_ids", ())
                if str(input_id) in frozen
            }
            if dict(transforms[binding_id].source_input_sha256) != expected:
                raise ValueError(
                    f"Prepared reducer {binding_id!r} is not bound to frozen inputs."
                )

    def _mark_published(self, run_id: str, receipt_id: str) -> None:
        self.lifecycle.transition(
            run_id,
            RunStatus.PUBLISHED,
            "The complete validated phase result was published atomically.",
            payload_updates={
                "publication_receipt_id": receipt_id,
                "current_stage_label": None,
            },
        )

    def _reject(
        self,
        run_id: str,
        code: str,
        message: str,
        findings: Sequence[ValidationFinding] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "validation_report": {"status": "failed", "summary": message},
            "terminal_reason": {
                "code": code,
                "message": message,
                "smallest_correction": "Review the validation result and launch a new run after correcting the basis or instructions.",
            },
        }
        if findings:
            payload["closure_findings"] = [f.to_dict() for f in findings]
        self.lifecycle.transition(
            run_id,
            RunStatus.REJECTED,
            "Submission validation failed. Formal project records were unchanged.",
            payload_updates=payload,
        )

    def _failed_closure_findings(
        self, run_id: str
    ) -> list[ValidationFinding] | None:
        """Collect the findings sealed on this run's FAILED role closures.

        K5-2: a role-group failure must carry the classified closure
        findings into the run payload; without them the lifecycle
        projection shows zero findings and every correction command is
        refused as 'integrity blockers' even when the failure is a
        correctable contract error (K-5 production evidence).
        """
        collected: list[ValidationFinding] = []
        for row in self.repository.list_role_closures_for_run(run_id):
            document = json.loads(str(row["payload_json"]))
            if type(document) is not dict or document.get("status") != "failed":
                continue
            for item in document.get("findings") or ():
                finding = finding_from_dict(item)
                if finding is not None:
                    collected.append(finding)
        return collected or None

    def _fail(
        self,
        run_id: str,
        code: str,
        message: str,
        findings: Sequence[ValidationFinding] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "terminal_reason": {"code": code, "message": message},
            "current_stage_label": None,
        }
        if findings:
            payload["closure_findings"] = [f.to_dict() for f in findings]
        self.lifecycle.transition(
            run_id,
            RunStatus.FAILED,
            message,
            payload_updates=payload,
        )

    def _handle_error(self, run_id: str, error: Exception) -> bool:
        row = self.repository.get_run(run_id)
        status = str(row["status"])
        if status in _TERMINAL:
            return True
        if status == "cancellation_requested":
            return True
        if isinstance(error, RepositoryConflictError) and status in (
            "promoting",
            "preparing",
        ):
            self.lifecycle.transition(
                run_id,
                RunStatus.CONFLICTED,
                "The frozen publication basis changed. Formal records were not replaced.",
                payload_updates={
                    "terminal_reason": {
                        "code": error.code,
                        "message": error.message,
                        "smallest_correction": "Review the current project state before launching another run.",
                    }
                },
            )
            return True
        self._fail(
            run_id,
            getattr(error, "code", "run.coordination_failed"),
            f"The run stopped safely: {error}",
        )
        return True


def _selected_method(choice_values: Any) -> MethodIdentity | None:
    for key, value in choice_values.items():
        if str(key).endswith(".selected_method"):
            return MethodIdentity.from_dict(value)
    return None


def _publication_outputs(plan, validation: SubmissionValidationResult):
    required = {
        str(output_id)
        for binding in plan.publication_bindings
        for output_id in binding["output_ids"]
    }
    missing = sorted(required - set(validation.outputs))
    if missing:
        raise ValueError(f"Publication outputs are missing: {missing}.")
    return {output_id: validation.outputs[output_id] for output_id in required}


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _append_gaps_to_role_instructions(
    repository: HubRepository,
    queries: RepositoryQueries,
    project_id: str,
    role_instructions: dict[str, str],
) -> None:
    """Append open LITERATURE_GAP items to each P1 role instruction in place.

    Stage templates shadow the phase-level instruction, so the gap
    enrichment done in ``service.py`` would be lost if we didn't also
    enrich role-level instructions here. This mutates ``role_instructions``
    in place by appending the gap list to each entry.
    """
    from .repository_views import row_json

    p1_published_at: str | None = None
    for row in repository.list_current_records(project_id):
        if str(row["record_type"]) == "literature_synthesis":
            published = str(row["published_at"])
            if p1_published_at is None or published > p1_published_at:
                p1_published_at = published
    run_phases: dict[str, str] = {}
    for run in queries.list_runs(project_id):
        payload = row_json(run)
        run_id = str(run["run_id"])
        if type(payload.get("phase")) is str:
            run_phases[run_id] = str(payload["phase"])
    gaps: list[str] = []
    for row in repository.list_collection_items(
        project_id, "project.attention_history"
    ):
        payload = row_json(row)
        if str(payload.get("disposition", "open")) != "open":
            continue
        question = str(payload.get("question", ""))
        if not question.startswith("LITERATURE_GAP:"):
            continue
        appended_at = str(row["appended_at"])
        if p1_published_at is not None and appended_at <= p1_published_at:
            continue
        source_run_id = str(
            row["source_run_id"] or payload.get("source_run_id", "")
        )
        item_phase = payload.get("phase")
        if type(item_phase) is not str:
            item_phase = run_phases.get(source_run_id)
        if item_phase not in PHASE_IDS:
            continue
        reference = question[len("LITERATURE_GAP:"):].strip()
        gaps.append(f"[{item_phase}] {reference}")
    if not gaps:
        return
    block = ["", "The following references were flagged as missing from the"]
    block.append("project library by downstream phases. Assess each one and")
    block.append("incorporate those that are directly relevant:")
    for gap in gaps:
        block.append(f"  - {gap}")
    block.append("")
    suffix = "\n".join(block)
    for key in role_instructions:
        role_instructions[key] = role_instructions[key].rstrip() + suffix


__all__ = ["RunCoordinator"]
