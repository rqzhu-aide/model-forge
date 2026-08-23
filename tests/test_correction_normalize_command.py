"""K-1b: normalize command path + read-only preview (service level, P4c).

Covers ``request_output_correction``'s normalize branch end to end
(allowlist gates, the D3 coverability gate, Lane A execution to
SUBMITTED), the D5 succeeded-closure fallback for REJECTED runs under
normalize, and the zero-state-write ``preview_output_correction``
service method.  Fixture stack: ``_ServiceStack`` from
test_correction_command_path.py plus the defect recipes from
test_correction_normalize.py (golden theorist handoff minus the required
``created_at``, fixed mechanically by ``timestamp_injection``).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from model_forge.api.errors import CommandRejected
from model_forge.api.models import CorrectionPreviewRequest, CorrectionRequest
from model_forge.application.correction_execution import (
    record_revalidation_closure,
)
from model_forge.digests.jcs import canonicalize
from model_forge.executors import DeterministicFakeExecutor
from model_forge.harness.execution_records import (
    closure_artifact_id,
    correction_role_identity,
    document_sha256,
    output_artifact_id,
    role_identity,
)
from model_forge.json_io import loads_json
from model_forge.orchestration import SubmissionStatus

from test_correction_command_path import (
    CORRECTABLE,
    PROJECT,
    RUN,
    _ServiceStack,
    _correction_action,
    _execute_discovery_except,
    _execute_stage,
    _preserve,
    _run_payload,
    _scope,
    _seal_failed_closure_bytes,
    _set_run,
)
from test_correction_execution import _Fixture, _record_passed_attempt
from test_correction_normalize import _artifact_count, _fixable_defect_bytes
from test_correction_submission import _golden_output, _stage_outcomes


def _seal_succeeded_closure_bytes(fixture: _Fixture, role: str, payload: bytes) -> str:
    """_seal_failed_closure_bytes variant: a SUCCEEDED hand-written closure."""
    stage = fixture.stage
    spec = fixture.output_plan.for_stage_role(stage.stage_id, role)[0]
    stored = fixture.artifacts.put_bytes(payload)
    artifact_id = output_artifact_id(fixture.context, spec, str(stored.sha256))
    fixture.repository.record_artifact(
        artifact_id,
        PROJECT,
        str(stored.sha256),
        stored.size,
        "application/json",
        f"artifact://sha256/{stored.sha256}",
        {
            "kind": "validated_role_output",
            "run_id": RUN,
            "contract_output_id": spec.contract_output_id,
            "output_id": spec.output_id,
            "storage_relative_path": stored.relative_path,
        },
    )
    invocation_id, execution_id, closure_id = role_identity(
        fixture.context, stage, role
    )
    invocation_sha256 = hashlib.sha256(b"s").hexdigest()
    fixture.repository.get_or_create_execution(
        execution_id,
        invocation_id,
        RUN,
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
        "run_id": RUN,
        "project_id": PROJECT,
        "phase": fixture.plan.identity.phase_id,
        "mode": fixture.plan.mode_id,
        "sequence": stage.sequence,
        "stage_id": stage.stage_id,
        "role": role,
        "status": "succeeded",
        "external_execution_id": f"external.base.{role}",
        "exit_code": 0,
        "summary": "Base invocation succeeded.",
        "diagnostic_text": None,
        "failure_code": None,
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
        PROJECT,
        str(stored_closure.sha256),
        stored_closure.size,
        "application/json",
        f"artifact://sha256/{stored_closure.sha256}",
        {
            "kind": "role_invocation_closure",
            "run_id": RUN,
            "closure_id": closure_id,
            "storage_relative_path": stored_closure.relative_path,
        },
    )
    fixture.repository.close_execution(
        execution_id, closure_id, closure_sha256, document
    )
    return closure_id


# --------------------------------------------------------------------------- #
# Acceptance: a FAILED run normalizes to SUBMITTED
# --------------------------------------------------------------------------- #


def test_normalize_correction_completes_to_submission(tmp_path: Path) -> None:
    asyncio.run(_normalize_acceptance(tmp_path))


async def _normalize_acceptance(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    stack = _ServiceStack(fixture)

    # Two discovery roles succeed; the theorist gets a hand-written FAILED
    # base closure whose sealed bytes miss the required created_at
    # timestamp (fixed mechanically by timestamp_injection).
    await _execute_discovery_except(fixture, "theorist")
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )

    # A prior correction recovered the theorist so the downstream stages
    # could execute against the family-aware basis (D4).
    _record_passed_attempt(fixture, "cmd_pre")
    record_revalidation_closure(
        repository=fixture.repository,
        artifacts=fixture.artifacts,
        specification=fixture.specification,
        run_id=RUN,
        role_closure_id=base_closure_id,
        correction_command_id="cmd_pre",
        invocation_sha256="9" * 64,
    )
    for stage in fixture.plan.stages[1:]:
        await _execute_stage(fixture, stage)

    _set_run(fixture, "failed", _run_payload(fixture, CORRECTABLE))

    # The failed detail advertises BOTH correction controls.
    detail = await stack.service.get_run(PROJECT, RUN)
    action_types = {item.action_type for item in detail.actions}
    assert {"revalidate_run", "normalize_run_outputs"} <= action_types
    assert detail.lifecycle_projection.available_recovery_controls == [
        "revalidate",
        "normalize",
        "packaging",
        "scientific",
    ]
    action = _correction_action(detail, "normalize_run_outputs")

    command = CorrectionRequest(
        correction_type="normalize",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=action.descriptor_id,
        transformation_codes=["timestamp_injection"],
    )
    receipt = await _preserve(stack.service, command, "corr-normalize")
    result = await stack.service.request_output_correction(
        PROJECT, RUN, command, raw_request=receipt
    )
    await asyncio.sleep(0)  # let the scheduled handoff launcher run

    assert result.state == "submitted"
    assert stack.launched == [RUN]

    # The sealed command document names the normalize correction + codes.
    command_row = fixture.repository.get_command_by_idempotency(
        PROJECT, receipt.request_artifact_id
    )
    assert command_row is not None
    command_payload = loads_json(command_row["payload_json"], source="command")
    assert command_payload["correction_type"] == "normalize"
    assert command_payload["transformation_codes"] == ["timestamp_injection"]
    sealed_command_id = str(command_payload["command_id"])

    # The newest validation attempt is the normalize attempt, passed, and
    # carries the output transformation records.
    attempts = fixture.repository.list_validation_attempts(RUN)
    latest = attempts[-1]
    assert str(latest["correction_type"]) == "normalize"
    assert str(latest["correction_command_id"]) == sealed_command_id
    report = json.loads(latest["report_json"])
    assert report["passed"] is True
    assert report["output_transformations"]

    # The submission's theorist entry references the normalize closure.
    expected_closure_id = correction_role_identity(
        RUN, fixture.recipe.sha256, fixture.stage, "theorist", sealed_command_id
    )[2]
    submission = fixture.repository.get_submission(RUN)
    assert submission is not None
    document = loads_json(submission["payload_json"], source="submission")
    theorist = [
        item for item in document["closure_chain"] if item["role"] == "theorist"
    ]
    assert theorist[0]["invocation_closure_id"] == expected_closure_id

    events = fixture.repository.list_run_events(RUN)
    event_types = {
        loads_json(item["payload_json"], source="event").get("event_type")
        for item in events
    }
    assert {"run.correction_authorized", "run.correcting", "run_submitted"} <= event_types


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #


def _failed_fixable_stack(tmp_path: Path):
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    stack = _ServiceStack(fixture)
    _seal_failed_closure_bytes(fixture, "theorist", _fixable_defect_bytes())
    _set_run(fixture, "failed", _run_payload(fixture, CORRECTABLE))
    return fixture, stack


def test_normalize_d3_gate_refuses_non_coverable(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture, stack = _failed_fixable_stack(tmp_path)
        detail = await stack.service.get_run(PROJECT, RUN)
        action = _correction_action(detail, "normalize_run_outputs")
        command = CorrectionRequest(
            correction_type="normalize",
            permitted_output_scope=[_scope(fixture)],
            action_descriptor_id=action.descriptor_id,
            transformation_codes=["null_strip"],  # does not fix created_at
        )
        receipt = await _preserve(stack.service, command, "corr-d3")
        attempts_before = len(fixture.repository.list_validation_attempts(RUN))
        with pytest.raises(CommandRejected) as caught:
            await stack.service.request_output_correction(
                PROJECT, RUN, command, raw_request=receipt
            )
        assert caught.value.error.code == "CORRECTION_NOT_APPLICABLE"
        # D3: refused BEFORE any command is sealed or attempt recorded.
        assert (
            fixture.repository.get_command_by_idempotency(
                PROJECT, receipt.request_artifact_id
            )
            is None
        )
        assert len(fixture.repository.list_validation_attempts(RUN)) == attempts_before

    asyncio.run(scenario())


def test_normalize_empty_codes_is_scope_invalid(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture, stack = _failed_fixable_stack(tmp_path)
        detail = await stack.service.get_run(PROJECT, RUN)
        action = _correction_action(detail, "normalize_run_outputs")
        command = CorrectionRequest(
            correction_type="normalize",
            permitted_output_scope=[_scope(fixture)],
            action_descriptor_id=action.descriptor_id,
            transformation_codes=[],
        )
        receipt = await _preserve(stack.service, command, "corr-empty")
        with pytest.raises(CommandRejected) as caught:
            await stack.service.request_output_correction(
                PROJECT, RUN, command, raw_request=receipt
            )
        assert caught.value.error.code == "CORRECTION_SCOPE_INVALID"

    asyncio.run(scenario())


def test_normalize_disallowed_code_is_scope_invalid(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture, stack = _failed_fixable_stack(tmp_path)
        detail = await stack.service.get_run(PROJECT, RUN)
        action = _correction_action(detail, "normalize_run_outputs")
        command = CorrectionRequest(
            correction_type="normalize",
            permitted_output_scope=[_scope(fixture)],
            action_descriptor_id=action.descriptor_id,
            transformation_codes=["value_rewrite"],  # not allowlisted
        )
        receipt = await _preserve(stack.service, command, "corr-bad-code")
        attempts_before = len(fixture.repository.list_validation_attempts(RUN))
        with pytest.raises(CommandRejected) as caught:
            await stack.service.request_output_correction(
                PROJECT, RUN, command, raw_request=receipt
            )
        assert caught.value.error.code == "CORRECTION_SCOPE_INVALID"
        assert len(fixture.repository.list_validation_attempts(RUN)) == attempts_before

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# D5: a REJECTED run normalizes through the succeeded-closure fallback
# --------------------------------------------------------------------------- #


def test_rejected_run_normalize_recovers_to_submission(tmp_path: Path) -> None:
    asyncio.run(_rejected_normalize(tmp_path))


async def _rejected_normalize(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    stack = _ServiceStack(fixture)

    # All roles except the theorist execute; the theorist gets a
    # hand-written SUCCEEDED closure whose sealed bytes miss created_at.
    await _execute_discovery_except(fixture, "theorist")
    succeeded_closure_id = _seal_succeeded_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    for stage in fixture.plan.stages[1:]:
        await _execute_stage(fixture, stage)

    # The base submission seals through the normal gate; submission
    # validation then rejects the run.
    base_outcome = fixture.services.submissions.submit_or_reconcile(
        stage_outcomes=_stage_outcomes(fixture.services)
    )
    assert base_outcome.status is SubmissionStatus.SUBMITTED
    _set_run(fixture, "rejected", _run_payload(fixture, CORRECTABLE))

    detail = await stack.service.get_run(PROJECT, RUN)
    action = _correction_action(detail, "normalize_run_outputs")
    command = CorrectionRequest(
        correction_type="normalize",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=action.descriptor_id,
        transformation_codes=["timestamp_injection"],
    )
    receipt = await _preserve(stack.service, command, "corr-rej-norm")
    result = await stack.service.request_output_correction(
        PROJECT, RUN, command, raw_request=receipt
    )
    await asyncio.sleep(0)

    assert result.state == "submitted"
    # D5 fallback: the target is the SUCCEEDED theorist closure (no failed
    # closure exists anywhere in this run).
    command_row = fixture.repository.get_command_by_idempotency(
        PROJECT, receipt.request_artifact_id
    )
    assert command_row is not None
    command_payload = loads_json(command_row["payload_json"], source="command")
    assert command_payload["correction_type"] == "normalize"
    assert command_payload["role_closure_id"] == succeeded_closure_id

    # The correction re-entry appends ONE submission attempt; the base
    # submission row stays untouched.
    assert fixture.repository.count_submission_attempts(RUN) == 1


# --------------------------------------------------------------------------- #
# Preview (read-only)
# --------------------------------------------------------------------------- #


def test_preview_is_read_only_and_reports_fixable(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture, stack = _failed_fixable_stack(tmp_path)
        attempts_before = len(fixture.repository.list_validation_attempts(RUN))
        artifacts_before = _artifact_count(fixture)
        command = CorrectionPreviewRequest(transformation_codes=[])
        receipt = await _preserve(stack.service, command, "prev-1")
        view = await stack.service.preview_output_correction(
            PROJECT, RUN, command, raw_request=receipt
        )
        assert view.passing is True
        assert view.fixed_findings
        assert view.transformations
        # Zero state writes: no attempts, no artifacts, no sealed command.
        assert len(fixture.repository.list_validation_attempts(RUN)) == attempts_before
        assert _artifact_count(fixture) == artifacts_before
        assert (
            fixture.repository.get_command_by_idempotency(
                PROJECT, receipt.request_artifact_id
            )
            is None
        )

    asyncio.run(scenario())


def test_preview_rejects_wrong_state(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
        stack = _ServiceStack(fixture)
        # The run is still running: not correction-eligible.  (_set_run
        # also installs the payload keys the run detail view requires.)
        _set_run(fixture, "running", _run_payload(fixture, CORRECTABLE))
        command = CorrectionPreviewRequest(transformation_codes=[])
        receipt = await _preserve(stack.service, command, "prev-state")
        with pytest.raises(CommandRejected) as caught:
            await stack.service.preview_output_correction(
                PROJECT, RUN, command, raw_request=receipt
            )
        assert caught.value.error.code == "CORRECTION_NOT_APPLICABLE"

    asyncio.run(scenario())


def test_preview_disallowed_code_is_scope_invalid(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture, stack = _failed_fixable_stack(tmp_path)
        command = CorrectionPreviewRequest(transformation_codes=["value_rewrite"])
        receipt = await _preserve(stack.service, command, "prev-bad")
        with pytest.raises(CommandRejected) as caught:
            await stack.service.preview_output_correction(
                PROJECT, RUN, command, raw_request=receipt
            )
        assert caught.value.error.code == "CORRECTION_SCOPE_INVALID"

    asyncio.run(scenario())
