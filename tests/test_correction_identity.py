"""Correction identity families (K-1a2): identity_suffix on the execution
context and family-aware closure loading in ``load_existing``.

A correction re-invocation under the same run must not collide with the
failed base closure (closures are immutable), so a non-empty
``identity_suffix`` extends the deterministic identity basis.
``RoleLifecycleService.load_existing`` walks the run's correction attempts
newest-first and returns the first SUCCEEDED correction closure.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
from pathlib import Path

from model_forge.contracts import (
    ResolvedPhasePlan,
    ResolvedRoleStep,
    ResolvedStage,
)
from model_forge.digests.jcs import canonicalize
from model_forge.domain import PhaseContractIdentity
from model_forge.executors import (
    DeterministicFakeExecutor,
    RoleExecutionStatus,
)
from model_forge.harness.execution_context import RunExecutionContext
from model_forge.harness.execution_records import FrozenInputPath, role_identity
from model_forge.harness.outputs import build_output_plan
from model_forge.harness.preparation import PreparedRunRecipe
from model_forge.harness.role_execution import RoleLifecycleService
from model_forge.harness.stage_execution import HarnessExecutionServices
from model_forge.orchestration import StageStatus
from model_forge.schemas import SchemaCatalog
from model_forge.storage import ArtifactStore, WorkspacePaths
from model_forge.storage.repository import HubRepository

ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


class _PermissiveSchemas:
    def __init__(self) -> None:
        self.catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
        self.directory = self.catalog.directory

    def validate(self, schema_ref: str, document: object):
        return ()


def _output(output_id: str, producer: str, *, required: bool) -> dict[str, object]:
    return {
        "output_id": output_id,
        "output_kind": "record",
        "producer": producer,
        "schema_application": "object",
        "schema_uri": "statement.schema.json",
        "required": required,
    }


def _plan() -> ResolvedPhasePlan:
    stage = ResolvedStage(
        sequence=1,
        stage_id="p4.solo",
        execution="serial",
        objective="Produce a decision with an optional note.",
        role_steps=(
            ResolvedRoleStep(
                "research_lead",
                ("p4.method",),
                ("p4.decision", "p4.optional_note"),
            ),
        ),
        writes=("p4.decision", "p4.optional_note"),
        handoff_required=False,
        isolation_rule=None,
    )
    return ResolvedPhasePlan(
        identity=PhaseContractIdentity("P4", "1.0.0", "a" * 64),
        mode_id="p4.preliminary",
        choice_values={"p4.instructions": "Use the exact selected method."},
        context_policy="current_only",
        stages=(stage,),
        output_contracts=(
            _output("p4.decision", "research_lead", required=True),
            _output("p4.optional_note", "research_lead", required=False),
        ),
        prepared_contexts=(),
        validation_rules=(),
        publication_bindings=(),
        promotion={},
    )


def _digest(character: str) -> str:
    return character * 64


class _Fixture:
    def __init__(self, tmp_path: Path, executor) -> None:
        self.workspace = WorkspacePaths(tmp_path / "workspace", create=True)
        self.artifacts = ArtifactStore(self.workspace)
        self.repository = HubRepository(self.workspace.root / "hub.sqlite3")
        self.repository.initialize()
        self.repository.create_project("project.closure_test", {"name": "Closure test"})
        self.repository.record_raw_command(
            "request.run", "project.closure_test", _digest("b"), {"request": "run"}
        )
        self.repository.seal_command(
            "command.run",
            "project.closure_test",
            "request.run",
            "run-once",
            _digest("c"),
            {"command": "run"},
        )
        self.repository.create_run(
            "run.closure_test",
            "project.closure_test",
            "command.run",
            "running",
            {"state": "running"},
            "event.run_created",
            _digest("d"),
            {"to": "running"},
        )
        method_payload = b'{"method":"fixture","version":1}\n'
        self.method = self.artifacts.put_bytes(method_payload)
        self.repository.record_artifact(
            "artifact.method",
            "project.closure_test",
            str(self.method.sha256),
            self.method.size,
            "application/json",
            f"artifact://sha256/{self.method.sha256}",
            {"kind": "method", "storage_relative_path": self.method.relative_path},
        )
        self.plan = _plan()
        self.output_plan = build_output_plan(self.plan)
        recipe_document = {
            "format": "model-forge.prepared-run-recipe",
            "format_version": "1.0.0",
            "run_id": "run.closure_test",
            "project_id": "project.closure_test",
            "command_id": "command.run",
            "command_sha256": _digest("c"),
            "command_idempotency_key": "run-once",
            "phase": "P4",
            "phase_contract_version": "1.0.0",
            "phase_contract_sha256": "a" * 64,
            "mode": "p4.preliminary",
            "user_request": {
                "choice_values": {"p4.instructions": "Use the exact selected method."},
                "context_policy": "current_only",
            },
            "frozen_inputs": [
                {
                    "contract_input_id": "p4.method",
                    "record_id": "record.method",
                    "generation_id": "generation.method",
                    "generation_number": 1,
                    "record_type": "method",
                    "logical_slot": "method/current",
                    "method_identity": None,
                    "artifact": {
                        "artifact_id": "artifact.method",
                        "uri": f"artifact://sha256/{self.method.sha256}",
                        "sha256": str(self.method.sha256),
                        "media_type": "application/json",
                    },
                    "purpose": "Freeze the method calculation.",
                    "selected_by": "phase_contract",
                }
            ],
            "selected_history": [],
            "prepared_contexts": [],
            "stages": [
                {
                    "sequence": stage.sequence,
                    "stage_id": stage.stage_id,
                    "execution": stage.execution,
                    "roles": [
                        {
                            "role": step.role,
                            "profile": f"profile.{step.role}",
                            "input_ids": list(step.input_ids),
                            "output_ids": list(step.output_ids),
                        }
                        for step in stage.role_steps
                    ],
                }
                for stage in self.plan.stages
            ],
            "expected_outputs": [],
            "validation_rules": [],
            "publication_bindings": [],
            "promotion": {},
            "orchestration_binding": {},
            "prepared_at": "2026-08-15T12:00:00Z",
        }
        recipe_sha256 = hashlib.sha256(canonicalize(recipe_document)).hexdigest()
        self.recipe = PreparedRunRecipe(recipe_document, recipe_sha256)
        self.repository.freeze_manifest("run.closure_test", recipe_sha256, recipe_document)
        self.context = RunExecutionContext(
            run_id="run.closure_test",
            project_id="project.closure_test",
            manifest_sha256=recipe_sha256,
            recipe=self.recipe,
            plan=self.plan,
            output_plan=self.output_plan,
            phase_instruction="Use the exact selected method.",
            role_souls={"research_lead": "State the decision basis."},
            preloaded_skills={"research_lead": ()},
        )
        self.executor = executor
        self.schemas = _PermissiveSchemas()
        self.services = HarnessExecutionServices(
            context=self.context,
            repository=self.repository,
            executor=executor,
            schemas=self.schemas,
            artifacts=self.artifacts,
            workspace=self.workspace,
        )

    @property
    def stage(self) -> ResolvedStage:
        return self.plan.stages[0]

    def role_inputs(self) -> dict[str, FrozenInputPath]:
        stored = self.artifacts.verify(str(self.method.sha256))
        return {
            "p4.method": FrozenInputPath(
                input_id="p4.method",
                artifact_id="artifact.method",
                sha256=str(self.method.sha256),
                path=self.workspace.for_read(stored.relative_path),
                media_type="application/json",
            )
        }

    def lifecycle(
        self, context: RunExecutionContext, executor
    ) -> RoleLifecycleService:
        return RoleLifecycleService(
            context=context,
            repository=self.repository,
            executor=executor,
            schemas=self.schemas,
            artifacts=self.artifacts,
            workspace=self.workspace,
        )

    def execute_stage(self) -> object:
        return asyncio.run(
            self.services.execute_or_reconcile_stage(
                run_id=self.context.run_id,
                manifest_sha256=self.context.manifest_sha256,
                stage=self.stage,
            )
        )


def test_empty_suffix_leaves_identity_byte_identical(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor())
    base = role_identity(fixture.context, fixture.stage, "research_lead")
    explicit_empty = dataclasses.replace(fixture.context, identity_suffix="")
    again = role_identity(explicit_empty, fixture.stage, "research_lead")
    assert again == base


def test_nonempty_suffix_changes_all_ids_deterministically(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor())
    base = role_identity(fixture.context, fixture.stage, "research_lead")
    corrected = dataclasses.replace(fixture.context, identity_suffix="correction.cmd_1")
    first = role_identity(corrected, fixture.stage, "research_lead")
    second = role_identity(corrected, fixture.stage, "research_lead")
    assert first == second
    assert first != base
    for base_id, corrected_id in zip(base, first):
        assert base_id != corrected_id
        assert base_id.split(".")[0] == corrected_id.split(".")[0]
    other = dataclasses.replace(fixture.context, identity_suffix="correction.cmd_2")
    assert role_identity(other, fixture.stage, "research_lead") != first


def test_load_existing_returns_succeeded_correction_closure(tmp_path: Path) -> None:
    failing = DeterministicFakeExecutor(fail_roles=frozenset({"research_lead"}))
    fixture = _Fixture(tmp_path, failing)
    outcome = fixture.execute_stage()
    assert outcome.status is StageStatus.FAILED

    fixture.repository.record_validation_attempt(
        "attempt.1",
        "run.closure_test",
        1,
        "policy.v1",
        '{"passed": false}',
        _digest("e"),
        correction_command_id="cmd_1",
    )

    corrected_context = dataclasses.replace(
        fixture.context, identity_suffix="correction.cmd_1"
    )
    correction = fixture.lifecycle(corrected_context, DeterministicFakeExecutor())
    corrected_closure = asyncio.run(
        correction.execute_or_reconcile(
            stage=fixture.stage,
            role="research_lead",
            inputs=fixture.role_inputs(),
        )
    )
    assert corrected_closure.status is RoleExecutionStatus.SUCCEEDED

    loaded = fixture.services.roles.load_existing(
        stage=fixture.stage, role="research_lead"
    )
    assert loaded is not None
    assert loaded.status is RoleExecutionStatus.SUCCEEDED
    assert loaded.execution_id == corrected_closure.execution_id
    assert loaded.closure_id == corrected_closure.closure_id


def test_load_existing_without_corrections_returns_failed_base(tmp_path: Path) -> None:
    failing = DeterministicFakeExecutor(fail_roles=frozenset({"research_lead"}))
    fixture = _Fixture(tmp_path, failing)
    outcome = fixture.execute_stage()
    assert outcome.status is StageStatus.FAILED

    loaded = fixture.services.roles.load_existing(
        stage=fixture.stage, role="research_lead"
    )
    assert loaded is not None
    assert loaded.status is RoleExecutionStatus.FAILED
