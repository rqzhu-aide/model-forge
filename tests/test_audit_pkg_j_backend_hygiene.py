"""Audit-2026-09-02 Package P-J: backend hygiene regression coverage.

F13: ``_recover_frozen_contract`` (both copies) skips an unreadable/corrupt
     ``phase_contract_frozen`` artifact row instead of aborting recovery.
F14: ``_fix_record`` iterates to a fixpoint so ``handoff_artifact.sha256``
     seals the FINAL corrected content snapshot, not a stale one.
F15: the executor-failed correction close path preserves the agent's raw
     workspace bytes (R7 parity with the validated-failure path).
F18: ``validate_materialization`` is genuinely side-effect-free: the R32
     bundle digest is computed in memory without ``put_bytes`` /
     ``record_artifact`` writes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from model_forge.application.run_coordinator import RunCoordinator
from model_forge.digests.jcs import canonicalize
from model_forge.executors import DeterministicFakeExecutor
from model_forge.harness.publication import (
    ContractPublicationService,
    FrozenPublicationHead,
)
from model_forge.storage.repository import HubRepository, ZERO_SHA256
from model_forge.storage import ArtifactStore

from test_correction_command_path import (
    RUN,
    _scope,
    _seal_failed_closure_bytes,
)
from test_correction_execution import _Fixture
from test_correction_lane_b import _drive, _lane_b_services
from test_correction_normalize import _fixable_defect_bytes
from test_correction_submission import _golden_output
from test_frozen_contract_recovery import (
    _recipe_document,
    specification,  # noqa: F401  (fixture)
    stores,  # noqa: F401  (fixture)
)
from test_harness_publication import (
    _artifact_store,
    _bundle_binding,
    _output,
    _repository,
    _run,
)


# --------------------------------------------------------------------------- #
# F13: corrupt frozen-contract artifact rows are skipped, not fatal
# --------------------------------------------------------------------------- #

def _seed_corrupt_then_correct(specification, repository, artifacts):
    """Seed a correct pinned contract row (older) and a corrupt row (newer).

    ``find_artifacts_by_purpose`` scans newest first, so the corrupt row is
    encountered BEFORE the intact one - the pre-fix loop aborts on it.
    """
    document = specification.phases.contract_document("P1")
    identity = specification.phases.identity("P1")
    stored = artifacts.put_bytes(canonicalize(document))
    repository.record_artifact(
        "artifact.phase_contract.intact",
        "prj_frozen",
        str(stored.sha256),
        stored.size,
        "application/json",
        f"artifact://sha256/{stored.sha256}",
        {"purpose": "phase_contract_frozen", "phase_id": "P1"},
        recorded_at="2026-09-01T00:00:00Z",
    )
    corrupt = artifacts.put_bytes(b"{ this is not valid json")
    repository.record_artifact(
        "artifact.phase_contract.corrupt",
        "prj_frozen",
        str(corrupt.sha256),
        corrupt.size,
        "application/json",
        f"artifact://sha256/{corrupt.sha256}",
        {"purpose": "phase_contract_frozen", "phase_id": "P1"},
        recorded_at="2026-09-02T00:00:00Z",
    )
    return document, str(identity.phase_contract_sha256)


@pytest.mark.parametrize("call_path", ["run_coordinator", "correction_execution"])
def test_frozen_contract_recovery_skips_corrupt_artifact_row(
    specification, stores, call_path
) -> None:
    repository, artifacts = stores
    document, pinned = _seed_corrupt_then_correct(
        specification, repository, artifacts
    )

    if call_path == "run_coordinator":
        coordinator = RunCoordinator.__new__(RunCoordinator)
        coordinator.specification = specification
        coordinator.repository = repository
        coordinator.artifacts = artifacts

        class _Recipe:
            document = _recipe_document(
                specification, stale_version="0.0.0-superseded"
            )

        recovered = coordinator._recover_frozen_contract(_Recipe())
    else:
        from model_forge.application.correction_execution import (
            _recover_frozen_contract,
        )

        recovered = _recover_frozen_contract(
            specification, repository, artifacts, "prj_frozen", pinned
        )

    assert recovered == document


# --------------------------------------------------------------------------- #
# F14: handoff_artifact.sha256 fixpoint seals the final content snapshot
# --------------------------------------------------------------------------- #

def test_handoff_artifact_sha256_seals_final_content_snapshot(
    tmp_path: Path,
) -> None:
    from model_forge.harness.role_execution import _fix_self_referential_hashes

    output = tmp_path / "output.json"
    output.write_text("{}")
    record = {
        "handoff_id": "ho.f14",
        "handoff_artifact": {
            "media_type": "application/json",
            "sha256": "0" * 64,  # stale
        },
        "content_sha256": "1" * 64,  # stale; corrected at step 5
        "completed_work": ["did_something"],
    }

    changed = _fix_self_referential_hashes(record, output)
    assert changed is True

    # The handoff hash must cover the record carrying the FINAL corrected
    # content_sha256 - pre-fix it covers the stale "1"*64 snapshot.
    snapshot = dict(record)
    snapshot["handoff_artifact"] = {
        key: value
        for key, value in record["handoff_artifact"].items()
        if key != "sha256"
    }
    expected = hashlib.sha256(canonicalize(snapshot)).hexdigest()
    assert record["handoff_artifact"]["sha256"] == expected

    # NOTE: a hybrid record carrying BOTH content_sha256 and handoff_artifact
    # is not idempotent under any stamping order (each hash covers the other;
    # no contracted record type has both fields - handoff.schema.json has no
    # content_sha256, and the *.content digest contracts cover schemas with
    # no handoff_artifact).  Idempotency for content-only records is pinned
    # by test_harness_repairs.py::test_content_sha256_idempotent.


# --------------------------------------------------------------------------- #
# F15: executor-failed corrections preserve the agent's raw bytes (R7 parity)
# --------------------------------------------------------------------------- #

def test_executor_failed_correction_preserves_raw_output(tmp_path: Path) -> None:
    fixture = _Fixture(
        tmp_path,
        DeterministicFakeExecutor(
            _golden_output, fail_roles=frozenset({"theorist"})
        ),
    )
    base_closure_id = _seal_failed_closure_bytes(
        fixture, "theorist", _fixable_defect_bytes()
    )

    services = _lane_b_services(fixture, "cmd_f15", "packaging")
    outcome = _drive(
        fixture,
        services,
        base_closure_id,
        "cmd_f15",
        "packaging",
        (_scope(fixture),),
    )

    assert outcome.passed is False
    row = fixture.repository.get_role_closure(outcome.closure_id)
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["status"] == "failed"
    assert payload["failure_code"] == "executor.role_failed"

    # R7 mirror: even though the executor failed, the correction workspace's
    # raw bytes are sealed into the artifact store and pinned on the closure.
    raw_sha256 = payload["raw_output_sha256"]
    assert type(raw_sha256) is str
    assert len(raw_sha256) == 64
    assert all(character in "0123456789abcdef" for character in raw_sha256)
    fixture.artifacts.verify(raw_sha256)


# --------------------------------------------------------------------------- #
# F18: validate_materialization is side-effect-free; publish persists
# --------------------------------------------------------------------------- #

def test_validate_materialization_writes_no_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    run_id, command_id = _run(repository, "f18_dry_run")
    manuscript = _output(
        repository, "p5.manuscript_candidate", {"title": "A manuscript"}
    )
    trace = _output(
        repository, "p5.claim_traceability", {"claims": ["claim.one"]}
    )
    outputs = {
        manuscript.contract_output_id: manuscript,
        trace.contract_output_id: trace,
    }
    artifacts = _artifact_store(tmp_path)

    calls = {"put_bytes": 0, "record_artifact": 0}
    real_put_bytes = ArtifactStore.put_bytes
    real_record_artifact = HubRepository.record_artifact

    def spy_put_bytes(self, *args, **kwargs):
        calls["put_bytes"] += 1
        return real_put_bytes(self, *args, **kwargs)

    def spy_record_artifact(self, *args, **kwargs):
        calls["record_artifact"] += 1
        return real_record_artifact(self, *args, **kwargs)

    monkeypatch.setattr(ArtifactStore, "put_bytes", spy_put_bytes)
    monkeypatch.setattr(HubRepository, "record_artifact", spy_record_artifact)

    slot = "methods/method.alpha/v1/p5.manuscript.current"
    service = ContractPublicationService(repository)
    service.validate_materialization(
        project_id="project.publication",
        run_id=run_id,
        command_id=command_id,
        bindings=[_bundle_binding()],
        outputs=outputs,
        expected_head=FrozenPublicationHead(0, ZERO_SHA256, 0, {slot: None}),
        slot_scope_prefix="methods/method.alpha/v1",
        artifacts=artifacts,
    )

    # The dry-run bundle check must not touch the artifact store or the
    # artifact registry at all.
    assert calls == {"put_bytes": 0, "record_artifact": 0}

    # Guard the other half of the contract: publish still persists the bundle.
    from datetime import datetime, timezone

    result = service.publish(
        project_id="project.publication",
        run_id=run_id,
        command_id=command_id,
        bindings=[_bundle_binding()],
        outputs=outputs,
        expected_head=FrozenPublicationHead(0, ZERO_SHA256, 0, {slot: None}),
        published_at=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
        slot_scope_prefix="methods/method.alpha/v1",
        artifacts=artifacts,
    )
    assert calls == {"put_bytes": 1, "record_artifact": 1}
    assert set(result.current_slots) == {slot}
    current = repository.get_current_record("project.publication", slot)
    assert current is not None
    bundle = json.loads(current["payload_json"])
    assert bundle["format"] == "model-forge.deterministic-bundle"
