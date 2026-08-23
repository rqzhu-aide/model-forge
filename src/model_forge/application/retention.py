"""Explicit retention rules for run directories and E2 state backups (WP-E3).

:func:`apply_retention` prunes only expired, resolved, non-current
evidence, under explicit rules:

* a run directory may be pruned only when EVERY launch record of its
  invocation is terminal AND its outcome is resolved (a failing WP-E1
  validation, a completed promotion record, or a passing validation
  whose promotion is refused by memory policy) AND it is older than
  :data:`RETAIN_COMPLETED_DAYS`;
* E2 state backups (timestamped ``memories.bak-*`` / ``state.db.bak-*``
  siblings of the canonical project-role state) may be pruned only when
  older than :data:`RETAIN_BACKUP_DAYS`;
* never pruned: any run with a ``running`` launch record, a run with no
  launch record, an unsealed run directory, an unvalidated/unresolved
  run, the current canonical project-role state, the newest successful
  backup of each canonical target, or anything whose seal/manifest
  digest fails verification (tampering evidence is reported, never
  deleted).

``dry_run=True`` (the default) only reports what WOULD be pruned;
``dry_run=False`` actually deletes and records each deletion in the
report.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..domain.runs import isoformat_utc, utc_now
from ..profiles.project_profiles import MemoryPolicy
from .run_profile_assembler import (
    ManifestDigestError,
    RunProfileAssembler,
    RunSealError,
)

#: Run directories with all-terminal launches and a resolved outcome are
#: prunable once older than this many days.
RETAIN_COMPLETED_DAYS = 30

#: E2 state backups of canonical memories/state.db are prunable once older
#: than this many days (the newest backup of each target is always kept).
RETAIN_BACKUP_DAYS = 90

#: Canonical promotion targets whose timestamped backups are retained.
_BACKUP_TARGETS = ("memories", "state.db")

#: Matches WP-E2 backup names: ``<target>.bak-YYYYmmddTHHMMSSffffff-<8hex>``.
_BACKUP_NAME_RE = re.compile(r"^.+\.bak-(\d{8}T\d{12})-[0-9a-f]{8}$")
_BACKUP_STAMP_FORMAT = "%Y%m%dT%H%M%S%f"


@dataclass(slots=True)
class RetentionDecision:
    """One evaluated candidate: what would (or did) happen to it."""

    path: str
    rule: str
    age_days: float | None
    decision: str  # "prune" | "keep"
    reason: str
    deleted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "rule": self.rule,
            "age_days": self.age_days,
            "decision": self.decision,
            "reason": self.reason,
            "deleted": self.deleted,
        }


@dataclass(frozen=True, slots=True)
class RetentionReport:
    """The complete retention evaluation for one ``apply_retention`` call."""

    dry_run: bool
    now: str
    entries: tuple[RetentionDecision, ...] = field(default_factory=tuple)

    @property
    def prune_paths(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.entries if entry.decision == "prune")

    @property
    def kept_paths(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.entries if entry.decision == "keep")

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "now": self.now,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def _keep(
    path: Path, rule: str, reason: str, age_days: float | None
) -> RetentionDecision:
    return RetentionDecision(str(path), rule, age_days, "keep", reason)


def _prune(
    path: Path, rule: str, reason: str, age_days: float | None
) -> RetentionDecision:
    return RetentionDecision(str(path), rule, age_days, "prune", reason)


def _coerce_now(now: datetime | None) -> datetime:
    if now is None:
        return utc_now()
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_days(stamp: str | datetime | None, now: datetime) -> float | None:
    if isinstance(stamp, datetime):
        parsed = stamp
    elif isinstance(stamp, str):
        parsed = _parse_iso(stamp)
    else:
        return None
    if parsed is None:
        return None
    return (now - parsed).total_seconds() / 86_400.0


def _parse_backup_stamp(name: str) -> datetime | None:
    match = _BACKUP_NAME_RE.match(name)
    if match is None:
        return None
    try:
        return datetime.strptime(
            match.group(1), _BACKUP_STAMP_FORMAT
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _evaluate_run_dir(
    assembler: RunProfileAssembler,
    run_dir: Path,
    now: datetime,
    completed_days: float,
) -> RetentionDecision:
    invocation_id = run_dir.name
    record = assembler.store.find_by_invocation_id(invocation_id)
    if record is None:
        return _keep(
            run_dir,
            "run_unsealed",
            "No seal record for this run directory; unresolved evidence "
            "is never pruned.",
            None,
        )
    try:
        sealed = assembler._reconstruct(record)  # noqa: SLF001 — verifies digest
    except (RunSealError, ManifestDigestError) as error:
        return _keep(
            run_dir,
            "run_tampered_manifest",
            f"Seal/manifest digest verification failed ({error}); "
            "tampering evidence is reported, never pruned.",
            _age_days(record["sealed_at"], now),
        )

    launches = assembler.store.list_launch_records_by_invocation(invocation_id)
    if not launches:
        return _keep(
            run_dir,
            "run_no_launch",
            "No launch record; unresolved evidence is never pruned.",
            _age_days(sealed.sealed_at, now),
        )
    if any(launch["status"] == "running" for launch in launches):
        return _keep(
            run_dir,
            "run_running",
            "A launch record is still running; never pruned.",
            _age_days(sealed.sealed_at, now),
        )

    resolved, resolution = _run_resolution(assembler, sealed, launches)
    if not resolved:
        return _keep(
            run_dir,
            "run_unresolved",
            f"Outcome unresolved ({resolution}); unresolved evidence is "
            "never pruned.",
            _age_days(sealed.sealed_at, now),
        )
    age = _age_days(sealed.sealed_at, now)
    if age is None or age <= completed_days:
        reason = (
            f"Outcome resolved ({resolution}) but only "
            f"{age:.1f} days old; the completed-retention window is "
            f"{completed_days:.0f} days."
            if age is not None
            else f"Outcome resolved ({resolution}) but its age is "
            "unreadable; kept conservatively."
        )
        return _keep(run_dir, "run_young", reason, age)
    return _prune(
        run_dir,
        "run_expired",
        f"All launches terminal, outcome resolved ({resolution}), "
        f"{age:.1f} days old; beyond the {completed_days:.0f}-day window.",
        age,
    )


def _run_resolution(
    assembler: RunProfileAssembler,
    sealed: Any,
    launches: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    """Resolved = failing validation, completed promotion, or policy refusal.

    A passing validation with no promotion record stays unresolved
    (promotion may merely be pending), so it is never pruned.
    """
    for launch in launches:
        report = assembler.store.get_validation_report(launch["launch_id"])
        if report is not None and report["verdict"] == "fail":
            return True, "validation failed"
    if assembler.store.find_promotion_record_by_invocation(
        sealed.invocation_id
    ) is not None:
        return True, "promotion completed"
    policy = (sealed.manifest.get("memory_snapshot") or {}).get("policy")
    latest = launches[-1]
    latest_report = assembler.store.get_validation_report(latest["launch_id"])
    if (
        latest["status"] == "succeeded"
        and latest_report is not None
        and latest_report["verdict"] == "pass"
        and policy in {MemoryPolicy.EPHEMERAL.value, MemoryPolicy.READ_ONLY.value}
    ):
        return True, "promotion refused by memory policy"
    return False, "no failed validation, completed promotion, or refused promotion"


def _evaluate_backups(
    profile_dir: Path,
    now: datetime,
    backup_days: float,
) -> list[RetentionDecision]:
    entries: list[RetentionDecision] = []
    for target in _BACKUP_TARGETS:
        matches = sorted(profile_dir.glob(f"{target}.bak-*"))
        if not matches:
            continue
        stamped = sorted(
            ((_parse_backup_stamp(path.name), path) for path in matches),
            key=lambda item: (
                item[0] if item[0] is not None else datetime.min.replace(
                    tzinfo=timezone.utc
                ),
                item[1].name,
            ),
        )
        newest_path = stamped[-1][1]
        for stamp, path in stamped:
            if path == newest_path:
                entries.append(
                    _keep(
                        path,
                        "backup_newest",
                        "Newest successful backup of the canonical target "
                        "is never pruned.",
                        _age_days(stamp, now),
                    )
                )
                continue
            age = _age_days(stamp, now)
            if age is None or age <= backup_days:
                reason = (
                    f"Backup is {age:.1f} days old; the backup window "
                    f"is {backup_days:.0f} days."
                    if age is not None
                    else "Backup timestamp is unreadable; kept conservatively."
                )
                entries.append(_keep(path, "backup_young", reason, age))
            else:
                entries.append(
                    _prune(
                        path,
                        "backup_expired",
                        f"Backup is {age:.1f} days old; beyond the "
                        f"{backup_days:.0f}-day window.",
                        age,
                    )
                )
    return entries


def apply_retention(
    assembler: RunProfileAssembler,
    *,
    now: datetime | None = None,
    dry_run: bool = True,
    completed_days: float = RETAIN_COMPLETED_DAYS,
    backup_days: float = RETAIN_BACKUP_DAYS,
) -> RetentionReport:
    """Evaluate (and, when ``dry_run=False``, perform) retention pruning.

    Prunable run directories are removed with ``shutil.rmtree`` and
    prunable backups with ``rmtree``/``unlink``; every deletion is
    recorded in the returned report.
    """
    reference = _coerce_now(now)
    entries: list[RetentionDecision] = []

    if assembler.runs_root.is_dir():
        for run_dir in sorted(
            path
            for path in assembler.runs_root.iterdir()
            if path.is_dir() and not path.is_symlink()
        ):
            entries.append(
                _evaluate_run_dir(assembler, run_dir, reference, completed_days)
            )

    hermes_root = getattr(assembler, "_hermes_root", None)  # noqa: SLF001
    if hermes_root is not None:
        profiles_root = hermes_root / "profiles"
        if profiles_root.is_dir():
            for profile_dir in sorted(
                path
                for path in profiles_root.iterdir()
                if path.is_dir() and not path.is_symlink()
            ):
                entries.extend(_evaluate_backups(profile_dir, reference, backup_days))

    entries.sort(key=lambda entry: entry.path)

    if not dry_run:
        for entry in entries:
            if entry.decision != "prune":
                continue
            try:
                _remove_path(Path(entry.path))
            except OSError as error:
                entry.reason += f" Deletion failed: {error}."
            else:
                entry.deleted = True

    return RetentionReport(
        dry_run=dry_run,
        now=isoformat_utc(reference),
        entries=tuple(entries),
    )


__all__ = [
    "RETAIN_BACKUP_DAYS",
    "RETAIN_COMPLETED_DAYS",
    "RetentionDecision",
    "RetentionReport",
    "apply_retention",
]
