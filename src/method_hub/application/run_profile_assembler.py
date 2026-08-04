"""Run-profile assembler core (Block 3, first half).

This service converts one run decision into a private, reconstructible
Hermes run packet without launching any process.  It owns the *prepare*
half of the trusted-local boundary (ADR-012 items 3-6); execution
integration is a later block.

Responsibilities:

* **Project-role state lock** — one writer owns role state across
  prepare/execute/promote.  The lock is DB-backed with a lease and a
  monotonically increasing fencing token; a stale owner cannot release,
  renew, or operate.  The lock and fencing semantics mirror
  :class:`method_hub.diagnostics.store.DiagnosticStore` (C5 profile
  mutex, S5.7 fencing tokens, H0.6 owner-checked release) but live on
  standalone tables so a scientific run seal never appears as a
  nonterminal *diagnostic* invocation in the diagnostic lane's restart
  reconciliation.
* **Run directory layout** — one dedicated directory per invocation
  under the Method Hub data root (never the Hermes root):
  ``runs/<invocation_id>/{profile,workspace,inputs,outputs,logs,manifest}``.
* **Profile assembly** — the run profile is an exact copy of the
  current WP-C role definition (SOUL, base configuration, recommended
  skills, library guidance), recorded with per-asset digests.  The run
  profile is never the canonical source and never writes back.
* **Memory snapshot** — the selected project-role memory is copied per
  the declared persistence policy; a first run or fresh mode gets clean
  memory; the outside reviewer always defaults to fresh.
* **Session snapshot** — for persistent/read-only policies the canonical
  project-role ``state.db`` is snapshotted into the run profile through
  the verified SQLite online backup procedure (WP-D2a): read-only source,
  zero-wait refusal when the store is busy, integrity-checked copy with a
  recorded sha256.  Fresh/ephemeral policy (and therefore always the
  outside reviewer) records empty session state.  Conversation content is
  never parsed, printed, or logged.
* **Credential hygiene** — provider credentials, tokens, and other
  secret material (``.env``, ``auth.json``, ``credential_pool``, ...)
  are never copied into the run profile, manifest, or run directory.
* **Immutable manifest** — one JCS-digested manifest per invocation
  records the phase, role, method identity, user choices, selected
  context references, role-definition revision and asset digests,
  input memory snapshot identity, working roots, Hermes executable
  path and version (detected at assembly time), and declared expected
  outputs.
* **Idempotency** — sealing twice with the same idempotency key returns
  the existing sealed record instead of creating a second run directory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from ..configuration.profiles import PROFILE_ROLES
from ..configuration.resources import RoleResource, RoleResourceCatalog
from ..configuration.skill_installer import SkillInstallationError, directory_sha256
from ..digests.jcs import canonicalize
from ..domain.runs import isoformat_utc, thaw_json, utc_now
from ..profiles.project_profiles import (
    CREDENTIAL_FILES,
    MemoryPolicy,
    project_role_profile_name,
)
from .session_snapshots import (
    SESSION_SNAPSHOT_EMPTY,
    SessionSnapshotBusy,
    SessionSnapshotError,
    snapshot_session_db,
)
from ..storage.database import Database

# --------------------------------------------------------------------------- #
# Constants                                                                    #
# --------------------------------------------------------------------------- #

MANIFEST_FORMAT = "method-hub.run-profile-manifest"
MANIFEST_FORMAT_VERSION = "1.0.0"

#: Subdirectories created for every sealed invocation (relative to run_dir).
RUN_DIR_LAYOUT: tuple[str, ...] = (
    "profile",
    "workspace",
    "inputs",
    "outputs",
    "logs",
    "manifest",
)

#: Secret file and directory names excluded from every copy at any depth.
#: Extends the project-profile scrub list (C7) with the SOUL-adjacent
#: credential files named by the trusted-local brief.
SECRET_FILE_NAMES: frozenset[str] = frozenset(
    {
        *CREDENTIAL_FILES,
        "credential_pool",
        "credentials.json",
        "secrets.json",
        "secret",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
    }
)

#: Writable profile directories the run profile needs after assembly.
_WRITABLE_PROFILE_DIRS: tuple[str, ...] = (
    "sessions",
    "logs",
    "checkpoints",
    "cache",
    "home",
    "workspace",
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


# --------------------------------------------------------------------------- #
# Errors                                                                       #
# --------------------------------------------------------------------------- #


class RunSealError(RuntimeError):
    """A run profile could not be sealed."""


class StateLockHeld(RunSealError):
    """The project-role state lock is held by another invocation."""

    def __init__(self, profile_name: str, holder_invocation_id: str) -> None:
        self.profile_name = profile_name
        self.holder_invocation_id = holder_invocation_id
        super().__init__(
            f"Project-role state for profile {profile_name!r} is locked by "
            f"invocation {holder_invocation_id}."
        )


class StateFencingError(RunSealError):
    """A fencing token is stale or invalid — the owner cannot operate."""


class ManifestDigestError(RunSealError):
    """A stored manifest digest does not match the manifest document."""


# --------------------------------------------------------------------------- #
# Records                                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class FencingToken:
    """A monotonically increasing fencing token for one invocation."""

    invocation_id: str
    token: int
    holder: str | None
    lease_expires_at: str | None


@dataclass(frozen=True, slots=True)
class StateLock:
    """A held project-role state lock handle."""

    profile_name: str
    invocation_id: str
    token: int
    lease_expires_at: str | None


@dataclass(frozen=True, slots=True)
class HermesProbe:
    """Detected Hermes executable identity at assembly time (ADR-012 item 8)."""

    executable: str | None
    version: str | None


@dataclass(frozen=True, slots=True)
class SealedRun:
    """One sealed, immutable run packet."""

    seal_id: str
    invocation_id: str
    project_id: str
    role: str
    idempotency_key: str
    run_dir: Path
    manifest_sha256: str
    manifest: Mapping[str, Any]
    sealed_at: str


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_document(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonicalize(document)).hexdigest()


def _validate_identifier(value: str, label: str) -> str:
    if type(value) is not str or not value or _IDENTIFIER_RE.fullmatch(value) is None:
        raise RunSealError(f"{label} must match {_IDENTIFIER_RE.pattern!r}.")
    if value in {".", ".."}:
        raise RunSealError(f"{label} must not be a path component.")
    return value


def _default_hermes_probe(binary: str) -> HermesProbe:
    """Locate *binary* on PATH and read its ``--version`` output.

    Returns ``HermesProbe(None, None)`` when the executable cannot be
    found or does not answer the version probe.  Never raises.
    """
    path = shutil.which(binary)
    if path is None:
        return HermesProbe(None, None)
    try:
        completed = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return HermesProbe(path, None)
    version = (completed.stdout or completed.stderr).strip() or None
    return HermesProbe(path, version)


def resolve_memory_policy(role: str, requested: MemoryPolicy | str | None) -> MemoryPolicy:
    """Resolve the effective memory policy for one role.

    The outside reviewer always defaults to fresh state (ADR-012 item 3);
    a first run or fresh mode gets clean memory.
    """
    if role not in PROFILE_ROLES:
        raise RunSealError(f"Unknown research role {role!r}.")
    if role == "outside_reviewer":
        return MemoryPolicy.EPHEMERAL
    if requested is None:
        return MemoryPolicy.default_for_role(role)
    if isinstance(requested, MemoryPolicy):
        return requested
    return MemoryPolicy(requested)


def _copy_tree_excluding(
    source: Path,
    dest: Path,
    excluded_names: frozenset[str] = SECRET_FILE_NAMES,
) -> None:
    """Copy *source* to *dest*, skipping any entry whose name matches.

    The exclusion applies at every depth, so a ``credential_pool``
    directory or a nested ``.env`` file is never copied.  Linked and
    non-regular entries fail closed.
    """
    if not source.is_dir() or source.is_symlink():
        raise RunSealError(f"Source is not a real directory: {source}")
    dest.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(source.rglob("*")):
        relative = source_path.relative_to(source)
        if any(part in excluded_names for part in relative.parts):
            continue
        target = dest / relative
        metadata = source_path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise RunSealError(f"Refusing to copy linked path: {source_path}")
        if stat.S_ISDIR(metadata.st_mode):
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise RunSealError(f"Refusing to copy non-file entry: {source_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f".{path.name}.write-{uuid.uuid4().hex}"
    staging.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os_replace(staging, path)


def os_replace(source: Path, target: Path) -> None:
    """Replace *target* with *source* atomically (POSIX rename)."""
    os.replace(source, target)


# --------------------------------------------------------------------------- #
# Run seal store                                                               #
# --------------------------------------------------------------------------- #


class RunSealStore:
    """DB-backed seal registry, project-role state lock, and fencing tokens.

    The lock and fencing semantics deliberately mirror
    :class:`~method_hub.diagnostics.store.DiagnosticStore` (C5 profile
    mutex, S5.7 fencing tokens, H0.6 owner-checked release) on standalone
    tables so scientific run seals stay out of the diagnostic lane's
    restart reconciliation.
    """

    def __init__(self, database: Database) -> None:
        self._db = database

    # -- seal registry ---------------------------------------------------

    def find_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_profile_seals WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        return dict(row) if row is not None else None

    def find_by_invocation_id(self, invocation_id: str) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_profile_seals WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def get_seal(self, seal_id: str) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_profile_seals WHERE seal_id = ?",
                (seal_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_seals(
        self,
        *,
        project_id: str | None = None,
        role: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM run_profile_seals"
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if role is not None:
            clauses.append("role = ?")
            params.append(role)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY sealed_at DESC LIMIT ?"
        params.append(limit)
        with self._db.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def create_seal(
        self,
        *,
        seal_id: str,
        invocation_id: str,
        project_id: str,
        role: str,
        idempotency_key: str,
        run_dir: str,
        manifest_sha256: str,
        sealed_at: str,
    ) -> dict[str, Any]:
        """Insert one seal row, returning the surviving record.

        The ``UNIQUE(idempotency_key)`` constraint makes concurrent
        double-seals idempotent: the loser of the race returns the
        winner's existing record.
        """
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT INTO run_profile_seals "
                    "(seal_id, invocation_id, project_id, role, idempotency_key, "
                    " run_dir, manifest_sha256, sealed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        seal_id,
                        invocation_id,
                        project_id,
                        role,
                        idempotency_key,
                        run_dir,
                        manifest_sha256,
                        sealed_at,
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
            raise
        record = self.get_seal(seal_id)
        if record is None:  # pragma: no cover — defensive
            raise RunSealError(f"Seal {seal_id!r} was not persisted.")
        return record

    # -- launch records (WP-E0) -----------------------------------------

    def create_launch_record(
        self,
        *,
        launch_id: str,
        seal_id: str,
        invocation_id: str,
        launched_at: str,
    ) -> None:
        """Insert one launch record in ``running`` state.

        The record is created when the launch intent is recorded, inside
        the project-role state lock, and closed once by
        :meth:`close_launch_record` with a terminal status.
        """
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO run_launch_records "
                "(launch_id, seal_id, invocation_id, status, launched_at) "
                "VALUES (?, ?, ?, 'running', ?)",
                (launch_id, seal_id, invocation_id, launched_at),
            )

    def record_launch_brief(self, launch_id: str, task_brief_sha256: str) -> None:
        """Record the materialized task brief digest on a launch record."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE run_launch_records SET task_brief_sha256 = ? "
                "WHERE launch_id = ?",
                (task_brief_sha256, launch_id),
            )

    def close_launch_record(
        self,
        launch_id: str,
        *,
        status: str,
        external_execution_id: str | None,
        exit_code: int | None,
        closed_at: str,
    ) -> None:
        """Close one launch record with its terminal outcome."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE run_launch_records SET status = ?, "
                "external_execution_id = ?, exit_code = ?, closed_at = ? "
                "WHERE launch_id = ?",
                (status, external_execution_id, exit_code, closed_at, launch_id),
            )

    def get_launch_record(self, launch_id: str) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_launch_records WHERE launch_id = ?",
                (launch_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def find_launch_record_by_invocation(
        self, invocation_id: str
    ) -> dict[str, Any] | None:
        """Return the most recent launch record for one invocation."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_launch_records WHERE invocation_id = ? "
                "ORDER BY launched_at DESC LIMIT 1",
                (invocation_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    # -- validation reports (WP-E1) ------------------------------------

    def record_validation_report(
        self,
        *,
        launch_id: str,
        invocation_id: str,
        seal_id: str,
        verdict: str,
        report_json: str,
        validated_at: str,
    ) -> None:
        """Record one output-validation verdict for a closed launch.

        Re-validating the same launch replaces the stored report.  The
        seal registry is never modified by validation.
        """
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO run_validation_reports "
                "(launch_id, invocation_id, seal_id, verdict, report_json, "
                " validated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(launch_id) DO UPDATE SET "
                " verdict = excluded.verdict, "
                " report_json = excluded.report_json, "
                " validated_at = excluded.validated_at",
                (launch_id, invocation_id, seal_id, verdict, report_json, validated_at),
            )

    def get_validation_report(self, launch_id: str) -> dict[str, Any] | None:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM run_validation_reports WHERE launch_id = ?",
                (launch_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    # -- fencing tokens --------------------------------------------------

    def issue_fencing_token(
        self,
        invocation_id: str,
        *,
        holder: str = "run-profile-assembler",
        lease_seconds: int = 14_400,
    ) -> FencingToken:
        """Issue a new monotonically increasing fencing token (UPSERT)."""
        now = datetime.now(timezone.utc).isoformat()
        expires = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).isoformat()
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT token FROM run_fencing_tokens WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()
            current = row[0] if row is not None else 0
            new_token = current + 1
            conn.execute(
                "INSERT INTO run_fencing_tokens "
                "(invocation_id, token, holder, lease_expires_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(invocation_id) DO UPDATE SET "
                " token = excluded.token, holder = excluded.holder, "
                " lease_expires_at = excluded.lease_expires_at, "
                " updated_at = excluded.updated_at",
                (invocation_id, new_token, holder, expires, now),
            )
        return FencingToken(
            invocation_id=invocation_id,
            token=new_token,
            holder=holder,
            lease_expires_at=expires,
        )

    def validate_fencing_token(self, invocation_id: str, expected_token: int) -> None:
        """Raise :class:`StateFencingError` when the token is stale."""
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT token FROM run_fencing_tokens WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()
        if row is None:
            raise StateFencingError(
                f"No fencing token for invocation {invocation_id}."
            )
        actual = row[0]
        if actual != expected_token:
            raise StateFencingError(
                f"Stale fencing token for {invocation_id}: "
                f"expected {expected_token}, got {actual}."
            )

    # -- project-role state lock -----------------------------------------

    def acquire_state_lock(
        self,
        *,
        profile_name: str,
        invocation_id: str,
        token: int,
        lease_seconds: int = 14_400,
    ) -> None:
        """Acquire the exclusive project-role state lock.

        Raises :class:`StateLockHeld` when another invocation holds an
        unexpired lock.  The same invocation re-acquiring is allowed
        (lease refresh), matching the diagnostic profile mutex.
        """
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=lease_seconds)
        with self._db.immediate_transaction() as conn:
            row = conn.execute(
                "SELECT invocation_id, lease_expires_at "
                "FROM project_role_state_locks WHERE profile_name = ?",
                (profile_name,),
            ).fetchone()
            if row is not None:
                existing_invocation = row[0]
                lease_expires = datetime.fromisoformat(row[1])
                if lease_expires > now and existing_invocation != invocation_id:
                    raise StateLockHeld(profile_name, existing_invocation)
                conn.execute(
                    "UPDATE project_role_state_locks "
                    "SET invocation_id = ?, token = ?, acquired_at = ?, "
                    "    lease_expires_at = ? "
                    "WHERE profile_name = ?",
                    (
                        invocation_id,
                        token,
                        now.isoformat(),
                        expires.isoformat(),
                        profile_name,
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO project_role_state_locks "
                    "(profile_name, invocation_id, token, acquired_at, "
                    " lease_expires_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        profile_name,
                        invocation_id,
                        token,
                        now.isoformat(),
                        expires.isoformat(),
                    ),
                )

    def release_state_lock(
        self,
        profile_name: str,
        *,
        expected_invocation_id: str | None = None,
        expected_token: int | None = None,
    ) -> None:
        """Release the state lock, owner-checked when both are supplied.

        A stale owner's release attempt (wrong invocation or token) is a
        no-op and cannot steal the lock from the current holder.
        """
        with self._db.transaction() as conn:
            if expected_invocation_id is not None and expected_token is not None:
                conn.execute(
                    "DELETE FROM project_role_state_locks "
                    "WHERE profile_name = ? AND invocation_id = ? AND token = ?",
                    (profile_name, expected_invocation_id, expected_token),
                )
            else:
                conn.execute(
                    "DELETE FROM project_role_state_locks WHERE profile_name = ?",
                    (profile_name,),
                )

    def state_lock_holder(self, profile_name: str) -> str | None:
        """Return the invocation_id holding the lock, or None."""
        now = datetime.now(timezone.utc)
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT invocation_id, lease_expires_at "
                "FROM project_role_state_locks WHERE profile_name = ?",
                (profile_name,),
            ).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(row[1]) <= now:
            return None
        return row[0]

    def renew_state_lease(
        self,
        profile_name: str,
        *,
        invocation_id: str,
        expected_token: int,
        extension_seconds: int = 14_400,
    ) -> None:
        """Extend the lock lease; only the current owner can renew."""
        now = datetime.now(timezone.utc)
        new_expiry = now + timedelta(seconds=extension_seconds)
        with self._db.immediate_transaction() as conn:
            row = conn.execute(
                "SELECT invocation_id, token "
                "FROM project_role_state_locks WHERE profile_name = ?",
                (profile_name,),
            ).fetchone()
            if row is None:
                raise StateLockHeld(profile_name, "<none>")
            if row[0] != invocation_id or row[1] != expected_token:
                raise StateFencingError(
                    f"Cannot renew lease for {profile_name}: "
                    f"invocation/token mismatch."
                )
            conn.execute(
                "UPDATE project_role_state_locks SET lease_expires_at = ? "
                "WHERE profile_name = ?",
                (new_expiry.isoformat(), profile_name),
            )


