"""Durable lifecycle for one already-frozen scientific role invocation."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..contracts import ResolvedPhasePlan, ResolvedStage
from ..digests.jcs import canonicalize
from ..domain.runs import isoformat_utc, thaw_json, utc_now
from ..executors import (
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleExecutor,
    RoleInvocation,
)
from ..json_io import loads_json
from ..schemas import SchemaCatalog
from ..storage import ArtifactStore, WorkspacePaths
from ..storage.repository import (
    HubRepository,
    RepositoryConflictError,
)
from .execution_context import RunExecutionContext
from .outputs import OutputSpec, validate_role_outputs
from .task_briefs import render_task_brief


from .execution_observer import RepositoryExecutionObserver as _RepositoryObserver
from .execution_records import (
    FrozenInputPath,
    RoleClosureResult,
    RoleExecutionPending,
    RoleLifecycleError,
    SealedRoleOutput,
    closure_artifact_id as _closure_artifact_id,
    deterministic_id,
    document_sha256,
    immutable_write as _immutable_write,
    output_artifact_id as _output_artifact_id,
    role_identity as _role_identity,
)

class RoleLifecycleService:
    """Execute exactly one role invocation or recover its immutable closure."""

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
        self.context = context
        self.repository = repository
        self.executor = executor
        self.schemas = schemas
        self.artifacts = artifacts
        self.workspace = workspace

    async def execute_or_reconcile(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        inputs: Mapping[str, FrozenInputPath],
    ) -> RoleClosureResult:
        invocation_id, execution_id, closure_id = _role_identity(
            self.context, stage, role
        )
        recovered = self._load_closure(
            stage=stage,
            role=role,
            invocation_id=invocation_id,
            execution_id=execution_id,
            closure_id=closure_id,
        )
        if recovered is not None:
            return recovered
        if self.repository.cancellation_requested(str(self.context.run_id)):
            return RoleClosureResult(
                role=role,
                status=RoleExecutionStatus.CANCELLED,
                execution_id=execution_id,
                invocation_id=invocation_id,
                invocation_sha256="0" * 64,
                closure_id=None,
                closure_sha256=None,
                closure_artifact_id=None,
                outputs=(),
                closed_at=None,
            )

        invocation, invocation_document, invocation_sha256 = self._prepare_invocation(
            stage=stage,
            role=role,
            inputs=inputs,
            invocation_id=invocation_id,
            execution_id=execution_id,
        )
        observer = _RepositoryObserver(
            repository=self.repository,
            executor=self.executor,
            invocation_document=invocation_document,
            invocation_sha256=invocation_sha256,
        )
        await observer.launch_intent(invocation)
        acknowledgement = self._acknowledgement(execution_id)
        try:
            if acknowledgement is None:
                result = await self.executor.execute(invocation, observer)
            else:
                external_id = str(acknowledgement["external_execution_id"])
                observer.external_execution_id = external_id
                result = await self.executor.reconcile(external_id)
                if result is None:
                    raise RoleExecutionPending(
                        f"Execution {execution_id} is acknowledged but not terminal."
                    )
        except RoleExecutionPending:
            raise
        except Exception as error:
            result = RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=observer.external_execution_id,
                exit_code=None,
                summary="The role executor raised an exception.",
                diagnostic_text=f"{type(error).__name__}: {error}",
            )
        if type(result) is not RoleExecutionResult:
            result = RoleExecutionResult(
                status=RoleExecutionStatus.FAILED,
                external_execution_id=observer.external_execution_id,
                exit_code=None,
                summary="The role executor returned an invalid result.",
                diagnostic_text=type(result).__name__,
            )

        return self._validate_and_close(
            stage=stage,
            role=role,
            invocation=invocation,
            invocation_sha256=invocation_sha256,
            closure_id=closure_id,
            result=result,
        )

    def load_existing(
        self, *, stage: ResolvedStage, role: str
    ) -> RoleClosureResult | None:
        invocation_id, execution_id, closure_id = _role_identity(
            self.context, stage, role
        )
        return self._load_closure(
            stage=stage,
            role=role,
            invocation_id=invocation_id,
            execution_id=execution_id,
            closure_id=closure_id,
        )

    async def settle_cancellation(
        self, *, stage: ResolvedStage, role: str
    ) -> bool:
        """Stop and seal one prior acknowledged execution without relaunching it."""

        invocation_id, execution_id, closure_id = _role_identity(
            self.context, stage, role
        )
        recovered = self._load_closure(
            stage=stage,
            role=role,
            invocation_id=invocation_id,
            execution_id=execution_id,
            closure_id=closure_id,
        )
        if recovered is not None:
            return True
        intent = self.repository.get_execution_for_invocation(invocation_id)
        if intent is None:
            return True
        acknowledgement = self._acknowledgement(execution_id)
        if acknowledgement is None:
            raise RoleExecutionPending(
                f"Execution {execution_id} has a launch intent but no durable acknowledgement."
            )
        external_id = str(acknowledgement["external_execution_id"])
        await self.executor.cancel(external_id)
        result = await self.executor.reconcile(external_id)
        if result is None:
            return False
        invocation_document = loads_json(
            intent["payload_json"], source=f"execution intent {execution_id}"
        )
        if type(invocation_document) is not dict:
            raise RoleLifecycleError("Execution intent payload must be an object.")
        invocation = self._recovery_invocation(
            stage=stage,
            role=role,
            invocation_id=invocation_id,
            execution_id=execution_id,
        )
        closure = self._validate_and_close(
            stage=stage,
            role=role,
            invocation=invocation,
            invocation_sha256=str(intent["invocation_sha256"]),
            closure_id=closure_id,
            result=result,
        )
        return closure.status is RoleExecutionStatus.CANCELLED

    def _recovery_invocation(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        invocation_id: str,
        execution_id: str,
    ) -> RoleInvocation:
        run_relative = f"runs/{self.context.run_id}"
        role_relative = f"{run_relative}/roles/{stage.sequence:02d}-{role}"
        task_relative = f"{run_relative}/tasks/{stage.sequence:02d}-{role}/task.md"
        specs = self.context.output_plan.for_stage_role(stage.stage_id, role)
        return RoleInvocation(
            execution_id=execution_id,
            invocation_id=invocation_id,
            run_id=str(self.context.run_id),
            project_id=str(self.context.project_id),
            phase=self.context.plan.identity.phase_id,
            mode=self.context.plan.mode_id,
            stage_id=stage.stage_id,
            role=role,
            profile=self.context.profile_for(role),
            workspace=self.workspace.ensure_directory(role_relative),
            task_brief=self.workspace.for_write(task_relative),
            expected_output_paths=tuple(
                self.workspace.for_write(f"{run_relative}/{spec.relative_path}")
                for spec in specs
            ),
            preloaded_skills=self.context.preloaded_skills.get(role, ()),
            timeout_seconds=self.context.timeout_seconds,
            metadata=MappingProxyType(
                {"manifest_sha256": str(self.context.manifest_sha256)}
            ),
        )
    def _prepare_invocation(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        inputs: Mapping[str, FrozenInputPath],
        invocation_id: str,
        execution_id: str,
    ) -> tuple[RoleInvocation, dict[str, Any], str]:
        role_step = stage.step_for(role)
        missing = sorted(set(role_step.input_ids) - set(inputs))
        if missing:
            raise RoleLifecycleError(
                f"Role {role!r} is missing frozen inputs {missing}."
            )
        run_relative = f"runs/{self.context.run_id}"
        role_relative = f"{run_relative}/roles/{stage.sequence:02d}-{role}"
        task_relative = f"{run_relative}/tasks/{stage.sequence:02d}-{role}"
        role_root = self.workspace.ensure_directory(role_relative)
        task_root = self.workspace.ensure_directory(task_relative)
        task_path = self.workspace.for_write(f"{task_relative}/task.md")

        brief_plan = self._brief_plan(stage, role)
        task_text = render_task_brief(
            run_id=str(self.context.run_id),
            project_id=str(self.context.project_id),
            plan=brief_plan,
            stage=stage,
            role=role,
            input_paths={key: str(item.path) for key, item in inputs.items()},
            output_plan=self.context.output_plan,
            phase_instruction=self.context.phase_instruction,
            scientific_stance=self.context.role_souls[role],
            same_group_roles=stage.roles,
        )
        task_payload = task_text.encode("utf-8")
        _immutable_write(task_path, task_payload)

        specs = self.context.output_plan.for_stage_role(stage.stage_id, role)
        run_root = self.workspace.ensure_directory(run_relative)
        output_paths = tuple(
            self.workspace.for_write(f"{run_relative}/{spec.relative_path}")
            for spec in specs
        )
        input_bindings = [
            {
                "input_id": input_id,
                "artifact_id": inputs[input_id].artifact_id,
                "sha256": inputs[input_id].sha256,
            }
            for input_id in role_step.input_ids
        ]
        invocation_document: dict[str, Any] = {
            "format": "method-hub.role-invocation-start",
            "format_version": "1.0.0",
            "conformance_state": "vertical_slice",
            "invocation_id": invocation_id,
            "execution_id": execution_id,
            "run_id": str(self.context.run_id),
            "project_id": str(self.context.project_id),
            "manifest_sha256": str(self.context.manifest_sha256),
            "phase": self.context.plan.identity.phase_id,
            "mode": self.context.plan.mode_id,
            "sequence": stage.sequence,
            "stage_id": stage.stage_id,
            "execution": stage.execution,
            "role": role,
            "profile": self.context.profile_for(role),
            "input_bindings": input_bindings,
            "output_ids": [spec.contract_output_id for spec in specs],
            "task_brief_sha256": hashlib.sha256(task_payload).hexdigest(),
            "role_soul_sha256": hashlib.sha256(
                self.context.role_souls[role].encode("utf-8")
            ).hexdigest(),
            "preloaded_skills": list(self.context.preloaded_skills.get(role, ())),
            "timeout_seconds": self.context.timeout_seconds,
        }
        invocation_sha256 = document_sha256(invocation_document)
        invocation = RoleInvocation(
            execution_id=execution_id,
            invocation_id=invocation_id,
            run_id=str(self.context.run_id),
            project_id=str(self.context.project_id),
            phase=self.context.plan.identity.phase_id,
            mode=self.context.plan.mode_id,
            stage_id=stage.stage_id,
            role=role,
            profile=self.context.profile_for(role),
            workspace=role_root,
            task_brief=task_path,
            expected_output_paths=output_paths,
            preloaded_skills=self.context.preloaded_skills.get(role, ()),
            timeout_seconds=self.context.timeout_seconds,
            metadata=MappingProxyType(
                {
                    "manifest_sha256": str(self.context.manifest_sha256),
                    "invocation_sha256": invocation_sha256,
                    "run_root": str(run_root),
                    "expected_outputs": [
                        {
                            "contract_output_id": spec.contract_output_id,
                            "schema_file": spec.schema_file,
                            "schema_application": spec.schema_application,
                            "relative_path": spec.relative_path,
                        }
                        for spec in specs
                    ],
                }
            ),
        )
        return invocation, invocation_document, invocation_sha256

    def _brief_plan(self, stage: ResolvedStage, role: str) -> ResolvedPhasePlan:
        role_inputs = set(stage.step_for(role).input_ids)
        contexts = {
            str(item["context_id"]): item
            for item in self.context.plan.prepared_contexts
        }
        if not role_inputs or not role_inputs.issubset(contexts):
            return replace(
                self.context.plan,
                choice_values=thaw_json(self.context.plan.choice_values),
            )
        allowed_choices = {
            choice_id
            for context_id in role_inputs
            for choice_id in contexts[context_id].get("source_choice_ids", ())
        }
        choices = {
            key: thaw_json(value)
            for key, value in self.context.plan.choice_values.items()
            if key in allowed_choices
        }
        return replace(
            self.context.plan,
            choice_values=MappingProxyType(choices),
        )

    def _validate_and_close(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        invocation: RoleInvocation,
        invocation_sha256: str,
        closure_id: str,
        result: RoleExecutionResult,
    ) -> RoleClosureResult:
        status = RoleExecutionStatus(result.status)
        failure_code: str | None = None
        sealed_outputs: tuple[SealedRoleOutput, ...] = ()
        findings: list[dict[str, Any]] = []
        if self.repository.cancellation_requested(str(self.context.run_id)):
            status = RoleExecutionStatus.CANCELLED
        elif status is RoleExecutionStatus.SUCCEEDED:
            validation = validate_role_outputs(
                schema_catalog=self.schemas,
                run_root=self.workspace.for_read(f"runs/{self.context.run_id}"),
                output_plan=self.context.output_plan,
                stage=stage,
                role=role,
            )
            findings = [item.to_dict() for item in validation.findings]
            if not validation.passed:
                status = RoleExecutionStatus.FAILED
                failure_code = "output.structural_validation_failed"
            sealed_outputs = tuple(
                self._seal_output(item.spec, item.path, item.sha256)
                for item in validation.outputs
            )
        elif status is RoleExecutionStatus.FAILED:
            failure_code = "executor.role_failed"

        if status is RoleExecutionStatus.CANCELLED:
            failure_code = None
        closed_at = isoformat_utc(utc_now())
        closure_document: dict[str, Any] = {
            "format": "method-hub.role-invocation-closure",
            "format_version": "1.0.0",
            "conformance_state": "vertical_slice",
            "closure_id": closure_id,
            "execution_id": invocation.execution_id,
            "invocation_id": invocation.invocation_id,
            "invocation_sha256": invocation_sha256,
            "run_id": invocation.run_id,
            "project_id": invocation.project_id,
            "phase": invocation.phase,
            "mode": invocation.mode,
            "sequence": stage.sequence,
            "stage_id": stage.stage_id,
            "role": role,
            "status": status.value,
            "external_execution_id": result.external_execution_id,
            "exit_code": result.exit_code,
            "summary": result.summary,
            "diagnostic_text": result.diagnostic_text,
            "failure_code": failure_code,
            "outputs": [self._output_document(item) for item in sealed_outputs],
            "findings": findings,
            "closed_at": closed_at,
        }
        closure_sha256 = document_sha256(closure_document)
        closure_document["closure_sha256"] = closure_sha256
        closure_bytes = canonicalize(closure_document)
        stored = self.artifacts.put_bytes(
            closure_bytes, expected_sha256=hashlib.sha256(closure_bytes).hexdigest()
        )
        closure_artifact_id = _closure_artifact_id(closure_id)
        self.repository.record_artifact(
            closure_artifact_id,
            str(self.context.project_id),
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "kind": "role_invocation_closure",
                "run_id": str(self.context.run_id),
                "closure_id": closure_id,
                "storage_relative_path": stored.relative_path,
            },
        )
        try:
            self.repository.close_execution(
                invocation.execution_id,
                closure_id,
                closure_sha256,
                closure_document,
            )
        except RepositoryConflictError:
            recovered = self._load_closure(
                stage=stage,
                role=role,
                invocation_id=invocation.invocation_id,
                execution_id=invocation.execution_id,
                closure_id=closure_id,
            )
            if recovered is not None:
                return recovered
            raise
        return RoleClosureResult(
            role=role,
            status=status,
            execution_id=invocation.execution_id,
            invocation_id=invocation.invocation_id,
            invocation_sha256=invocation_sha256,
            closure_id=closure_id,
            closure_sha256=closure_sha256,
            closure_artifact_id=closure_artifact_id,
            outputs=sealed_outputs,
            closed_at=closed_at,
            failure_code=failure_code,
        )

    def _seal_output(
        self, spec: OutputSpec, path: Path, expected_sha256: str
    ) -> SealedRoleOutput:
        payload = path.read_bytes()
        stored = self.artifacts.put_bytes(payload, expected_sha256=expected_sha256)
        artifact_id = _output_artifact_id(
            self.context, spec, str(stored.sha256)
        )
        self.repository.record_artifact(
            artifact_id,
            str(self.context.project_id),
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "kind": "validated_role_output",
                "run_id": str(self.context.run_id),
                "contract_output_id": spec.contract_output_id,
                "output_id": spec.output_id,
                "storage_relative_path": stored.relative_path,
            },
        )
        return SealedRoleOutput(
            contract_output_id=spec.contract_output_id,
            output_id=spec.output_id,
            artifact_id=artifact_id,
            sha256=str(stored.sha256),
            size=stored.size,
            media_type="application/json",
            storage_relative_path=stored.relative_path,
        )

    def _load_closure(
        self,
        *,
        stage: ResolvedStage,
        role: str,
        invocation_id: str,
        execution_id: str,
        closure_id: str,
    ) -> RoleClosureResult | None:
        with self.repository.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM role_execution_closures WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        if row is None:
            return None
        document = loads_json(
            row["payload_json"], source=f"repository closure {closure_id}"
        )
        expected = {
            "closure_id": closure_id,
            "execution_id": execution_id,
            "invocation_id": invocation_id,
            "run_id": str(self.context.run_id),
            "project_id": str(self.context.project_id),
            "phase": self.context.plan.identity.phase_id,
            "mode": self.context.plan.mode_id,
            "sequence": stage.sequence,
            "stage_id": stage.stage_id,
            "role": role,
        }
        if type(document) is not dict or any(
            document.get(key) != value for key, value in expected.items()
        ):
            raise RoleLifecycleError(
                f"Stored closure {closure_id} does not match its frozen invocation."
            )
        closure_sha256 = document.get("closure_sha256")
        unhashed = dict(document)
        unhashed.pop("closure_sha256", None)
        if (
            closure_sha256 != row["closure_sha256"]
            or document_sha256(unhashed) != closure_sha256
        ):
            raise RoleLifecycleError(f"Stored closure {closure_id} has an invalid digest.")
        with self.repository.database.connect() as connection:
            intent_row = connection.execute(
                "SELECT * FROM role_execution_intents WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
        if (
            intent_row is None
            or intent_row["invocation_id"] != invocation_id
            or intent_row["invocation_sha256"] != document.get("invocation_sha256")
        ):
            raise RoleLifecycleError(
                f"Stored closure {closure_id} is not bound to its execution intent."
            )
        status = RoleExecutionStatus(document["status"])
        outputs = tuple(self._parse_output(item) for item in document.get("outputs", ()))
        expected_specs = {
            spec.contract_output_id: spec
            for spec in self.context.output_plan.for_stage_role(stage.stage_id, role)
        }
        expected_outputs = set(expected_specs)
        actual_outputs = {item.contract_output_id for item in outputs}
        if len(actual_outputs) != len(outputs) or not actual_outputs.issubset(expected_outputs):
            raise RoleLifecycleError(
                f"Closure {closure_id} contains undeclared or duplicate outputs."
            )
        if status is RoleExecutionStatus.SUCCEEDED and actual_outputs != expected_outputs:
            raise RoleLifecycleError(
                f"Successful closure {closure_id} does not bind every declared output."
            )
        for output in outputs:
            spec = expected_specs[output.contract_output_id]
            if output.output_id != spec.output_id or output.media_type != "application/json":
                raise RoleLifecycleError(
                    f"Closure {closure_id} changes the contract binding for "
                    f"{output.contract_output_id!r}."
                )
            stored_output = self.artifacts.verify(output.sha256)
            if stored_output.relative_path != output.storage_relative_path:
                raise RoleLifecycleError(
                    f"Closure {closure_id} cites the wrong storage path for "
                    f"{output.contract_output_id!r}."
                )
            with self.repository.database.connect() as connection:
                output_row = connection.execute(
                    "SELECT * FROM artifacts WHERE artifact_id = ?",
                    (output.artifact_id,),
                ).fetchone()
            if (
                output_row is None
                or output_row["project_id"] != str(self.context.project_id)
                or output_row["sha256"] != output.sha256
                or output_row["size"] != output.size
            ):
                raise RoleLifecycleError(
                    f"Closure {closure_id} has an inconsistent artifact record for "
                    f"{output.contract_output_id!r}."
                )
        closure_artifact_id = _closure_artifact_id(closure_id)
        with self.repository.database.connect() as connection:
            artifact_row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (closure_artifact_id,)
            ).fetchone()
        if artifact_row is None:
            raise RoleLifecycleError(f"Closure artifact {closure_artifact_id} is missing.")
        closure_bytes = canonicalize(document)
        closure_artifact_sha256 = hashlib.sha256(closure_bytes).hexdigest()
        if (
            artifact_row["project_id"] != str(self.context.project_id)
            or artifact_row["sha256"] != closure_artifact_sha256
        ):
            raise RoleLifecycleError(
                f"Closure artifact {closure_artifact_id} does not bind the closure bytes."
            )
        self.artifacts.verify(closure_artifact_sha256)
        return RoleClosureResult(
            role=role,
            status=status,
            execution_id=execution_id,
            invocation_id=invocation_id,
            invocation_sha256=str(document["invocation_sha256"]),
            closure_id=closure_id,
            closure_sha256=str(closure_sha256),
            closure_artifact_id=closure_artifact_id,
            outputs=outputs,
            closed_at=str(document["closed_at"]),
            failure_code=document.get("failure_code"),
            reconciled=True,
        )

    def _acknowledgement(self, execution_id: str) -> Any | None:
        with self.repository.database.connect() as connection:
            return connection.execute(
                """
                SELECT * FROM role_execution_acknowledgements
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()

    @staticmethod
    def _output_document(output: SealedRoleOutput) -> dict[str, Any]:
        return {
            "contract_output_id": output.contract_output_id,
            "output_id": output.output_id,
            "artifact_id": output.artifact_id,
            "sha256": output.sha256,
            "size": output.size,
            "media_type": output.media_type,
            "storage_relative_path": output.storage_relative_path,
        }

    @staticmethod
    def _parse_output(document: Any) -> SealedRoleOutput:
        if type(document) is not dict:
            raise RoleLifecycleError("Stored closure output must be a JSON object.")
        try:
            size = document["size"]
            if type(size) is not int or size < 0:
                raise TypeError("size must be a nonnegative integer")
            return SealedRoleOutput(
                contract_output_id=str(document["contract_output_id"]),
                output_id=str(document["output_id"]),
                artifact_id=str(document["artifact_id"]),
                sha256=str(document["sha256"]),
                size=size,
                media_type=str(document["media_type"]),
                storage_relative_path=str(document["storage_relative_path"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise RoleLifecycleError("Stored closure output is malformed.") from error


__all__ = [
    "FrozenInputPath",
    "RoleClosureResult",
    "RoleExecutionPending",
    "RoleLifecycleError",
    "RoleLifecycleService",
    "SealedRoleOutput",
    "deterministic_id",
    "document_sha256",
]
