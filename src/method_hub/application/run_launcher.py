"""Supervised launch path for sealed runs (Block 5, WP-E0).

This service is the single launch path from a sealed invocation to a
running Hermes process.  It connects the WP-D1 assembler (seal registry,
project-role state lock, fencing tokens), the WP-D2b preflight, and the
Block 4 :class:`~method_hub.executors.local_hermes.LocalHermesExecutor`
into one supervised operation.  Output validation (WP-E1) and promotion
(WP-E2) are deliberately out of scope here.

Launch protocol
===============

1. **Seal resolution** — the caller passes a :class:`SealedRun` or an
   invocation id; an id is looked up in the seal registry and
   reconstructed from disk with manifest-digest verification.
2. **State lock reacquisition** — the project-role state lock for the
   seal's invocation is reacquired through the WP-D1
   ``assembler.state_lock`` machinery (a fresh fencing token is issued).
   The lock is held for the whole launch *and* execution and released
   owner-checked on exit.  A second launch of the same project-role
   fails with :class:`StateLockHeld` before any process is created.
3. **Preflight** — the WP-D2b preflight must pass.  A failing preflight
   aborts before any process is created; the launch record is closed as
   ``failed`` and :class:`LaunchPreflightError` is raised.  The
   preflight's ``lock_ownership`` warning is by design unreachable here:
   we hold the lock, so the check passes (its warning exists for
   preflight runs outside the launch flow).
4. **Task brief materialization** — the caller-supplied brief file is
   copied into ``run_dir/workspace/task.md``.  A missing, empty, or
   symlinked source fails the launch; the sha256 of the materialized
   brief is recorded on the launch record.
5. **Launch** — ``LocalHermesExecutor.execute`` runs the Hermes binary
   recorded in the manifest with a :class:`RoleInvocation` whose
   workspace is ``run_dir/workspace``, whose task brief is the
   materialized ``task.md``, whose expected outputs are the manifest's
   declared outputs resolved under ``run_dir/outputs``, and whose
   timeout comes from the explicit argument or ``user_choices``
   (``timeout_seconds``) or a default.
6. **Bounded logs** — after the process ends, the executor's captured
   (bounded and redacted) stdout/stderr are written to
   ``run_dir/logs/stdout.log`` and ``run_dir/logs/stderr.log``.  During
   execution the observer heartbeats are appended to
   ``run_dir/logs/heartbeat.log``, bounded to the last
   ``heartbeat_log_limit`` lines.
7. **Outcome recording** — the launch record is closed with the
   terminal status (``succeeded``/``failed``/``cancelled``), the
   external execution id, the exit code, and the close timestamp.

Credentials are never copied: the launch record, logs, and manifest
contain no secret material.  Provider keys are injected only through
the executor's ``secret_env`` mechanism at launch time (from the host
environment), and the executor redacts likely-secret substrings from
every captured stream before the launcher persists them.

The Hermes-home question
========================

The assembled run profile (``run_dir/profile/``) contains ``SOUL.md``,
the base configuration file, ``skills/``, ``memories/``, ``state.db``,
and the writable home directories (``sessions/``, ``logs/``,
``checkpoints/``, ``cache/``, ``home/``, ``workspace/``).  That is the
shape of a Hermes *home*, not of a named profile inside one: a Hermes
profile IS a self-contained home, and ``-p <name>`` merely selects
``$HERMES_HOME/profiles/<name>`` as the active home.  Launching this
run with ``-p`` would require the assembled profile to live under a
shared ``$HERMES_HOME/profiles/<name>`` — a shared root this launcher
must not touch.

This launcher therefore runs Hermes with ``HERMES_HOME`` pointing
directly at ``run_dir/profile`` and with NO ``-p`` argument, so the
sealed profile IS the entire Hermes home for the run.  The executor's
``use_profile_arg=False`` setting guarantees the profile argument is
never emitted (the diagnostic lane keeps its real ``-p`` behavior via
the default ``use_profile_arg=True``), and ``hermes_home`` makes the
executor set ``HERMES_HOME`` accordingly.  ``hermes -z`` accepts this
combination: ``-z``/``--oneshot``, ``--usage-file``, ``-m``,
``--provider`` and ``--skills`` are all top-level options of the Hermes
CLI (verified with ``hermes --help`` and the stub binary in
``tests/test_run_launcher.py``).

Known limitation: the state lock lease is not renewed during very long
executions (the WP-D1 lease default is 14,400 s); lease renewal is left
to a later package.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import uuid
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ..domain.runs import isoformat_utc, utc_now
from ..executors.local_hermes import (
    LocalHermesExecutor,
    LocalHermesExecutorSettings,
)
from ..executors.protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)
from .run_preflight import DEFAULT_MIN_FREE_BYTES, PreflightReport, run_preflight
from .run_profile_assembler import (
    HermesProbe,
    RunProfileAssembler,
    RunSealError,
    SealedRun,
)

#: Default execution timeout when neither the argument nor ``user_choices``
#: declares one (matches the :class:`RoleInvocation` default).
DEFAULT_RUN_TIMEOUT_SECONDS = 14_400

#: Default bound on the heartbeat log (lines kept).
DEFAULT_HEARTBEAT_LOG_LIMIT = 200

#: Default executor heartbeat polling interval.
_DEFAULT_POLL_INTERVAL_SECONDS = 10.0

#: Manifest keys that may declare an execution timeout in ``user_choices``.
_TIMEOUT_CHOICE_KEYS = ("timeout_seconds",)

#: Manifest keys that may declare an expected output path.
_OUTPUT_PATH_KEYS = ("relative_path", "path")


class LaunchError(RuntimeError):
    """A sealed run could not be launched."""


class LaunchPreflightError(LaunchError):
    """Preflight failed; the launch aborted before any process was created."""

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        super().__init__(
            f"Preflight failed for invocation {report.invocation_id}: "
            f"{report.failed} failed check(s): "
            f"{', '.join(report.to_dict()['failed_checks']) or 'none'}."
        )


class TaskBriefError(LaunchError):
    """The caller-supplied task brief could not be materialized."""


@dataclass(frozen=True, slots=True)
class LaunchResult:
    """The recorded outcome of one supervised launch attempt."""

    launch_id: str
    seal_id: str
    invocation_id: str
    status: RoleExecutionStatus
    external_execution_id: str | None
    exit_code: int | None
    task_brief_sha256: str | None
    launched_at: str
    closed_at: str
    run_dir: Path


class HeartbeatLogObserver:
    """ExecutionObserver that appends bounded heartbeats to a log file.

    Keeps at most *limit* lines (oldest dropped) and rewrites the log on
    every event so the file on disk always reflects the bound.  Every
    callback is forwarded to an optional *delegate* so callers can
    observe the launch themselves.
    """

    def __init__(
        self,
        log_path: Path,
        *,
        limit: int = DEFAULT_HEARTBEAT_LOG_LIMIT,
        delegate: ExecutionObserver | None = None,
    ) -> None:
        self._log_path = log_path
        self._limit = limit
        self._delegate = delegate
        self._lines: deque[str] = deque(maxlen=limit)

    def _append(self, line: str) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        self._lines.append(f"[{stamp}] {line}")
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")

    async def launch_intent(self, invocation: RoleInvocation) -> None:
        self._append(f"launch_intent invocation={invocation.invocation_id}")
        if self._delegate is not None:
            await self._delegate.launch_intent(invocation)

    async def launch_acknowledged(
        self, invocation: RoleInvocation, external_execution_id: str
    ) -> None:
        self._append(
            f"launch_acknowledged external_execution_id={external_execution_id}"
        )
        if self._delegate is not None:
            await self._delegate.launch_acknowledged(
                invocation, external_execution_id
            )

    async def heartbeat(self, invocation: RoleInvocation, activity: str) -> None:
        self._append(activity)
        if self._delegate is not None:
            await self._delegate.heartbeat(invocation, activity)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
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


def _resolve_expected_outputs(sealed: SealedRun) -> tuple[Path, ...]:
    """Resolve the manifest's declared outputs under ``run_dir/outputs``.

    Entries without a concrete path key are skipped (mirroring the
    preflight's output contract check); the preflight has already
    rejected absolute paths, ``..`` escapes, and pre-existing outputs.
    """
    outputs_dir = sealed.run_dir / "outputs"
    resolved_root = outputs_dir.resolve()
    paths: list[Path] = []
    for entry in sealed.manifest.get("expected_outputs") or []:
        if not isinstance(entry, Mapping):
            continue
        value = next(
            (entry[key] for key in _OUTPUT_PATH_KEYS if key in entry), None
        )
        if not isinstance(value, str) or not value:
            continue
        candidate = (outputs_dir / value).resolve()
        if candidate.is_relative_to(resolved_root):
            paths.append(candidate)
    return tuple(paths)


def _resolve_timeout(
    user_choices: Mapping[str, Any], timeout_seconds: int | None
) -> int:
    if timeout_seconds is not None:
        return timeout_seconds
    for key in _TIMEOUT_CHOICE_KEYS:
        raw = user_choices.get(key)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
            return int(raw)
    return DEFAULT_RUN_TIMEOUT_SECONDS


def _materialize_task_brief(source: Path, target: Path) -> str:
    """Copy *source* into *target* and return the sha256 of the copy.

    Fails closed on a missing, empty, or symlinked source and on a
    symlinked target.
    """
    if source.is_symlink() or not source.is_file():
        raise TaskBriefError(
            f"Task brief must be a regular file, not a symlink: {source}"
        )
    if source.stat().st_size == 0:
        raise TaskBriefError(f"Task brief is empty: {source}")
    if target.is_symlink():
        raise TaskBriefError(f"Refusing to overwrite a symlink: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    if target.is_symlink() or not target.is_file():
        raise TaskBriefError(f"Task brief copy failed at {target}")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _build_invocation(
    sealed: SealedRun,
    *,
    timeout_seconds: int,
    mode: str,
    metadata: Mapping[str, Any],
) -> RoleInvocation:
    """Build the role invocation for one sealed run.

    ``profile`` stays empty and the executor runs with
    ``use_profile_arg=False``: the assembled run profile IS the Hermes
    home (see module docstring).
    """
    return RoleInvocation(
        execution_id=sealed.invocation_id,
        invocation_id=sealed.invocation_id,
        run_id=sealed.invocation_id,
        project_id=sealed.project_id,
        phase=sealed.manifest.get("phase") or "run",
        mode=mode,
        stage_id="run",
        role=sealed.role,
        profile="",
        workspace=sealed.run_dir / "workspace",
        task_brief=sealed.run_dir / "workspace" / "task.md",
        expected_output_paths=_resolve_expected_outputs(sealed),
        timeout_seconds=timeout_seconds,
        metadata=dict(metadata),
    )


def _build_executor(
    recorded_executable: str | None,
    run_dir: Path,
    base_settings: LocalHermesExecutorSettings | None,
    secret_env: Mapping[str, str] | None,
) -> LocalHermesExecutor:
    """Build the executor for one sealed run.

    The Hermes binary recorded in the manifest (and verified by the
    preflight) is used when present; the run profile is the Hermes home;
    the profile argument is disabled; ``secret_env`` (host provider
    keys) is merged into the executor's runtime environment and never
    persisted.
    """
    base = base_settings or LocalHermesExecutorSettings(
        poll_interval_seconds=_DEFAULT_POLL_INTERVAL_SECONDS
    )
    merged_secret_env = {**base.secret_env, **(secret_env or {})}
    settings = replace(
        base,
        hermes_binary=recorded_executable or base.hermes_binary,
        hermes_home=run_dir / "profile",
        use_profile_arg=False,
        secret_env=merged_secret_env,
    )
    return LocalHermesExecutor(settings)


def _write_captured_logs(run_dir: Path, result: RoleExecutionResult) -> None:
    """Persist the executor's bounded, redacted streams after the run."""
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "stdout.log").write_text(result.captured_stdout, encoding="utf-8")
    (logs_dir / "stderr.log").write_text(result.captured_stderr, encoding="utf-8")


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


