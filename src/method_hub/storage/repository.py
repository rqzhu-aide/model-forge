"""Phase-neutral SQLite repository for operational and formal Hub state."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .database import Database
from .errors import StorageError
from .migrations import HUB_MIGRATIONS, ZERO_SHA256


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RepositoryError(StorageError):
    """Base class for durable repository failures."""


class RepositoryValidationError(RepositoryError, ValueError):
    pass


class RepositoryConflictError(RepositoryError):
    pass


class RepositoryNotFoundError(RepositoryError, LookupError):
    def __init__(self, entity: str, identity: str) -> None:
        self.entity = entity
        self.identity = identity
        super().__init__(
            "repository.not_found",
            f"No {entity} exists for identity {identity!r}.",
        )


@dataclass(frozen=True, slots=True)
class RecordResult:
    created: bool
    row: sqlite3.Row


@dataclass(frozen=True, slots=True)
class RunTransitionResult:
    applied: bool
    reason: str
    run: sqlite3.Row


def _text(value: str, field: str) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise RepositoryValidationError(
            "repository.invalid_text",
            f"{field} must be nonempty text without NUL characters.",
        )
    return value


def _digest(value: str, field: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise RepositoryValidationError(
            "repository.invalid_sha256",
            f"{field} must contain exactly 64 lowercase hexadecimal characters.",
        )
    return value


def _json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise RepositoryValidationError(
            "repository.invalid_json",
            "Repository payloads must be finite JSON values.",
        ) from error


def _time(value: str | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise RepositoryValidationError(
                "repository.invalid_time",
                "Repository timestamps must include a timezone.",
            )
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return _text(value, "timestamp")


def _same(row: sqlite3.Row, **values: Any) -> bool:
    return all(row[key] == value for key, value in values.items())


def _not_found(entity: str, identity: str) -> RepositoryNotFoundError:
    return RepositoryNotFoundError(entity, identity)


class HubRepository:
    """High-level persistence without phase-specific scientific semantics."""

    __slots__ = ("_database",)

    def __init__(self, path: str | Path) -> None:
        self._database = Database(path, migrations=HUB_MIGRATIONS)

    @property
    def database(self) -> Database:
        return self._database

    def initialize(self) -> int:
        return self._database.initialize()

    def create_project(
        self,
        project_id: str,
        payload: Any,
        *,
        created_at: str | datetime | None = None,
    ) -> RecordResult:
        project_id = _text(project_id, "project_id")
        payload_json = _json(payload)
        at = _time(created_at)
        with self._database.immediate_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if row is not None:
                if row["payload_json"] != payload_json:
                    raise RepositoryConflictError(
                        "repository.immutable_conflict",
                        f"Project {project_id!r} already has different content.",
                    )
                return RecordResult(False, row)
            connection.execute(
                """
                INSERT INTO projects(project_id, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (project_id, payload_json, at, at),
            )
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            assert row is not None
            return RecordResult(True, row)

    def get_project(self, project_id: str) -> sqlite3.Row:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            raise _not_found("project", project_id)
        return row

    def record_raw_command(
        self,
        request_id: str,
        project_id: str,
        raw_sha256: str,
        payload: Any,
        *,
        received_at: str | datetime | None = None,
    ) -> RecordResult:
        request_id = _text(request_id, "request_id")
        project_id = _text(project_id, "project_id")
        raw_sha256 = _digest(raw_sha256, "raw_sha256")
        payload_json = _json(payload)
        at = _time(received_at)
        with self._database.immediate_transaction() as connection:
            self._require_project(connection, project_id)
            row = connection.execute(
                "SELECT * FROM raw_command_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is not None:
                if not _same(
                    row,
                    project_id=project_id,
                    raw_sha256=raw_sha256,
                    payload_json=payload_json,
                ):
                    raise RepositoryConflictError(
                        "repository.immutable_conflict",
                        f"Raw request {request_id!r} already has different content.",
                    )
                return RecordResult(False, row)
            connection.execute(
                """
                INSERT INTO raw_command_requests(
                    request_id, project_id, raw_sha256, payload_json, received_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (request_id, project_id, raw_sha256, payload_json, at),
            )
            row = connection.execute(
                "SELECT * FROM raw_command_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            assert row is not None
            return RecordResult(True, row)

    def seal_command(
        self,
        command_id: str,
        project_id: str,
        raw_request_id: str,
        idempotency_key: str,
        command_sha256: str,
        payload: Any,
        *,
        sealed_at: str | datetime | None = None,
    ) -> RecordResult:
        command_id = _text(command_id, "command_id")
        project_id = _text(project_id, "project_id")
        raw_request_id = _text(raw_request_id, "raw_request_id")
        idempotency_key = _text(idempotency_key, "idempotency_key")
        command_sha256 = _digest(command_sha256, "command_sha256")
        payload_json = _json(payload)
        at = _time(sealed_at)
        with self._database.immediate_transaction() as connection:
            raw = connection.execute(
                "SELECT project_id FROM raw_command_requests WHERE request_id = ?",
                (raw_request_id,),
            ).fetchone()
            if raw is None:
                raise _not_found("raw command request", raw_request_id)
            if raw["project_id"] != project_id:
                raise RepositoryConflictError(
                    "repository.project_mismatch",
                    "Raw and sealed commands must belong to the same project.",
                )
            existing = connection.execute(
                """
                SELECT * FROM sealed_commands
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if not _same(
                    existing,
                    command_id=command_id,
                    command_sha256=command_sha256,
                    payload_json=payload_json,
                ):
                    raise RepositoryConflictError(
                        "repository.idempotency_key_reused",
                        "The project idempotency key is bound to another command.",
                    )
                return RecordResult(False, existing)
            by_id = connection.execute(
                "SELECT * FROM sealed_commands WHERE command_id = ?", (command_id,)
            ).fetchone()
            if by_id is not None:
                raise RepositoryConflictError(
                    "repository.immutable_conflict",
                    f"Command {command_id!r} already exists.",
                )
            connection.execute(
                """
                INSERT INTO sealed_commands(
                    command_id, project_id, raw_request_id, idempotency_key,
                    command_sha256, payload_json, sealed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command_id,
                    project_id,
                    raw_request_id,
                    idempotency_key,
                    command_sha256,
                    payload_json,
                    at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM sealed_commands WHERE command_id = ?", (command_id,)
            ).fetchone()
            assert row is not None
            return RecordResult(True, row)

    def get_command_by_idempotency(
        self, project_id: str, idempotency_key: str
    ) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT * FROM sealed_commands
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()

    def get_sealed_command(self, command_id: str) -> sqlite3.Row:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sealed_commands WHERE command_id = ?", (command_id,)
            ).fetchone()
        if row is None:
            raise _not_found("sealed command", command_id)
        return row
    def create_run(
        self,
        run_id: str,
        project_id: str,
        command_id: str,
        status: str,
        payload: Any,
        event_id: str,
        event_sha256: str,
        event_payload: Any,
        *,
        recorded_at: str | datetime | None = None,
    ) -> RecordResult:
        run_id = _text(run_id, "run_id")
        project_id = _text(project_id, "project_id")
        command_id = _text(command_id, "command_id")
        status = _text(status, "status")
        event_id = _text(event_id, "event_id")
        event_sha256 = _digest(event_sha256, "event_sha256")
        payload_json = _json(payload)
        event_json = _json(event_payload)
        at = _time(recorded_at)
        with self._database.immediate_transaction() as connection:
            command = connection.execute(
                "SELECT project_id FROM sealed_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if command is None:
                raise _not_found("sealed command", command_id)
            if command["project_id"] != project_id:
                raise RepositoryConflictError(
                    "repository.project_mismatch",
                    "Run and launch command must belong to the same project.",
                )
            prior = connection.execute(
                "SELECT * FROM runs WHERE command_id = ?", (command_id,)
            ).fetchone()
            if prior is not None:
                return RecordResult(False, prior)
            by_id = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if by_id is not None:
                raise RepositoryConflictError(
                    "repository.immutable_conflict",
                    f"Run {run_id!r} already exists for another command.",
                )
            connection.execute(
                """
                INSERT INTO runs(
                    run_id, project_id, command_id, status, head_sequence,
                    payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (run_id, project_id, command_id, status, payload_json, at, at),
            )
            connection.execute(
                """
                INSERT INTO run_events(
                    event_id, run_id, sequence, status, event_sha256,
                    payload_json, recorded_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?)
                """,
                (event_id, run_id, status, event_sha256, event_json, at),
            )
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            assert row is not None
            return RecordResult(True, row)

    def get_run(self, run_id: str) -> sqlite3.Row:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise _not_found("run", run_id)
        return row

    def list_incomplete_runs(self) -> tuple[sqlite3.Row, ...]:
        terminal = (
            "cancelled", "published", "failed", "rejected", "conflicted",
            "correction_exhausted",
        )
        placeholders = ", ".join("?" for _ in terminal)
        with self._database.connect() as connection:
            return tuple(
                connection.execute(
                    f"SELECT * FROM runs WHERE status NOT IN ({placeholders}) "
                    "ORDER BY created_at, run_id",
                    terminal,
                ).fetchall()
            )
    def list_run_events(self, run_id: str) -> tuple[sqlite3.Row, ...]:
        self.get_run(run_id)
        with self._database.connect() as connection:
            return tuple(
                connection.execute(
                    "SELECT * FROM run_events WHERE run_id = ? ORDER BY sequence",
                    (run_id,),
                ).fetchall()
            )

    def compare_and_swap_run(
        self,
        run_id: str,
        expected_status: str,
        expected_sequence: int,
        new_status: str,
        payload: Any,
        event_id: str,
        event_sha256: str,
        event_payload: Any,
        *,
        recorded_at: str | datetime | None = None,
    ) -> RunTransitionResult:
        with self._database.immediate_transaction() as connection:
            return self._cas_run(
                connection,
                run_id=run_id,
                expected_status=expected_status,
                expected_sequence=expected_sequence,
                new_status=new_status,
                payload_json=_json(payload),
                event_id=event_id,
                event_sha256=event_sha256,
                event_json=_json(event_payload),
                at=_time(recorded_at),
            )

    def request_cancellation(
        self,
        run_id: str,
        command_id: str,
        expected_status: str,
        expected_sequence: int,
        payload: Any,
        event_id: str,
        event_sha256: str,
        event_payload: Any,
        *,
        recorded_at: str | datetime | None = None,
    ) -> RunTransitionResult:
        run_id = _text(run_id, "run_id")
        command_id = _text(command_id, "command_id")
        at = _time(recorded_at)
        with self._database.immediate_transaction() as connection:
            run = self._require_run(connection, run_id)
            command = connection.execute(
                "SELECT project_id FROM sealed_commands WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if command is None:
                raise _not_found("sealed command", command_id)
            if command["project_id"] != run["project_id"]:
                raise RepositoryConflictError(
                    "repository.project_mismatch",
                    "Cancellation command and run must belong to the same project.",
                )
            if run["cancellation_command_id"] == command_id:
                return RunTransitionResult(False, "already_applied", run)
            submitted = connection.execute(
                "SELECT 1 FROM run_submissions WHERE run_id = ?", (run_id,)
            ).fetchone()
            if submitted is not None:
                return RunTransitionResult(False, "already_submitted", run)
            if run["cancellation_fenced"]:
                return RunTransitionResult(False, "cancellation_fenced", run)
            if (
                run["status"] != expected_status
                or run["head_sequence"] != expected_sequence
            ):
                return RunTransitionResult(False, "compare_and_swap_failed", run)
            result = self._cas_run(
                connection,
                run_id=run_id,
                expected_status=expected_status,
                expected_sequence=expected_sequence,
                new_status="cancellation_requested",
                payload_json=_json(payload),
                event_id=event_id,
                event_sha256=event_sha256,
                event_json=_json(event_payload),
                at=at,
                extra_sql=(
                    ", cancellation_fenced = 1, new_role_fenced = 1, "
                    "cancellation_command_id = ?"
                ),
                extra_parameters=(command_id,),
            )
            return result

    def cancellation_requested(self, run_id: str) -> bool:
        return bool(self.get_run(run_id)["cancellation_fenced"])

    def freeze_manifest(
        self,
        run_id: str,
        manifest_sha256: str,
        payload: Any,
        *,
        sealed_at: str | datetime | None = None,
    ) -> RecordResult:
        run_id = _text(run_id, "run_id")
        manifest_sha256 = _digest(manifest_sha256, "manifest_sha256")
        payload_json = _json(payload)
        at = _time(sealed_at)
        with self._database.immediate_transaction() as connection:
            self._require_run(connection, run_id)
            row = connection.execute(
                "SELECT * FROM run_manifests WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is not None:
                if not _same(
                    row,
                    manifest_sha256=manifest_sha256,
                    payload_json=payload_json,
                ):
                    raise RepositoryConflictError(
                        "repository.immutable_conflict",
                        f"Run {run_id!r} already has a different manifest.",
                    )
                return RecordResult(False, row)
            connection.execute(
                """
                INSERT INTO run_manifests(
                    run_id, manifest_sha256, payload_json, sealed_at
                ) VALUES (?, ?, ?, ?)
                """,
                (run_id, manifest_sha256, payload_json, at),
            )
            row = connection.execute(
                "SELECT * FROM run_manifests WHERE run_id = ?", (run_id,)
            ).fetchone()
            assert row is not None
            return RecordResult(True, row)

    def get_manifest(self, run_id: str) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                "SELECT * FROM run_manifests WHERE run_id = ?", (run_id,)
            ).fetchone()
    def seal_submission(
        self,
        run_id: str,
        submission_id: str,
        submission_sha256: str,
        expected_status: str,
        expected_sequence: int,
        new_status: str,
        submission_payload: Any,
        run_payload: Any,
        event_id: str,
        event_sha256: str,
        event_payload: Any,
        *,
        recorded_at: str | datetime | None = None,
    ) -> RunTransitionResult:
        run_id = _text(run_id, "run_id")
        submission_id = _text(submission_id, "submission_id")
        submission_sha256 = _digest(submission_sha256, "submission_sha256")
        submission_json = _json(submission_payload)
        run_json = _json(run_payload)
        at = _time(recorded_at)
        with self._database.immediate_transaction() as connection:
            run = self._require_run(connection, run_id)
            prior = connection.execute(
                "SELECT * FROM run_submissions WHERE run_id = ?", (run_id,)
            ).fetchone()
            if prior is not None:
                if _same(
                    prior,
                    submission_id=submission_id,
                    submission_sha256=submission_sha256,
                    payload_json=submission_json,
                ):
                    return RunTransitionResult(False, "already_applied", run)
                return RunTransitionResult(False, "already_submitted", run)
            if run["cancellation_fenced"]:
                return RunTransitionResult(False, "cancellation_fenced", run)
            if (
                run["status"] != expected_status
                or run["head_sequence"] != expected_sequence
            ):
                return RunTransitionResult(False, "compare_and_swap_failed", run)
            connection.execute(
                """
                INSERT INTO run_submissions(
                    submission_id, run_id, submission_sha256, payload_json, submitted_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (submission_id, run_id, submission_sha256, submission_json, at),
            )
            return self._cas_run(
                connection,
                run_id=run_id,
                expected_status=expected_status,
                expected_sequence=expected_sequence,
                new_status=new_status,
                payload_json=run_json,
                event_id=event_id,
                event_sha256=event_sha256,
                event_json=_json(event_payload),
                at=at,
            )

    def get_submission(self, run_id: str) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                "SELECT * FROM run_submissions WHERE run_id = ?", (run_id,)
            ).fetchone()

    def insert_submission_attempt(
        self,
        run_id: str,
        attempt_id: str,
        submission_id: str,
        attempt_ordinal: int,
        payload_json: str,
        submission_sha256: str,
        correction_command_id: str | None = None,
        correction_type: str | None = None,
    ) -> sqlite3.Row:
        run_id = _text(run_id, "run_id")
        attempt_id = _text(attempt_id, "attempt_id")
        submission_id = _text(submission_id, "submission_id")
        if type(attempt_ordinal) is not int or attempt_ordinal < 1:
            raise RepositoryValidationError(
                "repository.invalid_ordinal",
                "attempt_ordinal must be a positive integer.",
            )
        payload_json = _text(payload_json, "payload_json")
        submission_sha256 = _digest(submission_sha256, "submission_sha256")
        if correction_command_id is not None:
            correction_command_id = _text(
                correction_command_id, "correction_command_id"
            )
        if correction_type is not None and correction_type not in (
            "revalidate",
            "normalize",
            "packaging",
            "scientific",
        ):
            raise RepositoryValidationError(
                "repository.invalid_correction_type",
                "correction_type must be one of 'revalidate', 'normalize', "
                "'packaging', or 'scientific'.",
            )
        with self._database.immediate_transaction() as connection:
            self._require_run(connection, run_id)
            connection.execute(
                """
                INSERT INTO run_submission_attempts(
                    attempt_id, run_id, submission_id, attempt_ordinal,
                    payload_json, submission_sha256, submitted_at,
                    correction_command_id, correction_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    run_id,
                    submission_id,
                    attempt_ordinal,
                    payload_json,
                    submission_sha256,
                    _time(None),
                    correction_command_id,
                    correction_type,
                ),
            )
            row = connection.execute(
                "SELECT * FROM run_submission_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            assert row is not None
            return row

    def get_latest_submission_attempt(self, run_id: str) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT * FROM run_submission_attempts
                WHERE run_id = ?
                ORDER BY attempt_ordinal DESC, attempt_id
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()

    def count_submission_attempts(self, run_id: str) -> int:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS n FROM run_submission_attempts "
                "WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        assert row is not None
        return int(row["n"])

    def record_validation_attempt(
        self,
        attempt_id: str,
        run_id: str,
        attempt_ordinal: int,
        policy_version: str,
        report_json: str,
        source_sha256: str,
        correction_type: str | None = None,
        prior_attempt_id: str | None = None,
        correction_command_id: str | None = None,
        attempted_at: str | datetime | None = None,
    ) -> sqlite3.Row:
        attempt_id = _text(attempt_id, "attempt_id")
        run_id = _text(run_id, "run_id")
        if type(attempt_ordinal) is not int or attempt_ordinal < 1:
            raise RepositoryValidationError(
                "repository.invalid_ordinal",
                "attempt_ordinal must be a positive integer.",
            )
        policy_version = _text(policy_version, "policy_version")
        report_json = _text(report_json, "report_json")
        source_sha256 = _digest(source_sha256, "source_sha256")
        if correction_type is not None and correction_type not in (
            "revalidate",
            "normalize",
            "packaging",
            "scientific",
        ):
            raise RepositoryValidationError(
                "repository.invalid_correction_type",
                "correction_type must be one of 'revalidate', 'normalize', "
                "'packaging', or 'scientific'.",
            )
        if prior_attempt_id is not None:
            prior_attempt_id = _text(prior_attempt_id, "prior_attempt_id")
        if correction_command_id is not None:
            correction_command_id = _text(
                correction_command_id, "correction_command_id"
            )
        with self._database.immediate_transaction() as connection:
            connection.execute(
                """
                INSERT INTO run_validation_attempts(
                    attempt_id, run_id, attempt_ordinal, policy_version,
                    report_json, source_sha256, correction_type,
                    prior_attempt_id, correction_command_id, attempted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    run_id,
                    attempt_ordinal,
                    policy_version,
                    report_json,
                    source_sha256,
                    correction_type,
                    prior_attempt_id,
                    correction_command_id,
                    _time(attempted_at),
                ),
            )
            row = connection.execute(
                "SELECT * FROM run_validation_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
            assert row is not None
            return row

    def get_validation_attempt(self, attempt_id: str) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                "SELECT * FROM run_validation_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()

    def get_latest_validation_attempt(self, run_id: str) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT * FROM run_validation_attempts
                WHERE run_id = ?
                ORDER BY attempt_ordinal DESC, attempt_id
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()

    def list_validation_attempts(self, run_id: str) -> list[sqlite3.Row]:
        with self._database.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT * FROM run_validation_attempts
                    WHERE run_id = ?
                    ORDER BY attempt_ordinal, attempt_id
                    """,
                    (run_id,),
                ).fetchall()
            )

    def count_validation_attempts(
        self, run_id: str, correction_type: str | None = None
    ) -> int:
        with self._database.connect() as connection:
            if correction_type is None:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM run_validation_attempts "
                    "WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM run_validation_attempts "
                    "WHERE run_id = ? AND correction_type = ?",
                    (run_id, correction_type),
                ).fetchone()
        assert row is not None
        return int(row["n"])

    def get_role_closure(self, closure_id: str) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                "SELECT * FROM role_execution_closures WHERE closure_id = ?",
                (closure_id,),
            ).fetchone()

    def get_or_create_execution(
        self,
        execution_id: str,
        invocation_id: str,
        run_id: str,
        invocation_sha256: str,
        payload: Any,
        *,
        created_at: str | datetime | None = None,
    ) -> RecordResult:
        execution_id = _text(execution_id, "execution_id")
        invocation_id = _text(invocation_id, "invocation_id")
        run_id = _text(run_id, "run_id")
        invocation_sha256 = _digest(invocation_sha256, "invocation_sha256")
        payload_json = _json(payload)
        at = _time(created_at)
        with self._database.immediate_transaction() as connection:
            self._require_run(connection, run_id)
            row = connection.execute(
                "SELECT * FROM role_execution_intents WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()
            if row is not None:
                if not _same(
                    row,
                    run_id=run_id,
                    invocation_sha256=invocation_sha256,
                    payload_json=payload_json,
                ):
                    raise RepositoryConflictError(
                        "repository.execution_conflict",
                        "The invocation is bound to a different execution intent.",
                    )
                return RecordResult(False, row)
            connection.execute(
                """
                INSERT INTO role_execution_intents(
                    execution_id, invocation_id, run_id, invocation_sha256,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    invocation_id,
                    run_id,
                    invocation_sha256,
                    payload_json,
                    at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM role_execution_intents WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            assert row is not None
            return RecordResult(True, row)

    def get_execution_for_invocation(self, invocation_id: str) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                "SELECT * FROM role_execution_intents WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()

    def acknowledge_execution(
        self,
        execution_id: str,
        external_execution_id: str,
        payload: Any,
        *,
        acknowledged_at: str | datetime | None = None,
    ) -> RecordResult:
        execution_id = _text(execution_id, "execution_id")
        external_execution_id = _text(
            external_execution_id, "external_execution_id"
        )
        payload_json = _json(payload)
        at = _time(acknowledged_at)
        with self._database.immediate_transaction() as connection:
            self._require_execution(connection, execution_id)
            row = connection.execute(
                """
                SELECT * FROM role_execution_acknowledgements
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()
            if row is not None:
                if not _same(
                    row,
                    external_execution_id=external_execution_id,
                    payload_json=payload_json,
                ):
                    raise RepositoryConflictError(
                        "repository.execution_conflict",
                        "Execution acknowledgement is already sealed differently.",
                    )
                return RecordResult(False, row)
            connection.execute(
                """
                INSERT INTO role_execution_acknowledgements(
                    execution_id, external_execution_id, payload_json, acknowledged_at
                ) VALUES (?, ?, ?, ?)
                """,
                (execution_id, external_execution_id, payload_json, at),
            )
            row = connection.execute(
                """
                SELECT * FROM role_execution_acknowledgements
                WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()
            assert row is not None
            return RecordResult(True, row)

    def append_execution_heartbeat(
        self,
        execution_id: str,
        heartbeat_id: str,
        payload: Any,
        *,
        recorded_at: str | datetime | None = None,
    ) -> RecordResult:
        execution_id = _text(execution_id, "execution_id")
        heartbeat_id = _text(heartbeat_id, "heartbeat_id")
        payload_json = _json(payload)
        at = _time(recorded_at)
        with self._database.immediate_transaction() as connection:
            self._require_execution(connection, execution_id)
            row = connection.execute(
                """
                SELECT * FROM role_execution_heartbeats WHERE heartbeat_id = ?
                """,
                (heartbeat_id,),
            ).fetchone()
            if row is not None:
                if not _same(
                    row, execution_id=execution_id, payload_json=payload_json
                ):
                    raise RepositoryConflictError(
                        "repository.execution_conflict",
                        "Heartbeat identity is already bound to different content.",
                    )
                return RecordResult(False, row)
            sequence = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM role_execution_heartbeats WHERE execution_id = ?
                """,
                (execution_id,),
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO role_execution_heartbeats(
                    heartbeat_id, execution_id, sequence, payload_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (heartbeat_id, execution_id, sequence, payload_json, at),
            )
            row = connection.execute(
                "SELECT * FROM role_execution_heartbeats WHERE heartbeat_id = ?",
                (heartbeat_id,),
            ).fetchone()
            assert row is not None
            return RecordResult(True, row)

    def close_execution(
        self,
        execution_id: str,
        closure_id: str,
        closure_sha256: str,
        payload: Any,
        *,
        closed_at: str | datetime | None = None,
    ) -> RecordResult:
        execution_id = _text(execution_id, "execution_id")
        closure_id = _text(closure_id, "closure_id")
        closure_sha256 = _digest(closure_sha256, "closure_sha256")
        payload_json = _json(payload)
        at = _time(closed_at)
        with self._database.immediate_transaction() as connection:
            self._require_execution(connection, execution_id)
            row = connection.execute(
                "SELECT * FROM role_execution_closures WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if row is not None:
                if not _same(
                    row,
                    closure_id=closure_id,
                    closure_sha256=closure_sha256,
                    payload_json=payload_json,
                ):
                    raise RepositoryConflictError(
                        "repository.execution_conflict",
                        "Execution closure is already sealed differently.",
                    )
                return RecordResult(False, row)
            connection.execute(
                """
                INSERT INTO role_execution_closures(
                    closure_id, execution_id, closure_sha256, payload_json, closed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (closure_id, execution_id, closure_sha256, payload_json, at),
            )
            row = connection.execute(
                "SELECT * FROM role_execution_closures WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            assert row is not None
            return RecordResult(True, row)

    def list_unclosed_acknowledged_executions(
        self, run_id: str
    ) -> tuple[sqlite3.Row, ...]:
        self.get_run(run_id)
        with self._database.connect() as connection:
            return tuple(
                connection.execute(
                    """
                    SELECT i.*, a.external_execution_id, a.acknowledged_at
                    FROM role_execution_intents AS i
                    JOIN role_execution_acknowledgements AS a
                      ON a.execution_id = i.execution_id
                    LEFT JOIN role_execution_closures AS c
                      ON c.execution_id = i.execution_id
                    WHERE i.run_id = ? AND c.execution_id IS NULL
                    ORDER BY i.created_at, i.execution_id
                    """,
                    (run_id,),
                ).fetchall()
            )
    def record_artifact(
        self,
        artifact_id: str,
        project_id: str,
        sha256: str,
        size: int,
        media_type: str,
        storage_uri: str,
        payload: Any,
        *,
        recorded_at: str | datetime | None = None,
    ) -> RecordResult:
        artifact_id = _text(artifact_id, "artifact_id")
        project_id = _text(project_id, "project_id")
        sha256 = _digest(sha256, "sha256")
        if type(size) is not int or size < 0:
            raise RepositoryValidationError(
                "repository.invalid_size", "Artifact size must be a nonnegative integer."
            )
        media_type = _text(media_type, "media_type")
        storage_uri = _text(storage_uri, "storage_uri")
        payload_json = _json(payload)
        at = _time(recorded_at)
        with self._database.immediate_transaction() as connection:
            self._require_project(connection, project_id)
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
            values = {
                "project_id": project_id,
                "sha256": sha256,
                "size": size,
                "media_type": media_type,
                "storage_uri": storage_uri,
                "payload_json": payload_json,
            }
            if row is not None:
                if not _same(row, **values):
                    raise RepositoryConflictError(
                        "repository.immutable_conflict",
                        f"Artifact {artifact_id!r} already has different metadata.",
                    )
                return RecordResult(False, row)
            connection.execute(
                """
                INSERT INTO artifacts(
                    artifact_id, project_id, sha256, size, media_type,
                    storage_uri, payload_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    project_id,
                    sha256,
                    size,
                    media_type,
                    storage_uri,
                    payload_json,
                    at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
            assert row is not None
            return RecordResult(True, row)

    def get_artifact(self, artifact_id: str) -> sqlite3.Row:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise _not_found("artifact", artifact_id)
        return row

    def set_profile_mapping(
        self,
        project_id: str,
        role_key: str,
        profile_name: str,
        settings: Any,
        *,
        expected_revision: int,
        updated_at: str | datetime | None = None,
    ) -> sqlite3.Row:
        return self._set_revisioned(
            table="profile_mappings",
            project_id=project_id,
            key_column="role_key",
            key=role_key,
            value_columns=("profile_name", "settings_json"),
            values=(_text(profile_name, "profile_name"), _json(settings)),
            expected_revision=expected_revision,
            at=_time(updated_at),
        )

    def compare_and_set_profile_mapping(
        self,
        project_id: str,
        role_key: str,
        profile_name: str,
        settings: Any,
        *,
        expected_profiles: Mapping[str, str],
        expected_revisions: Mapping[str, int],
        updated_at: str | datetime | None = None,
    ) -> sqlite3.Row:
        """Commit one mapping only if the complete effective mapping is unchanged."""

        project_id = _text(project_id, "project_id")
        role_key = _text(role_key, "role_key")
        profile_name = _text(profile_name, "profile_name")
        if not isinstance(expected_profiles, Mapping) or not isinstance(
            expected_revisions, Mapping
        ):
            raise RepositoryValidationError(
                "repository.invalid_profile_state",
                "Expected profile names and revisions must be mappings.",
            )
        profiles = {
            _text(role, "expected profile role"): _text(
                expected_profile,
                "expected profile name",
            )
            for role, expected_profile in expected_profiles.items()
        }
        revisions: dict[str, int] = {}
        for role, revision in expected_revisions.items():
            normalized_role = _text(role, "expected revision role")
            if type(revision) is not int or revision < 0:
                raise RepositoryValidationError(
                    "repository.invalid_revision",
                    "Expected profile revisions must be nonnegative integers.",
                )
            revisions[normalized_role] = revision
        if not profiles or set(profiles) != set(revisions) or role_key not in profiles:
            raise RepositoryValidationError(
                "repository.invalid_profile_state",
                "Expected profile state must cover the same roles including the target.",
            )

        settings_json = _json(settings)
        at = _time(updated_at)
        with self._database.immediate_transaction() as connection:
            self._require_project(connection, project_id)
            rows = connection.execute(
                """
                SELECT * FROM profile_mappings
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchall()
            current = {str(row["role_key"]): row for row in rows}
            for expected_role in profiles:
                row = current.get(expected_role)
                actual_revision = 0 if row is None else int(row["revision"])
                if actual_revision != revisions[expected_role]:
                    raise RepositoryConflictError(
                        "repository.profile_mapping_state_conflict",
                        "The effective profile mapping changed before commit.",
                    )
                if (
                    row is not None
                    and str(row["profile_name"]) != profiles[expected_role]
                ):
                    raise RepositoryConflictError(
                        "repository.profile_mapping_state_conflict",
                        "The effective profile mapping changed before commit.",
                    )

            target = current.get(role_key)
            revision = revisions[role_key] + 1
            if target is None:
                connection.execute(
                    """
                    INSERT INTO profile_mappings(
                        project_id, role_key, profile_name, settings_json,
                        revision, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        role_key,
                        profile_name,
                        settings_json,
                        revision,
                        at,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE profile_mappings
                    SET profile_name = ?, settings_json = ?,
                        revision = ?, updated_at = ?
                    WHERE project_id = ? AND role_key = ? AND revision = ?
                    """,
                    (
                        profile_name,
                        settings_json,
                        revision,
                        at,
                        project_id,
                        role_key,
                        revisions[role_key],
                    ),
                )
            result = connection.execute(
                """
                SELECT * FROM profile_mappings
                WHERE project_id = ? AND role_key = ?
                """,
                (project_id, role_key),
            ).fetchone()
            assert result is not None
            return result

    def get_profile_mapping(
        self, project_id: str, role_key: str
    ) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT * FROM profile_mappings
                WHERE project_id = ? AND role_key = ?
                """,
                (project_id, role_key),
            ).fetchone()

    def set_project_setting(
        self,
        project_id: str,
        setting_key: str,
        value: Any,
        *,
        expected_revision: int,
        updated_at: str | datetime | None = None,
    ) -> sqlite3.Row:
        return self._set_revisioned(
            table="project_settings",
            project_id=project_id,
            key_column="setting_key",
            key=setting_key,
            value_columns=("value_json",),
            values=(_json(value),),
            expected_revision=expected_revision,
            at=_time(updated_at),
        )

    def get_project_setting(
        self, project_id: str, setting_key: str
    ) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT * FROM project_settings
                WHERE project_id = ? AND setting_key = ?
                """,
                (project_id, setting_key),
            ).fetchone()

    def get_current_record(
        self, project_id: str, slot_key: str
    ) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                """
                SELECT
                    s.project_id, s.slot_key, s.revision AS slot_revision,
                    s.updated_at AS slot_updated_at, g.*, a.sha256 AS artifact_sha256,
                    a.storage_uri AS artifact_storage_uri
                FROM current_slots AS s
                JOIN formal_generations AS g
                    ON g.project_id = s.project_id
                    AND g.generation_id = s.generation_id
                JOIN artifacts AS a ON a.artifact_id = g.artifact_id
                WHERE s.project_id = ? AND s.slot_key = ?
                """,
                (project_id, slot_key),
            ).fetchone()

    def list_current_records(self, project_id: str) -> tuple[sqlite3.Row, ...]:
        with self._database.connect() as connection:
            return tuple(
                connection.execute(
                    """
                    SELECT
                        s.project_id, s.slot_key, s.revision AS slot_revision,
                        g.*, a.sha256 AS artifact_sha256,
                        a.storage_uri AS artifact_storage_uri,
                        a.size AS artifact_size
                    FROM current_slots AS s
                    JOIN formal_generations AS g
                        ON g.project_id = s.project_id
                        AND g.generation_id = s.generation_id
                    JOIN artifacts AS a ON a.artifact_id = g.artifact_id
                    WHERE s.project_id = ? ORDER BY s.slot_key
                    """,
                    (project_id,),
                ).fetchall()
            )

    def list_collection_items(
        self, project_id: str, collection_key: str
    ) -> tuple[sqlite3.Row, ...]:
        with self._database.connect() as connection:
            return tuple(
                connection.execute(
                    """
                    SELECT * FROM cumulative_collection_items
                    WHERE project_id = ? AND collection_key = ?
                    ORDER BY appended_at, item_id
                    """,
                    (project_id, collection_key),
                ).fetchall()
            )

    def get_publication_receipt(self, receipt_id: str) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            return connection.execute(
                "SELECT * FROM publication_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone()

    def get_publication_receipt_for_run(self, run_id: str) -> sqlite3.Row | None:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM publication_receipts WHERE run_id = ? "
                "ORDER BY committed_at, receipt_id",
                (run_id,),
            ).fetchall()
        if len(rows) > 1:
            raise RepositoryConflictError(
                "repository.multiple_run_publications",
                f"Run {run_id!r} has more than one publication receipt.",
            )
        return rows[0] if rows else None
    @contextmanager
    def publication_transaction(
        self,
        project_id: str,
        receipt_id: str,
        expected_authority_sequence: int,
        expected_authority_root: str,
        *,
        expected_current_revision: int | None = None,
    ) -> Iterator[PublicationUnitOfWork]:
        project_id = _text(project_id, "project_id")
        receipt_id = _text(receipt_id, "receipt_id")
        expected_authority_root = _digest(
            expected_authority_root, "expected_authority_root"
        )
        with self._database.immediate_transaction() as connection:
            project = self._require_project(connection, project_id)
            if (
                project["authority_sequence"] != expected_authority_sequence
                or project["authority_root_sha256"] != expected_authority_root
                or (
                    expected_current_revision is not None
                    and project["current_revision"] != expected_current_revision
                )
            ):
                raise RepositoryConflictError(
                    "repository.publication_basis_changed",
                    "The expected publication head no longer matches the project.",
                )
            if connection.execute(
                "SELECT 1 FROM publication_receipts WHERE receipt_id = ?",
                (receipt_id,),
            ).fetchone():
                raise RepositoryConflictError(
                    "repository.publication_exists",
                    f"Publication receipt {receipt_id!r} already exists.",
                )
            unit = PublicationUnitOfWork(
                repository=self,
                connection=connection,
                project_id=project_id,
                receipt_id=receipt_id,
                authority_sequence=expected_authority_sequence,
                authority_root=expected_authority_root,
                current_revision=project["current_revision"],
            )
            try:
                yield unit
                unit._finish()
            finally:
                unit._closed = True

    def _cas_run(
        self,
        connection: sqlite3.Connection,
        *,
        run_id: str,
        expected_status: str,
        expected_sequence: int,
        new_status: str,
        payload_json: str,
        event_id: str,
        event_sha256: str,
        event_json: str,
        at: str,
        extra_sql: str = "",
        extra_parameters: tuple[Any, ...] = (),
    ) -> RunTransitionResult:
        run_id = _text(run_id, "run_id")
        expected_status = _text(expected_status, "expected_status")
        new_status = _text(new_status, "new_status")
        event_id = _text(event_id, "event_id")
        event_sha256 = _digest(event_sha256, "event_sha256")
        if type(expected_sequence) is not int or expected_sequence < 1:
            raise RepositoryValidationError(
                "repository.invalid_sequence",
                "Expected run sequence must be a positive integer.",
            )
        prior_event = connection.execute(
            "SELECT * FROM run_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        run = self._require_run(connection, run_id)
        if prior_event is not None:
            if _same(
                prior_event,
                run_id=run_id,
                status=new_status,
                event_sha256=event_sha256,
                payload_json=event_json,
            ):
                return RunTransitionResult(False, "already_applied", run)
            raise RepositoryConflictError(
                "repository.event_id_reused",
                f"Run event {event_id!r} already has different content.",
            )
        if run["status"] != expected_status or run["head_sequence"] != expected_sequence:
            return RunTransitionResult(False, "compare_and_swap_failed", run)
        next_sequence = expected_sequence + 1
        parameters = (
            new_status,
            next_sequence,
            payload_json,
            at,
            *extra_parameters,
            run_id,
            expected_status,
            expected_sequence,
        )
        cursor = connection.execute(
            f"""
            UPDATE runs
            SET status = ?, head_sequence = ?, payload_json = ?, updated_at = ?
                {extra_sql}
            WHERE run_id = ? AND status = ? AND head_sequence = ?
            """,
            parameters,
        )
        if cursor.rowcount != 1:
            current = self._require_run(connection, run_id)
            return RunTransitionResult(False, "compare_and_swap_failed", current)
        connection.execute(
            """
            INSERT INTO run_events(
                event_id, run_id, sequence, status, event_sha256,
                payload_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                run_id,
                next_sequence,
                new_status,
                event_sha256,
                event_json,
                at,
            ),
        )
        current = self._require_run(connection, run_id)
        return RunTransitionResult(True, "applied", current)

    def _set_revisioned(
        self,
        *,
        table: str,
        project_id: str,
        key_column: str,
        key: str,
        value_columns: tuple[str, ...],
        values: tuple[Any, ...],
        expected_revision: int,
        at: str,
    ) -> sqlite3.Row:
        project_id = _text(project_id, "project_id")
        key = _text(key, key_column)
        if type(expected_revision) is not int or expected_revision < 0:
            raise RepositoryValidationError(
                "repository.invalid_revision",
                "Expected revision must be a nonnegative integer.",
            )
        with self._database.immediate_transaction() as connection:
            self._require_project(connection, project_id)
            row = connection.execute(
                f"SELECT * FROM {table} WHERE project_id = ? AND {key_column} = ?",
                (project_id, key),
            ).fetchone()
            current_revision = 0 if row is None else row["revision"]
            if current_revision != expected_revision:
                raise RepositoryConflictError(
                    "repository.revision_conflict",
                    f"Expected revision {expected_revision}, found {current_revision}.",
                )
            revision = current_revision + 1
            if row is None:
                columns = ", ".join(("project_id", key_column, *value_columns, "revision", "updated_at"))
                placeholders = ", ".join("?" for _ in range(2 + len(values) + 2))
                connection.execute(
                    f"INSERT INTO {table}({columns}) VALUES ({placeholders})",
                    (project_id, key, *values, revision, at),
                )
            else:
                assignments = ", ".join(f"{column} = ?" for column in value_columns)
                connection.execute(
                    f"""
                    UPDATE {table}
                    SET {assignments}, revision = ?, updated_at = ?
                    WHERE project_id = ? AND {key_column} = ? AND revision = ?
                    """,
                    (*values, revision, at, project_id, key, expected_revision),
                )
            result = connection.execute(
                f"SELECT * FROM {table} WHERE project_id = ? AND {key_column} = ?",
                (project_id, key),
            ).fetchone()
            assert result is not None
            return result

    @staticmethod
    def _require_project(
        connection: sqlite3.Connection, project_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise _not_found("project", project_id)
        return row

    @staticmethod
    def _require_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise _not_found("run", run_id)
        return row

    @staticmethod
    def _require_execution(
        connection: sqlite3.Connection, execution_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM role_execution_intents WHERE execution_id = ?",
            (execution_id,),
        ).fetchone()
        if row is None:
            raise _not_found("role execution", execution_id)
        return row


@dataclass(frozen=True, slots=True)
class _Receipt:
    receipt_sha256: str
    payload_json: str
    run_id: str | None
    command_id: str | None
    committed_at: str


class PublicationUnitOfWork:
    """Formal writes sharing one repository-owned ``BEGIN IMMEDIATE``."""

    __slots__ = (
        "_authority_root",
        "_authority_sequence",
        "_closed",
        "_connection",
        "_current_revision",
        "_events_added",
        "_prior_authority_root",
        "_prior_authority_sequence",
        "_prior_current_revision",
        "_receipt",
        "_repository",
        "_touched_slots",
        "project_id",
        "receipt_id",
    )

    def __init__(
        self,
        *,
        repository: HubRepository,
        connection: sqlite3.Connection,
        project_id: str,
        receipt_id: str,
        authority_sequence: int,
        authority_root: str,
        current_revision: int,
    ) -> None:
        self._repository = repository
        self._connection = connection
        self.project_id = project_id
        self.receipt_id = receipt_id
        self._prior_authority_sequence = authority_sequence
        self._authority_sequence = authority_sequence
        self._prior_authority_root = authority_root
        self._authority_root = authority_root
        self._prior_current_revision = current_revision
        self._current_revision = current_revision + 1
        self._events_added = 0
        self._touched_slots: set[str] = set()
        self._receipt: _Receipt | None = None
        self._closed = False

    def add_formal_generation(
        self,
        generation_id: str,
        record_type: str,
        artifact_id: str,
        content_sha256: str,
        payload: Any,
        *,
        logical_slot: str | None = None,
        source_run_id: str | None = None,
        supersedes_generation_id: str | None = None,
        published_at: str | datetime | None = None,
    ) -> RecordResult:
        self._ensure_open()
        generation_id = _text(generation_id, "generation_id")
        record_type = _text(record_type, "record_type")
        artifact_id = _text(artifact_id, "artifact_id")
        content_sha256 = _digest(content_sha256, "content_sha256")
        logical_slot = None if logical_slot is None else _text(logical_slot, "logical_slot")
        payload_json = _json(payload)
        at = _time(published_at)
        self._require_same_project("artifacts", "artifact_id", artifact_id)
        if source_run_id is not None:
            self._require_same_project("runs", "run_id", source_run_id)
        if supersedes_generation_id is not None:
            self._require_same_project(
                "formal_generations", "generation_id", supersedes_generation_id
            )
        row = self._connection.execute(
            "SELECT * FROM formal_generations WHERE generation_id = ?",
            (generation_id,),
        ).fetchone()
        values = {
            "project_id": self.project_id,
            "record_type": record_type,
            "logical_slot": logical_slot,
            "artifact_id": artifact_id,
            "source_run_id": source_run_id,
            "supersedes_generation_id": supersedes_generation_id,
            "content_sha256": content_sha256,
            "payload_json": payload_json,
        }
        if row is not None:
            if not _same(row, **values):
                raise RepositoryConflictError(
                    "repository.immutable_conflict",
                    f"Generation {generation_id!r} already has different content.",
                )
            return RecordResult(False, row)
        self._connection.execute(
            """
            INSERT INTO formal_generations(
                generation_id, project_id, record_type, logical_slot, artifact_id,
                source_run_id, supersedes_generation_id, content_sha256,
                payload_json, published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                generation_id,
                self.project_id,
                record_type,
                logical_slot,
                artifact_id,
                source_run_id,
                supersedes_generation_id,
                content_sha256,
                payload_json,
                at,
            ),
        )
        row = self._connection.execute(
            "SELECT * FROM formal_generations WHERE generation_id = ?",
            (generation_id,),
        ).fetchone()
        assert row is not None
        return RecordResult(True, row)

    def replace_current_slot(
        self,
        slot_key: str,
        generation_id: str,
        *,
        expected_generation_id: str | None,
        updated_at: str | datetime | None = None,
    ) -> sqlite3.Row:
        self._ensure_open()
        slot_key = _text(slot_key, "slot_key")
        generation_id = _text(generation_id, "generation_id")
        if slot_key in self._touched_slots:
            raise RepositoryConflictError(
                "repository.slot_reused",
                f"Current slot {slot_key!r} was already changed in this transaction.",
            )
        self._require_same_project("formal_generations", "generation_id", generation_id)
        row = self._connection.execute(
            """
            SELECT * FROM current_slots WHERE project_id = ? AND slot_key = ?
            """,
            (self.project_id, slot_key),
        ).fetchone()
        current = None if row is None else row["generation_id"]
        if current != expected_generation_id:
            raise RepositoryConflictError(
                "repository.current_slot_conflict",
                f"Current slot {slot_key!r} no longer matches its expected generation.",
            )
        if current == generation_id and row is not None:
            return row
        at = _time(updated_at)
        if row is None:
            self._connection.execute(
                """
                INSERT INTO current_slots(
                    project_id, slot_key, generation_id, revision, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self.project_id,
                    slot_key,
                    generation_id,
                    self._current_revision,
                    at,
                ),
            )
        else:
            self._connection.execute(
                """
                UPDATE current_slots
                SET generation_id = ?, revision = ?, updated_at = ?
                WHERE project_id = ? AND slot_key = ? AND generation_id = ?
                """,
                (
                    generation_id,
                    self._current_revision,
                    at,
                    self.project_id,
                    slot_key,
                    expected_generation_id,
                ),
            )
        self._touched_slots.add(slot_key)
        result = self._connection.execute(
            """
            SELECT * FROM current_slots WHERE project_id = ? AND slot_key = ?
            """,
            (self.project_id, slot_key),
        ).fetchone()
        assert result is not None
        return result

    def append_collection_item(
        self,
        collection_key: str,
        item_id: str,
        object_type: str,
        content_sha256: str,
        payload: Any,
        *,
        artifact_id: str | None = None,
        source_run_id: str | None = None,
        appended_at: str | datetime | None = None,
    ) -> RecordResult:
        self._ensure_open()
        collection_key = _text(collection_key, "collection_key")
        item_id = _text(item_id, "item_id")
        object_type = _text(object_type, "object_type")
        content_sha256 = _digest(content_sha256, "content_sha256")
        payload_json = _json(payload)
        if artifact_id is not None:
            self._require_same_project("artifacts", "artifact_id", artifact_id)
        if source_run_id is not None:
            self._require_same_project("runs", "run_id", source_run_id)
        row = self._connection.execute(
            """
            SELECT * FROM cumulative_collection_items
            WHERE project_id = ? AND collection_key = ? AND item_id = ?
            """,
            (self.project_id, collection_key, item_id),
        ).fetchone()
        content_values = {
            "object_type": object_type,
            "content_sha256": content_sha256,
            "payload_json": payload_json,
        }
        if row is not None:
            if not _same(row, **content_values):
                raise RepositoryConflictError(
                    "repository.immutable_conflict",
                    f"Collection item {item_id!r} already has different content.",
                )
            return RecordResult(False, row)
        self._connection.execute(
            """
            INSERT INTO cumulative_collection_items(
                project_id, collection_key, item_id, object_type, artifact_id,
                source_run_id, content_sha256, payload_json, appended_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.project_id,
                collection_key,
                item_id,
                object_type,
                artifact_id,
                source_run_id,
                content_sha256,
                payload_json,
                _time(appended_at),
            ),
        )
        row = self._connection.execute(
            """
            SELECT * FROM cumulative_collection_items
            WHERE project_id = ? AND collection_key = ? AND item_id = ?
            """,
            (self.project_id, collection_key, item_id),
        ).fetchone()
        assert row is not None
        return RecordResult(True, row)

    def append_authority_event(
        self,
        event_id: str,
        event_type: str,
        content_sha256: str,
        root_sha256: str,
        payload: Any,
        *,
        committed_at: str | datetime | None = None,
    ) -> sqlite3.Row:
        self._ensure_open()
        event_id = _text(event_id, "event_id")
        event_type = _text(event_type, "event_type")
        content_sha256 = _digest(content_sha256, "content_sha256")
        root_sha256 = _digest(root_sha256, "root_sha256")
        expected_root = hashlib.sha256(
            bytes.fromhex(self._authority_root) + bytes.fromhex(content_sha256)
        ).hexdigest()
        if root_sha256 != expected_root:
            raise RepositoryValidationError(
                "repository.invalid_authority_root",
                "Authority root does not extend the current root and content digest.",
            )
        sequence = self._authority_sequence + 1
        self._connection.execute(
            """
            INSERT INTO authority_events(
                project_id, sequence, event_id, event_type, prior_root_sha256,
                content_sha256, root_sha256, receipt_id, payload_json, committed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.project_id,
                sequence,
                event_id,
                event_type,
                self._authority_root,
                content_sha256,
                root_sha256,
                self.receipt_id,
                _json(payload),
                _time(committed_at),
            ),
        )
        self._authority_sequence = sequence
        self._authority_root = root_sha256
        self._events_added += 1
        row = self._connection.execute(
            "SELECT * FROM authority_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        assert row is not None
        return row

    def record_receipt(
        self,
        receipt_sha256: str,
        payload: Any,
        *,
        run_id: str | None = None,
        command_id: str | None = None,
        committed_at: str | datetime | None = None,
    ) -> None:
        self._ensure_open()
        if self._receipt is not None:
            raise RepositoryConflictError(
                "repository.receipt_reused",
                "A publication unit of work accepts exactly one receipt.",
            )
        if run_id is not None:
            self._require_same_project("runs", "run_id", run_id)
        if command_id is not None:
            self._require_same_project("sealed_commands", "command_id", command_id)
        self._receipt = _Receipt(
            receipt_sha256=_digest(receipt_sha256, "receipt_sha256"),
            payload_json=_json(payload),
            run_id=run_id,
            command_id=command_id,
            committed_at=_time(committed_at),
        )

    def _finish(self) -> None:
        self._ensure_open()
        if self._receipt is None:
            raise RepositoryValidationError(
                "repository.receipt_required",
                "Publication must seal exactly one receipt before commit.",
            )
        if self._events_added == 0:
            raise RepositoryValidationError(
                "repository.authority_event_required",
                "Publication must append at least one authority event.",
            )
        receipt = self._receipt
        self._connection.execute(
            """
            INSERT INTO publication_receipts(
                receipt_id, project_id, run_id, command_id,
                prior_authority_sequence, new_authority_sequence,
                prior_authority_root_sha256, new_authority_root_sha256,
                prior_current_revision, new_current_revision,
                receipt_sha256, payload_json, committed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.receipt_id,
                self.project_id,
                receipt.run_id,
                receipt.command_id,
                self._prior_authority_sequence,
                self._authority_sequence,
                self._prior_authority_root,
                self._authority_root,
                self._prior_current_revision,
                self._current_revision,
                receipt.receipt_sha256,
                receipt.payload_json,
                receipt.committed_at,
            ),
        )
        cursor = self._connection.execute(
            """
            UPDATE projects
            SET authority_sequence = ?, authority_root_sha256 = ?,
                current_revision = ?, updated_at = ?
            WHERE project_id = ? AND authority_sequence = ?
                AND authority_root_sha256 = ? AND current_revision = ?
            """,
            (
                self._authority_sequence,
                self._authority_root,
                self._current_revision,
                receipt.committed_at,
                self.project_id,
                self._prior_authority_sequence,
                self._prior_authority_root,
                self._prior_current_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise RepositoryConflictError(
                "repository.publication_basis_changed",
                "Project heads changed before publication commit.",
            )

    def _require_same_project(self, table: str, key: str, value: str) -> sqlite3.Row:
        row = self._connection.execute(
            f"SELECT * FROM {table} WHERE {key} = ?", (value,)
        ).fetchone()
        if row is None:
            raise _not_found(table.replace("_", " ").rstrip("s"), value)
        if row["project_id"] != self.project_id:
            raise RepositoryConflictError(
                "repository.project_mismatch",
                f"{table} identity {value!r} belongs to another project.",
            )
        return row

    def _ensure_open(self) -> None:
        if self._closed:
            raise RepositoryError(
                "repository.transaction_closed",
                "Publication unit of work is already closed.",
            )


__all__ = [
    "HubRepository",
    "PublicationUnitOfWork",
    "RecordResult",
    "RepositoryConflictError",
    "RepositoryError",
    "RepositoryNotFoundError",
    "RepositoryValidationError",
    "RunTransitionResult",
    "ZERO_SHA256",
]
