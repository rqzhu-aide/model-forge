"""Harness-owned stage execution behind the engine-neutral orchestrator port."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Mapping

from ..contracts import ResolvedStage
from ..digests.jcs import canonicalize
from ..domain import Sha256Digest, StableId
from ..domain.runs import thaw_json
from ..executors import RoleExecutionStatus, RoleExecutor
from ..orchestration import (
    StageOutcome,
    StageStatus,
    SubmissionOutcome,
)
from ..schemas import SchemaCatalog
from ..storage import ArtifactStore, WorkspacePaths
from ..storage.repository import HubRepository
from .execution_context import RunExecutionContext
from .role_execution import (
    FrozenInputPath,
    RoleClosureResult,
    RoleLifecycleError,
    RoleLifecycleService,
    deterministic_id,
)
from .submissions import SubmissionAssembler


class StageExecutionError(RuntimeError):
    """A selected contract stage cannot be advanced safely."""


class HarnessExecutionServices:
    """Mechanical execution and submission services for one prepared run.

    Validation after submission and all publication decisions remain outside
    this service. Contract-declared parallel roles receive one basis resolved
    before any role in that group is launched.
    """

    def __init__(
        self,
        *,
        context: RunExecutionContext,
        repository: HubRepository,
        executor: RoleExecutor,
        schemas: SchemaCatalog,
        artifacts: ArtifactStore,
        workspace: WorkspacePaths,
    ) -> None:
        if artifacts.workspace.root != workspace.root:
            raise ValueError("Artifact store and run workspace must share one root.")
        self.context = context
        self.repository = repository
        self.executor = executor
        self.schemas = schemas
        self.artifacts = artifacts
        self.workspace = workspace
        self.roles = RoleLifecycleService(
            context=context,
            repository=repository,
            executor=executor,
            schemas=schemas,
            artifacts=artifacts,
            workspace=workspace,
        )
        self.submissions = SubmissionAssembler(
            context=context,
            repository=repository,
            schemas=schemas,
            artifacts=artifacts,
            roles=self.roles,
        )

    async def cancellation_requested(
        self, *, run_id: StableId, manifest_sha256: Sha256Digest
    ) -> bool:
        self._require_scope(run_id, manifest_sha256)
        return self.repository.cancellation_requested(str(self.context.run_id))

    async def execute_or_reconcile_stage(
        self,
        *,
        run_id: StableId,
        manifest_sha256: Sha256Digest,
        stage: ResolvedStage,
    ) -> StageOutcome:
        self._require_scope(run_id, manifest_sha256)
        selected = self._selected_stage(stage)
        if self.repository.cancellation_requested(str(self.context.run_id)):
            return StageOutcome(
                sequence=selected.sequence,
                stage_id=StableId(selected.stage_id),
                status=StageStatus.CANCELLED,
            )

        basis = self._basis_before(selected)
        role_inputs: list[tuple[str, Mapping[str, FrozenInputPath]]] = []
        for step in selected.role_steps:
            missing = sorted(set(step.input_ids) - set(basis))
            if missing:
                raise StageExecutionError(
                    f"Stage {selected.stage_id!r} role {step.role!r} lacks inputs {missing}."
                )
            role_inputs.append(
                (step.role, {input_id: basis[input_id] for input_id in step.input_ids})
            )

        if selected.execution == "serial":
            if len(role_inputs) != 1:
                raise StageExecutionError(
                    f"Serial stage {selected.stage_id!r} must contain one role."
                )
            role, inputs = role_inputs[0]
            results: tuple[RoleClosureResult, ...] = (
                await self.roles.execute_or_reconcile(
                    stage=selected, role=role, inputs=inputs
                ),
            )
        elif selected.execution == "parallel":
            pending = tuple(
                self.roles.execute_or_reconcile(
                    stage=selected, role=role, inputs=inputs
                )
                for role, inputs in role_inputs
            )
            gathered = await asyncio.gather(*pending, return_exceptions=True)
            errors = tuple(item for item in gathered if isinstance(item, BaseException))
            if errors:
                raise errors[0]
            results = tuple(item for item in gathered if isinstance(item, RoleClosureResult))
            if len(results) != len(role_inputs):
                raise StageExecutionError(
                    f"Parallel stage {selected.stage_id!r} returned an invalid role result."
                )
        else:
            raise StageExecutionError(
                f"Stage {selected.stage_id!r} has unknown execution mode "
                f"{selected.execution!r}."
            )

        closure_ids = tuple(
            StableId(item.closure_id)
            for item in results
            if item.closure_id is not None
        )
        reconciled = bool(results) and all(item.reconciled for item in results)
        if (
            self.repository.cancellation_requested(str(self.context.run_id))
            or any(item.status is RoleExecutionStatus.CANCELLED for item in results)
        ):
            return StageOutcome(
                sequence=selected.sequence,
                stage_id=StableId(selected.stage_id),
                status=StageStatus.CANCELLED,
                invocation_closure_ids=closure_ids,
                reconciled=reconciled,
            )
        failures = tuple(
            item for item in results if item.status is RoleExecutionStatus.FAILED
        )
        if failures:
            return StageOutcome(
                sequence=selected.sequence,
                stage_id=StableId(selected.stage_id),
                status=StageStatus.FAILED,
                invocation_closure_ids=closure_ids,
                failure_code=failures[0].failure_code or "role_execution.failed",
                reconciled=reconciled,
            )
        if len(closure_ids) != len(selected.role_steps):
            raise StageExecutionError(
                f"Successful stage {selected.stage_id!r} lacks a closure for every role."
            )
        return StageOutcome(
            sequence=selected.sequence,
            stage_id=StableId(selected.stage_id),
            status=StageStatus.SUCCEEDED,
            invocation_closure_ids=closure_ids,
            reconciled=reconciled,
        )

    async def submit_or_reconcile(
        self,
        *,
        run_id: StableId,
        manifest_sha256: Sha256Digest,
        stage_outcomes: tuple[StageOutcome, ...],
    ) -> SubmissionOutcome:
        self._require_scope(run_id, manifest_sha256)
        return self.submissions.submit_or_reconcile(
            stage_outcomes=tuple(stage_outcomes)
        )

    def _require_scope(
        self, run_id: StableId | str, manifest_sha256: Sha256Digest | str
    ) -> None:
        if (
            str(run_id) != str(self.context.run_id)
            or str(manifest_sha256) != str(self.context.manifest_sha256)
        ):
            raise StageExecutionError(
                "The orchestration request does not match this prepared run."
            )

    def _selected_stage(self, candidate: ResolvedStage) -> ResolvedStage:
        matches = tuple(
            stage
            for stage in self.context.plan.stages
            if stage.sequence == candidate.sequence and stage.stage_id == candidate.stage_id
        )
        if matches != (candidate,):
            raise StageExecutionError(
                f"Stage {candidate.stage_id!r} is not the selected frozen stage."
            )
        return matches[0]

    def _basis_before(self, stage: ResolvedStage) -> dict[str, FrozenInputPath]:
        basis = self._frozen_formal_inputs()
        basis.update(self._prepared_contexts(basis))
        output_ids = {
            spec.contract_output_id for spec in self.context.output_plan.specs
        }
        needed_base_ids = {
            input_id
            for selected in self.context.plan.stages
            if selected.sequence <= stage.sequence
            for step in selected.role_steps
            for input_id in step.input_ids
            if input_id not in output_ids
        }
        for input_id in sorted(needed_base_ids - set(basis)):
            basis[input_id] = self._absent_input(input_id)

        for prior in self.context.plan.stages:
            if prior.sequence >= stage.sequence:
                break
            for step in prior.role_steps:
                closure = self.roles.load_existing(stage=prior, role=step.role)
                if closure is None or closure.status is not RoleExecutionStatus.SUCCEEDED:
                    raise StageExecutionError(
                        f"Prior stage {prior.stage_id!r} is not successfully closed."
                    )
                for input_id, item in closure.output_inputs(
                    artifacts=self.artifacts
                ).items():
                    if input_id in basis:
                        raise StageExecutionError(
                            f"Frozen input identity {input_id!r} is produced more than once."
                        )
                    basis[input_id] = item
        return basis

    def _frozen_formal_inputs(self) -> dict[str, FrozenInputPath]:
        result: dict[str, FrozenInputPath] = {}
        for item in self.context.recipe.document.get("frozen_inputs", ()):
            input_id = str(item["contract_input_id"])
            pointer = item["artifact"]
            sha256 = str(pointer["sha256"])
            stored = self.artifacts.verify(sha256)
            result[input_id] = FrozenInputPath(
                input_id=input_id,
                artifact_id=str(pointer["artifact_id"]),
                sha256=sha256,
                path=self.workspace.for_read(stored.relative_path),
                media_type=str(pointer.get("media_type", "application/json")),
            )
        return result

    def _prepared_contexts(
        self, basis: Mapping[str, FrozenInputPath]
    ) -> dict[str, FrozenInputPath]:
        result: dict[str, FrozenInputPath] = {}
        prepared_at = str(self.context.recipe.document["prepared_at"])
        for declaration in self.context.plan.prepared_contexts:
            context_id = str(declaration["context_id"])
            source_ids = tuple(str(item) for item in declaration["source_input_ids"])
            missing = sorted(set(source_ids) - set(basis))
            if missing:
                raise StageExecutionError(
                    f"Prepared context {context_id!r} lacks source inputs {missing}."
                )
            choice_ids = tuple(
                str(item) for item in declaration.get("source_choice_ids", ())
            )
            document: dict[str, Any] = {
                "format": "method-hub.prepared-role-context",
                "format_version": "1.0.0",
                "conformance_state": "vertical_slice",
                "context_id": context_id,
                "run_id": str(self.context.run_id),
                "manifest_sha256": str(self.context.manifest_sha256),
                "purpose": str(declaration["purpose"]),
                "content_requirements": list(declaration["content_requirements"]),
                "source_inputs": [
                    {
                        "input_id": input_id,
                        "artifact_id": basis[input_id].artifact_id,
                        "sha256": basis[input_id].sha256,
                        "path": str(basis[input_id].path),
                    }
                    for input_id in source_ids
                ],
                "source_choice_values": {
                    choice_id: thaw_json(self.context.plan.choice_values[choice_id])
                    for choice_id in choice_ids
                },
                "prepared_at": prepared_at,
            }
            payload = canonicalize(document)
            stored = self.artifacts.put_bytes(payload)
            artifact_id = deterministic_id(
                "artifact", "prepared_context", str(self.context.run_id), context_id
            )
            self.repository.record_artifact(
                artifact_id,
                str(self.context.project_id),
                str(stored.sha256),
                stored.size,
                "application/json",
                f"artifact://sha256/{stored.sha256}",
                {
                    "kind": "prepared_role_context",
                    "run_id": str(self.context.run_id),
                    "context_id": context_id,
                    "storage_relative_path": stored.relative_path,
                },
            )
            result[context_id] = FrozenInputPath(
                input_id=context_id,
                artifact_id=artifact_id,
                sha256=str(stored.sha256),
                path=self.workspace.for_read(stored.relative_path),
            )
        return result

    def _absent_input(self, input_id: str) -> FrozenInputPath:
        document = {
            "format": "method-hub.absent-frozen-input",
            "format_version": "1.0.0",
            "run_id": str(self.context.run_id),
            "manifest_sha256": str(self.context.manifest_sha256),
            "input_id": input_id,
            "status": "not_present_on_frozen_basis",
        }
        payload = canonicalize(document)
        sha256 = hashlib.sha256(payload).hexdigest()
        stored = self.artifacts.put_bytes(payload, expected_sha256=sha256)
        artifact_id = deterministic_id(
            "artifact", "absent_input", str(self.context.run_id), input_id
        )
        self.repository.record_artifact(
            artifact_id,
            str(self.context.project_id),
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "kind": "absent_frozen_input",
                "run_id": str(self.context.run_id),
                "input_id": input_id,
                "storage_relative_path": stored.relative_path,
            },
        )
        return FrozenInputPath(
            input_id=input_id,
            artifact_id=artifact_id,
            sha256=sha256,
            path=self.workspace.for_read(stored.relative_path),
        )


__all__ = ["HarnessExecutionServices", "StageExecutionError"]
