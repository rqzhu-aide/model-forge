"""K-1a5 Lane A: correction submission re-entry.

Covers ``seal_correction_submission`` and the attempt-aware
``SubmissionAssembler`` correction branch:

- Scenario A: a FAILED run with no base submission seals one from the
  ``correcting`` state, and the closure chain references the
  correction-family closure for the recovered role.
- Scenario B: a REJECTED run with a base submission appends a
  ``run_submission_attempts`` row (base row untouched) and CASes
  correcting -> submitted; ``validate_submission`` reads the attempt.
- Scenario C: a missing successful closure aborts before any write.

Fixtures reuse the K-1a3/K-1a4 stack from test_correction_execution.py
(real P1 plan, permissive sealing catalog, golden handoff outputs).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from pathlib import Path

import pytest

from method_hub.application.correction_execution import (
    record_revalidation_closure,
    seal_correction_submission,
)
from method_hub.executors import DeterministicFakeExecutor
from method_hub.harness.execution_records import (
    correction_role_identity,
    document_sha256,
)
from method_hub.harness.stage_execution import HarnessExecutionServices
from method_hub.harness.submission_validation import validate_submission
from method_hub.harness.submissions import SubmissionAssemblyError
from method_hub.json_io import loads_json
from method_hub.orchestration import StageOutcome, StageStatus, SubmissionStatus
from method_hub.domain import StableId

from test_correction_execution import (
    GOLDEN,
    _Fixture,
    _PermissiveSchemas,
    _record_passed_attempt,
    _seal_failed_base_closure,
)


def _golden_output(invocation, offset: int):
    """Per-output golden bytes; each_item outputs must be JSON arrays."""
    name = Path(str(invocation.expected_output_paths[offset - 1])).name
    if name == "source-changes.json":
        return [json.loads((GOLDEN / "literature-source.example.json").read_text())]
    if name == "attention-items.json":
        return [json.loads((GOLDEN / "attention-item.example.json").read_text())]
    if name == "decision.json":
        return json.loads((GOLDEN / "decision-record.example.json").read_text())
    if name in ("synthesis-candidate.json", "coverage-candidate.json"):
        return json.loads((GOLDEN / "scientific-record.example.json").read_text())
    return json.loads((GOLDEN / "handoff.example.json").read_text())


def _cas(fixture: _Fixture, new_status: str, tag: str) -> None:
    """Direct fixture-level run transition (the repository CAS does not
    enforce the domain transition table; RunLifecycle does)."""
    run = fixture.repository.get_run("run.revalidate_test")
    payload = loads_json(run["payload_json"], source="run payload")
    event = {
        "event_type": f"run.{tag}",
        "message": f"Fixture transition to {new_status}.",
        "occurred_at": "2026-08-17T00:00:00Z",
    }
    result = fixture.repository.compare_and_swap_run(
        "run.revalidate_test",
        str(run["status"]),
        int(run["head_sequence"]),
        new_status,
        payload,
        f"event.run.revalidate_test.{tag}",
        document_sha256(event),
        event,
    )
    assert result.applied, f"CAS to {new_status} failed: {result.reason}"


def _correction_services(fixture: _Fixture, command_id: str) -> HarnessExecutionServices:
    context = dataclasses.replace(
        fixture.context,
        submission_from_status="correcting",
        correction_command_id=command_id,
        correction_type="revalidate",
    )
    return HarnessExecutionServices(
        context=context,
        repository=fixture.repository,
        executor=fixture.executor,
        schemas=_PermissiveSchemas(),
        artifacts=fixture.artifacts,
        workspace=fixture.workspace,
    )


def _stage_outcomes(services: HarnessExecutionServices) -> tuple[StageOutcome, ...]:
    outcomes: list[StageOutcome] = []
    for stage in services.context.plan.stages:
        closure_ids: list[StableId] = []
        for step in stage.role_steps:
            closure = services.roles.load_existing(stage=stage, role=step.role)
            assert closure is not None and closure.status.value == "succeeded"
            assert closure.closure_id is not None
            closure_ids.append(StableId(closure.closure_id))
        outcomes.append(
            StageOutcome(
                sequence=stage.sequence,
                stage_id=StableId(stage.stage_id),
                status=StageStatus.SUCCEEDED,
                invocation_closure_ids=tuple(closure_ids),
                reconciled=True,
            )
        )
    return tuple(outcomes)


def _execute_stage(fixture: _Fixture, stage) -> None:
    outcome = asyncio.run(
        fixture.services.execute_or_reconcile_stage(
            run_id=str(fixture.context.run_id),
            manifest_sha256=str(fixture.context.manifest_sha256),
            stage=stage,
        )
    )
    assert outcome.status is StageStatus.SUCCEEDED


# --------------------------------------------------------------------------- #
# Scenario A: FAILED run (no base submission) seals one from correcting
# --------------------------------------------------------------------------- #


def test_failed_run_correction_seals_base_submission(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    discovery = fixture.stage
    # Execute two of the three discovery roles; the theorist gets a
    # hand-written FAILED base closure whose sealed bytes actually conform
    # (a stale/transient failure: "would this output pass today" -> yes).
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
    base_closure_id = _seal_failed_base_closure(fixture, "theorist")

    # Passed revalidation -> correction-family closure for the theorist.
    _record_passed_attempt(fixture, "cmd_1")
    correction_closure_id = record_revalidation_closure(
        repository=fixture.repository,
        artifacts=fixture.artifacts,
        specification=fixture.specification,
        run_id="run.revalidate_test",
        role_closure_id=base_closure_id,
        correction_command_id="cmd_1",
        invocation_sha256="9" * 64,
    )
    expected_correction_id = correction_role_identity(
        "run.revalidate_test",
        fixture.recipe.sha256,
        discovery,
        "theorist",
        "cmd_1",
    )[2]
    assert correction_closure_id == expected_correction_id

    # The remaining stages execute against the family-aware basis.
    for stage in fixture.plan.stages[1:]:
        _execute_stage(fixture, stage)

    # FAILED -> CORRECTION_AUTHORIZED -> CORRECTING (command acceptance path).
    _cas(fixture, "failed", "failed")
    _cas(fixture, "correction_authorized", "correction_authorized")
    _cas(fixture, "correcting", "correcting")

    submission_id = seal_correction_submission(
        services=_correction_services(fixture, "cmd_1"),
        correction_command_id="cmd_1",
        correction_type="revalidate",
    )

    row = fixture.repository.get_submission("run.revalidate_test")
    assert row is not None
    assert str(row["submission_id"]) == submission_id
    # No attempt rows: the base seal path wrote the base submission.
    assert fixture.repository.count_submission_attempts("run.revalidate_test") == 0
    run = fixture.repository.get_run("run.revalidate_test")
    assert str(run["status"]) == "submitted"
    events = fixture.repository.list_run_events("run.revalidate_test")
    assert any(
        loads_json(item["payload_json"], source="event").get("event_type")
        == "run_submitted"
        for item in events
    )
    document = loads_json(row["payload_json"], source="submission")
    theorist_entries = [
        item for item in document["closure_chain"] if item["role"] == "theorist"
    ]
    assert theorist_entries[0]["invocation_closure_id"] == correction_closure_id


# --------------------------------------------------------------------------- #
# Scenario B: REJECTED run (base submission) seals a submission attempt
# --------------------------------------------------------------------------- #


def test_rejected_run_correction_seals_submission_attempt(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    for stage in fixture.plan.stages:
        _execute_stage(fixture, stage)

    # Seal the base submission through the normal running -> submitted gate.
    base_outcome = fixture.services.submissions.submit_or_reconcile(
        stage_outcomes=_stage_outcomes(fixture.services)
    )
    assert base_outcome.status is SubmissionStatus.SUBMITTED
    assert fixture.repository.get_submission("run.revalidate_test") is not None

    # Submission validation rejects the run.
    _cas(fixture, "rejected", "rejected")

    # A passed revalidation writes a correction-family closure (new
    # identity), so the corrected submission document differs from the base.
    _record_passed_attempt(fixture, "cmd_1")
    correction_closure_id = record_revalidation_closure(
        repository=fixture.repository,
        artifacts=fixture.artifacts,
        specification=fixture.specification,
        run_id="run.revalidate_test",
        role_closure_id=fixture.closure_id_for("theorist"),
        correction_command_id="cmd_1",
        invocation_sha256="9" * 64,
    )

    _cas(fixture, "correction_authorized", "correction_authorized")
    _cas(fixture, "correcting", "correcting")

    seal_correction_submission(
        services=_correction_services(fixture, "cmd_1"),
        correction_command_id="cmd_1",
        correction_type="revalidate",
    )

    # The base row is untouched; exactly one attempt row was appended.
    base_row = fixture.repository.get_submission("run.revalidate_test")
    assert base_row is not None
    assert fixture.repository.count_submission_attempts("run.revalidate_test") == 1
    attempt = fixture.repository.get_latest_submission_attempt("run.revalidate_test")
    assert attempt is not None
    assert int(attempt["attempt_ordinal"]) == 1
    assert str(attempt["correction_command_id"]) == "cmd_1"
    assert str(attempt["correction_type"]) == "revalidate"
    run = fixture.repository.get_run("run.revalidate_test")
    assert str(run["status"]) == "submitted"

    # The attempt payload is the corrected document: the theorist entry
    # references the correction closure, not the base closure.
    attempt_document = loads_json(attempt["payload_json"], source="attempt")
    theorist_entries = [
        item
        for item in attempt_document["closure_chain"]
        if item["role"] == "theorist"
    ]
    assert theorist_entries[0]["invocation_closure_id"] == correction_closure_id

    # validate_submission is attempt-aware (HV-5 revision A1): it reads the
    # attempt payload, not the stale base submission.
    validation = validate_submission(
        repository=fixture.repository,
        artifacts=fixture.artifacts,
        schemas=fixture.specification.schemas,
        project_id="project.revalidate_test",
        run_id="run.revalidate_test",
        plan=fixture.plan,
        output_plan=fixture.output_plan,
        selected_method=None,
    )
    validated_theorist = [
        item
        for item in validation.submission["closure_chain"]
        if item["role"] == "theorist"
    ]
    assert (
        validated_theorist[0]["invocation_closure_id"] == correction_closure_id
    )


# --------------------------------------------------------------------------- #
# Scenario C: a missing successful closure aborts before any write
# --------------------------------------------------------------------------- #


def test_correction_submission_requires_complete_closure_chain(
    tmp_path: Path,
) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    # Nothing executed: no closures exist at all.
    _cas(fixture, "failed", "failed")
    _cas(fixture, "correction_authorized", "correction_authorized")
    _cas(fixture, "correcting", "correcting")

    with pytest.raises(SubmissionAssemblyError):
        seal_correction_submission(
            services=_correction_services(fixture, "cmd_1"),
            correction_command_id="cmd_1",
            correction_type="revalidate",
        )

    assert fixture.repository.get_submission("run.revalidate_test") is None
    assert fixture.repository.count_submission_attempts("run.revalidate_test") == 0
    run = fixture.repository.get_run("run.revalidate_test")
    assert str(run["status"]) == "correcting"
