"""Allowlisted memory/session state promotion for validated runs (Block 5, WP-E2).

This service promotes ONLY the project-role MEMORY and SESSION state of a
successful, validated run into the canonical project-role profile.  It is the
write-back half of the trusted-local boundary (ADR-012 item 6): SOUL, skills,
base configuration, credentials, logs, and caches are never copied back from
a run.  Formal-artifact promotion into the artifact store is a later concern
(WP-E3 receipts / the formal lane) and is deliberately absent here.

Protocol (``promote_run_state``)
================================

1. **Gates** — every gate must hold before anything is read or written:

   * the invocation's most recent launch record is closed with status
     ``succeeded`` (a missing/``running``/``failed``/``cancelled`` launch
     promotes nothing);
   * a passing WP-E1 validation report exists for that launch (verdict
     ``pass``; failed, cancelled, timed-out, invalid, or unresolved outcomes
     promote nothing);
   * the resolved memory policy is neither ``ephemeral`` nor ``read_only``
     (the outside reviewer is always ephemeral per WP-D1, so it can never
     promote; ``read_only`` inspects without promotion per Block 3 rule 3);
   * the caller holds the project-role state lock for the whole promotion
     (``assembler.state_lock``), so one writer owns role state across
     prepare/execute/promote.

2. **Inventories** — raw evidence captured before any mutation, mirroring the
   WP-E1 raw-inventory style (relative path, sha256, size; symlinks are
   recorded with an empty digest and never followed):

   * ``memory_before`` — digest inventory of the canonical project-role
     ``memories/`` (empty on the first promotion);
   * ``runtime_after`` — digest inventory of the run profile's ``memories/``
     and ``state.db``.

3. **Allowlisted staging** — only the run profile's ``memories/`` tree and
   its ``state.db`` are copied into a staging directory.  ``SECRET_FILE_NAMES``
   entries are excluded at every depth; symlinks and special entries fail
   closed; every staged file's digest is verified against the runtime-after
   inventory.

4. **Atomic replace with last-known-good preservation** — for each target
   (canonical ``memories/`` and canonical ``state.db``) in one locked
   transaction-like sequence: back up the current canonical target by
   renaming it to a timestamped sibling, move the staged replacement into
   place, and verify the replacement's digests post-move.  On ANY failure at
   ANY step (backup, move, verify, or the promotion-record write) every
   completed target is restored from its backup so the previous canonical
   state is byte-identical after a failed promotion (the Block 5 checkpoint).
   On success the backups are kept; retention pruning is WP-E3's concern.

5. **Promotion record** — one row in ``run_promotion_records`` proves what
   happened: seal and invocation identity, per-target before/after digests,
   backup paths, and status.  Full receipts are WP-E3.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..digests.jcs import canonicalize
from ..domain.runs import isoformat_utc, utc_now
from ..profiles.project_profiles import MemoryPolicy
from .run_profile_assembler import (
    SECRET_FILE_NAMES,
    RunProfileAssembler,
    RunSealError,
    SealedRun,
    resolve_memory_policy,
)

#: Promotion record identity recorded in ``run_promotion_records``.
PROMOTION_FORMAT = "model-forge.run-promotion"
PROMOTION_FORMAT_VERSION = "1.0.0"

#: Launch status that may promote (the validation lane accepts a wider
#: terminal set; promotion is deliberately narrower).
_LAUNCH_STATUS_SUCCEEDED = "succeeded"

#: Promotion target names, in swap order.
_TARGET_MEMORIES = "memories"
_TARGET_STATE_DB = "state.db"

#: Directory prefix used for the temporary staging directory.  The staging
#: directory lives INSIDE the canonical profile directory so the final
#: ``os.replace`` moves stay on one filesystem (atomic rename).
_STAGING_PREFIX = ".promotion-staging-"

#: Backup name suffix format for last-known-good preservation.
_BACKUP_SUFFIX_FORMAT = "bak-%Y%m%dT%H%M%S%f"


# --------------------------------------------------------------------------- #
# Errors                                                                       #
# --------------------------------------------------------------------------- #


class PromotionError(RuntimeError):
    """Project-role state could not be promoted."""


class LaunchNotSucceededError(PromotionError):
    """The invocation's launch record is not closed with status succeeded."""


