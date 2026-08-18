"""K-1a5 command path: ``request_output_correction`` service (P3a).

Service-level coverage of the revalidate correction command flow:

- Acceptance: a FAILED run with a correctable finding and a failed base
  closure whose sealed bytes conform to the REAL catalog revalidates,
  writes the correction-family closure, transits
  failed -> correction_authorized -> correcting -> submitted, seals the
  base submission, and schedules the handoff launcher.
- Revalidate-fail (D1): the run stays correction_authorized, the failed
  attempt row is the evidence, and no submission is sealed.
- Gates: stale descriptor (CONTROL_HEAD_STALE), wrong state and
  integrity-blocked findings (CORRECTION_NOT_APPLICABLE), out-of-scope
  outputs (CORRECTION_SCOPE_INVALID), unimplemented correction type
  (CORRECTION_NOT_APPLICABLE), idempotent replay.

Fixture strategy: the K-1a3 ``_Fixture`` stack (real P1 plan resolved
through the real ``SpecificationPackage``) is wrapped in a REAL
``MethodHubService`` + ``RunCoordinator`` built over the fixture's
repository/artifacts.  The coordinator's ``_execution_components``
requires a frozen ``role_resources`` key that the K-1a3 fixture recipe
predates (the CURRENT preparation pipeline freezes it; this fixture
stack is older).  ``run_manifests`` rows are immutability-trigger
protected, so the fixture amends the recipe BEFORE any execution by
temporarily dropping that table's triggers, rewriting payload+digest,
and restoring the triggers — the resulting stored state is exactly what
today's preparation pipeline would freeze.  The fixture's in-memory
recipe/context/services are rebound to the same digest, so every
identity derivation (base closures, correction closures, submission
assembly, and the service's own repository-side recipe reads) shares
one recipe digest.  No production code path is stubbed.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from method_hub.api.errors import CommandRejected
from method_hub.api.models import CorrectionRequest
from method_hub.api.ports import RawRequestBody
from method_hub.application.correction_execution import record_revalidation_closure
from method_hub.application.run_coordinator import RunCoordinator
from method_hub.application.service import MethodHubService
from method_hub.application.settings import ApplicationSettings
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.digests.jcs import canonicalize
from method_hub.executors import DeterministicFakeExecutor
from method_hub.harness.execution_records import (
    closure_artifact_id,
    correction_role_identity,
    document_sha256,
    output_artifact_id,
    role_identity,
)
from method_hub.harness.preparation import PreparedRunRecipe
from method_hub.harness.stage_execution import HarnessExecutionServices
from method_hub.json_io import loads_json

from test_correction_execution import (
    GOLDEN,
    _Fixture,
    _PermissiveSchemas,
    _digest,
    _record_passed_attempt,
    _seal_failed_base_closure,
)
from test_correction_submission import _golden_output

ROOT = Path(__file__).resolve().parents[1]
RUN = "run.revalidate_test"
PROJECT = "project.revalidate_test"

CORRECTABLE = [
    {
        "finding_class": "correctable_contract_error",
        "blocks_publication": True,
        "code": "schema.output_drift",
        "message": "Sealed bytes no longer conform to the current catalog.",
    }
]
BLOCKER = [
    {
        "finding_class": "integrity_blocker",
        "blocks_publication": True,
        "code": "integrity.digest_mismatch",
        "message": "Sealed bytes do not match their recorded digest.",
    }
]


def _refreeze_recipe_with_role_resources(fixture: _Fixture) -> None:
    """Amend the stored recipe with the frozen ``role_resources`` key.

    The K-1a3 fixture recipe predates the ``role_resources`` freeze that
    ``RunCoordinator._execution_components`` requires.  ``run_manifests``
    is immutability-trigger protected, so the triggers are dropped for
    one rewrite and immediately restored; the resulting row matches what
    the current preparation pipeline would have frozen.  The fixture's
    in-memory recipe/context/services are rebound to the new digest.
    """

    resources: dict[str, dict[str, object]] = {}
    for stage in fixture.plan.stages:
        for step in stage.role_steps:
            soul = "State the discovery basis."
            resources[step.role] = {
                "soul_text": soul,
                "soul_sha256": hashlib.sha256(soul.encode("utf-8")).hexdigest(),
                "skills": [],
            }
    document = dict(fixture.recipe.document)
    document["role_resources"] = resources
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
    fixture.services = HarnessExecutionServices(
        context=context,
        repository=fixture.repository,
        executor=fixture.executor,
        schemas=_PermissiveSchemas(),
        artifacts=fixture.artifacts,
        workspace=fixture.workspace,
    )


class _ServiceStack:
    """A real MethodHubService + RunCoordinator over the fixture stack."""

    def __init__(self, fixture: _Fixture) -> None:
        _refreeze_recipe_with_role_resources(fixture)
        self.fixture = fixture
        settings = ApplicationSettings(data_root=fixture.workspace.root)
        role_resources = RoleResourceCatalog.load(ROOT / "resources" / "team")
        self.coordinator = RunCoordinator(
            settings=settings,
            specification=fixture.specification,
            repository=fixture.repository,
            artifacts=fixture.artifacts,
            role_resources=role_resources,
            executor=fixture.executor,
        )
        self.launched: list[str] = []

        async def _launcher(run_id: str) -> None:
            self.launched.append(run_id)

        self.service = MethodHubService(
            settings=settings,
            specification=fixture.specification,
            repository=fixture.repository,
            artifacts=fixture.artifacts,
            role_resources=role_resources,
            run_launcher=_launcher,
            run_coordinator=self.coordinator,
        )


def _run_payload(fixture: _Fixture, findings: list[dict[str, object]]) -> dict:
    """Run payload carrying every key the run detail view requires."""

    return {
        "phase": "P1",
        "mode": str(fixture.plan.mode_id),
        "requested_at": "2026-08-17T00:00:00Z",
        "requested_by": "tester",
        "phase_contract_version": str(fixture.identity.contract_version),
        "phase_contract_sha256": str(fixture.identity.phase_contract_sha256),
        "closure_findings": findings,
    }


def _set_run(fixture: _Fixture, status: str, payload: dict) -> None:
    """Direct fixture-level transition that also replaces the payload."""

    run = fixture.repository.get_run(RUN)
    event = {
        "event_type": f"run.{status}",
        "message": f"Fixture transition to {status}.",
        "occurred_at": "2026-08-17T00:00:00Z",
    }
    result = fixture.repository.compare_and_swap_run(
        RUN,
        str(run["status"]),
        int(run["head_sequence"]),
        status,
        payload,
        f"event.run.revalidate_test.{status}",
        document_sha256(event),
        event,
    )
    assert result.applied, f"CAS to {status} failed: {result.reason}"


def _seal_failed_closure_bytes(fixture: _Fixture, role: str, payload: bytes) -> str:
    """_seal_failed_base_closure with caller-supplied output bytes."""

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
    invocation_sha256 = _digest("f")
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
        "format": "method-hub.role-invocation-closure",
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


def _scope(fixture: _Fixture, role: str = "theorist") -> str:
    spec = fixture.output_plan.for_stage_role(fixture.stage.stage_id, role)[0]
    return str(spec.contract_output_id)


def _correction_action(detail):
    action = next(
        (item for item in detail.actions if item.action_type == "revalidate_run"),
        None,
    )
    assert action is not None, "run detail must expose a revalidate_run action"
    return action


async def _preserve(
    service: MethodHubService, command: CorrectionRequest, key: str
):
    body = json.dumps(command.model_dump()).encode("utf-8")
    return await service.preserve_raw_request(
        RawRequestBody(
            body=body,
            byte_length=len(body),
            media_type="application/json",
            content_sha256=hashlib.sha256(body).hexdigest(),
            method="POST",
            path=f"/api/v1/projects/{PROJECT}/runs/{RUN}/corrections",
            command_family="request_output_correction",  # type: ignore[arg-type]
            project_id=PROJECT,
            idempotency_key=key,
        )
    )


def _sealed_command_count(fixture: _Fixture) -> int:
    with fixture.repository.database.connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM sealed_commands"
        ).fetchone()
    return int(row["count"])


async def _execute_discovery_except(fixture: _Fixture, skip_role: str) -> None:
    discovery = fixture.stage
    basis = fixture.services._basis_before(discovery)
    for step in discovery.role_steps:
        if step.role == skip_role:
            continue
        inputs = {iid: basis[iid] for iid in step.input_ids}
        result = await fixture.services.roles.execute_or_reconcile(
            stage=discovery, role=step.role, inputs=inputs
        )
        assert result.status.value == "succeeded"


async def _execute_stage(fixture: _Fixture, stage) -> None:
    outcome = await fixture.services.execute_or_reconcile_stage(
        run_id=RUN,
        manifest_sha256=str(fixture.context.manifest_sha256),
        stage=stage,
    )
    assert outcome.status.value == "succeeded"


# --------------------------------------------------------------------------- #
# Acceptance: FAILED run revalidates and completes to submitted
# --------------------------------------------------------------------------- #


def test_revalidate_correction_completes_to_submission(tmp_path: Path) -> None:
    asyncio.run(_acceptance(tmp_path))


async def _acceptance(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    stack = _ServiceStack(fixture)

    # Two of the three discovery roles succeed; the theorist gets a
    # hand-written FAILED base closure whose sealed bytes actually conform
    # to the real catalog (a stale/transient failure -> revalidation passes).
    await _execute_discovery_except(fixture, "theorist")
    base_closure_id = _seal_failed_base_closure(fixture, "theorist")

    # A prior correction attempt recovered the theorist so the downstream
    # stages could execute against the family-aware basis (D4).
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

    # The failed detail advertises the correction control.
    detail = await stack.service.get_run(PROJECT, RUN)
    action = _correction_action(detail)
    assert action.enabled is True
    assert detail.lifecycle_projection.available_recovery_controls == ["revalidate"]

    command = CorrectionRequest(
        correction_type="revalidate",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=action.descriptor_id,
    )
    receipt = await _preserve(stack.service, command, "corr-accept")
    commands_before = _sealed_command_count(fixture)

    result = await stack.service.request_output_correction(
        PROJECT, RUN, command, raw_request=receipt
    )
    await asyncio.sleep(0)  # let the scheduled handoff launcher run

    assert result.state == "submitted"
    assert stack.launched == [RUN]

    # The correction command was sealed with the failed closure as target.
    command_row = fixture.repository.get_command_by_idempotency(
        PROJECT, receipt.request_artifact_id
    )
    assert command_row is not None
    command_payload = loads_json(command_row["payload_json"], source="command")
    assert command_payload["correction_type"] == "revalidate"
    assert command_payload["role_closure_id"] == base_closure_id
    sealed_command_id = str(command_payload["command_id"])

    # The service's revalidation attempt is the newest one and passed.
    attempts = fixture.repository.list_validation_attempts(RUN)
    assert [int(row["attempt_ordinal"]) for row in attempts] == [1, 2]
    assert str(attempts[1]["correction_command_id"]) == sealed_command_id
    report = json.loads(attempts[1]["report_json"])
    assert report["passed"] is True

    # The base submission was sealed (no attempt rows on a FAILED run) and
    # its theorist entry references the service's correction closure.
    assert fixture.repository.count_submission_attempts(RUN) == 0
    submission = fixture.repository.get_submission(RUN)
    assert submission is not None
    expected_closure_id = correction_role_identity(
        RUN, fixture.recipe.sha256, fixture.stage, "theorist", sealed_command_id
    )[2]
    document = loads_json(submission["payload_json"], source="submission")
    theorist = [
        item for item in document["closure_chain"] if item["role"] == "theorist"
    ]
    assert theorist[0]["invocation_closure_id"] == expected_closure_id
    assert theorist[0]["invocation_closure_id"] != base_closure_id

    # Lifecycle events: authorized, correcting, submitted.
    events = fixture.repository.list_run_events(RUN)
    event_types = {
        loads_json(item["payload_json"], source="event").get("event_type")
        for item in events
    }
    assert {"run.correction_authorized", "run.correcting", "run_submitted"} <= event_types

    # Idempotent replay: the same idempotency key returns the current detail
    # without sealing a second command.
    replay = await stack.service.request_output_correction(
        PROJECT, RUN, command, raw_request=receipt
    )
    assert replay.state == "submitted"
    assert _sealed_command_count(fixture) == commands_before + 1


# --------------------------------------------------------------------------- #
# D1: a failed revalidation stays in correction_authorized
# --------------------------------------------------------------------------- #


def test_revalidate_failure_stays_correction_authorized(tmp_path: Path) -> None:
    asyncio.run(_revalidate_fail(tmp_path))


async def _revalidate_fail(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    stack = _ServiceStack(fixture)
    # The sealed bytes are schema-invalid against the REAL catalog.
    _seal_failed_closure_bytes(fixture, "theorist", b'{"unexpected": true}')
    _set_run(fixture, "failed", _run_payload(fixture, CORRECTABLE))

    detail = await stack.service.get_run(PROJECT, RUN)
    action = _correction_action(detail)
    command = CorrectionRequest(
        correction_type="revalidate",
        permitted_output_scope=[_scope(fixture)],
        action_descriptor_id=action.descriptor_id,
    )
    receipt = await _preserve(stack.service, command, "corr-fail")

    result = await stack.service.request_output_correction(
        PROJECT, RUN, command, raw_request=receipt
    )

    # D1: no transition past correction_authorized; the attempt is evidence.
    assert result.state == "correction_authorized"
    assert stack.launched == []
    assert fixture.repository.get_submission(RUN) is None
    attempts = fixture.repository.list_validation_attempts(RUN)
    assert len(attempts) == 1
    report = json.loads(attempts[0]["report_json"])
    assert report["passed"] is False
    assert report["findings"]
    # The authorized detail still offers the retry control.
    assert _correction_action(result).enabled is True
    assert result.lifecycle_projection.available_recovery_controls == ["revalidate"]


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #


def test_correction_rejects_stale_descriptor(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
        stack = _ServiceStack(fixture)
        _set_run(fixture, "failed", _run_payload(fixture, CORRECTABLE))
        command = CorrectionRequest(
            correction_type="revalidate",
            permitted_output_scope=[_scope(fixture)],
            action_descriptor_id="action.bogus",
        )
        receipt = await _preserve(stack.service, command, "corr-stale")
        with pytest.raises(CommandRejected) as caught:
            await stack.service.request_output_correction(
                PROJECT, RUN, command, raw_request=receipt
            )
        assert caught.value.error.code == "CONTROL_HEAD_STALE"

    asyncio.run(scenario())


def test_correction_rejects_wrong_state(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
        stack = _ServiceStack(fixture)
        # Still running: corrections apply to failed/rejected/authorized runs.
        _set_run(fixture, "running", _run_payload(fixture, CORRECTABLE))
        command = CorrectionRequest(
            correction_type="revalidate",
            permitted_output_scope=[_scope(fixture)],
            action_descriptor_id="action.any",
        )
        receipt = await _preserve(stack.service, command, "corr-state")
        with pytest.raises(CommandRejected) as caught:
            await stack.service.request_output_correction(
                PROJECT, RUN, command, raw_request=receipt
            )
        assert caught.value.error.code == "CORRECTION_NOT_APPLICABLE"

    asyncio.run(scenario())


def test_correction_rejects_integrity_blocked_run(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
        stack = _ServiceStack(fixture)
        _set_run(fixture, "failed", _run_payload(fixture, BLOCKER))
        # An integrity-blocked failure does not advertise the control...
        detail = await stack.service.get_run(PROJECT, RUN)
        assert not any(
            item.action_type == "revalidate_run" for item in detail.actions
        )
        # ...and the service refuses even with a forged descriptor id.
        command = CorrectionRequest(
            correction_type="revalidate",
            permitted_output_scope=[_scope(fixture)],
            action_descriptor_id="action.forged",
        )
        receipt = await _preserve(stack.service, command, "corr-blocked")
        with pytest.raises(CommandRejected) as caught:
            await stack.service.request_output_correction(
                PROJECT, RUN, command, raw_request=receipt
            )
        assert caught.value.error.code == "CORRECTION_NOT_APPLICABLE"

    asyncio.run(scenario())


def test_correction_rejects_out_of_scope_output(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
        stack = _ServiceStack(fixture)
        _seal_failed_base_closure(fixture, "theorist")
        _set_run(fixture, "failed", _run_payload(fixture, CORRECTABLE))
        detail = await stack.service.get_run(PROJECT, RUN)
        action = _correction_action(detail)
        command = CorrectionRequest(
            correction_type="revalidate",
            permitted_output_scope=["output.not_declared"],
            action_descriptor_id=action.descriptor_id,
        )
        receipt = await _preserve(stack.service, command, "corr-scope")
        with pytest.raises(CommandRejected) as caught:
            await stack.service.request_output_correction(
                PROJECT, RUN, command, raw_request=receipt
            )
        assert caught.value.error.code == "CORRECTION_SCOPE_INVALID"

    asyncio.run(scenario())


def test_correction_rejects_unimplemented_type(tmp_path: Path) -> None:
    async def scenario() -> None:
        fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
        stack = _ServiceStack(fixture)
        _set_run(fixture, "failed", _run_payload(fixture, CORRECTABLE))
        command = CorrectionRequest(
            correction_type="normalize",
            permitted_output_scope=[_scope(fixture)],
            action_descriptor_id="action.any",
            transformation_codes=["schema.legacy_id"],
        )
        receipt = await _preserve(stack.service, command, "corr-type")
        with pytest.raises(CommandRejected) as caught:
            await stack.service.request_output_correction(
                PROJECT, RUN, command, raw_request=receipt
            )
        assert caught.value.error.code == "CORRECTION_NOT_APPLICABLE"

    asyncio.run(scenario())
