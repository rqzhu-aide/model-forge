from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from method_hub.storage.repository import (
    HubRepository,
    RepositoryConflictError,
    ZERO_SHA256,
)


def _digest(character: str) -> str:
    return character * 64


@pytest.fixture
def repository(tmp_path: Path) -> HubRepository:
    result = HubRepository(tmp_path / "hub.sqlite3")
    assert result.initialize() == 13
    result.create_project("prj_repo", {"name": "Repository test"})
    return result


def _command(
    repository: HubRepository,
    suffix: str,
    *,
    idempotency_key: str | None = None,
) -> str:
    request_id = f"req_{suffix}"
    command_id = f"cmd_{suffix}"
    repository.record_raw_command(
        request_id,
        "prj_repo",
        _digest("a"),
        {"request": suffix},
    )
    repository.seal_command(
        command_id,
        "prj_repo",
        request_id,
        idempotency_key or f"key_{suffix}",
        _digest("b"),
        {"command": suffix},
    )
    return command_id


def _run(repository: HubRepository, suffix: str) -> str:
    command_id = _command(repository, suffix)
    run_id = f"run_{suffix}"
    repository.create_run(
        run_id,
        "prj_repo",
        command_id,
        "created",
        {"state": "created"},
        f"evt_{suffix}_created",
        _digest("c"),
        {"to": "created"},
    )
    return run_id


def test_commands_are_project_idempotent_and_runs_use_sequence_cas(
    repository: HubRepository,
) -> None:
    command_id = _command(repository, "main", idempotency_key="one-action")
    repeated = repository.seal_command(
        command_id,
        "prj_repo",
        "req_main",
        "one-action",
        _digest("b"),
        {"command": "main"},
    )
    assert repeated.created is False

    repository.record_raw_command(
        "req_conflict", "prj_repo", _digest("d"), {"request": "different"}
    )
    with pytest.raises(RepositoryConflictError) as raised:
        repository.seal_command(
            "cmd_conflict",
            "prj_repo",
            "req_conflict",
            "one-action",
            _digest("e"),
            {"command": "different"},
        )
    assert raised.value.code == "repository.idempotency_key_reused"

    created = repository.create_run(
        "run_main",
        "prj_repo",
        command_id,
        "created",
        {"state": "created"},
        "evt_run_created",
        _digest("f"),
        {"to": "created"},
    )
    assert created.created is True
    advanced = repository.compare_and_swap_run(
        "run_main",
        "created",
        1,
        "running",
        {"state": "running"},
        "evt_run_running",
        _digest("1"),
        {"from": "created", "to": "running"},
    )
    stale = repository.compare_and_swap_run(
        "run_main",
        "created",
        1,
        "failed",
        {"state": "failed"},
        "evt_stale",
        _digest("2"),
        {"to": "failed"},
    )

    assert advanced.applied is True
    assert stale.reason == "compare_and_swap_failed"
    assert [row["sequence"] for row in repository.list_run_events("run_main")] == [
        1,
        2,
    ]


def test_frozen_manifest_execution_records_and_revisioned_settings(
    repository: HubRepository,
) -> None:
    run_id = _run(repository, "execution")
    first_manifest = repository.freeze_manifest(
        run_id, _digest("3"), {"run_id": run_id}
    )
    repeated_manifest = repository.freeze_manifest(
        run_id, _digest("3"), {"run_id": run_id}
    )
    assert first_manifest.created is True
    assert repeated_manifest.created is False
    with pytest.raises(RepositoryConflictError):
        repository.freeze_manifest(run_id, _digest("4"), {"changed": True})

    intent = repository.get_or_create_execution(
        "exec_1",
        "inv_1",
        run_id,
        _digest("5"),
        {"stage": "stage_1", "role": "analyst"},
    )
    recovered = repository.get_or_create_execution(
        "exec_replacement_not_used",
        "inv_1",
        run_id,
        _digest("5"),
        {"stage": "stage_1", "role": "analyst"},
    )
    repository.acknowledge_execution("exec_1", "external_1", {"accepted": True})
    heartbeat = repository.append_execution_heartbeat(
        "exec_1", "heartbeat_1", {"activity": "working"}
    )
    repository.close_execution(
        "exec_1", "closure_1", _digest("6"), {"status": "succeeded"}
    )

    assert intent.created is True
    assert recovered.created is False
    assert recovered.row["execution_id"] == "exec_1"
    assert heartbeat.row["sequence"] == 1

    mapping = repository.set_profile_mapping(
        "prj_repo",
        "analyst",
        "default",
        {"skills": ["statistics"]},
        expected_revision=0,
    )
    setting = repository.set_project_setting(
        "prj_repo", "theme", {"value": "dark"}, expected_revision=0
    )
    assert mapping["revision"] == 1
    assert setting["revision"] == 1
    with pytest.raises(RepositoryConflictError):
        repository.set_project_setting(
            "prj_repo", "theme", {"value": "light"}, expected_revision=0
        )


