"""Diagnostic persistence, fencing, and profile-level mutex.

Separate from the scientific ``runs`` table — diagnostic invocations never
enter submission, validation, or publication.  This module provides:

* ``diagnostic_invocations`` — one row per diagnostic execution attempt.
* ``diagnostic_fencing_tokens`` — DB-backed fencing tokens (S5.7).
* ``profile_execution_locks`` — per-profile mutex preventing concurrent
  access to the same Hermes profile (C5).

All tables live in the same SQLite database but are logically independent
of the scientific control schema.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..storage.database import Database, Migration


# --------------------------------------------------------------------------- #
# Schema migration                                                            #
# --------------------------------------------------------------------------- #

_DIAGNOSTIC_SCHEMA = (
    """
    CREATE TABLE diagnostic_invocations (
        invocation_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        role TEXT NOT NULL,
        profile_name TEXT NOT NULL,
        external_execution_id TEXT,
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'running', 'succeeded', 'failed',
                              'cancelled', 'timed_out')),
        exit_code INTEGER,
        summary TEXT NOT NULL DEFAULT '',
        diagnostic_text TEXT NOT NULL DEFAULT '',
        memory_state_before TEXT,
        memory_state_after TEXT,
        memory_policy TEXT NOT NULL DEFAULT 'persistent',
        payload_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX diagnostic_invocations_project
        ON diagnostic_invocations(project_id, created_at)
    """,
    """
    CREATE INDEX diagnostic_invocations_status
        ON diagnostic_invocations(status, updated_at)
    """,
    # S5.7: DB-backed fencing tokens.
    """
    CREATE TABLE diagnostic_fencing_tokens (
        invocation_id TEXT PRIMARY KEY
            REFERENCES diagnostic_invocations(invocation_id) ON DELETE CASCADE,
        token INTEGER NOT NULL,
        holder TEXT,
        lease_expires_at TEXT,
        updated_at TEXT NOT NULL
    )
    """,
    # C5: per-profile execution mutex.
    """
    CREATE TABLE profile_execution_locks (
        profile_name TEXT PRIMARY KEY,
        invocation_id TEXT NOT NULL
            REFERENCES diagnostic_invocations(invocation_id) ON DELETE CASCADE,
        acquired_at TEXT NOT NULL,
        lease_expires_at TEXT NOT NULL
    )
    """,
)


def diagnostic_migrations(after_version: int) -> tuple[Migration, ...]:
    """Return diagnostic migrations starting after the given version."""
    return (
        Migration(
            after_version + 1,
            _DIAGNOSTIC_SCHEMA,
            name="diagnostic invocations, fencing tokens, profile mutex",
        ),
    )


# --------------------------------------------------------------------------- #
# State machine                                                                #
# --------------------------------------------------------------------------- #

DIAGNOSTIC_STATES = frozenset(
    {"pending", "running", "succeeded", "failed", "cancelled", "timed_out"}
)
TERMINAL_STATES = frozenset(
    {"succeeded", "failed", "cancelled", "timed_out"}
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Fencing token                                                                #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FencingToken:
    """A DB-backed fencing token for one diagnostic invocation."""

    invocation_id: str
    token: int
    holder: str | None
    lease_expires_at: str | None


class FencingError(RuntimeError):
    """Raised when a fencing token is stale or invalid."""


class ProfileMutexError(RuntimeError):
    """Raised when a profile is already locked by another invocation."""


class ProfileLockHeld(ProfileMutexError):
    """Raised when attempting to lock a profile that is held by another invocation."""

    def __init__(self, profile_name: str, holder_invocation_id: str) -> None:
        self.profile_name = profile_name
        self.holder_invocation_id = holder_invocation_id
        super().__init__(
            f"Profile {profile_name!r} is locked by invocation "
            f"{holder_invocation_id}."
        )


# --------------------------------------------------------------------------- #
# Diagnostic store                                                             #
# --------------------------------------------------------------------------- #


class DiagnosticStore:
    """Persistence for diagnostic invocations, fencing, and profile locks.

    Uses the same SQLite database as the scientific store but operates on
    independent tables.  No FK references to ``runs`` or ``projects`` —
    diagnostic invocations are standalone.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    # ------------------------------------------------------------------ #
    # Invocation lifecycle                                               #
    # ------------------------------------------------------------------ #

    def create_invocation(
        self,
        *,
        invocation_id: str,
        project_id: str,
        role: str,
        profile_name: str,
        memory_policy: str = "persistent",
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        """Create a pending diagnostic invocation."""
        now = utc_now_iso()
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO diagnostic_invocations
                    (invocation_id, project_id, role, profile_name, status,
                     memory_policy, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
                """,
                (
                    invocation_id,
                    project_id,
                    role,
                    profile_name,
                    memory_policy,
                    json.dumps(payload or {}),
                    now,
                    now,
                ),
            )

    def get_invocation(self, invocation_id: str) -> dict[str, Any] | None:
        """Return one invocation as a dict, or None."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM diagnostic_invocations WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_invocations(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List diagnostic invocations with optional filters."""
        query = "SELECT * FROM diagnostic_invocations"
        params: list[Any] = []
        clauses: list[str] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def update_status(
        self,
        invocation_id: str,
        *,
        status: str,
        external_execution_id: str | None = None,
        exit_code: int | None = None,
        summary: str = "",
        diagnostic_text: str = "",
    ) -> None:
        """Update an invocation's status and terminal fields."""
        if status not in DIAGNOSTIC_STATES:
            raise ValueError(f"Unknown diagnostic status {status!r}.")
        now = utc_now_iso()
        sets = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, now]
        if external_execution_id is not None:
            sets.append("external_execution_id = ?")
            params.append(external_execution_id)
        if exit_code is not None:
            sets.append("exit_code = ?")
            params.append(exit_code)
        if summary:
            sets.append("summary = ?")
            params.append(summary)
        if diagnostic_text:
            sets.append("diagnostic_text = ?")
            params.append(diagnostic_text)
        params.append(invocation_id)
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE diagnostic_invocations SET {', '.join(sets)} "
                "WHERE invocation_id = ?",
                params,
            )

    def record_memory_state(
        self,
        invocation_id: str,
        *,
        before: Mapping[str, Any] | None = None,
        after: Mapping[str, Any] | None = None,
    ) -> None:
        """Record memory-state digests for reproducibility (C3)."""
        now = utc_now_iso()
        sets: list[str] = ["updated_at = ?"]
        params: list[Any] = [now]
        if before is not None:
            sets.append("memory_state_before = ?")
            params.append(json.dumps(before))
        if after is not None:
            sets.append("memory_state_after = ?")
            params.append(json.dumps(after))
        params.append(invocation_id)
        with self._db.transaction() as conn:
            conn.execute(
                f"UPDATE diagnostic_invocations SET {', '.join(sets)} "
                "WHERE invocation_id = ?",
                params,
            )

    # ------------------------------------------------------------------ #
    # Fencing tokens (S5.7)                                              #
    # ------------------------------------------------------------------ #

    def issue_fencing_token(
        self,
        invocation_id: str,
        *,
        holder: str = "coordinator",
        lease_seconds: int = 14_400,
    ) -> FencingToken:
        """Issue a new fencing token for an invocation.

        Uses an atomic UPSERT.  The token is monotonically increasing.
        """
        now = utc_now_iso()
        from datetime import timedelta

        expires = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).isoformat()
        with self._db.transaction() as conn:
            # Get current token (0 if none).
            row = conn.execute(
                "SELECT token FROM diagnostic_fencing_tokens "
                "WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()
            current_token = row[0] if row else 0
            new_token = current_token + 1
            conn.execute(
                """
                INSERT INTO diagnostic_fencing_tokens
                    (invocation_id, token, holder, lease_expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(invocation_id) DO UPDATE SET
                    token = excluded.token,
                    holder = excluded.holder,
                    lease_expires_at = excluded.lease_expires_at,
                    updated_at = excluded.updated_at
                """,
                (invocation_id, new_token, holder, expires, now),
            )
        return FencingToken(
            invocation_id=invocation_id,
            token=new_token,
            holder=holder,
            lease_expires_at=expires,
        )

    def validate_fencing_token(
        self, invocation_id: str, expected_token: int
    ) -> None:
        """Validate that a token matches.  Raises FencingError on mismatch."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT token FROM diagnostic_fencing_tokens "
                "WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()
        if row is None:
            raise FencingError(
                f"No fencing token for invocation {invocation_id}."
            )
        actual_token = row[0]
        if actual_token != expected_token:
            raise FencingError(
                f"Stale fencing token for {invocation_id}: "
                f"expected {expected_token}, got {actual_token}."
            )

    # ------------------------------------------------------------------ #
    # Profile mutex (C5)                                                 #
    # ------------------------------------------------------------------ #

    def acquire_profile_lock(
        self,
        *,
        profile_name: str,
        invocation_id: str,
        lease_seconds: int = 14_400,
    ) -> None:
        """Acquire an exclusive lock on a profile.

        Raises ProfileLockHeld if the profile is already locked by a
        different invocation (whose lease has not expired).
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=lease_seconds)
        with self._db.immediate_transaction() as conn:
            # Check for existing lock.
            row = conn.execute(
                "SELECT invocation_id, lease_expires_at "
                "FROM profile_execution_locks WHERE profile_name = ?",
                (profile_name,),
            ).fetchone()
            if row is not None:
                existing_invocation = row[0]
                lease_expires = datetime.fromisoformat(row[1])
                if lease_expires > now and existing_invocation != invocation_id:
                    raise ProfileLockHeld(profile_name, existing_invocation)
                # Stale or same invocation — overwrite.
                conn.execute(
                    "UPDATE profile_execution_locks "
                    "SET invocation_id = ?, acquired_at = ?, lease_expires_at = ? "
                    "WHERE profile_name = ?",
                    (invocation_id, now.isoformat(), expires.isoformat(), profile_name),
                )
            else:
                conn.execute(
                    "INSERT INTO profile_execution_locks "
                    "(profile_name, invocation_id, acquired_at, lease_expires_at) "
                    "VALUES (?, ?, ?, ?)",
                    (profile_name, invocation_id, now.isoformat(), expires.isoformat()),
                )

    def release_profile_lock(self, profile_name: str) -> None:
        """Release the profile lock."""
        with self._db.transaction() as conn:
            conn.execute(
                "DELETE FROM profile_execution_locks WHERE profile_name = ?",
                (profile_name,),
            )

    def profile_is_locked(self, profile_name: str) -> str | None:
        """Return the invocation_id holding the lock, or None."""
        now = datetime.now(timezone.utc)
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT invocation_id, lease_expires_at "
                "FROM profile_execution_locks WHERE profile_name = ?",
                (profile_name,),
            ).fetchone()
        if row is None:
            return None
        lease_expires = datetime.fromisoformat(row[1])
        if lease_expires <= now:
            return None  # Lease expired.
        return row[0]

    def reconcile_locks(self) -> list[str]:
        """Clean up expired locks.  Returns the freed profile names."""
        now = datetime.now(timezone.utc)
        freed: list[str] = []
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT profile_name, lease_expires_at FROM profile_execution_locks"
            ).fetchall()
            for row in rows:
                lease_expires = datetime.fromisoformat(row[1])
                if lease_expires <= now:
                    conn.execute(
                        "DELETE FROM profile_execution_locks WHERE profile_name = ?",
                        (row[0],),
                    )
                    freed.append(row[0])
        return freed


__all__ = [
    "DIAGNOSTIC_STATES",
    "DiagnosticStore",
    "FencingError",
    "FencingToken",
    "ProfileLockHeld",
    "ProfileMutexError",
    "TERMINAL_STATES",
    "diagnostic_migrations",
    "utc_now_iso",
]