class ValidationNotPassedError(PromotionError):
    """No passing WP-E1 validation report exists for the invocation."""


class MemoryPolicyNotPromotableError(PromotionError):
    """The resolved memory policy never promotes (ephemeral/read_only)."""


class PromotionStagingError(PromotionError):
    """The allowlisted staging step failed or detected disallowed content."""


class PromotionSwapError(PromotionError):
    """The atomic replace step failed; the previous state was restored."""


# --------------------------------------------------------------------------- #
# Records                                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class StateInventoryEntry:
    """One raw state entry: path + sha256 + size, symlinks never followed."""

    relative_path: str
    sha256: str
    size_bytes: int
    is_symlink: bool
    is_regular: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "is_symlink": self.is_symlink,
            "is_regular": self.is_regular,
        }


@dataclass(frozen=True, slots=True)
class PromotionTargetResult:
    """Before/after digest and backup location for one promoted target."""

    name: str
    before_digest: str | None
    after_digest: str | None
    backup_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "before_digest": self.before_digest,
            "after_digest": self.after_digest,
            "backup_path": self.backup_path,
        }


@dataclass(frozen=True, slots=True)
class PromotionResult:
    """The complete outcome of one successful promotion."""

    seal_id: str
    invocation_id: str
    project_id: str
    role: str
    promoted: bool
    promoted_at: str
    memory_before_inventory: tuple[StateInventoryEntry, ...]
    runtime_after_inventory: tuple[StateInventoryEntry, ...]
    targets: tuple[PromotionTargetResult, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": PROMOTION_FORMAT,
            "format_version": PROMOTION_FORMAT_VERSION,
            "promoted": self.promoted,
            "seal_id": self.seal_id,
            "invocation_id": self.invocation_id,
            "project_id": self.project_id,
            "role": self.role,
            "promoted_at": self.promoted_at,
            "memory_before_inventory": [
                entry.to_dict() for entry in self.memory_before_inventory
            ],
            "runtime_after_inventory": [
                entry.to_dict() for entry in self.runtime_after_inventory
            ],
            "targets": [target.to_dict() for target in self.targets],
        }


@dataclass(frozen=True, slots=True)
class _CompletedTarget:
    """One fully swapped target awaiting its record; used for rollback."""

    name: str
    backup_path: Path | None
    before_digest: str | None
    after_digest: str


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entries_digest(entries: Sequence[StateInventoryEntry]) -> str:
    """Content-addressed digest of one inventory slice (canonical JSON)."""
    payload = canonicalize([entry.to_dict() for entry in entries])
    return hashlib.sha256(payload).hexdigest()


def _lexists(path: Path) -> bool:
    return path.is_symlink() or path.exists()


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _is_excluded(relative: str) -> bool:
    """True when any path component matches the WP-D1 secret exclusion set."""
    return any(part in SECRET_FILE_NAMES for part in Path(relative).parts)


def _walk_inventory(root: Path) -> tuple[StateInventoryEntry, ...]:
    """Digest inventory of a directory tree; symlinks recorded, never followed.

    Mirrors the WP-E1 raw-output walk: regular files are digested, symlinks
    and special entries are recorded with an empty digest so the raw evidence
    preserves their presence and kind.  A missing root yields an empty
    inventory (first-promotion memory-before).
    """
    if not _lexists(root):
        return ()
    if root.is_symlink() or not root.is_dir():
        raise PromotionError(f"State tree is not a real directory: {root}")
    entries: list[StateInventoryEntry] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dir_path = Path(dirpath)
        for dirname in dirnames:
            candidate = dir_path / dirname
            metadata = candidate.lstat()
            if os.path.islink(candidate):
                entries.append(
                    StateInventoryEntry(
                        relative_path=candidate.relative_to(root).as_posix(),
                        sha256="",
                        size_bytes=metadata.st_size,
                        is_symlink=True,
                        is_regular=False,
                    )
                )
        for filename in filenames:
            candidate = dir_path / filename
            metadata = candidate.lstat()
            relative = candidate.relative_to(root).as_posix()
            if os.path.islink(candidate):
                entries.append(
                    StateInventoryEntry(
                        relative_path=relative,
                        sha256="",
                        size_bytes=metadata.st_size,
                        is_symlink=True,
                        is_regular=False,
                    )
                )
                continue
            if os.path.isfile(candidate):
                try:
                    sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
                except OSError:
                    sha256 = ""
                entries.append(
                    StateInventoryEntry(
                        relative_path=relative,
                        sha256=sha256,
                        size_bytes=metadata.st_size,
                        is_symlink=False,
                        is_regular=True,
                    )
                )
            else:
                entries.append(
                    StateInventoryEntry(
                        relative_path=relative,
                        sha256="",
                        size_bytes=metadata.st_size,
                        is_symlink=False,
                        is_regular=False,
                    )
                )
    return tuple(entries)


