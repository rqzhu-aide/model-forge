"""K-1c Lane B command path (P5b): packaging/scientific corrections.

Service-level coverage of ``request_output_correction`` for the two Lane B
correction types (a model re-invocation of the target role under
blast-radius verification):

- Packaging E2E: a FAILED run with a defective theorist closure (missing
  ``created_at``) transits failed -> correction_authorized -> correcting ->
  submitted, the sealed command carries correction_type "packaging", the
  newest validation attempt is the passed packaging attempt, and the
  handoff launcher fires.
- Scientific E2E: the sealed command carries the researcher
  ``user_instruction``.
- Bounds (HV-5.6): one pre-recorded spent packaging attempt makes a
  packaging command CORRECTION_EXHAUSTED while a scientific command is
  still accepted.
- D6: a failed Lane B attempt STAYS in correcting (no
  correcting -> authorized edge; the failed attempt row is the evidence)
  and a revalidate command FROM correcting is accepted as the retry.
- Exhaustion: after one failed packaging AND one failed scientific attempt
  the run transits correcting -> correction_exhausted with a
  run.correction_exhausted event.
- Descriptor surface: the correcting state advertises all four correction
  descriptors and lists all four available_recovery_controls.

Fixture strategy: the P3a ``_ServiceStack`` (real MethodHubService +
RunCoordinator over the K-1a3 fixture stack).  The passing lane uses the
golden-output executor; the failing lane uses a factory that re-emits the
SAME defective bytes so validation keeps failing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from method_hub.api.errors import CommandRejected
from method_hub.api.models import CorrectionRequest
from method_hub.application.correction_execution import (
    record_revalidation_closure,
)
from method_hub.executors import DeterministicFakeExecutor
from method_hub.json_io import loads_json

from test_correction_command_path import (
    CORRECTABLE,
    PROJECT,
    RUN,
    _ServiceStack,
    _execute_discovery_except,
    _execute_stage,
    _preserve,
    _run_payload,
    _scope,
    _seal_failed_closure_bytes,
    _set_run,
)
from test_correction_execution import (
    _Fixture,
    _digest,
    _record_passed_attempt,
)
from test_correction_normalize import _fixable_defect_bytes
from test_correction_submission import _golden_output


def _lane_b_action(detail, action_type: str):
    action = next(
        (item for item in detail.actions if item.action_type == action_type),
        None,
    )
    assert action is not None, f"run detail must expose a {action_type} action"
    return action


def _record_failed_packaging_attempt(
    fixture: _Fixture, correction_command_id: str, ordinal: int
) -> None:
    """``_record_passed_attempt``-style helper for a SPENT packaging attempt.

    The failed report row is the attempt-spent evidence the bounds gate
    counts (HV-5.6).
    """

    fixture.repository.record_validation_attempt(
        f"attempt.packaging.{ordinal}",
        RUN,
        ordinal,
        "policy.v1",
        '{"passed": false, "findings": []}',
        _digest("b"),
        correction_type="packaging",
        correction_command_id=correction_command_id,
    )


def _still_defective_output(invocation, offset):
    """DeterministicFakeExecutor factory that re-emits the SAME defect.

    The corrected bytes still miss the required ``created_at`` timestamp,
    so output validation (and therefore the Lane B attempt) fails.
    """

    return json.loads(_fixable_defect_bytes())


async def _prepare_failed_run(fixture: _Fixture) -> str:
    """Full-stage preparation for a Lane B pass (same shape as P3a/P4).

    Two discovery roles succeed; the theorist holds a FAILED base closure
    whose sealed bytes are defective; a prior revalidation closure lets
    the downstream stages execute against the family-aware basis (D4).
    """

    await _execute_discovery_except(fixture, "theorist")
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
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
    return base_closure_id


def _event_types(fixture: _Fixture) -> set[str]:
    return {
        loads_json(item["payload_json"], source="event").get("event_type")
        for item in fixture.repository.list_run_events(RUN)
    }


# --------------------------------------------------------------------------- #
# Acceptance: packaging correction completes to submitted
# --------------------------------------------------------------------------- #


def test_packaging_correction_completes_to_submission(tmp_path: Path) -> None:
    asyncio.run(_packaging_acceptance(tmp_path))


async def _packaging_acceptance(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    stack = _ServiceStack(fixture)
    base_closure_id = await _prepare_failed_run(fixture)

    detail = await stack.service.get_run(PROJECT, RUN)
    action = _lane_b_action(detail, "package_run_outputs")
    assert action.enabled is True
    command = CorrectionRequest(
        correction_type="packaging",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=action.descriptor_id,
    )
    receipt = await _preserve(stack.service, command, "corr-packaging")

    result = await stack.service.request_output_correction(
        PROJECT, RUN, command, raw_request=receipt
    )
    await asyncio.sleep(0)  # let the scheduled handoff launcher run

    assert result.state == "submitted"
    assert stack.launched == [RUN]

    # The sealed command document names the packaging lane.
    command_row = fixture.repository.get_command_by_idempotency(
        PROJECT, receipt.request_artifact_id
    )
    assert command_row is not None
    command_payload = loads_json(command_row["payload_json"], source="command")
    assert command_payload["correction_type"] == "packaging"
    assert command_payload["user_instruction"] is None
    assert command_payload["transformation_codes"] == []
    assert command_payload["role_closure_id"] == base_closure_id
    sealed_command_id = str(command_payload["command_id"])

    # The newest validation attempt is the passed packaging attempt.
    attempts = fixture.repository.list_validation_attempts(RUN)
    newest = attempts[-1]
    assert str(newest["correction_type"]) == "packaging"
    assert str(newest["correction_command_id"]) == sealed_command_id
    report = json.loads(newest["report_json"])
    assert report["passed"] is True

    # Lifecycle events: authorized, correcting, submitted.
    assert {
        "run.correction_authorized",
        "run.correcting",
        "run_submitted",
    } <= _event_types(fixture)


# --------------------------------------------------------------------------- #
# Acceptance: scientific correction carries the researcher instruction
# --------------------------------------------------------------------------- #


def test_scientific_correction_carries_user_instruction(tmp_path: Path) -> None:
    asyncio.run(_scientific_acceptance(tmp_path))


async def _scientific_acceptance(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    stack = _ServiceStack(fixture)
    await _prepare_failed_run(fixture)

    detail = await stack.service.get_run(PROJECT, RUN)
    action = _lane_b_action(detail, "revise_scientific_content")
    command = CorrectionRequest(
        correction_type="scientific",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=action.descriptor_id,
        user_instruction="Downgrade the claim.",
    )
    receipt = await _preserve(stack.service, command, "corr-scientific")

    result = await stack.service.request_output_correction(
        PROJECT, RUN, command, raw_request=receipt
    )
    await asyncio.sleep(0)

    assert result.state == "submitted"
    assert stack.launched == [RUN]

    command_row = fixture.repository.get_command_by_idempotency(
        PROJECT, receipt.request_artifact_id
    )
    assert command_row is not None
    command_payload = loads_json(command_row["payload_json"], source="command")
    assert command_payload["correction_type"] == "scientific"
    assert command_payload["user_instruction"] == "Downgrade the claim."
    sealed_command_id = str(command_payload["command_id"])

    newest = fixture.repository.list_validation_attempts(RUN)[-1]
    assert str(newest["correction_type"]) == "scientific"
    assert str(newest["correction_command_id"]) == sealed_command_id
    assert json.loads(newest["report_json"])["passed"] is True


# --------------------------------------------------------------------------- #
# Bounds (HV-5.6): a spent packaging attempt exhausts only that lane
# --------------------------------------------------------------------------- #


def test_spent_packaging_attempt_exhausts_only_packaging(
    tmp_path: Path,
) -> None:
    asyncio.run(_bounds_gate(tmp_path))


async def _bounds_gate(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    stack = _ServiceStack(fixture)
    await _prepare_failed_run(fixture)
    # One SPENT packaging attempt (ordinal 2; cmd_pre holds ordinal 1).
    _record_failed_packaging_attempt(fixture, "cmd_spent", ordinal=2)

    detail = await stack.service.get_run(PROJECT, RUN)
    packaging = _lane_b_action(detail, "package_run_outputs")
    command = CorrectionRequest(
        correction_type="packaging",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=packaging.descriptor_id,
    )
    receipt = await _preserve(stack.service, command, "corr-bounds-packaging")
    with pytest.raises(CommandRejected) as caught:
        await stack.service.request_output_correction(
            PROJECT, RUN, command, raw_request=receipt
        )
    assert caught.value.error.code == "CORRECTION_EXHAUSTED"

    # The scientific lane is unspent: its command is still accepted.
    detail = await stack.service.get_run(PROJECT, RUN)
    scientific = _lane_b_action(detail, "revise_scientific_content")
    retry = CorrectionRequest(
        correction_type="scientific",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=scientific.descriptor_id,
        user_instruction="Downgrade the claim.",
    )
    retry_receipt = await _preserve(stack.service, retry, "corr-bounds-sci")
    result = await stack.service.request_output_correction(
        PROJECT, RUN, retry, raw_request=retry_receipt
    )
    await asyncio.sleep(0)
    assert result.state == "submitted"


# --------------------------------------------------------------------------- #
# D6: a failed Lane B attempt stays correcting; the retry comes from there
# --------------------------------------------------------------------------- #


def test_failed_lane_b_stays_correcting_and_accepts_retry(
    tmp_path: Path,
) -> None:
    asyncio.run(_d6_retry(tmp_path))


async def _d6_retry(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_still_defective_output))
    stack = _ServiceStack(fixture)
    _seal_failed_closure_bytes(fixture, "theorist", _fixable_defect_bytes())
    _set_run(fixture, "failed", _run_payload(fixture, CORRECTABLE))

    detail = await stack.service.get_run(PROJECT, RUN)
    action = _lane_b_action(detail, "package_run_outputs")
    command = CorrectionRequest(
        correction_type="packaging",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=action.descriptor_id,
    )
    receipt = await _preserve(stack.service, command, "corr-d6-packaging")
    result = await stack.service.request_output_correction(
        PROJECT, RUN, command, raw_request=receipt
    )

    # D6: no transition out of correcting; the failed attempt row is the
    # evidence.  Exactly one packaging attempt, failed.
    assert result.state == "correcting"
    assert stack.launched == []
    assert fixture.repository.get_submission(RUN) is None
    attempts = fixture.repository.list_validation_attempts(RUN)
    assert len(attempts) == 1
    assert str(attempts[0]["correction_type"]) == "packaging"
    assert json.loads(attempts[0]["report_json"])["passed"] is False

    # The retry is a new command ACCEPTED from the correcting state (D6):
    # a revalidate against the still-defective bytes fails and leaves the
    # run in correcting without raising.
    detail = await stack.service.get_run(PROJECT, RUN)
    revalidate = _lane_b_action(detail, "revalidate_run")
    retry = CorrectionRequest(
        correction_type="revalidate",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=revalidate.descriptor_id,
    )
    retry_receipt = await _preserve(stack.service, retry, "corr-d6-revalidate")
    retry_result = await stack.service.request_output_correction(
        PROJECT, RUN, retry, raw_request=retry_receipt
    )
    assert retry_result.state == "correcting"
    attempts = fixture.repository.list_validation_attempts(RUN)
    assert len(attempts) == 2
    assert json.loads(attempts[1]["report_json"])["passed"] is False


# --------------------------------------------------------------------------- #
# Exhaustion: both bounded attempts spent -> correction_exhausted
# --------------------------------------------------------------------------- #


def test_exhaustion_after_both_bounded_attempts_fail(tmp_path: Path) -> None:
    asyncio.run(_exhaustion(tmp_path))


async def _exhaustion(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_still_defective_output))
    stack = _ServiceStack(fixture)
    _seal_failed_closure_bytes(fixture, "theorist", _fixable_defect_bytes())
    _set_run(fixture, "failed", _run_payload(fixture, CORRECTABLE))

    detail = await stack.service.get_run(PROJECT, RUN)
    packaging = _lane_b_action(detail, "package_run_outputs")
    first = CorrectionRequest(
        correction_type="packaging",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=packaging.descriptor_id,
    )
    first_receipt = await _preserve(stack.service, first, "corr-exh-packaging")
    first_result = await stack.service.request_output_correction(
        PROJECT, RUN, first, raw_request=first_receipt
    )
    assert first_result.state == "correcting"  # D6: bounds remain

    detail = await stack.service.get_run(PROJECT, RUN)
    scientific = _lane_b_action(detail, "revise_scientific_content")
    second = CorrectionRequest(
        correction_type="scientific",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=scientific.descriptor_id,
        user_instruction="Downgrade the claim.",
    )
    second_receipt = await _preserve(stack.service, second, "corr-exh-sci")
    second_result = await stack.service.request_output_correction(
        PROJECT, RUN, second, raw_request=second_receipt
    )

    # Both bounded attempts are now spent: correcting -> correction_exhausted.
    assert second_result.state == "correction_exhausted"
    assert "run.correction_exhausted" in _event_types(fixture)
    attempts = fixture.repository.list_validation_attempts(RUN)
    assert [str(row["correction_type"]) for row in attempts] == [
        "packaging",
        "scientific",
    ]
    assert all(
        json.loads(row["report_json"])["passed"] is False for row in attempts
    )


# --------------------------------------------------------------------------- #
# Descriptor surface: correcting advertises all four correction controls
# --------------------------------------------------------------------------- #


def test_correcting_state_advertises_all_four_descriptors(
    tmp_path: Path,
) -> None:
    asyncio.run(_descriptor_surface(tmp_path))


async def _descriptor_surface(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_still_defective_output))
    stack = _ServiceStack(fixture)
    _seal_failed_closure_bytes(fixture, "theorist", _fixable_defect_bytes())
    _set_run(fixture, "failed", _run_payload(fixture, CORRECTABLE))

    detail = await stack.service.get_run(PROJECT, RUN)
    packaging = _lane_b_action(detail, "package_run_outputs")
    command = CorrectionRequest(
        correction_type="packaging",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=packaging.descriptor_id,
    )
    receipt = await _preserve(stack.service, command, "corr-surface")
    result = await stack.service.request_output_correction(
        PROJECT, RUN, command, raw_request=receipt
    )
    assert result.state == "correcting"  # D6 retry surface

    actions = {item.action_type: item for item in result.actions}
    assert {
        "revalidate_run",
        "normalize_run_outputs",
        "package_run_outputs",
        "revise_scientific_content",
    } <= set(actions)
    assert all(
        actions[item].enabled is True
        for item in (
            "revalidate_run",
            "normalize_run_outputs",
            "package_run_outputs",
            "revise_scientific_content",
        )
    )
    assert result.lifecycle_projection.available_recovery_controls == [
        "revalidate",
        "normalize",
        "packaging",
        "scientific",
    ]
