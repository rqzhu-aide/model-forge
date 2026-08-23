"""K-1b: normalize execution core for the correction command path.

Covers ``normalize_closure_outputs`` (allowlist enforcement, transformed
bytes persisted as new artifacts, one ``run_validation_attempts`` row with
embedded output transformation records), ``record_normalize_closure``
(correction-family closure with overridden output digests and the
``output_transformations`` payload, family-aware ``load_existing``
recovery, idempotent replay, source-closure immutability), the full chain
into ``seal_correction_submission``, and the read-only
``preview_normalize`` dry run.

Fixtures reuse the K-1a3/K-1a4/K-1a5 stack from test_correction_execution.py
and test_correction_submission.py (real P1 plan, real schema catalog for
validation, golden handoff outputs).  The defective closure is the golden
theorist output with the required ``created_at`` timestamp removed (fixed
mechanically by ``timestamp_injection``); the non-fixable variant also
breaks ``sequence`` with a wrong type (no allowlisted code repairs types).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

import pytest

from model_forge.application.correction_execution import (
    normalize_closure_outputs,
    preview_normalize,
    record_normalize_closure,
    revalidate_closure_outputs,
    seal_correction_submission,
)
from model_forge.executors import DeterministicFakeExecutor, RoleExecutionStatus
from model_forge.harness.execution_records import correction_role_identity
from model_forge.harness.stage_execution import HarnessExecutionServices
from model_forge.json_io import loads_json

from test_correction_command_path import _seal_failed_closure_bytes
from test_correction_execution import (
    GOLDEN,
    _Fixture,
    _PermissiveSchemas,
    _digest,
)
from test_correction_submission import _cas, _golden_output

RUN = "run.revalidate_test"


def _fixable_defect_bytes() -> bytes:
    """Golden theorist output minus the required ``created_at`` timestamp."""
    golden = json.loads((GOLDEN / "handoff.example.json").read_text(encoding="utf-8"))
    del golden["created_at"]
    return json.dumps(golden, indent=2, ensure_ascii=False).encode("utf-8")


def _unfixable_defect_bytes() -> bytes:
    """The fixable defect plus a wrong-typed required ``sequence`` field."""
    golden = json.loads((GOLDEN / "handoff.example.json").read_text(encoding="utf-8"))
    del golden["created_at"]
    golden["sequence"] = "one"
    return json.dumps(golden, indent=2, ensure_ascii=False).encode("utf-8")


def _normalize(
    fixture: _Fixture,
    role_closure_id: str,
    codes: list[str],
    command_id: str = "cmd_1",
):
    return normalize_closure_outputs(
        repository=fixture.repository,
        specification=fixture.specification,
        artifacts=fixture.artifacts,
        schemas=fixture.specification.schemas,
        run_id=RUN,
        role_closure_id=role_closure_id,
        correction_command_id=command_id,
        transformation_codes=codes,
    )


def _record_normalize(fixture: _Fixture, role_closure_id: str, execution, command_id: str = "cmd_1") -> str:
    return record_normalize_closure(
        repository=fixture.repository,
        artifacts=fixture.artifacts,
        specification=fixture.specification,
        run_id=RUN,
        role_closure_id=role_closure_id,
        correction_command_id=command_id,
        invocation_sha256=_digest("9"),
        result_digests=dict(execution.result_digests),
        transformation_records=dict(execution.transformation_records),
        findings=execution.findings,
    )


def _artifact_count(fixture: _Fixture) -> int:
    with fixture.repository.database.connect() as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM artifacts").fetchone()
    return int(row["count"])


def _closure_count(fixture: _Fixture) -> int:
    with fixture.repository.database.connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM role_execution_closures"
        ).fetchone()
    return int(row["count"])


def _correction_services(fixture: _Fixture, command_id: str) -> HarnessExecutionServices:
    context = dataclasses.replace(
        fixture.context,
        submission_from_status="correcting",
        correction_command_id=command_id,
        correction_type="normalize",
    )
    return HarnessExecutionServices(
        context=context,
        repository=fixture.repository,
        executor=fixture.executor,
        schemas=_PermissiveSchemas(),
        artifacts=fixture.artifacts,
        workspace=fixture.workspace,
    )


def _execute_stage(fixture: _Fixture, stage) -> None:
    outcome = asyncio.run(
        fixture.services.execute_or_reconcile_stage(
            run_id=RUN,
            manifest_sha256=str(fixture.context.manifest_sha256),
            stage=stage,
        )
    )
    assert outcome.status.value == "succeeded"


# --------------------------------------------------------------------------- #
# The defect bites: revalidation of the defective sealed bytes fails
# --------------------------------------------------------------------------- #


def test_revalidate_fails_on_defective_sealed_bytes(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    closure_id = _seal_failed_closure_bytes(fixture, "theorist", _fixable_defect_bytes())

    result = revalidate_closure_outputs(
        repository=fixture.repository,
        specification=fixture.specification,
        artifacts=fixture.artifacts,
        schemas=fixture.specification.schemas,
        run_id=RUN,
        role_closure_id=closure_id,
        correction_command_id="correction.probe",
    )

    assert not result.attempt.passed
    assert any(
        finding.code == "schema.required" and "created_at" in finding.message
        for finding in result.findings
    )


# --------------------------------------------------------------------------- #
# normalize_closure_outputs
# --------------------------------------------------------------------------- #


def test_normalize_records_passed_attempt_with_transformations(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    closure_id = _seal_failed_closure_bytes(fixture, "theorist", _fixable_defect_bytes())
    source_row = fixture.repository.get_role_closure(closure_id)
    assert source_row is not None
    source_digest = loads_json(source_row["payload_json"], source="closure")["outputs"][0][
        "sha256"
    ]

    execution = _normalize(fixture, closure_id, ["timestamp_injection"])

    assert execution.attempt.passed
    assert execution.attempt.correction_type == "normalize"
    assert execution.attempt.correction_command_id == "cmd_1"
    assert execution.findings == ()
    # The defective output's result digest differs from its source digest.
    assert set(execution.result_digests) == {"p1.theory_discovery"}
    result_digest = execution.result_digests["p1.theory_discovery"]
    assert result_digest != source_digest
    record = execution.transformation_records["p1.theory_discovery"]
    assert record.source_sha256 == source_digest
    assert record.result_sha256 == result_digest
    assert record.changed
    assert any(
        entry.code == "timestamp_injection" and entry.json_pointer == "/created_at"
        for entry in record.entries
    )
    # The attempt row carries the embedded transformation records.
    row = fixture.repository.get_latest_validation_attempt(RUN)
    assert row is not None
    assert row["correction_type"] == "normalize"
    assert row["attempt_id"] == execution.attempt.attempt_id
    report = json.loads(row["report_json"])
    assert report["passed"] is True
    assert len(report["output_transformations"]) == 1
    assert report["output_transformations"][0]["result_sha256"] == result_digest
    # The transformed bytes were persisted as a normalized_role_output artifact.
    transformed = loads_json(
        fixture.artifacts.read_bytes(result_digest).decode("utf-8"),
        source="normalized output",
    )
    assert "created_at" in transformed
    with fixture.repository.database.connect() as connection:
        artifact_row = connection.execute(
            "SELECT payload_json FROM artifacts WHERE sha256 = ?", (result_digest,)
        ).fetchone()
    assert artifact_row is not None
    metadata = loads_json(artifact_row["payload_json"], source="artifact metadata")
    assert metadata["kind"] == "normalized_role_output"
    assert metadata["run_id"] == RUN
    assert metadata["contract_output_id"] == "p1.theory_discovery"
    # The sealed source bytes are untouched.
    source_after = fixture.repository.get_role_closure(closure_id)
    assert source_after is not None
    assert source_after["payload_json"] == source_row["payload_json"]


def test_normalize_rejects_disallowed_codes_before_any_write(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    closure_id = _seal_failed_closure_bytes(fixture, "theorist", _fixable_defect_bytes())
    attempts_before = fixture.repository.count_validation_attempts(RUN)
    artifacts_before = _artifact_count(fixture)

    with pytest.raises(ValueError, match="identity_version_bump"):
        _normalize(fixture, closure_id, ["timestamp_injection", "identity_version_bump"])

    assert fixture.repository.count_validation_attempts(RUN) == attempts_before
    assert _artifact_count(fixture) == artifacts_before


def test_normalize_still_failing_records_failed_attempt_only(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    closure_id = _seal_failed_closure_bytes(fixture, "theorist", _unfixable_defect_bytes())
    closures_before = _closure_count(fixture)

    execution = _normalize(fixture, closure_id, ["timestamp_injection"])

    assert not execution.attempt.passed
    assert any(finding.code == "schema.type" for finding in execution.findings)
    assert not any(finding.code == "schema.required" for finding in execution.findings)
    row = fixture.repository.get_latest_validation_attempt(RUN)
    assert row is not None
    assert row["correction_type"] == "normalize"
    report = json.loads(row["report_json"])
    assert report["passed"] is False
    # No correction closure is written by a failed normalize.
    assert _closure_count(fixture) == closures_before
    _, _, c_closure_id = correction_role_identity(
        RUN, fixture.recipe.sha256, fixture.stage, "theorist", "cmd_1"
    )
    assert fixture.repository.get_role_closure(c_closure_id) is None


# --------------------------------------------------------------------------- #
# record_normalize_closure
# --------------------------------------------------------------------------- #


def test_normalize_closure_overrides_digests_and_loads(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    source_row = fixture.repository.get_role_closure(base_closure_id)
    assert source_row is not None
    execution = _normalize(fixture, base_closure_id, ["timestamp_injection"])
    result_digest = execution.result_digests["p1.theory_discovery"]

    written = _record_normalize(fixture, base_closure_id, execution)

    _, c_exec, c_closure_id = correction_role_identity(
        RUN, fixture.recipe.sha256, fixture.stage, "theorist", "cmd_1"
    )
    assert written == c_closure_id
    # The closure payload carries the overridden digest and transformations.
    row = fixture.repository.get_role_closure(c_closure_id)
    assert row is not None
    document = loads_json(row["payload_json"], source="correction closure")
    assert document["status"] == "succeeded"
    assert document["outputs"][0]["sha256"] == result_digest
    assert (
        document["outputs"][0]["storage_relative_path"]
        == fixture.artifacts.verify(result_digest).relative_path
    )
    assert document["output_transformations"]
    assert (
        document["output_transformations"][0]["result_sha256"] == result_digest
    )
    assert "Normalization converged" in document["summary"]
    # The family-aware load_existing returns the correction closure.
    loaded = fixture.services.roles.load_existing(
        stage=fixture.stage, role="theorist"
    )
    assert loaded is not None
    assert loaded.status is RoleExecutionStatus.SUCCEEDED
    assert loaded.closure_id == c_closure_id
    assert loaded.execution_id == c_exec
    assert loaded.invocation_sha256 == _digest("9")
    assert loaded.outputs[0].sha256 == result_digest
    # The source (failed) closure is untouched.
    source_after = fixture.repository.get_role_closure(base_closure_id)
    assert source_after is not None
    assert source_after["payload_json"] == source_row["payload_json"]


def test_normalize_closure_write_is_idempotent(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    execution = _normalize(fixture, base_closure_id, ["timestamp_injection"])

    first = _record_normalize(fixture, base_closure_id, execution)
    row_after_first = fixture.repository.get_role_closure(first)
    assert row_after_first is not None
    second = _record_normalize(fixture, base_closure_id, execution)

    assert second == first
    row_after_second = fixture.repository.get_role_closure(first)
    assert row_after_second is not None
    assert row_after_second["payload_json"] == row_after_first["payload_json"]


# --------------------------------------------------------------------------- #
# Full chain: normalize -> correction closure -> correction submission
# --------------------------------------------------------------------------- #


def test_normalize_full_chain_seals_correction_submission(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    discovery = fixture.stage
    basis = fixture.services._basis_before(discovery)
    for step in discovery.role_steps:
        if step.role == "theorist":
            continue
        inputs = {iid: basis[iid] for iid in step.input_ids}
        result = asyncio.run(
            fixture.services.roles.execute_or_reconcile(
                stage=discovery, role=step.role, inputs=inputs
            )
        )
        assert result.status.value == "succeeded"
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )

    execution = _normalize(fixture, base_closure_id, ["timestamp_injection"])
    assert execution.attempt.passed
    correction_closure_id = _record_normalize(fixture, base_closure_id, execution)

    for stage in fixture.plan.stages[1:]:
        _execute_stage(fixture, stage)

    _cas(fixture, "failed", "failed")
    _cas(fixture, "correction_authorized", "correction_authorized")
    _cas(fixture, "correcting", "correcting")

    submission_id = seal_correction_submission(
        services=_correction_services(fixture, "cmd_1"),
        correction_command_id="cmd_1",
        correction_type="normalize",
    )

    row = fixture.repository.get_submission(RUN)
    assert row is not None
    assert str(row["submission_id"]) == submission_id
    run = fixture.repository.get_run(RUN)
    assert str(run["status"]) == "submitted"
    document = loads_json(row["payload_json"], source="submission")
    theorist_entries = [
        item for item in document["closure_chain"] if item["role"] == "theorist"
    ]
    assert theorist_entries[0]["invocation_closure_id"] == correction_closure_id


# --------------------------------------------------------------------------- #
# preview_normalize (read-only dry run)
# --------------------------------------------------------------------------- #


def test_preview_normalize_is_read_only_and_names_fixed_findings(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    closure_id = _seal_failed_closure_bytes(fixture, "theorist", _fixable_defect_bytes())
    attempts_before = fixture.repository.count_validation_attempts(RUN)
    artifacts_before = _artifact_count(fixture)

    preview = preview_normalize(
        repository=fixture.repository,
        specification=fixture.specification,
        artifacts=fixture.artifacts,
        schemas=fixture.specification.schemas,
        run_id=RUN,
        role_closure_id=closure_id,
        transformation_codes=["timestamp_injection"],
    )

    assert preview["passing"] is True
    assert preview["remaining_findings"] == []
    assert any(
        finding["code"] == "schema.required" and "created_at" in finding["message"]
        for finding in preview["current_findings"]
    )
    assert any(
        finding["code"] == "schema.required" and "created_at" in finding["message"]
        for finding in preview["fixed_findings"]
    )
    assert preview["transformations"][0]["changed"] is True
    assert any(
        entry["code"] == "timestamp_injection"
        for entry in preview["transformations"][0]["entries"]
    )
    # Zero writes of any kind.
    assert fixture.repository.count_validation_attempts(RUN) == attempts_before
    assert _artifact_count(fixture) == artifacts_before


def test_preview_normalize_reports_unfixable_remainder(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _unfixable_defect_bytes()
    )
    attempts_before = fixture.repository.count_validation_attempts(RUN)
    artifacts_before = _artifact_count(fixture)

    preview = preview_normalize(
        repository=fixture.repository,
        specification=fixture.specification,
        artifacts=fixture.artifacts,
        schemas=fixture.specification.schemas,
        run_id=RUN,
        role_closure_id=closure_id,
        transformation_codes=["timestamp_injection"],
    )

    assert preview["passing"] is False
    # The timestamp defect is fixed; the wrong-typed sequence remains.
    assert any(
        finding["code"] == "schema.required" for finding in preview["fixed_findings"]
    )
    assert any(
        finding["code"] == "schema.type" for finding in preview["remaining_findings"]
    )
    assert not any(
        finding["code"] == "schema.required"
        for finding in preview["remaining_findings"]
    )
    assert fixture.repository.count_validation_attempts(RUN) == attempts_before
    assert _artifact_count(fixture) == artifacts_before