def _file_entry(relative_path: str, path: Path) -> StateInventoryEntry:
    """One inventory entry for a regular, non-linked file."""
    if path.is_symlink() or not path.is_file():
        raise PromotionError(f"State file is not a regular file: {path}")
    return StateInventoryEntry(
        relative_path=relative_path,
        sha256=_digest_file(path),
        size_bytes=path.stat().st_size,
        is_symlink=False,
        is_regular=True,
    )


def _recompute_target_entries(
    name: str, canonical: Path
) -> tuple[StateInventoryEntry, ...]:
    """Re-derive the inventory slice directly from the canonical target."""
    if name == _TARGET_MEMORIES:
        return _walk_inventory(canonical)
    return (_file_entry(_TARGET_STATE_DB, canonical),)


def _backup_suffix(now: datetime) -> str:
    return now.strftime(_BACKUP_SUFFIX_FORMAT) + "-" + uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------- #
# Promotion steps (module-level so tests can inject failures per step)         #
# --------------------------------------------------------------------------- #


def _backup_target(canonical: Path, backup: Path) -> None:
    """Rename the current canonical target to its timestamped sibling backup."""
    os.replace(canonical, backup)


def _move_into_place(staged: Path, canonical: Path) -> None:
    """Move a staged replacement into the canonical position (atomic rename)."""
    os.replace(staged, canonical)


def _verify_replacement(name: str, canonical: Path, expected_digest: str) -> None:
    """Verify the moved-in replacement byte-for-byte against the inventory."""
    recomputed = _entries_digest(_recompute_target_entries(name, canonical))
    if recomputed != expected_digest:
        raise PromotionSwapError(
            f"Post-move verification failed for {name!r}: "
            f"expected {expected_digest}, recomputed {recomputed}."
        )


def _restore_target(canonical: Path, backup: Path | None) -> None:
    """Restore one canonical target completely from its backup.

    When *backup* is None the target did not exist before (first promotion):
    restoring means removing whatever was moved in.
    """
    if backup is not None and _lexists(backup):
        if _lexists(canonical):
            _remove_path(canonical)
        os.replace(backup, canonical)
    elif _lexists(canonical):
        _remove_path(canonical)


# --------------------------------------------------------------------------- #
# Staging                                                                      #
# --------------------------------------------------------------------------- #


