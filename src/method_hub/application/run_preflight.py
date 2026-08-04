"""Run preflight service (Block 3, one concern; WP-D2b).

A READ-ONLY verification layer over an already-sealed run packet
(:class:`~method_hub.application.run_profile_assembler.SealedRun`).
Preflight reports; it never repairs, and it changes no state — the only
registry it reads is the project-role state lock (and even that read is
non-mutating).  It is the "run preflight before launch" checklist of the
trusted-local brief (ADR-012 items 7-8):

1. ``hermes_executable`` — the executable recorded in the manifest still
   exists at that path and answers ``--version`` with the recorded
   version.  A changed version is a failure that shows both versions:
   ADR-012 item 8 requires a changed Hermes installation to be surfaced
   to the user, never silently accepted.
2. ``role_assets`` — every asset digest recorded in the manifest
   (SOUL, base configuration, library guidance, ``skills/``) still
   matches the bytes in the run profile.
3. ``selected_state`` — the memory snapshot identity recorded in the
   manifest matches the run-profile ``memories/`` digest; when the
   manifest records a session snapshot sha256, the run-profile
   ``state.db`` digest still matches.
4. ``paths_permissions`` — the run directory and its ``profile/``,
   ``workspace/``, ``inputs/``, ``outputs/``, ``logs/``, ``manifest/``
   subdirectories exist and are readable/writable as appropriate
   (workspace and outputs writable; manifest read-only is fine).
5. ``free_space`` — the filesystem holding the run directory has at
   least a configurable minimum of free bytes (default 512 MiB;
   injectable for tests).
6. ``lock_ownership`` — the project-role state lock, if held, is held
   by this invocation.  A lock held by another invocation — including an
   expired lock another invocation reacquired — fails.  No lock at all
   is a WARNING-level result, not a failure: the normal launch flow
   reacquires the lock at launch time.
7. ``task_brief`` — the declared task brief path (``user_choices`` key
   ``task_brief``, when present) exists and is a non-empty regular file,
   not a symlink.
8. ``output_contract`` — every declared expected output path
   (``relative_path`` or ``path`` on an ``expected_outputs`` entry) is
   relative, stays inside the run ``outputs/`` directory after
   normalization (``..`` escapes and absolute paths are rejected), and
   does not yet exist (a pre-existing expected output suggests a
   contaminated run directory).

Any failed check fails the run; warnings do not.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..configuration.skill_installer import SkillInstallationError, directory_sha256
from .run_profile_assembler import (
    RUN_DIR_LAYOUT,
    HermesProbe,
    RunProfileAssembler,
    RunSealError,
    SealedRun,
    _default_hermes_probe,
)

#: Default minimum free bytes on the run directory's filesystem (512 MiB).
DEFAULT_MIN_FREE_BYTES = 512 * 1024 * 1024

PASS = "pass"
FAIL = "fail"
WARNING = "warning"

#: Keys on an ``expected_outputs`` entry that declare its output path.
_OUTPUT_PATH_KEYS = ("relative_path", "path")


class PreflightError(RuntimeError):
    """The preflight could not be completed (read error, unknown seal)."""


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    """One named preflight verdict with a short detail string."""

    name: str
    status: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.status == PASS


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Overall preflight outcome: any failed check fails the run."""

    invocation_id: str
    seal_id: str
    checks: tuple[PreflightCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.status != FAIL for check in self.checks)

    @property
    def failed(self) -> int:
        return sum(check.status == FAIL for check in self.checks)

    @property
    def warnings(self) -> int:
        return sum(check.status == WARNING for check in self.checks)

    def check(self, name: str) -> PreflightCheck | None:
        """Return the named check, or None when absent."""
        for check in self.checks:
            if check.name == name:
                return check
        return None

    def to_dict(self) -> dict[str, Any]:
        """Compact API/manifest representation of the report."""
        return {
            "invocation_id": self.invocation_id,
            "seal_id": self.seal_id,
            "passed": self.passed,
            "failed_checks": [
                check.name for check in self.checks if check.status == FAIL
            ],
            "warnings": [
                check.name for check in self.checks if check.status == WARNING
            ],
            "checks": [
                {"name": check.name, "status": check.status, "detail": check.detail}
                for check in self.checks
            ],
        }