# --------------------------------------------------------------------------- #
# Assembler                                                                   #
# --------------------------------------------------------------------------- #


class RunProfileAssembler:
    """Assemble and seal one run packet from the current role definition.

    The assembler never launches a process and never writes back to the
    canonical role definition or the project-role profile.  It produces a
    prepared run directory that a later executor block can consume.
    """

    def __init__(
        self,
        *,
        data_root: Path,
        role_resources: RoleResourceCatalog,
        database: Database,
        bundle_root: Path | None = None,
        hermes_root: Path | None = None,
        hermes_binary: str = "hermes",
        hermes_probe: Callable[[str], HermesProbe] | None = None,
        seal_lease_seconds: int = 14_400,
    ) -> None:
        self._data_root = data_root.resolve()
        self._runs_root = self._data_root / "runs"
        self._role_resources = role_resources
        self._store = RunSealStore(database)
        self._bundle_root = bundle_root.resolve() if bundle_root is not None else None
        self._hermes_root = hermes_root.resolve() if hermes_root is not None else None
        self._hermes_binary = hermes_binary
        self._hermes_probe = hermes_probe or _default_hermes_probe
        self._lease_seconds = seal_lease_seconds

    # -- properties ------------------------------------------------------

    @property
    def runs_root(self) -> Path:
        return self._runs_root

    @property
    def store(self) -> RunSealStore:
        return self._store

    def run_dir_for(self, invocation_id: str) -> Path:
        _validate_identifier(invocation_id, "invocation_id")
        return self._runs_root / invocation_id

    # -- locking ---------------------------------------------------------

    @contextmanager
    def state_lock(
        self,
        project_id: str,
        role: str,
        invocation_id: str,
        *,
        lease_seconds: int | None = None,
    ) -> Iterator[StateLock]:
        """Hold the project-role state lock for one operation.

        Acquires a fresh fencing token and the exclusive DB-backed lock;
        releases owner-checked on exit.  Raises :class:`StateLockHeld`
        when another invocation owns the role state.
        """
        if role not in PROFILE_ROLES:
            raise RunSealError(f"Unknown research role {role!r}.")
        profile_name = project_role_profile_name(project_id, role)
        effective = self._lease_seconds if lease_seconds is None else lease_seconds
        token_record = self._store.issue_fencing_token(
            invocation_id,
            holder="run-profile-assembler",
            lease_seconds=effective,
        )
        self._store.acquire_state_lock(
            profile_name=profile_name,
            invocation_id=invocation_id,
            token=token_record.token,
            lease_seconds=effective,
        )
        try:
            yield StateLock(
                profile_name=profile_name,
                invocation_id=invocation_id,
                token=token_record.token,
                lease_expires_at=token_record.lease_expires_at,
            )
        finally:
            self._store.release_state_lock(
                profile_name,
                expected_invocation_id=invocation_id,
                expected_token=token_record.token,
            )

    # -- sealing ---------------------------------------------------------

    def seal_invocation(
        self,
        *,
        invocation_id: str,
        idempotency_key: str,
        project_id: str,
        role: str,
        phase: str,
        method_identity: Mapping[str, Any] | None = None,
        user_choices: Mapping[str, Any] | None = None,
        selected_context_references: Sequence[Mapping[str, Any]] = (),
        expected_outputs: Sequence[Mapping[str, Any]] = (),
        memory_policy: MemoryPolicy | str | None = None,
    ) -> SealedRun:
        """Seal one idempotent invocation into a prepared run directory.

        The first call with a given *idempotency_key* creates the run
        directory, assembles the profile, snapshots memory, writes the
        snapshots session state, writes the immutable manifest, and
        records the seal.  Later calls with the same key return the
        existing sealed record untouched.
        """
        _validate_identifier(invocation_id, "invocation_id")
        _validate_identifier(idempotency_key, "idempotency_key")
        _validate_identifier(project_id, "project_id")
        if role not in PROFILE_ROLES:
            raise RunSealError(f"Unknown research role {role!r}.")
        if type(phase) is not str or not phase:
            raise RunSealError("phase must be a nonempty string.")

        # Idempotency: an existing seal wins without touching the filesystem.
        existing = self._store.find_by_idempotency_key(idempotency_key)
        if existing is not None:
            return self._reconstruct(existing)

        resource = self._role_resources.role(role)
        policy = resolve_memory_policy(role, memory_policy)
        run_dir = self.run_dir_for(invocation_id)
        if run_dir.exists():
            raise RunSealError(
                f"Run directory already exists without a seal: {run_dir}"
            )

        with self.state_lock(project_id, role, invocation_id) as lock:
            try:
                self._create_layout(run_dir)
                profile_dir = run_dir / "profile"
                asset_digests = self._assemble_profile(resource, profile_dir)
                memory_snapshot = self._snapshot_memory(project_id, role, profile_dir, policy)
                session_snapshot = self._snapshot_session(
                    project_id, role, profile_dir, policy
                )
                probe = self._hermes_probe(self._hermes_binary)

                seal_id = uuid.uuid4().hex
                sealed_at = isoformat_utc(utc_now())
                document = self._build_manifest(
                    seal_id=seal_id,
                    invocation_id=invocation_id,
                    project_id=project_id,
                    role=role,
                    phase=phase,
                    method_identity=method_identity,
                    user_choices=user_choices,
                    selected_context_references=selected_context_references,
                    expected_outputs=expected_outputs,
                    resource=resource,
                    asset_digests=asset_digests,
                    memory_snapshot=memory_snapshot,
                    session_snapshot=session_snapshot,
                    run_dir=run_dir,
                    probe=probe,
                    lock=lock,
                    sealed_at=sealed_at,
                )
                manifest_sha256 = _digest_document(document)
                self._write_manifest(run_dir, document, manifest_sha256)

                record = self._store.create_seal(
                    seal_id=seal_id,
                    invocation_id=invocation_id,
                    project_id=project_id,
                    role=role,
                    idempotency_key=idempotency_key,
                    run_dir=str(run_dir),
                    manifest_sha256=manifest_sha256,
                    sealed_at=sealed_at,
                )
            except Exception:
                # Roll back a partially prepared run directory so a failed
                # seal never permanently blocks a retry of this invocation.
                shutil.rmtree(run_dir, ignore_errors=True)
                raise

        # The idempotency race loser returns the winner's record.
        if record["seal_id"] != seal_id:
            # This attempt lost the race after preparing its own directory;
            # remove it so no unsealed run directory is left behind.
            shutil.rmtree(run_dir, ignore_errors=True)
            return self._reconstruct(record)
        return SealedRun(
            seal_id=record["seal_id"],
            invocation_id=record["invocation_id"],
            project_id=record["project_id"],
            role=record["role"],
            idempotency_key=record["idempotency_key"],
            run_dir=Path(record["run_dir"]),
            manifest_sha256=record["manifest_sha256"],
            manifest=document,
            sealed_at=record["sealed_at"],
        )

    # -- internals -------------------------------------------------------

    def _create_layout(self, run_dir: Path) -> None:
        for name in RUN_DIR_LAYOUT:
            (run_dir / name).mkdir(parents=True, exist_ok=False)

    def _assemble_profile(
        self,
        resource: RoleResource,
        profile_dir: Path,
    ) -> dict[str, str]:
        """Copy the role definition exactly; record per-asset digests.

        The run profile is assembled only from the configuration-managed
        role definition (SOUL, base configuration, recommended skills,
        library guidance).  Custom skills are declarations in the catalog
        without bundled content, so they are recorded in the manifest and
        never fabricated here.
        """
        digests: dict[str, str] = {}

        soul_target = profile_dir / "SOUL.md"
        soul_target.write_text(resource.soul_text, encoding="utf-8")
        digests["SOUL.md"] = _digest_file(soul_target)

        config = resource.base_configuration
        config_target = profile_dir / config.file_name
        config_target.parent.mkdir(parents=True, exist_ok=True)
        config_target.write_text(config.content, encoding="utf-8")
        digests[config.file_name] = _digest_file(config_target)

        guidance = resource.library_guidance
        guidance_target = profile_dir / guidance.file_name
        guidance_target.parent.mkdir(parents=True, exist_ok=True)
        guidance_target.write_text(guidance.content, encoding="utf-8")
        digests[guidance.file_name] = _digest_file(guidance_target)

        skills_root = profile_dir / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)
        for skill in resource.recommended_skills:
            source = (
                self._bundle_root / skill.skill_id
                if self._bundle_root is not None
                else None
            )
            if source is None or not source.is_dir() or source.is_symlink():
                raise RunSealError(
                    f"Recommended skill {skill.skill_id!r} for role "
                    f"{resource.role_id!r} is unavailable in the bundle."
                )
            dest = skills_root / skill.skill_id
            _copy_tree_excluding(source, dest)
            try:
                digests[f"skills/{skill.skill_id}"] = directory_sha256(dest)
            except SkillInstallationError as error:
                raise RunSealError(
                    f"Skill {skill.skill_id!r} copy failed digest verification."
                ) from error

        for dirname in _WRITABLE_PROFILE_DIRS:
            (profile_dir / dirname).mkdir(exist_ok=True)

        return digests

    def _project_role_profile_dir(self, project_id: str, role: str) -> Path | None:
        if self._hermes_root is None:
            return None
        return self._hermes_root / "profiles" / project_role_profile_name(project_id, role)

    def _snapshot_memory(
        self,
        project_id: str,
        role: str,
        profile_dir: Path,
        policy: MemoryPolicy,
    ) -> dict[str, Any]:
        """Realize the memory snapshot per the resolved persistence policy.

        Persistent/read-only roles receive the latest promoted project-role
        memory when it exists; a first run or fresh mode gets clean memory.
        Secret files are excluded from the copy.
        """
        memories_dir = profile_dir / "memories"
        memories_dir.mkdir(parents=True, exist_ok=True)

        if policy is MemoryPolicy.EPHEMERAL:
            return {
                "policy": policy.value,
                "identity": "fresh",
                "digest": directory_sha256(memories_dir),
                "source": None,
            }

        source = self._project_role_profile_dir(project_id, role)
        source_memories = source / "memories" if source is not None else None
        if source_memories is not None and source_memories.is_dir():
            _copy_tree_excluding(source_memories, memories_dir)
            return {
                "policy": policy.value,
                "identity": directory_sha256(memories_dir),
                "digest": directory_sha256(memories_dir),
                "source": str(source_memories),
            }

        # First run: clean memory even for a persistent role.
        return {
            "policy": policy.value,
            "identity": "fresh",
            "digest": directory_sha256(memories_dir),
            "source": None,
        }

    def _snapshot_session(
        self,
        project_id: str,
        role: str,
        profile_dir: Path,
        policy: MemoryPolicy,
    ) -> dict[str, Any]:
        """Realize the session snapshot per the resolved persistence policy.

        Persistent/read-only roles receive a verified SQLite online backup
        of the canonical project-role ``state.db`` when one exists; a
        first run, fresh/ephemeral policy, and the outside reviewer
        (always fresh) record empty session state.  A busy source raises
        :class:`SessionSnapshotBusy`, aborting the seal — the WP-D1
        rollback removes the partially prepared run directory.
        """
        if policy is MemoryPolicy.EPHEMERAL:
            return dict(SESSION_SNAPSHOT_EMPTY)
        source_dir = self._project_role_profile_dir(project_id, role)
        source = source_dir / "state.db" if source_dir is not None else None
        if source is None or not source.is_file() or source.is_symlink():
            return dict(SESSION_SNAPSHOT_EMPTY)
        snapshot = snapshot_session_db(source, profile_dir / "state.db")
        return snapshot.to_manifest()

    def _build_manifest(
        self,
        *,
        seal_id: str,
        invocation_id: str,
        project_id: str,
        role: str,
        phase: str,
        method_identity: Mapping[str, Any] | None,
        user_choices: Mapping[str, Any] | None,
        selected_context_references: Sequence[Mapping[str, Any]],
        expected_outputs: Sequence[Mapping[str, Any]],
        resource: RoleResource,
        asset_digests: Mapping[str, str],
        memory_snapshot: Mapping[str, Any],
        session_snapshot: Mapping[str, Any],
        run_dir: Path,
        probe: HermesProbe,
        lock: StateLock,
        sealed_at: str,
    ) -> dict[str, Any]:
        return {
            "format": MANIFEST_FORMAT,
            "format_version": MANIFEST_FORMAT_VERSION,
            "invocation_id": invocation_id,
            "seal_id": seal_id,
            "project_id": project_id,
            "phase": phase,
            "role": role,
            "method_identity": (
                thaw_json(method_identity) if method_identity is not None else None
            ),
            "user_choices": thaw_json(user_choices or {}),
            "selected_context_references": [
                thaw_json(item) for item in selected_context_references
            ],
            "role_definition": {
                "role_id": resource.role_id,
                "display_name": resource.display_name,
                "revision": resource.profile_version,
                "default_profile": resource.default_profile,
                "asset_digests": dict(asset_digests),
                "recommended_skills": [
                    {
                        "skill_id": skill.skill_id,
                        "name": skill.name,
                        "source": skill.source,
                        "recommended_version": skill.recommended_version,
                    }
                    for skill in resource.recommended_skills
                ],
                "custom_skills": [
                    {
                        "skill_id": skill.skill_id,
                        "name": skill.name,
                        "source": skill.source,
                        "copied": False,
                    }
                    for skill in resource.custom_skills
                ],
            },
            "memory_snapshot": dict(memory_snapshot),
            "session_snapshot": dict(session_snapshot),
            "state_lock": {
                "profile_name": lock.profile_name,
                "token": lock.token,
            },
            "working_roots": {
                "run_dir": str(run_dir),
                "profile": str(run_dir / "profile"),
                "workspace": str(run_dir / "workspace"),
                "inputs": str(run_dir / "inputs"),
                "outputs": str(run_dir / "outputs"),
                "logs": str(run_dir / "logs"),
                "manifest": str(run_dir / "manifest"),
            },
            "hermes": {
                "executable": probe.executable,
                "version": probe.version,
            },
            "expected_outputs": [thaw_json(item) for item in expected_outputs],
            "sealed_at": sealed_at,
        }

    def _write_manifest(
        self,
        run_dir: Path,
        document: Mapping[str, Any],
        manifest_sha256: str,
    ) -> None:
        manifest_dir = run_dir / "manifest"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        _write_json_atomic(manifest_dir / "manifest.json", document)
        digest_path = manifest_dir / "manifest.sha256"
        staging = digest_path.parent / f".{digest_path.name}.write-{uuid.uuid4().hex}"
        staging.write_text(manifest_sha256 + "\n", encoding="utf-8")
        os.replace(staging, digest_path)

    def _reconstruct(self, record: Mapping[str, Any]) -> SealedRun:
        """Rebuild a :class:`SealedRun` from a stored seal record."""
        run_dir = Path(record["run_dir"])
        manifest_path = run_dir / "manifest" / "manifest.json"
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RunSealError(
                f"Sealed manifest is unreadable at {manifest_path}."
            ) from error
        recomputed = _digest_document(document)
        if recomputed != record["manifest_sha256"]:
            raise ManifestDigestError(
                f"Manifest digest mismatch for seal {record['seal_id']!r}: "
                f"recorded {record['manifest_sha256']}, recomputed {recomputed}."
            )
        return SealedRun(
            seal_id=record["seal_id"],
            invocation_id=record["invocation_id"],
            project_id=record["project_id"],
            role=record["role"],
            idempotency_key=record["idempotency_key"],
            run_dir=run_dir,
            manifest_sha256=record["manifest_sha256"],
            manifest=document,
            sealed_at=record["sealed_at"],
        )


__all__ = [
    "FencingToken",
    "HermesProbe",
    "MANIFEST_FORMAT",
    "MANIFEST_FORMAT_VERSION",
    "ManifestDigestError",
    "RUN_DIR_LAYOUT",
    "RunProfileAssembler",
    "RunSealError",
    "RunSealStore",
    "SECRET_FILE_NAMES",
    "SealedRun",
    "SessionSnapshotBusy",
    "SessionSnapshotError",
    "StateFencingError",
    "StateLock",
    "StateLockHeld",
    "_copy_tree_excluding",
    "_default_hermes_probe",
    "resolve_memory_policy",
]