def test_cancellation_fence_wins_over_immutable_submission(
    repository: HubRepository,
) -> None:
    run_id = _run(repository, "cancel")
    cancel_command = _command(repository, "cancel_command")
    cancelled = repository.request_cancellation(
        run_id,
        cancel_command,
        "created",
        1,
        {"state": "cancellation_requested"},
        "evt_cancel_requested",
        _digest("7"),
        {"to": "cancellation_requested"},
    )
    submitted = repository.seal_submission(
        run_id,
        "submission_late",
        _digest("8"),
        "created",
        1,
        "submitted",
        {"submission": "late"},
        {"state": "submitted"},
        "evt_submission_late",
        _digest("9"),
        {"to": "submitted"},
    )

    assert cancelled.applied is True
    assert repository.cancellation_requested(run_id) is True
    assert submitted.applied is False
    assert submitted.reason == "cancellation_fenced"
    assert repository.get_submission(run_id) is None


def test_publication_unit_of_work_is_atomic_and_current_queries_are_direct(
    repository: HubRepository,
) -> None:
    run_id = _run(repository, "publish")
    repository.record_artifact(
        "art_record",
        "prj_repo",
        _digest("a"),
        12,
        "application/json",
        "artifact://art_record",
        {"kind": "record"},
    )
    content_digest = _digest("b")
    event_root = hashlib.sha256(
        bytes.fromhex(ZERO_SHA256) + bytes.fromhex(content_digest)
    ).hexdigest()

    with repository.publication_transaction(
        "prj_repo",
        "receipt_1",
        0,
        ZERO_SHA256,
        expected_current_revision=0,
    ) as publication:
        publication.add_formal_generation(
            "generation_1",
            "generic_record",
            "art_record",
            _digest("c"),
            {"record": 1},
            logical_slot="slot/current",
            source_run_id=run_id,
        )
        publication.replace_current_slot(
            "slot/current", "generation_1", expected_generation_id=None
        )
        publication.append_collection_item(
            "collection/items",
            "item_1",
            "generic_item",
            _digest("d"),
            {"item": 1},
            source_run_id=run_id,
        )
        publication.append_authority_event(
            "authority_1",
            "generic_published",
            content_digest,
            event_root,
            {"event": 1},
        )
        publication.record_receipt(
            _digest("e"), {"receipt": 1}, run_id=run_id
        )

    current = repository.get_current_record("prj_repo", "slot/current")
    assert current is not None
    assert current["generation_id"] == "generation_1"
    assert len(repository.list_current_records("prj_repo")) == 1
    assert len(repository.list_collection_items("prj_repo", "collection/items")) == 1
    assert repository.get_publication_receipt("receipt_1") is not None

    next_content = _digest("f")
    next_root = hashlib.sha256(
        bytes.fromhex(event_root) + bytes.fromhex(next_content)
    ).hexdigest()
    with pytest.raises(RuntimeError, match="rollback publication"):
        with repository.publication_transaction(
            "prj_repo",
            "receipt_rollback",
            1,
            event_root,
            expected_current_revision=1,
        ) as publication:
            publication.add_formal_generation(
                "generation_rollback",
                "generic_record",
                "art_record",
                _digest("1"),
                {"record": 2},
                logical_slot="slot/current",
                source_run_id=run_id,
            )
            publication.replace_current_slot(
                "slot/current",
                "generation_rollback",
                expected_generation_id="generation_1",
            )
            publication.append_authority_event(
                "authority_rollback",
                "generic_published",
                next_content,
                next_root,
                {"event": 2},
            )
            publication.record_receipt(
                _digest("2"), {"receipt": 2}, run_id=run_id
            )
            raise RuntimeError("rollback publication")

    current = repository.get_current_record("prj_repo", "slot/current")
    assert current is not None
    assert current["generation_id"] == "generation_1"
    assert repository.get_publication_receipt("receipt_rollback") is None



