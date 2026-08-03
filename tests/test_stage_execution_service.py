from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from method_hub.contracts import (
    ResolvedPhasePlan,
    ResolvedRoleStep,
    ResolvedStage,
)
from method_hub.digests.jcs import canonicalize
from method_hub.domain import PhaseContractIdentity
from method_hub.executors import DeterministicFakeExecutor
from method_hub.harness.execution_context import RunExecutionContext
from method_hub.harness.outputs import build_output_plan
from method_hub.harness.preparation import PreparedRunRecipe
from method_hub.harness.stage_execution import HarnessExecutionServices
from method_hub.orchestration import StageStatus, SubmissionStatus
from method_hub.schemas import SchemaCatalog
from method_hub.storage import ArtifactStore, WorkspacePaths
from method_hub.storage.repository import HubRepository


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


class OutputPermissiveSchemas:
    """Accept fixture outputs while validating the real submission schema."""

    def __init__(self) -> None:
        self.catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")

    def validate(self, schema_ref: str, document: object):
        if schema_ref == "run-submission.schema.json":
            return self.catalog.validate(schema_ref, document)
        return ()


def _output(output_id: str, producer: str) -> dict[str, object]:
    return {
        "output_id": output_id,
        "output_kind": "record",
        "producer": producer,
        "schema_application": "object",
        "schema_uri": "statement.schema.json",
        "required": True,
    }


def _plan() -> ResolvedPhasePlan:
    first = ResolvedStage(
        sequence=1,
        stage_id="p4.parallel_check",
        execution="parallel",
        objective="Develop independent theoretical and empirical assessments.",
        role_steps=(
            ResolvedRoleStep(
                "theorist", ("p4.method",), ("p4.theory_note",)
            ),
            ResolvedRoleStep(
                "data_analyst", ("p4.method",), ("p4.empirical_note",)
            ),
        ),
        writes=("p4.theory_note", "p4.empirical_note"),
        handoff_required=True,
        isolation_rule="same_frozen_basis",
    )
    second = ResolvedStage(
        sequence=2,
        stage_id="p4.lead_summary",
        execution="serial",
        objective="Reconcile the theoretical and empirical assessments.",
        role_steps=(
            ResolvedRoleStep(
                "research_lead",
                ("p4.method", "p4.theory_note", "p4.empirical_note"),
                ("p4.decision",),
            ),
        ),
        writes=("p4.decision",),
        handoff_required=False,
        isolation_rule=None,
    )
    return ResolvedPhasePlan(
        identity=PhaseContractIdentity("P4", "1.0.0", "a" * 64),
        mode_id="p4.preliminary",
        choice_values={"p4.instructions": "Use the exact selected method."},
        context_policy="current_only",
        stages=(first, second),
        output_contracts=(
            _output("p4.theory_note", "theorist"),
            _output("p4.empirical_note", "data_analyst"),
            _output("p4.decision", "research_lead"),
        ),
        prepared_contexts=(),
        validation_rules=(),
        publication_bindings=(),
        promotion={},
    )


def _digest(character: str) -> str:
    return character * 64


class Fixture:
    def __init__(self, tmp_path: Path, *, fail_roles: frozenset[str] = frozenset()):
        self.workspace = WorkspacePaths(tmp_path / "workspace", create=True)
        self.artifacts = ArtifactStore(self.workspace)
        self.repository = HubRepository(self.workspace.root / "hub.sqlite3")
        self.repository.initialize()
        self.repository.create_project("project.stage_test", {"name": "Stage test"})
        self.repository.record_raw_command(
            "request.run", "project.stage_test", _digest("b"), {"request": "run"}
        )
        self.repository.seal_command(
            "command.run",
            "project.stage_test",
            "request.run",
            "run-once",
            _digest("c"),
            {"command": "run"},
        )
        self.repository.create_run(
            "run.stage_test",
            "project.stage_test",
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
            "project.stage_test",
            str(method.sha256),
            method.size,
            "application/json",
            f"artifact://sha256/{method.sha256}",
            {"kind": "method", "storage_relative_path": method.relative_path},
        )
        self.plan = _plan()
        self.output_plan = build_output_plan(self.plan)
        recipe_document = {
            "format": "method-hub.prepared-run-recipe",
            "format_version": "1.0.0",
            "conformance_state": "vertical_slice",
            "run_id": "run.stage_test",
            "project_id": "project.stage_test",
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
                "resource_constraints": {
                    "wall_time_limit_seconds": 600,
                    "network_policy": "none",
                },
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
            "prepared_at": "2026-08-02T12:00:00Z",
        }
        recipe_sha256 = hashlib.sha256(canonicalize(recipe_document)).hexdigest()
        self.recipe = PreparedRunRecipe(recipe_document, recipe_sha256)
        self.repository.freeze_manifest(
            "run.stage_test", recipe_sha256, recipe_document
        )
        self.context = RunExecutionContext(
            run_id="run.stage_test",
            project_id="project.stage_test",
            manifest_sha256=recipe_sha256,
            recipe=self.recipe,
            plan=self.plan,
            output_plan=self.output_plan,
            phase_instruction="Use the exact selected method.",
            role_souls={
                "theorist": "Check definitions, assumptions, and mathematical validity.",
                "data_analyst": "Check estimands, computation, and empirical validity.",
                "research_lead": "Reconcile the evidence and state the decision basis.",
            },
            preloaded_skills={
                "theorist": ("stat-paper-writing",),
                "data_analyst": ("stat-paper-writing",),
                "research_lead": ("stat-paper-writing",),
            },
        )
        self.executor = DeterministicFakeExecutor(fail_roles=fail_roles)
        self.schemas = OutputPermissiveSchemas()
        self.services = self.new_services(self.executor)

    def new_services(self, executor: DeterministicFakeExecutor):
        return HarnessExecutionServices(
            context=self.context,
            repository=self.repository,
            executor=executor,
            schemas=self.schemas,
            artifacts=self.artifacts,
            workspace=self.workspace,
        )

    def execute_stage(self, offset: int, *, services=None):
        target = services or self.services
        return asyncio.run(
            target.execute_or_reconcile_stage(
                run_id=self.context.run_id,
                manifest_sha256=self.context.manifest_sha256,
                stage=self.plan.stages[offset],
            )
        )


