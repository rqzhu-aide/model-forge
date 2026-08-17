"""K-1a3: revalidation core for the correction command path.

The fixture mirrors tests/test_role_closure_integrity.py's ``_Fixture``
stack (repository / artifact store / recipe / fake executor), but resolves a
REAL P1 plan through the real ``SpecificationPackage`` so that
``revalidate_closure_outputs`` re-derives the same plan from the frozen
recipe, and revalidates against the REAL schema catalog.  Closures are
sealed under a permissive catalog so both schema-valid and schema-invalid
output bytes can be sealed as SUCCEEDED.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from method_hub.application.correction_execution import revalidate_closure_outputs
from method_hub.digests.jcs import canonicalize
from method_hub.executors import DeterministicFakeExecutor
from method_hub.harness.execution_context import RunExecutionContext
from method_hub.harness.outputs import build_output_plan
from method_hub.harness.preparation import PreparedRunRecipe
from method_hub.harness.stage_execution import HarnessExecutionServices
from method_hub.json_io import loads_json
from method_hub.orchestration import StageStatus
from method_hub.schemas import SchemaCatalog
from method_hub.specification import SpecificationPackage
from method_hub.storage import ArtifactStore, WorkspacePaths
from method_hub.storage.repository import HubRepository

ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "golden"


class _PermissiveSchemas:
    def __init__(self) -> None:
        self.catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")

    def validate(self, schema_ref: str, document: object):
        return ()


def _digest(character: str) -> str:
    return character * 64


class _Fixture:
    def __init__(self, tmp_path: Path, executor) -> None:
        self.specification = SpecificationPackage.load(ARCHITECTURE)
        self.identity = self.specification.phases.identity("P1")
        self.choice_values = {
            "p1.scope": "broad_update",
            "p1.instructions": "Update the literature basis.",
            "p1.selected_history": [],
        }
        self.plan = self.specification.resolve_phase(
            self.identity,
            "p1.literature_update",
            self.choice_values,
            "current_only",
        )
        self.stage = self.plan.stages[0]  # p1.discovery (parallel, 3 roles)
        self.output_plan = build_output_plan(self.plan)
        self.workspace = WorkspacePaths(tmp_path / "workspace", create=True)
        self.artifacts = ArtifactStore(self.workspace)
        self.repository = HubRepository(self.workspace.root / "hub.sqlite3")
        self.repository.initialize()
        self.repository.create_project(
            "project.revalidate_test", {"name": "Revalidation test"}
        )
        self.repository.record_raw_command(
            "request.run", "project.revalidate_test", _digest("b"), {"request": "run"}
        )
        self.repository.seal_command(
            "command.run",
            "project.revalidate_test",
            "request.run",
            "run-once",
            _digest("c"),
            {"command": "run"},
        )
        self.repository.create_run(
            "run.revalidate_test",
            "project.revalidate_test",
            "command.run",
            "running",
            {"state": "running"},
            "event.run_created",
            _digest("d"),
            {"to": "running"},
        )
        frozen_inputs = []
        input_ids = sorted(
            {input_id for step in self.stage.role_steps for input_id in step.input_ids}
        )
        for input_id in input_ids:
            payload = (
                json.dumps({"input_id": input_id, "note": "frozen basis"}) + "\n"
            ).encode("utf-8")
            stored = self.artifacts.put_bytes(payload)
            artifact_id = f"artifact.{input_id}"
            self.repository.record_artifact(
                artifact_id,
                "project.revalidate_test",
                str(stored.sha256),
                stored.size,
                "application/json",
                f"artifact://sha256/{stored.sha256}",
                {
                    "kind": "input",
                    "storage_relative_path": stored.relative_path,
                },
            )
            frozen_inputs.append(
                {
                    "contract_input_id": input_id,
                    "record_id": f"record.{input_id}",
                    "generation_id": f"generation.{input_id}",
                    "generation_number": 1,
                    "record_type": input_id.split(".")[-1],
                    "logical_slot": f"{input_id.split('.')[-1]}/current",
                    "method_identity": None,
                    "artifact": {
                        "artifact_id": artifact_id,
                        "uri": f"artifact://sha256/{stored.sha256}",
                        "sha256": str(stored.sha256),
                        "media_type": "application/json",
                    },
                    "purpose": "Freeze the discovery basis.",
                    "selected_by": "phase_contract",
                }
            )
        recipe_document = {
            "format": "method-hub.prepared-run-recipe",
            "format_version": "1.0.0",
            "run_id": "run.revalidate_test",
            "project_id": "project.revalidate_test",
            "command_id": "command.run",
            "command_sha256": _digest("c"),
            "command_idempotency_key": "run-once",
            "phase": "P1",
            "phase_contract_version": str(self.identity.contract_version),
            "phase_contract_sha256": str(self.identity.phase_contract_sha256),
            "mode": "p1.literature_update",
            "user_request": {
                "choice_values": dict(self.choice_values),
                "context_policy": "current_only",
            },
            "frozen_inputs": frozen_inputs,
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
        self.repository.freeze_manifest(
            "run.revalidate_test", recipe_sha256, recipe_document
        )
        roles = [step.role for step in self.stage.role_steps]
        self.context = RunExecutionContext(
            run_id="run.revalidate_test",
            project_id="project.revalidate_test",
            manifest_sha256=recipe_sha256,
            recipe=self.recipe,
            plan=self.plan,
            output_plan=self.output_plan,
            phase_instruction="Update the literature basis.",
            role_souls={role: "State the discovery basis." for role in roles},
            preloaded_skills={role: () for role in roles},
        )
        self.executor = executor
        self.services = HarnessExecutionServices(
            context=self.context,
            repository=self.repository,
            executor=executor,
            schemas=_PermissiveSchemas(),
            artifacts=self.artifacts,
            workspace=self.workspace,
        )

    def execute(self) -> None:
        outcome = asyncio.run(
            self.services.execute_or_reconcile_stage(
                run_id=str(self.context.run_id),
                manifest_sha256=str(self.context.manifest_sha256),
                stage=self.stage,
            )
        )
        assert outcome.status is StageStatus.SUCCEEDED

    def closure_id_for(self, role: str) -> str:
        with self.repository.database.connect() as connection:
            rows = connection.execute(
                "SELECT closure_id, payload_json FROM role_execution_closures"
            ).fetchall()
        for row in rows:
            payload = loads_json(row["payload_json"], source="closure")
            if (
                payload.get("role") == role
                and payload.get("stage_id") == self.stage.stage_id
            ):
                return str(row["closure_id"])
        raise AssertionError(f"No closure found for role {role!r}.")

    def revalidate(self, role_closure_id: str):
        return revalidate_closure_outputs(
            repository=self.repository,
            specification=self.specification,
            artifacts=self.artifacts,
            schemas=self.specification.schemas,
            run_id=str(self.context.run_id),
            role_closure_id=role_closure_id,
            correction_command_id="correction.revalidate_test",
        )


def _valid_output(invocation, offset: int) -> dict:
    return json.loads((GOLDEN / "handoff.example.json").read_text(encoding="utf-8"))


def test_revalidate_succeeded_closure_records_passed_attempt(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_valid_output))
    fixture.execute()
    closure_id = fixture.closure_id_for("theorist")

    result = fixture.revalidate(closure_id)

    assert result.attempt.passed
    assert result.attempt.correction_type == "revalidate"
    assert result.attempt.correction_command_id == "correction.revalidate_test"
    assert result.attempt.prior_attempt_id is None
    assert result.findings == ()
    row = fixture.repository.get_latest_validation_attempt("run.revalidate_test")
    assert row is not None
    assert row["attempt_id"] == result.attempt.attempt_id
    assert row["attempt_ordinal"] == 1
    assert row["correction_type"] == "revalidate"
    report = json.loads(row["report_json"])
    assert report["passed"] is True
    assert report["findings"] == []


def test_revalidate_detects_schema_drift_in_sealed_bytes(tmp_path: Path) -> None:
    # The closure is sealed under a permissive catalog; revalidation against
    # the REAL catalog must surface the schema findings.
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor())
    fixture.execute()
    closure_id = fixture.closure_id_for("theorist")

    result = fixture.revalidate(closure_id)

    assert not result.attempt.passed
    assert result.findings
    assert all(item.code.startswith("schema.") for item in result.findings)
    row = fixture.repository.get_latest_validation_attempt("run.revalidate_test")
    assert row is not None
    assert row["attempt_ordinal"] == 1
    assert row["correction_type"] == "revalidate"
    report = json.loads(row["report_json"])
    assert report["passed"] is False
    assert len(report["findings"]) == len(result.findings)


class _ByteFlippingArtifacts:
    """Return each stored artifact with one byte flipped (tamper evidence)."""

    def __init__(self, inner: ArtifactStore) -> None:
        self._inner = inner

    def read_bytes(self, sha256: str) -> bytes:
        data = bytearray(self._inner.read_bytes(sha256))
        data[0] ^= 0xFF
        return bytes(data)


def test_revalidate_raises_on_digest_tamper(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_valid_output))
    fixture.execute()
    closure_id = fixture.closure_id_for("theorist")

    with pytest.raises(ValueError, match="SHA-256 digest"):
        revalidate_closure_outputs(
            repository=fixture.repository,
            specification=fixture.specification,
            artifacts=_ByteFlippingArtifacts(fixture.artifacts),
            schemas=fixture.specification.schemas,
            run_id=str(fixture.context.run_id),
            role_closure_id=closure_id,
            correction_command_id="correction.revalidate_test",
        )
    # The failed materialization must not record an attempt.
    assert fixture.repository.count_validation_attempts("run.revalidate_test") == 0


def test_revalidate_attempts_chain_by_ordinal(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_valid_output))
    fixture.execute()
    closure_id = fixture.closure_id_for("theorist")

    first = fixture.revalidate(closure_id)
    second = fixture.revalidate(closure_id)

    assert first.attempt.attempt_id != second.attempt.attempt_id
    assert second.attempt.prior_attempt_id == first.attempt.attempt_id
    rows = fixture.repository.list_validation_attempts("run.revalidate_test")
    assert [row["attempt_ordinal"] for row in rows] == [1, 2]
    assert rows[1]["prior_attempt_id"] == first.attempt.attempt_id
    latest = fixture.repository.get_latest_validation_attempt("run.revalidate_test")
    assert latest is not None
    assert latest["attempt_id"] == second.attempt.attempt_id
