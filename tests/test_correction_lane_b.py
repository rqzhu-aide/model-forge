"""K-1c Lane B: blast-radius verification + correction instruction (P5a-i).

Unit coverage for ``verify_correction_blast_radius`` (design 4a: a
correction is a patch with a verified blast radius) and the
``permitted_pointers`` extension of ``build_correction_instruction``.
Lane B integration tests land with the execution core (P5a-ii).
"""

from __future__ import annotations

from model_forge.application.correction import build_correction_instruction
from model_forge.application.correction_execution import (
    verify_correction_blast_radius,
)
from model_forge.domain.validation import make_finding


def _verify(source, corrected, correction_type, pointers, scope):
    return verify_correction_blast_radius(
        source_outputs=source,
        corrected_outputs=corrected,
        correction_type=correction_type,
        permitted_pointers=frozenset(pointers),
        output_scope=frozenset(scope),
    )


# --------------------------------------------------------------------------- #
# verify_correction_blast_radius
# --------------------------------------------------------------------------- #


def test_identical_outputs_are_clean() -> None:
    doc = {"a": 1, "b": [1, 2]}
    assert _verify({"out": doc}, {"out": doc}, "packaging", set(), {"out"}) == ()


def test_packaging_change_at_permitted_pointer_is_clean() -> None:
    source = {"out": {"created_at": None, "title": "x"}}
    corrected = {"out": {"created_at": "2026-08-19", "title": "x"}}
    assert _verify(
        source, corrected, "packaging", {"/created_at"}, {"out"}
    ) == ()


def test_packaging_change_below_permitted_pointer_is_clean() -> None:
    source = {"out": {"meta": {"created_at": None}}}
    corrected = {"out": {"meta": {"created_at": "2026-08-19"}}}
    assert _verify(source, corrected, "packaging", {"/meta"}, {"out"}) == ()


def test_packaging_change_outside_permitted_pointer_violates() -> None:
    source = {"out": {"created_at": None, "title": "x"}}
    corrected = {"out": {"created_at": "2026-08-19", "title": "CHANGED"}}
    violations = _verify(source, corrected, "packaging", {"/created_at"}, {"out"})
    assert len(violations) == 1
    assert violations[0].code == "correction.blast_radius_violated"
    assert violations[0].json_pointer == "/title"
    assert violations[0].blocks_publication is True


def test_scientific_in_scope_change_is_clean() -> None:
    source = {"out": {"claim": "weak"}}
    corrected = {"out": {"claim": "strong", "extra": [1]}}
    assert _verify(source, corrected, "scientific", set(), {"out"}) == ()


def test_out_of_scope_change_violates_for_both_types() -> None:
    source = {"scoped": {"a": 1}, "other": {"b": 2}}
    corrected = {"scoped": {"a": 9}, "other": {"b": 3}}
    for correction_type in ("packaging", "scientific"):
        violations = _verify(
            source, corrected, correction_type, {"/a"}, {"scoped"}
        )
        assert len(violations) == 1
        assert violations[0].code == "correction.blast_radius_violated"
        assert "out-of-scope" in violations[0].message


def test_array_index_paths() -> None:
    source = {"out": {"items": [1, 2, 3]}}
    corrected = {"out": {"items": [1, 9, 3]}}
    violations = _verify(source, corrected, "packaging", {"/items/0"}, {"out"})
    assert len(violations) == 1
    assert violations[0].json_pointer == "/items/1"
    assert _verify(source, corrected, "packaging", {"/items"}, {"out"}) == ()


# --------------------------------------------------------------------------- #
# build_correction_instruction permitted_pointers
# --------------------------------------------------------------------------- #


def _findings():
    return (
        make_finding("schema.required", "'created_at' is required", pointer=""),
    )


def test_packaging_instruction_lists_sorted_pointers() -> None:
    text = build_correction_instruction(
        correction_type="packaging",
        findings=_findings(),
        output_scope=("p1.theory",),
        permitted_pointers=("/created_at", "/meta"),
    )
    assert "change ONLY these" in text
    assert "  - /created_at" in text
    assert "  - /meta" in text
    assert text.index("/created_at") < text.index("/meta")  # sorted order


