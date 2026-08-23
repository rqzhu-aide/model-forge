"""K-1a3/K-1a4: revalidation core and closure write for the correction path.

The fixture mirrors tests/test_role_closure_integrity.py's ``_Fixture``
stack (repository / artifact store / recipe / fake executor), but resolves a
REAL P1 plan through the real ``SpecificationPackage`` so that
``revalidate_closure_outputs`` re-derives the same plan from the frozen
recipe, and revalidates against the REAL schema catalog.  Closures are
sealed under a permissive catalog so both schema-valid and schema-invalid
output bytes can be sealed as SUCCEEDED.

K-1a4 tests cover ``record_revalidation_closure``: the correction-family
intent/ack/closure write after a passed revalidation, its verification
through ``_load_closure`` (including the intent-row binding), idempotent
replay, and immutability of the source closure.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from model_forge.application.correction_execution import (
    record_revalidation_closure,
    revalidate_closure_outputs,
)
from model_forge.digests.jcs import canonicalize
from model_forge.executors import DeterministicFakeExecutor, RoleExecutionStatus
from model_forge.harness.execution_context import RunExecutionContext
from model_forge.harness.execution_records import (
    closure_artifact_id,
    correction_role_identity,
    document_sha256,
    output_artifact_id,
    role_identity,
)
from model_forge.harness.outputs import build_output_plan
from model_forge.harness.preparation import PreparedRunRecipe
from model_forge.harness.stage_execution import HarnessExecutionServices
from model_forge.json_io import loads_json
from model_forge.orchestration import StageStatus
from model_forge.schemas import SchemaCatalog
from model_forge.specification import SpecificationPackage
from model_forge.storage import ArtifactStore, WorkspacePaths
from model_forge.storage.repository import HubRepository

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
    def __init__(self, tmp_path: Path, executor, repository_cls=HubRepository) -> None:
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
        self.repository = repository_cls(self.workspace.root / "hub.sqlite3")
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
            "format": "model-forge.prepared-run-recipe",
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


# --------------------------------------------------------------------------- #
# K-1a4: correction-family closure write for passed revalidations
# --------------------------------------------------------------------------- #


def _seal_failed_base_closure(fixture: _Fixture, role: str) -> str:
    """Hand-write a FAILED base closure that still binds its sealed outputs.

    No executor path produces this shape for P1 (every declared output is
    required, so a failed validation seals nothing), but a run can fail
    after its outputs were sealed; the correction path must cope with that
    history.  Mirrors the writes in ``RoleLifecycleService._validate_and_close``.
    """
    stage = fixture.stage
    spec = fixture.output_plan.for_stage_role(stage.stage_id, role)[0]
    payload = (GOLDEN / "handoff.example.json").read_bytes()
    stored = fixture.artifacts.put_bytes(payload)
    artifact_id = output_artifact_id(fixture.context, spec, str(stored.sha256))
    fixture.repository.record_artifact(
        artifact_id,
        "project.revalidate_test",
        str(stored.sha256),
        stored.size,
        "application/json",
        f"artifact://sha256/{stored.sha256}",
        {
            "kind": "validated_role_output",
            "run_id": "run.revalidate_test",
            "contract_output_id": spec.contract_output_id,
            "output_id": spec.output_id,
            "storage_relative_path": stored.relative_path,
        },
    )
    invocation_id, execution_id, closure_id = role_identity(
        fixture.context, stage, role
    )
    invocation_sha256 = _digest("f")
    fixture.repository.get_or_create_execution(
        execution_id,
        invocation_id,
        "run.revalidate_test",
        invocation_sha256,
        {"kind": "role_invocation", "role": role},
    )
    fixture.repository.acknowledge_execution(
        execution_id,
        f"external.base.{role}",
        {"kind": "role_acknowledgement", "role": role},
    )
    document = {
        "format": "model-forge.role-invocation-closure",
        "format_version": "1.0.0",
        "conformance_state": "vertical_slice",
        "closure_id": closure_id,
        "execution_id": execution_id,
        "invocation_id": invocation_id,
        "invocation_sha256": invocation_sha256,
        "run_id": "run.revalidate_test",
        "project_id": "project.revalidate_test",
        "phase": fixture.plan.identity.phase_id,
        "mode": fixture.plan.mode_id,
        "sequence": stage.sequence,
        "stage_id": stage.stage_id,
        "role": role,
        "status": "failed",
        "external_execution_id": f"external.base.{role}",
        "exit_code": 1,
        "summary": "Base invocation failed after sealing its outputs.",
        "diagnostic_text": None,
        "failure_code": "output.structural_validation_failed",
        "outputs": [
            {
                "contract_output_id": spec.contract_output_id,
                "output_id": spec.output_id,
                "artifact_id": artifact_id,
                "sha256": str(stored.sha256),
                "size": stored.size,
                "media_type": "application/json",
                "storage_relative_path": stored.relative_path,
            }
        ],
        "findings": [],
        "output_transformations": [],
        "raw_output_sha256": None,
        "closed_at": "2026-08-16T00:00:00Z",
    }
    closure_sha256 = document_sha256(document)
    document["closure_sha256"] = closure_sha256
    closure_bytes = canonicalize(document)
    stored_closure = fixture.artifacts.put_bytes(
        closure_bytes, expected_sha256=hashlib.sha256(closure_bytes).hexdigest()
    )
    fixture.repository.record_artifact(
        closure_artifact_id(closure_id),
        "project.revalidate_test",
        str(stored_closure.sha256),
        stored_closure.size,
        "application/json",
        f"artifact://sha256/{stored_closure.sha256}",
        {
            "kind": "role_invocation_closure",
            "run_id": "run.revalidate_test",
            "closure_id": closure_id,
            "storage_relative_path": stored_closure.relative_path,
        },
    )
    fixture.repository.close_execution(
        execution_id, closure_id, closure_sha256, document
    )
    return closure_id


def _record_passed_attempt(fixture: _Fixture, correction_command_id: str) -> None:
    fixture.repository.record_validation_attempt(
        "attempt.1",
        "run.revalidate_test",
        1,
        "policy.v1",
        '{"passed": true}',
        _digest("e"),
        correction_type="revalidate",
        correction_command_id=correction_command_id,
    )


def _record_closure(fixture: _Fixture, role_closure_id: str, command_id: str) -> str:
    return record_revalidation_closure(
        repository=fixture.repository,
        artifacts=fixture.artifacts,
        specification=fixture.specification,
        run_id="run.revalidate_test",
        role_closure_id=role_closure_id,
        correction_command_id=command_id,
        invocation_sha256=_digest("9"),
    )


def test_correction_closure_joins_load_existing(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_valid_output))
    base_closure_id = _seal_failed_base_closure(fixture, "theorist")
    _record_passed_attempt(fixture, "cmd_1")

    # The helper provably agrees with role_identity under the suffix context.
    c_inv, c_exec, c_clo = correction_role_identity(
        "run.revalidate_test",
        fixture.recipe.sha256,
        fixture.stage,
        "theorist",
        "cmd_1",
    )
    corrected = dataclasses.replace(
        fixture.context, identity_suffix="correction.cmd_1"
    )
    assert (c_inv, c_exec, c_clo) == role_identity(corrected, fixture.stage, "theorist")

    written = _record_closure(fixture, base_closure_id, "cmd_1")
    assert written == c_clo

    loaded = fixture.services.roles.load_existing(
        stage=fixture.stage, role="theorist"
    )
    assert loaded is not None
    assert loaded.status is RoleExecutionStatus.SUCCEEDED
    assert loaded.closure_id == c_clo
    assert loaded.execution_id == c_exec
    assert loaded.invocation_sha256 == _digest("9")


def test_correction_closure_passes_full_load_verification(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_valid_output))
    fixture.execute()
    source_closure_id = fixture.closure_id_for("theorist")
    _record_passed_attempt(fixture, "cmd_1")

    c_inv, c_exec, c_clo = correction_role_identity(
        "run.revalidate_test",
        fixture.recipe.sha256,
        fixture.stage,
        "theorist",
        "cmd_1",
    )
    written = _record_closure(fixture, source_closure_id, "cmd_1")
    assert written == c_clo

    # Full _load_closure verification: expected fields, digest, output and
    # closure artifact binding, and the intent-row binding all pass.
    loaded = fixture.services.roles._load_closure(
        stage=fixture.stage,
        role="theorist",
        invocation_id=c_inv,
        execution_id=c_exec,
        closure_id=c_clo,
    )
    assert loaded is not None
    assert loaded.status is RoleExecutionStatus.SUCCEEDED
    assert loaded.invocation_sha256 == _digest("9")

    intent = fixture.repository.get_execution_for_invocation(c_inv)
    assert intent is not None
    assert intent["execution_id"] == c_exec
    assert intent["invocation_sha256"] == _digest("9")
    row = fixture.repository.get_role_closure(c_clo)
    assert row is not None
    document = loads_json(row["payload_json"], source="correction closure")
    assert document["invocation_sha256"] == intent["invocation_sha256"]
    unhashed = dict(document)
    closure_sha256 = unhashed.pop("closure_sha256")
    assert document_sha256(unhashed) == closure_sha256 == row["closure_sha256"]
    assert document["external_execution_id"] == "correction:cmd_1"
    assert document["failure_code"] is None
    assert document["exit_code"] == 0


class _RecordingRepository(HubRepository):
    """Spy on execution-intent writes to observe replay RecordResults."""

    def __init__(self, path) -> None:
        super().__init__(path)
        self.intent_results = []

    def get_or_create_execution(self, *args, **kwargs):
        result = super().get_or_create_execution(*args, **kwargs)
        self.intent_results.append(result)
        return result


def test_correction_closure_write_is_idempotent(tmp_path: Path) -> None:
    fixture = _Fixture(
        tmp_path, DeterministicFakeExecutor(_valid_output), _RecordingRepository
    )
    fixture.execute()
    source_closure_id = fixture.closure_id_for("theorist")
    _record_passed_attempt(fixture, "cmd_1")
    _, c_exec, _ = correction_role_identity(
        "run.revalidate_test",
        fixture.recipe.sha256,
        fixture.stage,
        "theorist",
        "cmd_1",
    )

    first = _record_closure(fixture, source_closure_id, "cmd_1")
    row_after_first = fixture.repository.get_role_closure(first)
    assert row_after_first is not None
    payload_after_first = row_after_first["payload_json"]
    second = _record_closure(fixture, source_closure_id, "cmd_1")

    assert second == first
    # The replay reached the repository and was recognized as an exact replay.
    repository = fixture.repository
    assert isinstance(repository, _RecordingRepository)
    # The last two intent writes are the two record_revalidation_closure calls.
    assert [result.created for result in repository.intent_results[-2:]] == [
        True,
        False,
    ]
    # No duplicate rows anywhere in the intent/ack/closure chain.
    with repository.database.connect() as connection:
        for table in (
            "role_execution_intents",
            "role_execution_acknowledgements",
            "role_execution_closures",
        ):
            count = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE execution_id = ?", (c_exec,)
            ).fetchone()[0]
            assert count == 1, table
    # The sealed closure bytes are untouched by the replay (closed_at stable).
    row_after_second = repository.get_role_closure(first)
    assert row_after_second is not None
    assert row_after_second["payload_json"] == payload_after_first


def test_correction_closure_preserves_source_closure(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_valid_output))
    source_closure_id = _seal_failed_base_closure(fixture, "theorist")
    _record_passed_attempt(fixture, "cmd_1")
    before = fixture.repository.get_role_closure(source_closure_id)
    assert before is not None
    before_payload = before["payload_json"]
    before_sha256 = before["closure_sha256"]

    written = _record_closure(fixture, source_closure_id, "cmd_1")
    assert written != source_closure_id

    after = fixture.repository.get_role_closure(source_closure_id)
    assert after is not None
    assert after["payload_json"] == before_payload
    assert after["closure_sha256"] == before_sha256