def _pass(name: str, detail: str) -> PreflightCheck:
    return PreflightCheck(name, PASS, detail)


def _fail(name: str, detail: str) -> PreflightCheck:
    return PreflightCheck(name, FAIL, detail)


def _warn(name: str, detail: str) -> PreflightCheck:
    return PreflightCheck(name, WARNING, detail)


# --------------------------------------------------------------------------- #
# Individual checks (each independent, named, read-only)                       #
# --------------------------------------------------------------------------- #


def _check_hermes_executable(
    sealed: SealedRun, probe: Callable[[str], HermesProbe]
) -> PreflightCheck:
    """The recorded executable still exists and still answers its version."""
    recorded = sealed.manifest.get("hermes") or {}
    recorded_exe = recorded.get("executable")
    recorded_version = recorded.get("version")
    if not recorded_exe:
        return _fail(
            "hermes_executable",
            "no Hermes executable was recorded when this run was sealed",
        )
    path = Path(recorded_exe)
    if not path.exists() or path.is_dir():
        return _fail(
            "hermes_executable", f"recorded executable no longer exists: {path}"
        )
    probed = probe(recorded_exe)
    if probed.version is None:
        return _fail(
            "hermes_executable",
            f"executable present at {path} but did not answer the --version probe",
        )
    if probed.version == recorded_version:
        return _pass(
            "hermes_executable", f"hermes {recorded_version} at {path}"
        )
    return _fail(
        "hermes_executable",
        f"hermes version changed: recorded {recorded_version!r}, "
        f"now {probed.version!r} at {path}",
    )


def _check_role_assets(sealed: SealedRun) -> PreflightCheck:
    """Every recorded asset digest still matches the run profile bytes."""
    profile_dir = sealed.run_dir / "profile"
    role_definition = sealed.manifest.get("role_definition") or {}
    digests = role_definition.get("asset_digests") or {}
    if not digests:
        return _fail("role_assets", "no asset digests recorded in the manifest")
    problems: list[str] = []
    for relative, recorded in sorted(digests.items()):
        target = profile_dir / relative
        try:
            if target.is_dir() and not target.is_symlink():
                actual = directory_sha256(target)
            elif target.is_file() and not target.is_symlink():
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
            else:
                problems.append(f"{relative}: missing from the run profile")
                continue
        except (OSError, SkillInstallationError):
            problems.append(f"{relative}: unreadable or contains linked entries")
            continue
        if actual != recorded:
            problems.append(
                f"{relative}: recorded {recorded[:12]}..., found {actual[:12]}..."
            )
    if problems:
        first = problems[0]
        remainder = f" ({len(problems) - 1} more)" if len(problems) > 1 else ""
        return _fail("role_assets", first + remainder)
    return _pass("role_assets", f"{len(digests)} assets verified against the manifest")