def _stage_allowlisted(
    run_memories: Path,
    run_state_db: Path,
    staging_dir: Path,
    after_inventory: Sequence[StateInventoryEntry],
) -> dict[str, Path]:
    """Stage ONLY allowlisted state: run ``memories/`` and ``state.db``.

    Secret-named entries are excluded at every depth; symlinks and special
    entries fail closed.  Every staged file's digest is verified against the
    runtime-after inventory (the allowlisted subset must match exactly).
    Returns the staged paths keyed by target name.
    """
    if not run_memories.is_dir() or run_memories.is_symlink():
        raise PromotionStagingError(
            f"Run profile memories are not a real directory: {run_memories}"
        )
    inventory_by_path = {
        entry.relative_path: entry
        for entry in after_inventory
        if entry.relative_path != _TARGET_STATE_DB
    }

    staged_memories = staging_dir / _TARGET_MEMORIES
    staged_memories.mkdir(parents=True, exist_ok=False)
    staged: dict[str, Path] = {_TARGET_MEMORIES: staged_memories}

    for source_path in sorted(run_memories.rglob("*")):
        relative = source_path.relative_to(run_memories).as_posix()
        if _is_excluded(relative):
            continue
        metadata = source_path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise PromotionStagingError(
                f"Refusing to promote linked path: {source_path}"
            )
        if stat.S_ISDIR(metadata.st_mode):
            (staged_memories / relative).mkdir(parents=True, exist_ok=True)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise PromotionStagingError(
                f"Refusing to promote non-file entry: {source_path}"
            )
        _copy_staged_file(source_path, staged_memories / relative)

    # Verify every staged file against the runtime-after inventory.
    staged_entries = _walk_inventory(staged_memories)
    staged_by_path = {
        entry.relative_path: entry for entry in staged_entries if entry.is_regular
    }
    expected_by_path = {
        relative: entry
        for relative, entry in inventory_by_path.items()
        if entry.is_regular and not _is_excluded(relative)
    }
    if set(staged_by_path) != set(expected_by_path):
        missing = sorted(set(expected_by_path) - set(staged_by_path))
        extra = sorted(set(staged_by_path) - set(expected_by_path))
        raise PromotionStagingError(
            "Staged memories do not match the runtime-after inventory: "
            f"missing={missing}, extra={extra}."
        )
    for relative, entry in staged_by_path.items():
        expected = expected_by_path[relative]
        if entry.sha256 != expected.sha256 or entry.size_bytes != expected.size_bytes:
            raise PromotionStagingError(
                f"Staged digest mismatch for memories/{relative}: "
                f"expected {expected.sha256}, got {entry.sha256}."
            )

    # Session state: the run profile's state.db, when one exists.
    if _lexists(run_state_db):
        if run_state_db.is_symlink() or not run_state_db.is_file():
            raise PromotionStagingError(
                f"Run session store is not a regular file: {run_state_db}"
            )
        db_entry = _file_entry(_TARGET_STATE_DB, run_state_db)
        if db_entry not in after_inventory:
            raise PromotionStagingError(
                "Run state.db is absent from the runtime-after inventory."
            )
        staged_db = staging_dir / _TARGET_STATE_DB
        _copy_staged_file(run_state_db, staged_db)
        staged[_TARGET_STATE_DB] = staged_db
        staged_db_entry = _file_entry(_TARGET_STATE_DB, staged_db)
        if (
            staged_db_entry.sha256 != db_entry.sha256
            or staged_db_entry.size_bytes != db_entry.size_bytes
        ):
            raise PromotionStagingError(
                "Staged state.db digest mismatch against the runtime-after "
                "inventory."
            )
    return staged


def _copy_staged_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


# --------------------------------------------------------------------------- #
# Gates                                                                        #
# --------------------------------------------------------------------------- #


def _resolve_seal(
    assembler: RunProfileAssembler, seal_or_invocation_id: SealedRun | str
) -> SealedRun:
    if isinstance(seal_or_invocation_id, SealedRun):
        return seal_or_invocation_id
    if isinstance(seal_or_invocation_id, str):
        record = assembler.store.find_by_invocation_id(seal_or_invocation_id)
        if record is None:
            raise RunSealError(
                f"No sealed run for invocation {seal_or_invocation_id!r}."
            )
        return assembler._reconstruct(record)  # verifies the manifest digest
    raise TypeError(
        "seal_or_invocation_id must be a SealedRun or an invocation id string"
    )


def _require_succeeded_launch(
    assembler: RunProfileAssembler, invocation_id: str
) -> dict[str, Any]:
    """Gate 1: the invocation's most recent launch record succeeded."""
    launch = assembler.store.find_launch_record_by_invocation(invocation_id)
    if launch is None:
        raise LaunchNotSucceededError(
            f"No launch record for invocation {invocation_id!r}; "
            "promotion requires a succeeded launch."
        )
    if launch["status"] != _LAUNCH_STATUS_SUCCEEDED:
        raise LaunchNotSucceededError(
            f"Launch {launch['launch_id']!r} for invocation "
            f"{invocation_id!r} has status {launch['status']!r}; "
            "promotion requires a succeeded launch."
        )
    return launch