def test_scientific_instruction_ignores_pointers() -> None:
    text = build_correction_instruction(
        correction_type="scientific",
        findings=_findings(),
        output_scope=("p1.theory",),
        user_instruction="Downgrade the claim.",
        permitted_pointers=("/created_at",),
    )
    assert "change ONLY these" not in text
    assert "Downgrade the claim." in text


# --------------------------------------------------------------------------- #
# P5a-ii: Lane B correction role re-invocation (execute_targeted_correction)
# --------------------------------------------------------------------------- #

import asyncio
import dataclasses
import json
from pathlib import Path

from model_forge.application.correction_execution import execute_targeted_correction
from model_forge.executors import DeterministicFakeExecutor
from model_forge.harness.execution_records import correction_role_identity
from model_forge.harness.stage_execution import HarnessExecutionServices
from model_forge.json_io import loads_json

from test_correction_command_path import (
    PROJECT,
    RUN,
    _scope,
    _seal_failed_closure_bytes,
)
from test_correction_execution import _Fixture, _PermissiveSchemas
from test_correction_normalize import _fixable_defect_bytes
from test_correction_submission import _golden_output


def _lane_b_services(
    fixture: _Fixture, command_id: str, correction_type: str
) -> HarnessExecutionServices:
    """_correction_services pattern with a Lane B correction type."""
    context = dataclasses.replace(
        fixture.context,
        submission_from_status="correcting",
        correction_command_id=command_id,
        correction_type=correction_type,
    )
    return HarnessExecutionServices(
        context=context,
        repository=fixture.repository,
        executor=fixture.executor,
        schemas=_PermissiveSchemas(),
        artifacts=fixture.artifacts,
        workspace=fixture.workspace,
    )


def _drive(
    fixture: _Fixture,
    services: HarnessExecutionServices,
    base_closure_id: str,
    command_id: str,
    correction_type: str,
    scope: tuple[str, ...],
    user_instruction: str | None = None,
):
    return asyncio.run(
        execute_targeted_correction(
            services=services,
            repository=fixture.repository,
            specification=fixture.specification,
            artifacts=fixture.artifacts,
            run_id=RUN,
            role_closure_id=base_closure_id,
            correction_command_id=command_id,
            correction_type=correction_type,
            permitted_output_scope=scope,
            user_instruction=user_instruction,
        )
    )


def _golden_with_unrelated_change(invocation, offset: int):
    """Conforming golden bytes plus one agent-authored field rewritten."""
    document = _golden_output(invocation, offset)
    if isinstance(document, dict) and "completed_work" in document:
        document = dict(document)
        document["completed_work"] = "REWITTEN BY AN OVERREACHING CORRECTION"
    return document