def _check_selected_state(sealed: SealedRun) -> PreflightCheck:
    """Memory snapshot identity and session snapshot digest still match."""
    profile_dir = sealed.run_dir / "profile"
    problems: list[str] = []

    snapshot = sealed.manifest.get("memory_snapshot") or {}
    recorded_digest = snapshot.get("digest")
    identity = snapshot.get("identity", "unknown")
    if not recorded_digest:
        problems.append("memory snapshot digest not recorded in the manifest")
    else:
        memories = profile_dir / "memories"
        try:
            actual = directory_sha256(memories)
        except (OSError, SkillInstallationError):
            problems.append("memories/ is unreadable or contains linked entries")
        else:
            if actual != recorded_digest:
                problems.append(
                    f"memories digest mismatch: recorded {recorded_digest[:12]}..., "
                    f"found {actual[:12]}..."
                )

    session = sealed.manifest.get("session_snapshot") or {}
    recorded_sha = session.get("sha256")
    if recorded_sha is None:
        if session.get("procedure") == "sqlite_backup_v1":
            problems.append("session snapshot recorded without a sha256 digest")
    else:
        state_db = profile_dir / "state.db"
        if not state_db.is_file() or state_db.is_symlink():
            problems.append("session snapshot recorded but state.db is missing")
        else:
            actual = hashlib.sha256(state_db.read_bytes()).hexdigest()
            if actual != recorded_sha:
                problems.append(
                    f"state.db digest mismatch: recorded {recorded_sha[:12]}..., "
                    f"found {actual[:12]}..."
                )

    if problems:
        return _fail("selected_state", "; ".join(problems))
    detail = f"memories digest matches (identity={identity!r})"
    if recorded_sha is not None:
        detail += "; state.db digest matches"
    return _pass("selected_state", detail)


def _check_paths_permissions(sealed: SealedRun) -> PreflightCheck:
    """Run directory and subdirectories exist with the right permissions."""
    run_dir = sealed.run_dir
    problems: list[str] = []
    for path in (run_dir, *(run_dir / name for name in RUN_DIR_LAYOUT)):
        label = path.name if path != run_dir else "run directory"
        if not path.is_dir() or path.is_symlink():
            problems.append(f"{label}: missing or not a real directory")
        elif not os.access(path, os.R_OK):
            problems.append(f"{label}: not readable")
    for name in ("workspace", "outputs"):
        path = run_dir / name
        if path.is_dir() and not os.access(path, os.W_OK):
            problems.append(f"{name}: not writable")
    if problems:
        return _fail("paths_permissions", "; ".join(problems))
    return _pass(
        "paths_permissions",
        "run directory and all subdirectories present; "
        "workspace/outputs writable",
    )


def _check_free_space(
    sealed: SealedRun, min_free_bytes: int
) -> PreflightCheck:
    """The run directory's filesystem has at least *min_free_bytes* free."""
    try:
        usage = shutil.disk_usage(sealed.run_dir)
    except OSError as error:
        return _fail("free_space", f"cannot stat the run directory: {error}")
    if usage.free < min_free_bytes:
        return _fail(
            "free_space",
            f"only {usage.free} bytes free; minimum required is {min_free_bytes}",
        )
    return _pass("free_space", f"{usage.free} bytes free")


def _check_lock_ownership(assembler: RunProfileAssembler, sealed: SealedRun) -> PreflightCheck:
    """The project-role state lock, if held, is held by this invocation."""
    lock = sealed.manifest.get("state_lock") or {}
    profile_name = lock.get("profile_name")
    if not profile_name:
        return _warn(
            "lock_ownership", "no state lock was recorded in the manifest"
        )
    holder = assembler.store.state_lock_holder(profile_name)
    if holder is None:
        return _warn(
            "lock_ownership",
            "no project-role state lock is held; the launch flow reacquires it",
        )
    if holder == sealed.invocation_id:
        token = lock.get("token", "?")
        return _pass(
            "lock_ownership",
            f"lock held by this invocation (token {token})",
        )
    return _fail(
        "lock_ownership",
        f"project-role state lock is held by another invocation: {holder}",
    )


def _check_task_brief(sealed: SealedRun) -> PreflightCheck:
    """The declared task brief exists and is a non-empty regular file."""
    choices = sealed.manifest.get("user_choices") or {}
    declared = choices.get("task_brief")
    if declared is None or declared == "":
        return _pass("task_brief", "no task brief declared")
    if not isinstance(declared, str):
        return _fail("task_brief", "declared task brief must be a path string")
    path = Path(declared)
    if not path.is_absolute():
        path = sealed.run_dir / path
    if path.is_symlink():
        return _fail("task_brief", f"task brief must not be a symlink: {path}")
    if not path.exists():
        return _fail("task_brief", f"task brief is missing: {path}")
    if not path.is_file():
        return _fail("task_brief", f"task brief is not a regular file: {path}")
    size = path.stat().st_size
    if size == 0:
        return _fail("task_brief", f"task brief is empty: {path}")
    return _pass("task_brief", f"task brief present ({size} bytes): {path}")