def _require_passing_validation(
    assembler: RunProfileAssembler,
    launch: Mapping[str, Any],
    invocation_id: str,
    seal_id: str,
) -> dict[str, Any]:
    """Gate 2: a passing WP-E1 validation report exists for the launch."""
    report = assembler.store.get_validation_report(launch["launch_id"])
    if report is None:
        raise ValidationNotPassedError(
            f"No validation report for launch {launch['launch_id']!r}; "
            "promotion requires a passing WP-E1 report."
        )
    if report["verdict"] != "pass":
        raise ValidationNotPassedError(
            f"Validation verdict for launch {launch['launch_id']!r} is "
            f"{report['verdict']!r}; only passing runs promote."
        )
    if report["invocation_id"] != invocation_id or report["seal_id"] != seal_id:
        raise ValidationNotPassedError(
            f"Validation report for launch {launch['launch_id']!r} does not "
            "match the sealed invocation; refusing promotion."
        )
    return report


def _require_promotable_policy(sealed: SealedRun) -> MemoryPolicy:
    """Gate 3: the resolved memory policy is neither ephemeral nor read_only.

    The manifest records the policy resolved at seal time (the outside
    reviewer is always ephemeral per WP-D1).  Re-resolving against the role
    keeps the gate honest even for a hypothetical mismatched manifest.
    """
    raw = sealed.manifest.get("memory_snapshot") or {}
    policy_value = raw.get("policy")
    try:
        requested = MemoryPolicy(policy_value) if policy_value else None
        policy = resolve_memory_policy(sealed.role, requested)
    except ValueError as error:
        raise PromotionError(
            f"Unrecognized memory policy {policy_value!r} in the manifest."
        ) from error
    if policy in (MemoryPolicy.EPHEMERAL, MemoryPolicy.READ_ONLY):
        raise MemoryPolicyNotPromotableError(
            f"Memory policy {policy.value!r} never promotes "
            f"(role {sealed.role!r}); only persistent runs may replace "
            "project-role state."
        )
    return policy


# --------------------------------------------------------------------------- #
# Atomic swap                                                                  #
# --------------------------------------------------------------------------- #


def _swap_targets(
    canonical_dir: Path,
    staged: Mapping[str, Path],
    now: datetime,
) -> tuple[tuple[PromotionTargetResult, ...], tuple[_CompletedTarget, ...]]:
    """Atomically replace each canonical target, preserving last-known-good.

    Every step (backup, move, verify) is inside one transaction-like
    sequence: on ANY failure every completed target — and the in-flight
    target, once its backup happened — is restored completely before the
    error propagates.  Returns the per-target results plus the completed
    bookkeeping so the caller can extend the rollback scope (e.g. to the
    promotion-record write).
    """
    target_names = [_TARGET_MEMORIES]
    if _TARGET_STATE_DB in staged:
        target_names.append(_TARGET_STATE_DB)

    completed: list[_CompletedTarget] = []
    in_flight: _CompletedTarget | None = None
    try:
        for name in target_names:
            canonical = canonical_dir / name
            backup: Path | None = None
            before_digest: str | None = None
            # The after digest describes exactly what will be moved into
            # place: the staged (allowlisted) content, not the raw
            # runtime-after inventory (which records secret-named entries
            # that are never staged).
            after_digest = _entries_digest(
                _recompute_target_entries(name, staged[name])
            )
            if _lexists(canonical):
                if canonical.is_symlink():
                    raise PromotionSwapError(
                        f"Canonical target is a symlink; refusing: {canonical}"
                    )
                backup = canonical_dir / (name + "." + _backup_suffix(now))
                _backup_target(canonical, backup)
                # Registered as in-flight immediately after the backup so any
                # later failure (including the before-digest read) restores it.
                in_flight = _CompletedTarget(
                    name=name,
                    backup_path=backup,
                    before_digest=None,
                    after_digest=after_digest,
                )
                before_digest = _entries_digest(
                    _recompute_target_entries(name, backup)
                )
            else:
                in_flight = _CompletedTarget(
                    name=name,
                    backup_path=None,
                    before_digest=None,
                    after_digest=after_digest,
                )
            in_flight = _CompletedTarget(
                name=name,
                backup_path=backup,
                before_digest=before_digest,
                after_digest=after_digest,
            )
            _move_into_place(staged[name], canonical)
            _verify_replacement(name, canonical, after_digest)
            completed.append(in_flight)
            in_flight = None
    except BaseException:
        for item in reversed(completed):
            _restore_target(canonical_dir / item.name, item.backup_path)
        if in_flight is not None:
            _restore_target(canonical_dir / in_flight.name, in_flight.backup_path)
        raise

    results = tuple(
        PromotionTargetResult(
            name=item.name,
            before_digest=item.before_digest,
            after_digest=item.after_digest,
            backup_path=(
                str(item.backup_path) if item.backup_path is not None else None
            ),
        )
        for item in completed
    )
    return results, tuple(completed)


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