def test_packaging_correction_passes(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    base_payload_before = fixture.repository.get_role_closure(base_closure_id)[
        "payload_json"
    ]
    # A base-run task brief exists and must survive the correction untouched.
    base_task = (
        fixture.workspace.root / "runs" / RUN / "tasks" / "01-theorist" / "task.md"
    )
    base_task.parent.mkdir(parents=True, exist_ok=True)
    base_task.write_bytes(b"BASE TASK BRIEF - DO NOT OVERWRITE")

    services = _lane_b_services(fixture, "cmd_b1", "packaging")
    outcome = _drive(
        fixture,
        services,
        base_closure_id,
        "cmd_b1",
        "packaging",
        (_scope(fixture),),
    )

    assert outcome.passed is True
    assert outcome.findings == ()
    expected_id = correction_role_identity(
        RUN, fixture.recipe.sha256, fixture.stage, "theorist", "cmd_b1"
    )[2]
    assert outcome.closure_id == expected_id

    # The family-aware load_existing returns the SUCCEEDED correction closure.
    closure = services.roles.load_existing(stage=fixture.stage, role="theorist")
    assert closure is not None
    assert closure.closure_id == outcome.closure_id
    assert closure.status.value == "succeeded"

    # Exactly one validation attempt row, bound to the packaging command.
    attempts = fixture.repository.list_validation_attempts(RUN)
    assert len(attempts) == 1
    assert attempts[0]["correction_type"] == "packaging"
    assert attempts[0]["correction_command_id"] == "cmd_b1"
    report = json.loads(attempts[0]["report_json"])
    assert report["passed"] is True

    # The source closure payload is unchanged; the base task brief survives.
    assert (
        fixture.repository.get_role_closure(base_closure_id)["payload_json"]
        == base_payload_before
    )
    assert base_task.read_bytes() == b"BASE TASK BRIEF - DO NOT OVERWRITE"

    # The correction ran in correction-suffixed workspace dirs.
    run_dir = fixture.workspace.root / "runs" / RUN
    assert (run_dir / "roles" / "01-theorist.correction.cmd_b1").is_dir()
    assert (
        run_dir / "tasks" / "01-theorist.correction.cmd_b1" / "task.md"
    ).is_file()


def test_packaging_correction_blast_violation_fails(tmp_path: Path) -> None:
    fixture = _Fixture(
        tmp_path, DeterministicFakeExecutor(_golden_with_unrelated_change)
    )
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    services = _lane_b_services(fixture, "cmd_b1", "packaging")
    outcome = _drive(
        fixture,
        services,
        base_closure_id,
        "cmd_b1",
        "packaging",
        (_scope(fixture),),
    )

    assert outcome.passed is False
    assert any(
        item.code == "correction.blast_radius_violated"
        for item in outcome.findings
    )
    row = fixture.repository.get_role_closure(outcome.closure_id)
    assert row is not None
    document = loads_json(row["payload_json"], source="correction closure")
    assert document["status"] == "failed"
    assert any(
        item["code"] == "correction.blast_radius_violated"
        for item in document["findings"]
    )

    # A FAILED correction closure never enters the family-aware walk: the
    # base closure is the fallback.
    closure = services.roles.load_existing(stage=fixture.stage, role="theorist")
    assert closure is not None
    assert closure.closure_id == base_closure_id


def test_scientific_correction_out_of_scope_fails(tmp_path: Path) -> None:
    # DEVIATION D: the theorist has exactly one output, so an empty scope
    # makes any change a blast-radius violation.
    fixture = _Fixture(tmp_path, DeterministicFakeExecutor(_golden_output))
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    services = _lane_b_services(fixture, "cmd_b1", "scientific")
    outcome = _drive(
        fixture,
        services,
        base_closure_id,
        "cmd_b1",
        "scientific",
        (),
    )

    assert outcome.passed is False
    assert any(
        item.code == "correction.blast_radius_violated"
        for item in outcome.findings
    )
    row = fixture.repository.get_role_closure(outcome.closure_id)
    assert row is not None
    document = loads_json(row["payload_json"], source="correction closure")
    assert document["status"] == "failed"


def test_correction_replay_is_idempotent(tmp_path: Path) -> None:
    executor = DeterministicFakeExecutor(_golden_output)
    fixture = _Fixture(tmp_path, executor)
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    services = _lane_b_services(fixture, "cmd_b1", "packaging")
    first = _drive(
        fixture,
        services,
        base_closure_id,
        "cmd_b1",
        "packaging",
        (_scope(fixture),),
    )
    assert first.passed is True
    invocations_after_first = len(executor.invocations)

    second = _drive(
        fixture,
        services,
        base_closure_id,
        "cmd_b1",
        "packaging",
        (_scope(fixture),),
    )

    assert second.closure_id == first.closure_id
    assert second.passed is True
    assert len(executor.invocations) == invocations_after_first
    assert fixture.repository.count_validation_attempts(RUN) == 1


# --------------------------------------------------------------------------- #
# F-3: correction closures populate harness-owned envelope fields (HV-4)
# --------------------------------------------------------------------------- #


def _golden_missing_envelope(invocation, offset: int):
    """Golden bytes minus every harness-owned envelope field (F-3 shape).

    Production, 2026-08-26: a scientific correction wrote structurally sound
    content but omitted schema_version/created_at; the correction close path
    validated the raw bytes directly (unlike the normal close path, which
    populates HV-4 fields first) and burned the attempt on schema.required
    plumbing findings.
    """
    document = _golden_output(invocation, offset)
    if isinstance(document, dict) and "handoff_id" in document:
        document = {
            key: value
            for key, value in document.items()
            if key
            not in {
                "schema_version",
                "created_at",
                "content_sha256",
                "run_id",
                "phase",
                "sequence",
                "from_role",
                "to_role",
                "handoff_id",
            }
        }
    return document


def test_correction_close_populates_harness_owned_fields(tmp_path: Path) -> None:
    from model_forge.schemas import SchemaCatalog
    from test_correction_execution import ARCHITECTURE

    fixture = _Fixture(
        tmp_path, DeterministicFakeExecutor(_golden_missing_envelope)
    )
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )
    # REAL schema catalog: without HV-4 population the stripped output fails
    # validation exactly as it did in production.
    context = dataclasses.replace(
        fixture.context,
        submission_from_status="correcting",
        correction_command_id="cmd_f3",
        correction_type="scientific",
    )
    services = HarnessExecutionServices(
        context=context,
        repository=fixture.repository,
        executor=fixture.executor,
        schemas=SchemaCatalog.load(ARCHITECTURE / "schemas"),
        artifacts=fixture.artifacts,
        workspace=fixture.workspace,
    )
    outcome = _drive(
        fixture,
        services,
        base_closure_id,
        "cmd_f3",
        "scientific",
        (_scope(fixture),),
        user_instruction="Re-issue the handoff without envelope fields.",
    )

    assert outcome.passed is True
    assert outcome.findings == ()

    row = fixture.repository.get_role_closure(outcome.closure_id)
    assert row is not None
    document = loads_json(row["payload_json"], source="correction closure")
    assert document["status"] == "succeeded"
    # The population is disclosed on the closure as transformation records.
    assert document["output_transformations"], (
        "envelope population must be recorded as output transformations"
    )

    # The sealed corrected bytes carry the populated envelope fields.
    sealed = document["outputs"][0]
    stored = fixture.artifacts.read_bytes(sealed["sha256"])
    corrected = loads_json(stored, source="sealed correction output")
    assert corrected["schema_version"]
    assert corrected["created_at"]
    assert corrected["run_id"] == RUN
    assert corrected["from_role"] == "theorist"


