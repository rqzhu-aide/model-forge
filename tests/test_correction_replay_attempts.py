"""Audit-2026-09-02 P-D (F7): correction replay attempt protection.

A correction replay after a restart reaches ``execute_correction`` with a
durable acknowledgement; the executor's post-restart reconcile is
exit-blind (FAILED with ``exit_code None``).  Before P-D that result
flowed straight into ``_validate_and_close_correction``'s FAILED branch,
spending one of the two bounded HV-5.6 attempts as ``executor.role_failed``
without ever validating the corrected bytes the agent wrote into the
correction workspace.  Post P-D the reconcile branch first applies P-A's
``_recover_completed_execution`` to the correction invocation's expected
output paths (which point into the correction workspace): all declared
outputs present -> the recovered result is validated and the attempt row
records the VALIDATION outcome; outputs absent -> the attempt was lost to
infrastructure, not judged, and ``RoleExecutionInfrastructureError``
surfaces WITHOUT spending the bounded attempt (D-7 re-issue).

Propagation (verified by reading, asserted here at harness level):
``execute_targeted_correction`` does not catch the infrastructure error;
the service's ``_drive_lane_b`` catch-all (service.py) logs it and leaves
the run in ``correcting`` with no CAS and no attempt recount, so the run
stays in the correction lane with zero new attempt rows.

Fixture patterns mirror tests/test_correction_lane_b.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_forge.executors import DeterministicFakeExecutor
from model_forge.executors.protocol import RoleExecutionResult, RoleExecutionStatus
from model_forge.harness.execution_records import (
    RoleExecutionInfrastructureError,
    RoleExecutionPending,
)

from test_correction_command_path import RUN, _scope, _seal_failed_closure_bytes
from test_correction_execution import _Fixture
from test_correction_lane_b import _drive, _lane_b_services
from test_correction_normalize import _fixable_defect_bytes
from test_correction_submission import _golden_output


class _VanishedAfterOutputsExecutor(DeterministicFakeExecutor):
    """Write outputs + acknowledge, crash, then reconcile exit-blind.

    First ``execute`` performs the full deterministic execution (writing
    the golden bytes into the correction workspace and recording the
    durable acknowledgement), then simulates the server crash.  Every
    later ``reconcile`` reports what a post-restart executor sees for a
    vanished process: FAILED with ``exit_code None``.
    """

    async def execute(self, invocation, observer) -> RoleExecutionResult:
        await super().execute(invocation, observer)
        raise RoleExecutionPending("Simulated post-acknowledgement crash.")

    async def reconcile(self, external_execution_id: str) -> RoleExecutionResult:
        return RoleExecutionResult(
            status=RoleExecutionStatus.FAILED,
            external_execution_id=external_execution_id,
            exit_code=None,
            summary="Process vanished post-restart; exit status unobservable.",
        )


class _RealFailureAfterAckExecutor(_VanishedAfterOutputsExecutor):
    """Same crash shape, but reconcile observed a REAL exit code."""

    async def reconcile(self, external_execution_id: str) -> RoleExecutionResult:
        return RoleExecutionResult(
            status=RoleExecutionStatus.FAILED,
            external_execution_id=external_execution_id,
            exit_code=1,
            summary="Observed exit code 1.",
        )


def _correction_output_path(fixture: _Fixture, command_id: str) -> Path:
    """The theorist's declared output path inside the correction workspace."""
    stage = fixture.stage
    spec = fixture.output_plan.for_stage_role(stage.stage_id, "theorist")[0]
    prefix = f"roles/{stage.sequence:02d}-theorist/"
    assert spec.relative_path.startswith(prefix)
    corrected = (
        f"roles/{stage.sequence:02d}-theorist.correction.{command_id}/"
        + spec.relative_path[len(prefix):]
    )
    return fixture.workspace.root / "runs" / RUN / corrected