def test_cumulative_collection_deduplicates_content_from_later_runs(
    repository: HubRepository,
) -> None:
    first_run = _run(repository, "collection_first")
    second_run = _run(repository, "collection_second")
    event_content = _digest("8")
    event_root = hashlib.sha256(
        bytes.fromhex(ZERO_SHA256) + bytes.fromhex(event_content)
    ).hexdigest()

    with repository.publication_transaction(
        "prj_repo",
        "receipt_collection",
        0,
        ZERO_SHA256,
        expected_current_revision=0,
    ) as publication:
        first = publication.append_collection_item(
            "collection/items",
            "item_same_content",
            "attention_item",
            _digest("9"),
            {"question": "Does the conclusion remain stable?"},
            source_run_id=first_run,
        )
        repeated = publication.append_collection_item(
            "collection/items",
            "item_same_content",
            "attention_item",
            _digest("9"),
            {"question": "Does the conclusion remain stable?"},
            source_run_id=second_run,
        )
        publication.append_authority_event(
            "authority_collection",
            "generic_published",
            event_content,
            event_root,
            {"event": "collection"},
        )
        publication.record_receipt(
            _digest("7"), {"receipt": "collection"}, run_id=first_run
        )

    assert first.created is True
    assert repeated.created is False
    stored = repository.list_collection_items("prj_repo", "collection/items")
    assert len(stored) == 1
    assert stored[0]["source_run_id"] == first_run


def test_validation_attempts_round_trip_latest_and_list_ordering(
    repository: HubRepository,
) -> None:
    run_id = _run(repository, "validation_roundtrip")
    first = repository.record_validation_attempt(
        "attempt_v1",
        run_id,
        1,
        "1.0.0",
        '{"verdict": "fail"}',
        _digest("a"),
    )
    assert first["attempted_at"]
    repository.record_validation_attempt(
        "attempt_v2",
        run_id,
        2,
        "1.0.0",
        '{"verdict": "pass"}',
        _digest("b"),
        correction_type="revalidate",
        prior_attempt_id="attempt_v1",
        correction_command_id="cmd_validate",
    )
    repository.record_validation_attempt(
        "attempt_v3",
        run_id,
        3,
        "2.0.0",
        '{"verdict": "pass"}',
        _digest("c"),
        correction_type="normalize",
        prior_attempt_id="attempt_v2",
    )

    fetched = repository.get_validation_attempt("attempt_v2")
    assert fetched is not None
    assert fetched["attempt_ordinal"] == 2
    assert fetched["prior_attempt_id"] == "attempt_v1"
    assert fetched["correction_command_id"] == "cmd_validate"
    assert repository.get_validation_attempt("attempt_missing") is None

    latest = repository.get_latest_validation_attempt(run_id)
    assert latest is not None
    assert latest["attempt_id"] == "attempt_v3"
    assert repository.get_latest_validation_attempt("run_missing") is None

    listed = repository.list_validation_attempts(run_id)
    assert [row["attempt_id"] for row in listed] == [
        "attempt_v1",
        "attempt_v2",
        "attempt_v3",
    ]
    assert repository.list_validation_attempts("run_missing") == []


def test_count_validation_attempts_with_and_without_correction_type(
    repository: HubRepository,
) -> None:
    run_id = _run(repository, "validation_count")
    repository.record_validation_attempt(
        "attempt_c1", run_id, 1, "1.0.0", "{}", _digest("a")
    )
    repository.record_validation_attempt(
        "attempt_c2",
        run_id,
        2,
        "1.0.0",
        "{}",
        _digest("b"),
        correction_type="revalidate",
    )
    repository.record_validation_attempt(
        "attempt_c3",
        run_id,
        3,
        "1.0.0",
        "{}",
        _digest("c"),
        correction_type="revalidate",
    )

    assert repository.count_validation_attempts(run_id) == 3
    assert (
        repository.count_validation_attempts(run_id, correction_type="revalidate")
        == 2
    )
    assert (
        repository.count_validation_attempts(run_id, correction_type="normalize")
        == 0
    )
    assert repository.count_validation_attempts("run_missing") == 0


def test_validation_attempts_are_immutable(repository: HubRepository) -> None:
    run_id = _run(repository, "validation_immutable")
    repository.record_validation_attempt(
        "attempt_i1", run_id, 1, "1.0.0", "{}", _digest("a")
    )

    with pytest.raises(sqlite3.IntegrityError):
        with repository.database.transaction() as connection:
            connection.execute(
                "UPDATE run_validation_attempts SET policy_version = '9.9.9' "
                "WHERE attempt_id = 'attempt_i1'"
            )
    with pytest.raises(sqlite3.IntegrityError):
        with repository.database.transaction() as connection:
            connection.execute(
                "DELETE FROM run_validation_attempts "
                "WHERE attempt_id = 'attempt_i1'"
            )

    unchanged = repository.get_validation_attempt("attempt_i1")
    assert unchanged is not None
    assert unchanged["policy_version"] == "1.0.0"


def test_validation_attempt_requires_existing_run(
    repository: HubRepository,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        repository.record_validation_attempt(
            "attempt_fk", "run_nonexistent", 1, "1.0.0", "{}", _digest("a")
        )
    assert repository.get_validation_attempt("attempt_fk") is None