def test_packaging_wholesale_creation_of_source_absent_output_is_clean() -> None:
    # K5-3: the source closure sealed no bytes for the output (validation
    # failed before sealing); wholesale creation in scope is the
    # correction's purpose, not a blast-radius violation.
    corrected = {"out": {"created_at": "2026-08-20", "title": "fresh"}}
    assert _verify({}, corrected, "packaging", set(), {"out"}) == ()


def test_packaging_source_absent_out_of_scope_output_still_violates() -> None:
    # The scope gate still bounds which outputs may appear at all.
    corrected = {"other": {"title": "surprise"}}
    violations = _verify({}, corrected, "packaging", set(), {"out"})
    assert [v.code for v in violations] == ["correction.blast_radius_violated"]


def test_packaging_root_change_with_present_source_still_violates() -> None:
    # A present source replaced wholesale (root change) remains a violation:
    # the K5-3 skip applies only when the source is genuinely absent.
    source = {"out": {"title": "old"}}
    corrected = {"out": "not-even-an-object"}
    violations = _verify(source, corrected, "packaging", set(), {"out"})
    assert [v.code for v in violations] == ["correction.blast_radius_violated"]


def test_executor_failed_correction_spends_the_bounded_attempt(tmp_path: Path) -> None:
    """HV-5.6: an executor-level failure still consumes the lane's attempt.

    Without the attempt row a persistently failing agent could be retried
    forever and the run would never reach correction_exhausted.
    """
    fixture = _Fixture(
        tmp_path,
        DeterministicFakeExecutor(_golden_output, fail_roles=frozenset({"theorist"})),
    )
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )

    services = _lane_b_services(fixture, "cmd_b_fail", "packaging")
    outcome = _drive(
        fixture,
        services,
        base_closure_id,
        "cmd_b_fail",
        "packaging",
        (_scope(fixture),),
    )

    assert outcome.passed is False
    correction_closure = fixture.repository.get_role_closure(outcome.closure_id)
    assert correction_closure is not None
    correction_payload = loads_json(
        correction_closure["payload_json"], source="correction closure"
    )
    assert correction_payload["status"] == "failed"
    assert correction_payload["failure_code"] == "executor.role_failed"

    # The bounded attempt is spent: exactly one failed attempt row exists,
    # bound to the packaging lane and command.
    attempts = fixture.repository.list_validation_attempts(RUN)
    assert len(attempts) == 1
    assert attempts[0]["correction_type"] == "packaging"
    assert attempts[0]["correction_command_id"] == "cmd_b_fail"
    report = json.loads(attempts[0]["report_json"])
    assert report["passed"] is False
    assert [item["code"] for item in report["findings"]] == ["executor.role_failed"]