def promote_run_state(
    assembler: RunProfileAssembler,
    seal_or_invocation_id: SealedRun | str,
) -> PromotionResult:
    """Promote one validated run's allowlisted memory/session state.

    All gates must hold or the promotion is refused with a specific error and
    NOTHING changes.  The project-role state lock is held for the whole
    promotion.  Returns a :class:`PromotionResult` with the memory-before and
    runtime-after inventories, per-target before/after digests, and backup
    locations; the promotion record row is written last, inside the same
    rollback scope as the filesystem swap.
    """
    sealed = _resolve_seal(assembler, seal_or_invocation_id)
    launch = _require_succeeded_launch(assembler, sealed.invocation_id)
    _require_passing_validation(
        assembler, launch, sealed.invocation_id, sealed.seal_id
    )
    _require_promotable_policy(sealed)

    with assembler.state_lock(sealed.project_id, sealed.role, sealed.invocation_id):
        canonical_dir = assembler._project_role_profile_dir(  # noqa: SLF001
            sealed.project_id, sealed.role
        )
        if canonical_dir is None:
            raise PromotionError(
                "No Hermes root is configured; project-role state cannot be "
                "promoted."
            )
        canonical_dir.mkdir(parents=True, exist_ok=True)

        run_profile_dir = sealed.run_dir / "profile"
        run_memories = run_profile_dir / "memories"
        run_state_db = run_profile_dir / _TARGET_STATE_DB

        # Inventories (raw evidence, captured before any mutation).
        memory_before = _walk_inventory(canonical_dir / _TARGET_MEMORIES)
        runtime_after = tuple(
            list(_walk_inventory(run_memories))
            + (
                [_file_entry(_TARGET_STATE_DB, run_state_db)]
                if _lexists(run_state_db)
                else []
            )
        )

        now = utc_now()
        promoted_at = isoformat_utc(now)
        staging_dir = canonical_dir / (_STAGING_PREFIX + uuid.uuid4().hex)
        completed: tuple[_CompletedTarget, ...] = ()
        try:
            staging_dir.mkdir(parents=True, exist_ok=False)
            staged = _stage_allowlisted(
                run_memories, run_state_db, staging_dir, runtime_after
            )
            targets, completed = _swap_targets(
                canonical_dir, staged, now
            )
            before_digest = {target.name: target.before_digest for target in targets}
            after_digest = {target.name: target.after_digest for target in targets}
            backup_paths = {
                target.name: target.backup_path for target in targets
            }
            assembler.store.record_promotion(
                record_id=uuid.uuid4().hex,
                seal_id=sealed.seal_id,
                invocation_id=sealed.invocation_id,
                project_id=sealed.project_id,
                role=sealed.role,
                promoted_at=promoted_at,
                before_digest=json.dumps(before_digest, sort_keys=True),
                after_digest=json.dumps(after_digest, sort_keys=True),
                backup_paths=json.dumps(backup_paths, sort_keys=True),
                status="succeeded",
            )
        except BaseException:
            # The swap rolls itself back on filesystem failures; a failure of
            # the record write (the last step) rolls the completed swap back
            # too, so a failed promotion never leaves promoted state behind.
            for item in reversed(completed):
                _restore_target(canonical_dir / item.name, item.backup_path)
            raise
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        return PromotionResult(
            seal_id=sealed.seal_id,
            invocation_id=sealed.invocation_id,
            project_id=sealed.project_id,
            role=sealed.role,
            promoted=True,
            promoted_at=promoted_at,
            memory_before_inventory=memory_before,
            runtime_after_inventory=runtime_after,
            targets=targets,
        )


__all__ = [
    "LaunchNotSucceededError",
    "MemoryPolicyNotPromotableError",
    "PROMOTION_FORMAT",
    "PROMOTION_FORMAT_VERSION",
    "PromotionError",
    "PromotionResult",
    "PromotionStagingError",
    "PromotionSwapError",
    "PromotionTargetResult",
    "StateInventoryEntry",
    "ValidationNotPassedError",
    "promote_run_state",
]