def launch_sealed_run(
    assembler: RunProfileAssembler,
    seal_or_invocation_id: SealedRun | str,
    task_brief: Path,
    observer: ExecutionObserver | None = None,
    *,
    executor_settings: LocalHermesExecutorSettings | None = None,
    secret_env: Mapping[str, str] | None = None,
    timeout_seconds: int | None = None,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    hermes_probe: Callable[[str], HermesProbe] | None = None,
    heartbeat_log_limit: int = DEFAULT_HEARTBEAT_LOG_LIMIT,
    cancel_requested: Callable[[str], bool] | None = None,
) -> LaunchResult:
    """Launch one sealed run under the project-role state lock.

    *seal_or_invocation_id* is a :class:`SealedRun` or an invocation id
    resolved through the seal registry.  *task_brief* is the caller-
    supplied brief file, copied into ``run_dir/workspace/task.md``.
    *observer* receives every executor callback; when omitted (or in
    addition, when provided) heartbeats are appended to
    ``run_dir/logs/heartbeat.log`` bounded to *heartbeat_log_limit*
    lines.  *executor_settings* customizes the executor (e.g. fast
    polling in tests); the Hermes binary, Hermes home, and profile
    argument behavior are always forced to the sealed-run values.
    *secret_env* injects provider keys into the Hermes process
    environment at launch time — never persisted.  *cancel_requested*
    (if given) is consulted at close time: when it reports an explicit
    user cancel for the invocation and the process died by signal, the
    launch record closes as ``cancelled`` instead of ``failed``.  The
    flag is never set by this launcher — only by the explicit cancel
    command path (WP-F1b).

    Raises :class:`StateLockHeld` when another invocation holds the
    project-role state lock, :class:`LaunchPreflightError` when the
    preflight fails (no process is created), and :class:`TaskBriefError`
    when the brief cannot be materialized.  Every aborted launch closes
    its launch record as ``failed``.
    """
    sealed = _resolve_seal(assembler, seal_or_invocation_id)
    run_dir = sealed.run_dir
    launch_id = uuid.uuid4().hex
    launched_at = isoformat_utc(utc_now())
    records = assembler.store

    user_choices = sealed.manifest.get("user_choices") or {}
    if not isinstance(user_choices, Mapping):
        user_choices = {}
    raw_mode = user_choices.get("mode")
    mode: str = raw_mode if isinstance(raw_mode, str) and raw_mode else "headless"
    metadata: dict[str, Any] = {}
    for key in ("model", "provider"):
        if user_choices.get(key):
            metadata[key] = user_choices[key]
    effective_timeout = _resolve_timeout(user_choices, timeout_seconds)
    recorded_executable = (sealed.manifest.get("hermes") or {}).get("executable")
    if recorded_executable is not None and not isinstance(recorded_executable, str):
        recorded_executable = None

    heartbeat_observer = HeartbeatLogObserver(
        run_dir / "logs" / "heartbeat.log",
        limit=heartbeat_log_limit,
        delegate=observer,
    )

    closed = False

    def _close(status: str, result: RoleExecutionResult | None = None) -> str:
        """Close the launch record once, returning the recorded status."""
        nonlocal closed
        if closed:
            return status
        closed = True
        if (
            cancel_requested is not None
            and result is not None
            and result.status is RoleExecutionStatus.FAILED
            and cancel_requested(sealed.invocation_id)
        ):
            # The process was terminated by an EXPLICIT user cancel
            # (WP-F1b): the executor reports a signal death as FAILED,
            # and only the cancel path can know the death was a user
            # command.  Classification happens here, at close time, so
            # the launch record keeps a single writer.  This is never
            # automatic: the flag is set solely by cancel_supervised_run.
            status = "cancelled"
        records.close_launch_record(
            launch_id,
            status=status,
            external_execution_id=(
                result.external_execution_id if result is not None else None
            ),
            exit_code=result.exit_code if result is not None else None,
            closed_at=isoformat_utc(utc_now()),
        )
        return status

    with assembler.state_lock(sealed.project_id, sealed.role, sealed.invocation_id):
        records.create_launch_record(
            launch_id=launch_id,
            seal_id=sealed.seal_id,
            invocation_id=sealed.invocation_id,
            launched_at=launched_at,
        )
        try:
            report = run_preflight(
                assembler,
                sealed,
                min_free_bytes=min_free_bytes,
                hermes_probe=hermes_probe,
            )
            if not report.passed:
                raise LaunchPreflightError(report)

            brief_sha256 = _materialize_task_brief(
                task_brief, run_dir / "workspace" / "task.md"
            )
            records.record_launch_brief(launch_id, brief_sha256)

            invocation = _build_invocation(
                sealed,
                timeout_seconds=effective_timeout,
                mode=mode,
                metadata=metadata,
            )
            executor = _build_executor(
                recorded_executable, run_dir, executor_settings, secret_env
            )
            result = asyncio.run(executor.execute(invocation, heartbeat_observer))
            _write_captured_logs(run_dir, result)
            effective_status = _close(result.status.value, result)
            return LaunchResult(
                launch_id=launch_id,
                seal_id=sealed.seal_id,
                invocation_id=sealed.invocation_id,
                status=RoleExecutionStatus(effective_status),
                external_execution_id=result.external_execution_id,
                exit_code=result.exit_code,
                task_brief_sha256=brief_sha256,
                launched_at=launched_at,
                closed_at=isoformat_utc(utc_now()),
                run_dir=run_dir,
            )
        except Exception:
            # Any abort (preflight, brief, executor failure, log write)
            # closes the launch record as failed and re-raises.
            try:
                _close("failed")
            except Exception:  # pragma: no cover — never mask the original
                pass
            raise


__all__ = [
    "DEFAULT_HEARTBEAT_LOG_LIMIT",
    "DEFAULT_RUN_TIMEOUT_SECONDS",
    "HeartbeatLogObserver",
    "LaunchError",
    "LaunchPreflightError",
    "LaunchResult",
    "TaskBriefError",
    "launch_sealed_run",
]