def _check_output_contract(sealed: SealedRun) -> PreflightCheck:
    """Declared expected outputs are safe, relative, and not yet present."""
    outputs_dir = sealed.run_dir / "outputs"
    entries = sealed.manifest.get("expected_outputs") or []
    problems: list[str] = []
    declared_count = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            problems.append(f"expected output #{index} is not an object")
            continue
        output_id = entry.get("output_id", f"#{index}")
        path_value = next(
            (entry[key] for key in _OUTPUT_PATH_KEYS if key in entry), None
        )
        if path_value is None:
            continue  # entry declares no concrete path
        declared_count += 1
        if not isinstance(path_value, str) or path_value == "":
            problems.append(f"{output_id}: declared path is empty or not a string")
            continue
        if path_value.startswith(("/", "\\")) or Path(path_value).is_absolute():
            problems.append(f"{output_id}: absolute path rejected: {path_value!r}")
            continue
        parts = Path(path_value).parts
        if ".." in parts:
            problems.append(f"{output_id}: '..' escape rejected: {path_value!r}")
            continue
        resolved = (outputs_dir / path_value).resolve()
        if not resolved.is_relative_to(outputs_dir.resolve()):
            problems.append(f"{output_id}: path escapes outputs/: {path_value!r}")
            continue
        if resolved.exists():
            problems.append(
                f"{output_id}: expected output already exists: {path_value!r}"
            )
    if problems:
        shown = "; ".join(problems[:3])
        remainder = f" ({len(problems) - 3} more)" if len(problems) > 3 else ""
        return _fail("output_contract", shown + remainder)
    if declared_count == 0:
        return _pass("output_contract", "no declared expected output paths")
    return _pass(
        "output_contract", f"{declared_count} declared output paths verified"
    )


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


def run_preflight(
    assembler: RunProfileAssembler,
    seal: SealedRun | str,
    *,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    hermes_probe: Callable[[str], HermesProbe] | None = None,
) -> PreflightReport:
    """Run every preflight check over one sealed run and return the report.

    *seal* is either a :class:`SealedRun` (already reconstructed) or an
    invocation id, which is looked up in the seal registry and
    reconstructed from disk with manifest-digest verification.  The
    function never repairs and never writes; it only reads the run
    directory and the lock registry.

    *hermes_probe* mirrors the assembler's probe hook and is injectable
    for tests; it defaults to the real ``--version`` probe.
    """
    if isinstance(seal, str):
        record = assembler.store.find_by_invocation_id(seal)
        if record is None:
            raise RunSealError(f"No sealed run for invocation {seal!r}.")
        sealed = assembler._reconstruct(record)  # verifies the manifest digest
    elif isinstance(seal, SealedRun):
        sealed = seal
    else:
        raise TypeError("seal must be a SealedRun or an invocation id string")

    probe = hermes_probe or _default_hermes_probe
    checks = (
        _check_hermes_executable(sealed, probe),
        _check_role_assets(sealed),
        _check_selected_state(sealed),
        _check_paths_permissions(sealed),
        _check_free_space(sealed, min_free_bytes),
        _check_lock_ownership(assembler, sealed),
        _check_task_brief(sealed),
        _check_output_contract(sealed),
    )
    return PreflightReport(
        invocation_id=sealed.invocation_id,
        seal_id=sealed.seal_id,
        checks=checks,
    )


__all__ = [
    "DEFAULT_MIN_FREE_BYTES",
    "FAIL",
    "PASS",
    "PreflightCheck",
    "PreflightError",
    "PreflightReport",
    "WARNING",
    "run_preflight",
]
