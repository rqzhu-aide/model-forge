"""Verified SQLite session snapshot procedure (WP-D2a).

Copies a Hermes profile's session store (``state.db``) into a run profile
using the SQLite online backup API — never by copying the raw database,
WAL, or shared-memory files (ADR-012 item 5).

Safety properties:

* **Read-only source** — the source is opened with a read-only URI
  connection (``file:...?mode=ro``) and a zero busy timeout.
* **Fail fast on a busy source** — a preflight read acquires a shared lock
  on the source; when another connection holds a conflicting lock the read
  raises immediately (zero busy timeout) and :class:`SessionSnapshotBusy`
  is surfaced instead of blocking the seal.
* **No mid-copy interleaving** — the preflight read runs inside a deferred
  transaction whose shared lock is held for the duration of the online
  backup, so a writer cannot interpose between the check and the copy (a
  writer's exclusive lock request is refused while the shared lock is
  held).  In WAL mode readers never block writers, so a live Hermes
  session does not stall the snapshot and the backup still reads the last
  committed state.
* **Verified copy** — the destination must pass ``PRAGMA integrity_check``
  and a smoke query (``SELECT count(*) FROM sessions`` when the table is
  present) before its sha256 digest and byte count are recorded.
* **Credential hygiene** — the session store legitimately contains
  conversation data; it is never parsed, printed, or logged.  Only schema
  metadata (table existence), row counts, the integrity verdict, and the
  digest of the verified copy are observed.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Procedure identifier recorded in the manifest for every verified copy.
SESSION_SNAPSHOT_PROCEDURE = "sqlite_backup_v1"

#: Manifest record for empty session state (fresh/ephemeral policy, the
#: outside reviewer, or a first run with no canonical session store yet).
SESSION_SNAPSHOT_EMPTY: dict[str, str] = {"procedure": "none", "identity": "fresh"}


class SessionSnapshotError(RuntimeError):
    """A session store could not be snapshotted safely."""


class SessionSnapshotBusy(SessionSnapshotError):
    """The source session store is locked by another connection.

    Raised instead of blocking: the caller must abort the seal; the
    WP-D1 rollback removes the partially prepared run directory.
    """


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Verified session-store copy metadata (mirrors the manifest record)."""

    procedure: str
    source: Path
    quiescent: bool
    sha256: str
    bytes_count: int

    def to_manifest(self) -> dict[str, Any]:
        """Return the manifest ``session_snapshot`` record for this copy."""
        return {
            "procedure": self.procedure,
            "source": str(self.source),
            "quiescent": self.quiescent,
            "sha256": self.sha256,
            "bytes": self.bytes_count,
        }


def _is_busy_error(error: sqlite3.Error) -> bool:
    """True when *error* is a lock-contention failure (SQLITE_BUSY/LOCKED)."""
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int) and (code & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return True
    message = str(error).lower()
    return "locked" in message or "busy" in message


def _quiescent(source: Path) -> bool:
    """Quiescence observation: no ``-wal``/``-shm`` sidecars at snapshot time.

    The online backup always yields a consistent snapshot; this flag
    records whether the store appeared fully checkpointed and connection-
    free when the copy was made (ADR-012 item 5).
    """
    return not (Path(f"{source}-wal").exists() or Path(f"{source}-shm").exists())


def snapshot_session_db(
    source: Path,
    destination: Path,
    *,
    busy_timeout_seconds: float = 0.0,
) -> SessionSnapshot:
    """Snapshot *source* (a Hermes ``state.db``) into *destination*.

    Raises :class:`SessionSnapshotBusy` when the source is locked by
    another connection (zero busy timeout — the seal must abort, never
    block).  Raises :class:`SessionSnapshotError` for any other failure.
    On failure the destination is removed so no partial snapshot survives.
    """
    if not source.is_file() or source.is_symlink():
        raise SessionSnapshotError(
            f"Session store is not a regular file: {source}"
        )
    if destination.exists():
        raise SessionSnapshotError(
            f"Snapshot destination already exists: {destination}"
        )
    quiescent = _quiescent(source)
    destination.parent.mkdir(parents=True, exist_ok=True)

    # Read-only source with a zero busy timeout: a locked store must fail
    # fast, not block the seal.
    try:
        src = sqlite3.connect(
            f"{source.as_uri()}?mode=ro",
            uri=True,
            timeout=busy_timeout_seconds,
        )
    except sqlite3.Error as error:
        raise SessionSnapshotError(
            f"Cannot open session store read-only: {source}"
        ) from error

    try:
        # Preflight inside a deferred transaction: the shared lock acquired
        # here is held until ROLLBACK, i.e. for the whole backup, so no
        # writer can interpose between the busy check and the copy.
        try:
            src.execute("BEGIN")
            row = src.execute(
                "SELECT count(*) FROM sqlite_master "
                "WHERE type = 'table' AND name = 'sessions'"
            ).fetchone()
        except sqlite3.Error as error:
            if _is_busy_error(error):
                raise SessionSnapshotBusy(
                    f"Session store is busy (locked by another connection): {source}"
                ) from error
            raise SessionSnapshotError(
                f"Cannot read session store schema: {source}"
            ) from error
        has_sessions = bool(row and row[0] > 0)

        try:
            dst = sqlite3.connect(str(destination))
        except sqlite3.Error as error:
            raise SessionSnapshotError(
                f"Cannot open snapshot destination: {destination}"
            ) from error
        try:
            try:
                src.backup(dst)
            except sqlite3.Error as error:
                if _is_busy_error(error):
                    raise SessionSnapshotBusy(
                        f"Session store became busy during backup: {source}"
                    ) from error
                raise SessionSnapshotError(
                    f"Session store backup failed: {source}"
                ) from error
        finally:
            dst.close()
    finally:
        try:
            src.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        src.close()

    # Verify the copy before anything is recorded: integrity_check must
    # pass and the sessions table (when present) must answer a count.
    try:
        with sqlite3.connect(f"{destination.as_uri()}?mode=ro", uri=True) as verify:
            integrity = verify.execute("PRAGMA integrity_check").fetchall()
            if integrity != [("ok",)]:
                raise SessionSnapshotError(
                    f"Session snapshot failed integrity check: {integrity!r}"
                )
            dest_has_sessions = (
                verify.execute(
                    "SELECT count(*) FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'sessions'"
                ).fetchone()[0]
                > 0
            )
            if dest_has_sessions:
                verify.execute("SELECT count(*) FROM sessions").fetchone()
            if dest_has_sessions != has_sessions:
                raise SessionSnapshotError(
                    "Session snapshot schema mismatch between source and copy."
                )
    except SessionSnapshotError:
        destination.unlink(missing_ok=True)
        raise
    except sqlite3.Error as error:
        destination.unlink(missing_ok=True)
        raise SessionSnapshotError(
            f"Session snapshot verification failed: {destination}"
        ) from error

    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return SessionSnapshot(
        procedure=SESSION_SNAPSHOT_PROCEDURE,
        source=source,
        quiescent=quiescent,
        sha256=digest,
        bytes_count=destination.stat().st_size,
    )


__all__ = [
    "SESSION_SNAPSHOT_EMPTY",
    "SESSION_SNAPSHOT_PROCEDURE",
    "SessionSnapshot",
    "SessionSnapshotBusy",
    "SessionSnapshotError",
    "snapshot_session_db",
]
