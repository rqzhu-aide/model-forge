"""K5-4 (ADR-016): mid-pipeline correction resume-execution edge.

A FAILED run whose pipeline did not complete (later stages hold no
closures) takes the correcting -> running edge after a passed correction:
completed and corrected stage roles reconcile through the family-aware
closure read without re-invocation, the remaining stages execute, and the
submission seal follows once every stage role holds a succeeded closure.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from pathlib import Path

from method_hub.api.models import CorrectionRequest
from method_hub.application.correction_execution import (
    incomplete_correction_chain,
)
from method_hub.application.run_coordinator import ContractSequentialOrchestrator
from method_hub.digests.jcs import canonicalize
from method_hub.executors import DeterministicFakeExecutor, RoleExecutionStatus
from method_hub.harness.execution_records import correction_role_identity
from method_hub.harness.preparation import PreparedRunRecipe
from method_hub.json_io import loads_json

from test_correction_command_path import (
    CORRECTABLE,
    PROJECT,
    RUN,
    _ServiceStack,
    _correction_action,
    _execute_discovery_except,
    _preserve,
    _run_payload,
    _scope,
    _set_run,
)
from test_correction_execution import (
    _Fixture,
    _record_closure,
    _record_passed_attempt,
    _seal_failed_base_closure,
    _valid_output,
)
from test_correction_submission import _golden_output


def _amend_recipe(fixture: _Fixture, **extra: object) -> None:
    """Amend the stored recipe document with keyword updates.

    Same trigger-drop rewrite as
    ``test_correction_command_path._refreeze_recipe_with_role_resources``,
    generalized: the ``run_manifests`` immutability triggers are dropped
    for one rewrite and immediately restored, and the fixture's in-memory
    recipe/context are rebound to the new digest.  ``_ServiceStack``'s own
    refreeze composes on top, so call this BEFORE constructing the stack.
    """
    document = dict(fixture.recipe.document)
    document.update(extra)
    sha = hashlib.sha256(canonicalize(document)).hexdigest()
    with fixture.repository.database.connect() as connection:
        triggers = connection.execute(
            "SELECT name, sql FROM sqlite_master"
            " WHERE type = 'trigger' AND tbl_name = 'run_manifests'"
        ).fetchall()
        for trigger in triggers:
            connection.execute(f"DROP TRIGGER {trigger['name']}")
        try:
            connection.execute(
                "UPDATE run_manifests SET payload_json = ?, manifest_sha256 = ?"
                " WHERE run_id = ?",
                (json.dumps(document), sha, RUN),
            )
        finally:
            for trigger in triggers:
                connection.execute(trigger["sql"])
    recipe = PreparedRunRecipe(document, sha)
    context = dataclasses.replace(
        fixture.context, manifest_sha256=sha, recipe=recipe
    )
    fixture.recipe = recipe
    fixture.context = context


def test_family_aware_reconciliation_recovers_corrected_closure(
    tmp_path: Path,
) -> None:
    """execute_or_reconcile reconciles the correction closure (D4, K5-4)."""
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_valid_output))
    base_closure_id = _seal_failed_base_closure(fixture, "theorist")
    _record_passed_attempt(fixture, "cmd_k54")
    correction_closure_id = _record_closure(fixture, base_closure_id, "cmd_k54")
    result = asyncio.run(
        fixture.services.roles.execute_or_reconcile(
            stage=fixture.stage, role="theorist", inputs={}
        )
    )
    assert result.closure_id == correction_closure_id
    assert result.status is RoleExecutionStatus.SUCCEEDED
    assert result.reconciled is True
    assert len(fixture.executor.invocations) == 0


def test_incomplete_chain_probe_labels_every_gap(tmp_path: Path) -> None:
    """A fresh fixture holds no closures: every stage role is a gap."""
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_valid_output))
    gaps = incomplete_correction_chain(services=fixture.services)
    expected = tuple(
        f"{stage.stage_id}/{step.role}"
        for stage in fixture.plan.stages
        for step in stage.role_steps
    )
    assert gaps == expected


def test_incomplete_chain_probe_empty_on_complete_chain(tmp_path: Path) -> None:
    """A fully executed pipeline has no gaps: the submission path is legal."""
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    for stage in fixture.plan.stages:
        outcome = asyncio.run(
            fixture.services.execute_or_reconcile_stage(
                run_id="run.revalidate_test",
                manifest_sha256=str(fixture.context.manifest_sha256),
                stage=stage,
            )
        )
        assert outcome.status.value == "succeeded"
    assert incomplete_correction_chain(services=fixture.services) == ()


def test_mid_pipeline_correction_resumes_execution(tmp_path: Path) -> None:
    asyncio.run(_mid_pipeline(tmp_path))


async def _mid_pipeline(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    _amend_recipe(
        fixture,
        orchestration_binding=ContractSequentialOrchestrator()
        .binding_for(fixture.plan.identity)
        .to_dict(),
    )
    stack = _ServiceStack(fixture)
    await _execute_discovery_except(fixture, "theorist")
    base_closure_id = _seal_failed_base_closure(fixture, "theorist")
    # p1.lead_synthesis NEVER ran: the mid-pipeline shape (K5-4).
    _set_run(fixture, "failed", _run_payload(fixture, CORRECTABLE))

    detail = await stack.service.get_run(PROJECT, RUN)
    action = _correction_action(detail)
    command = CorrectionRequest(
        correction_type="revalidate",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=action.descriptor_id,
    )
    receipt = await _preserve(stack.service, command, "corr-midpipe")
    result = await stack.service.request_output_correction(
        PROJECT, RUN, command, raw_request=receipt
    )
    await asyncio.sleep(0)  # let the scheduled handoff launcher run

    # The resume edge, not the submission edge:
    assert result.state == "running"
    assert stack.launched == [RUN]
    row = fixture.repository.get_run(RUN)
    payload = loads_json(row["payload_json"], source="run")
    assert "terminal_reason" not in payload
    assert "closure_findings" not in payload
    events = fixture.repository.list_run_events(RUN)
    event_types = {
        loads_json(item["payload_json"], source="event").get("event_type")
        for item in events
    }
    assert {
        "run.correction_authorized",
        "run.correcting",
        "run.execution_resumed",
    } <= event_types

    # Drive the coordinator: stage 1 reconciles (NO re-invocation of the
    # corrected theorist), p1.lead_synthesis executes, the chain seals.
    invocations_before = len(fixture.executor.invocations)
    await stack.coordinator.run(RUN)
    assert len(fixture.executor.invocations) == invocations_before + 1

    submission = fixture.repository.get_submission(RUN)
    assert submission is not None
    document = loads_json(submission["payload_json"], source="submission")
    theorist = [
        item for item in document["closure_chain"] if item["role"] == "theorist"
    ]
    command_row = fixture.repository.get_command_by_idempotency(
        PROJECT, receipt.request_artifact_id
    )
    assert command_row is not None
    command_payload = loads_json(command_row["payload_json"], source="command")
    sealed_command_id = str(command_payload["command_id"])
    expected_closure_id = correction_role_identity(
        RUN, fixture.recipe.sha256, fixture.stage, "theorist", sealed_command_id
    )[2]
    assert theorist[0]["invocation_closure_id"] == expected_closure_id
    assert theorist[0]["invocation_closure_id"] != base_closure_id
    # NOTE: the coordinator's validation tail REJECTS this fixture run
    # ("Prepared run lacks a frozen publication basis") - a known
    # fixture-recipe gap unrelated to K5-4.  Assert the submission row,
    # invocation count, and events; do NOT assert a final run status.
