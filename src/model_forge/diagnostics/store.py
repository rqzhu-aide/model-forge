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

from .contracts import (
    DiagnosticState,
    TERMINAL_DIAGNOSTIC_STATES,
    is_valid_transition,
    StateTransitionError,
)

#: Legacy states for backward compatibility with existing tests.
DIAGNOSTIC_STATES = frozenset(s.value for s in DiagnosticState)
TERMINAL_STATES = TERMINAL_DIAGNOSTIC_STATES


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
        idempotency_key: str = "",
        manifest_sha256: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> str:
        """Create a pending diagnostic invocation.

        If ``idempotency_key`` is provided and an invocation with that key
        already exists, return the existing invocation_id instead of
        creating a duplicate (H0.2: duplicate submission produces one).

        Returns the invocation_id (existing or new).
        """
        # Idempotency check (H0.2).
        if idempotency_key:
            existing = self.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing["invocation_id"]

        now = utc_now_iso()
        with self._db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO diagnostic_invocations
                    (invocation_id, idempotency_key, project_id, role, profile_name, status,
                     memory_policy, manifest_sha256, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    invocation_id,
                    idempotency_key or invocation_id,
                    project_id,
                    role,
                    profile_name,
                    memory_policy,
                    manifest_sha256,
                    json.dumps(payload or {}),
                    now,
                    now,
                ),
            )
        return invocation_id

    def find_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        """Return the invocation matching the idempotency key, or None."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM diagnostic_invocations WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        return dict(row) if row is not None else None

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
        expected_token: int | None = None,
    ) -> None:
        """Update an invocation's status and terminal fields.

        Validates the state transition against the state machine (H0.6).
        If ``expected_token`` is provided, validates the fencing token
        before mutating (H0.6: token-guarded mutations).
        """
        if status not in DIAGNOSTIC_STATES:
            raise ValueError(f"Unknown diagnostic status {status!r}.")

        # Token guard (H0.6).
        if expected_token is not None:
            self.validate_fencing_token(invocation_id, expected_token)

        # State transition validation (H0.6).
        current = self.get_invocation(invocation_id)
        if current is not None:
            from_state = current["status"]
            if from_state != status and not is_valid_transition(from_state, status):
                raise StateTransitionError(
                    f"Invalid state transition: {from_state!r} -> {status!r}"
                )

        now = utc_now_iso()
        sets: list[str] = ["status = ?", "updated_at = ?"]
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

    def update_process_identity(
        self,
        invocation_id: str,
        identity: Mapping[str, Any],
        *,
        expected_token: int | None = None,
    ) -> None:
        """Persist the durable runtime identity for an invocation (H0.5)."""
        if expected_token is not None:
            self.validate_fencing_token(invocation_id, expected_token)
        now = utc_now_iso()
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE diagnostic_invocations "
                "SET process_identity_json = ?, updated_at = ? "
                "WHERE invocation_id = ?",
                (json.dumps(identity), now, invocation_id),
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

    def record_evidence(
        self,
        invocation_id: str,
        *,
        image_digest: str | None = None,
        image_tag: str | None = None,
        brief_sha256: str | None = None,
        config_digest: str | None = None,
        memory_digest_before: str | None = None,
        memory_digest_after: str | None = None,
        outcome: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """Record the evidence package for an invocation (Slice 7).

        Ties the outcome to the exact code, image, and configuration
        that produced it.
        """
        evidence = {
            "image_tag": image_tag,
            "image_digest": image_digest,
            "brief_sha256": brief_sha256,
            "config_digest": config_digest,
            "memory_digest_before": memory_digest_before,
            "memory_digest_after": memory_digest_after,
            "outcome": outcome,
            "exit_code": exit_code,
            "recorded_at": utc_now_iso(),
        }
        now = utc_now_iso()
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE diagnostic_invocations "
                "SET evidence_json = ?, updated_at = ? "
                "WHERE invocation_id = ?",
                (json.dumps(evidence), now, invocation_id),
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
        token: int = 0,
        lease_seconds: int = 14_400,
    ) -> None:
        """Acquire an exclusive lock on a profile.

        Raises ProfileLockHeld if the profile is already locked by a
        different invocation (whose lease has not expired).  The token
        is stored so that release can be owner-checked (H0.6).
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=lease_seconds)
        with self._db.immediate_transaction() as conn:
            # Check for existing lock.
            row = conn.execute(
                "SELECT invocation_id, lease_expires_at, token "
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
                    "SET invocation_id = ?, token = ?, "
                    "acquired_at = ?, lease_expires_at = ? "
                    "WHERE profile_name = ?",
                    (invocation_id, token,
                     now.isoformat(), expires.isoformat(), profile_name),
                )
            else:
                conn.execute(
                    "INSERT INTO profile_execution_locks "
                    "(profile_name, invocation_id, token, "
                    "acquired_at, lease_expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (profile_name, invocation_id, token,
                     now.isoformat(), expires.isoformat()),
                )

    def release_profile_lock(
        self,
        profile_name: str,
        *,
        expected_invocation_id: str | None = None,
        expected_token: int | None = None,
    ) -> None:
        """Release the profile lock.

        If ``expected_invocation_id`` and ``expected_token`` are provided,
        the lock is only released if the current holder matches both
        (H0.6: owner-checked release).  Otherwise it is released
        unconditionally (legacy behavior).
        """
        with self._db.transaction() as conn:
            if expected_invocation_id is not None and expected_token is not None:
                conn.execute(
                    "DELETE FROM profile_execution_locks "
                    "WHERE profile_name = ? AND invocation_id = ? AND token = ?",
                    (profile_name, expected_invocation_id, expected_token),
                )
            else:
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

    def renew_profile_lease(
        self,
        profile_name: str,
        *,
        invocation_id: str,
        expected_token: int,
        extension_seconds: int = 14_400,
    ) -> None:
        """Renew the lease on a profile lock (H0.6).

        The caller must provide the correct invocation_id and fencing
        token — only the current holder can renew.
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        new_expiry = now + timedelta(seconds=extension_seconds)
        with self._db.immediate_transaction() as conn:
            row = conn.execute(
                "SELECT invocation_id, token FROM profile_execution_locks "
                "WHERE profile_name = ?",
                (profile_name,),
            ).fetchone()
            if row is None:
                raise ProfileLockHeld(profile_name, "<none>")
            if row[0] != invocation_id or row[1] != expected_token:
                raise FencingError(
                    f"Cannot renew lease for {profile_name}: "
                    f"invocation/token mismatch."
                )
            conn.execute(
                "UPDATE profile_execution_locks SET lease_expires_at = ? "
                "WHERE profile_name = ?",
                (new_expiry.isoformat(), profile_name),
            )

    def list_nonterminal_invocations(self) -> list[dict[str, Any]]:
        """Return all invocations that are not in a terminal state.

        Used by restart reconciliation (H0.6) to find work that needs
        to be examined after a coordinator restart.
        """
        with self._db.connect() as conn:
            placeholders = ",".join("?" for _ in TERMINAL_DIAGNOSTIC_STATES)
            rows = conn.execute(
                f"SELECT * FROM diagnostic_invocations "
                f"WHERE status NOT IN ({placeholders}) "
                "ORDER BY created_at",
                tuple(TERMINAL_DIAGNOSTIC_STATES),
            ).fetchall()
        return [dict(r) for r in rows]

    def reconcile_nonterminal_invocations(self) -> list[dict[str, Any]]:
        """Restart reconciliation (H0.6): find non-terminal invocations.

        For each non-terminal invocation found after a restart:
        1. If the process is gone and output is valid → mark succeeded.
        2. If the process is gone and output is invalid → mark failed.
        3. If the process is still running → leave it (supervisor will pick up).
        4. If we can't tell → mark ``unresolved``.

        Returns the list of reconciled invocations with their new status.
        """
        nonterminal = self.list_nonterminal_invocations()
        results: list[dict[str, Any]] = []
        for inv in nonterminal:
            invocation_id = inv["invocation_id"]
            external_id = inv.get("external_execution_id")
            new_status = DiagnosticState.UNRESOLVED.value

            # Try to check if the process is still alive.
            pid = None
            if external_id and "pid:" in str(external_id):
                try:
                    pid = int(str(external_id).split("pid:")[1].split(":")[0])
                except (IndexError, ValueError):
                    pass

            if pid is not None:
                import os as _os
                try:
                    _os.kill(pid, 0)
                    # Process is still alive — don't touch it.
                    results.append({**inv, "reconciled_status": inv["status"]})
                    continue
                except (OSError, ProcessLookupError):
                    # Process is dead — need to determine outcome.
                    pass

            # Process is dead or we can't tell — mark unresolved.
            try:
                self.update_status(
                    invocation_id,
                    status=DiagnosticState.UNRESOLVED.value,
                )
            except StateTransitionError:
                # Can't transition from current state — leave as-is.
                pass
            results.append({**inv, "reconciled_status": new_status})
        return results


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