def test_parallel_stage_uses_one_frozen_basis_and_submission_is_immutable(
    tmp_path: Path,
) -> None:
    fixture = Fixture(tmp_path)
    parallel = fixture.execute_stage(0)
    assert parallel.status is StageStatus.SUCCEEDED
    assert len(parallel.invocation_closure_ids) == 2
    assert {item.role for item in fixture.executor.invocations} == {
        "theorist",
        "data_analyst",
    }

    briefs = {
        item.role: item.task_brief.read_text(encoding="utf-8")
        for item in fixture.executor.invocations
    }
    assert "p4.empirical_note" not in briefs["theorist"]
    assert "p4.theory_note" not in briefs["data_analyst"]
    with fixture.repository.database.connect() as connection:
        intents = connection.execute(
            "SELECT payload_json FROM role_execution_intents ORDER BY execution_id"
        ).fetchall()
    assert len(intents) == 2
    assert all('"input_id":"p4.method"' in row["payload_json"] for row in intents)

    lead = fixture.execute_stage(1)
    assert lead.status is StageStatus.SUCCEEDED
    lead_invocation = fixture.executor.invocations[-1]
    lead_brief = lead_invocation.task_brief.read_text(encoding="utf-8")
    assert "artifacts\\objects" in lead_brief or "artifacts/objects" in lead_brief

    submission = asyncio.run(
        fixture.services.submit_or_reconcile(
            run_id=fixture.context.run_id,
            manifest_sha256=fixture.context.manifest_sha256,
            stage_outcomes=(parallel, lead),
        )
    )
    assert submission.status is SubmissionStatus.SUBMITTED
    assert submission.reference is not None
    stored = fixture.repository.get_submission("run.stage_test")
    assert stored is not None
    assert stored["submission_sha256"] == str(submission.reference.submission_sha256)
    assert fixture.repository.get_run("run.stage_test")["status"] == "submitted"


def test_failed_role_closes_once_without_scientific_retry(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path, fail_roles=frozenset({"theorist"}))
    first = fixture.execute_stage(0)
    second = fixture.execute_stage(0)

    assert first.status is StageStatus.FAILED
    assert first.failure_code == "executor.role_failed"
    assert second.status is StageStatus.FAILED
    assert second.reconciled is True
    assert len(fixture.executor.invocations) == 2


def test_cancellation_fence_prevents_new_role_launch(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    fixture.repository.record_raw_command(
        "request.cancel", "project.stage_test", _digest("e"), {"request": "cancel"}
    )
    fixture.repository.seal_command(
        "command.cancel",
        "project.stage_test",
        "request.cancel",
        "cancel-once",
        _digest("f"),
        {"command": "cancel"},
    )
    cancelled = fixture.repository.request_cancellation(
        "run.stage_test",
        "command.cancel",
        "running",
        1,
        {"state": "cancellation_requested"},
        "event.cancel",
        _digest("1"),
        {"to": "cancellation_requested"},
    )
    outcome = fixture.execute_stage(0)

    assert cancelled.applied is True
    assert outcome.status is StageStatus.CANCELLED
    assert fixture.executor.invocations == []


def test_new_service_reconciles_closures_without_relaunch(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    first = fixture.execute_stage(0)
    replacement_executor = DeterministicFakeExecutor()
    recovered_service = fixture.new_services(replacement_executor)
    recovered = fixture.execute_stage(0, services=recovered_service)

    assert first.status is StageStatus.SUCCEEDED
    assert recovered.status is StageStatus.SUCCEEDED
    assert recovered.reconciled is True
    assert recovered.invocation_closure_ids == first.invocation_closure_ids
    assert replacement_executor.invocations == []


def test_invalid_role_output_becomes_structural_failure(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)

    class RejectOutputs(OutputPermissiveSchemas):
        def validate(self, schema_ref: str, document: object):
            if schema_ref == "run-submission.schema.json":
                return super().validate(schema_ref, document)
            return self.catalog.validate("statement.schema.json", document)

    fixture.schemas = RejectOutputs()
    fixture.services = fixture.new_services(fixture.executor)
    outcome = fixture.execute_stage(0)

    assert outcome.status is StageStatus.FAILED
    assert outcome.failure_code == "output.structural_validation_failed"
