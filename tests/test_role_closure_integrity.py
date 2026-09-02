"""Closure integrity: optional outputs on reload (ISS-4) and fail-closed raw
preservation (ISS-5).

ISS-4: a SUCCEEDED closure that legitimately omits an OPTIONAL output must
reload cleanly during recovery.  Before the fix, ``_load_closure`` required
strict equality with every declared output, so the first P5 run omitting an
optional output (for example ``p5.assembly_report``) would have become
unreloadable.

ISS-5: when raw-output preservation fails on the SUCCEEDED path, the closure
must fail closed (``output.raw_preservation_failed``): without the sealed raw
snapshot the harness cannot prove which bytes the agent wrote.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
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
    RoleExecutionResult,
    RoleExecutionStatus,
)
from model_forge.harness.execution_context import RunExecutionContext
from model_forge.harness.outputs import build_output_plan
from model_forge.harness.preparation import PreparedRunRecipe
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
        method = self.artifacts.put_bytes(method_payload)
        self.repository.record_artifact(
            "artifact.method",
            "project.closure_test",
            str(method.sha256),
            method.size,
            "application/json",
            f"artifact://sha256/{method.sha256}",
            {"kind": "method", "storage_relative_path": method.relative_path},
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
                        "uri": f"artifact://sha256/{method.sha256}",
                        "sha256": str(method.sha256),
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
        self.services = self.new_services(executor)

    def new_services(self, executor) -> HarnessExecutionServices:
        return HarnessExecutionServices(
            context=self.context,
            repository=self.repository,
            executor=executor,
            schemas=self.schemas,
            artifacts=self.artifacts,
            workspace=self.workspace,
        )

    def execute(self, *, services=None) -> object:
        target = services or self.services
        return asyncio.run(
            target.execute_or_reconcile_stage(
                run_id=self.context.run_id,
                manifest_sha256=self.context.manifest_sha256,
                stage=self.plan.stages[0],
            )
        )


class _SkipOptionalExecutor(DeterministicFakeExecutor):
    """Writes every expected output EXCEPT the optional one."""

    async def execute(self, invocation, observer) -> RoleExecutionResult:
        # RoleInvocation is frozen: derive a filtered copy instead of
        # mutating the invocation in place.
        invocation = dataclasses.replace(
            invocation,
            expected_output_paths=tuple(
                path
                for path in invocation.expected_output_paths
                if "optional" not in path.name
            ),
        )
        return await super().execute(invocation, observer)


def test_succeeded_closure_without_optional_output_reloads(tmp_path: Path) -> None:
    """ISS-4: a closure omitting an optional output must reconcile cleanly."""
    fixture = _Fixture(tmp_path, _SkipOptionalExecutor())
    first = fixture.execute()
    assert first.status is StageStatus.SUCCEEDED

    # A fresh service (simulating a restart) must reload the closure without
    # relaunching the role and without raising.
    replacement = _SkipOptionalExecutor()
    recovered = fixture.execute(services=fixture.new_services(replacement))
    assert recovered.status is StageStatus.SUCCEEDED
    assert recovered.reconciled is True
    assert recovered.invocation_closure_ids == first.invocation_closure_ids
    assert replacement.invocations == []


def test_raw_preservation_failure_fails_closed(tmp_path: Path, monkeypatch) -> None:
    """ISS-5: preservation failure on the success path fails the closure."""

    def _boom(**kwargs):
        raise OSError("artifact store unavailable")

    monkeypatch.setattr(
        "model_forge.harness.output_adapters.preserve_raw_output", _boom
    )
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor())
    outcome = fixture.execute()
    assert outcome.status is StageStatus.FAILED
    assert outcome.failure_code == "output.raw_preservation_failed"