def test_correction_replay_judges_recovered_outputs(tmp_path: Path) -> None:
    # F7 case 1: the vanished process DID finish - every declared output is
    # present in the correction workspace.  The replay must validate those
    # bytes and spend the attempt on the validation outcome, not record a
    # blind executor.role_failed.
    fixture = _Fixture(
        tmp_path, _VanishedAfterOutputsExecutor(_golden_output)
    )
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    services = _lane_b_services(fixture, "cmd_f7a", "scientific")

    with pytest.raises(RoleExecutionPending):
        _drive(
            fixture,
            services,
            base_closure_id,
            "cmd_f7a",
            "scientific",
            (_scope(fixture),),
        )
    assert fixture.repository.list_validation_attempts(RUN) == []

    outcome = _drive(
        fixture,
        services,
        base_closure_id,
        "cmd_f7a",
        "scientific",
        (_scope(fixture),),
    )

    # The replay reconciled the acknowledged execution: no fresh execute.
    assert len(fixture.executor.invocations) == 1
    # The recovered outputs were validated and the correction sealed SUCCEEDED.
    assert outcome.passed is True
    row = fixture.repository.get_role_closure(outcome.closure_id)
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["status"] == RoleExecutionStatus.SUCCEEDED.value
    assert "Recovered post-restart" in payload["diagnostic_text"]
    # Exactly ONE attempt row, recording the VALIDATION outcome - never
    # executor.role_failed.
    attempts = fixture.repository.list_validation_attempts(RUN)
    assert len(attempts) == 1
    assert attempts[0]["correction_command_id"] == "cmd_f7a"
    report = json.loads(attempts[0]["report_json"])
    assert report["passed"] is True
    assert all(
        finding["code"] != "executor.role_failed"
        for finding in report["findings"]
    )


def test_correction_replay_without_outputs_spends_no_attempt(
    tmp_path: Path,
) -> None:
    # F7 case 2: the vanished process left NO completed outputs - the
    # attempt was lost to infrastructure, not judged.  The replay must
    # surface RoleExecutionInfrastructureError and spend NOTHING.
    fixture = _Fixture(
        tmp_path, _VanishedAfterOutputsExecutor(_golden_output)
    )
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    services = _lane_b_services(fixture, "cmd_f7b", "scientific")

    with pytest.raises(RoleExecutionPending):
        _drive(
            fixture,
            services,
            base_closure_id,
            "cmd_f7b",
            "scientific",
            (_scope(fixture),),
        )
    assert fixture.repository.list_validation_attempts(RUN) == []

    # Simulate the workspace holding no completed outputs (e.g. the agent
    # died before producing anything recoverable).
    _correction_output_path(fixture, "cmd_f7b").unlink()
    run_status_before = fixture.repository.get_run(RUN)["status"]

    with pytest.raises(RoleExecutionInfrastructureError):
        _drive(
            fixture,
            services,
            base_closure_id,
            "cmd_f7b",
            "scientific",
            (_scope(fixture),),
        )

    # ZERO new attempt rows: the bounded attempt was not spent.
    assert fixture.repository.list_validation_attempts(RUN) == []
    # No status mutation at the harness level; the service's _drive_lane_b
    # catch-all keeps the run in the correction lane (correcting) for a
    # D-7 re-issue.
    assert fixture.repository.get_run(RUN)["status"] == run_status_before


def test_correction_replay_with_real_exit_code_spends_attempt(
    tmp_path: Path,
) -> None:
    # Guard-the-guard: a reconcile FAILED with a REAL exit code is a judged
    # failure, not a vanished process - behavior is unchanged (the bounded
    # attempt is spent as executor.role_failed).
    fixture = _Fixture(
        tmp_path, _RealFailureAfterAckExecutor(_golden_output)
    )
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    services = _lane_b_services(fixture, "cmd_f7c", "scientific")

    with pytest.raises(RoleExecutionPending):
        _drive(
            fixture,
            services,
            base_closure_id,
            "cmd_f7c",
            "scientific",
            (_scope(fixture),),
        )

    outcome = _drive(
        fixture,
        services,
        base_closure_id,
        "cmd_f7c",
        "scientific",
        (_scope(fixture),),
    )

    assert outcome.passed is False
    row = fixture.repository.get_role_closure(outcome.closure_id)
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["status"] == RoleExecutionStatus.FAILED.value
    assert payload["failure_code"] == "executor.role_failed"
    assert payload["exit_code"] == 1
    attempts = fixture.repository.list_validation_attempts(RUN)
    assert len(attempts) == 1
    report = json.loads(attempts[0]["report_json"])
    assert report["passed"] is False
    assert [finding["code"] for finding in report["findings"]] == [
        "executor.role_failed"
    ]
