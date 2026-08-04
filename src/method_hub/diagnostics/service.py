"""Diagnostic execution service: run Hermes one-shot invocations for verification.

Orchestrates the complete diagnostic lane:

1. Idempotency check (H0.2) — duplicate request returns existing invocation.
2. Create invocation → ``pending``.
3. Preflight → ``preflight`` → ``creating``.
4. Acquire profile mutex with fencing token (C5, H0.6).
5. Create per-invocation runtime profile (H0.3).
6. Record memory-state snapshot before (C3).
7. Build and execute one-shot (H0.4, H0.5).
8. Validate output independently of exit code (H0.5).
9. Promote or quarantine runtime changes (H0.3).
10. Record terminal state with token guard (H0.6).
11. Release lock owner-checked (H0.6).

This service never enters submission, validation, or publication.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..executors.oneshot import OneShotExecutor
from ..executors.protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)
from ..profiles.project_profiles import (
    MemoryPolicy,
    ProjectProfileManager,
    RoleProfileSpec,
)
from .contracts import (
    DiagnosticOutputContract,
    DiagnosticState,
    ProcessIdentity,
    ProfileManifest,
    StateTransitionError,
    UsageReport,
    validate_diagnostic_output,
    validate_profile_manifest,
)
from .runtime_profiles import (
    RuntimeProfileManager,
    RuntimeSnapshot,
    SnapshotError,
)
from .store import (
    DiagnosticStore,
    FencingError,
    FencingToken,
    ProfileLockHeld,
    utc_now_iso,
)


@dataclass(frozen=True, slots=True)
class DiagnosticRequest:
    """Request to run one diagnostic one-shot invocation."""

    project_id: str
    role: str
    profile_name: str
    workspace: Path
    task_brief: Path
    preloaded_skills: tuple[str, ...] = ()
    timeout_seconds: int = 3600
    model: str = ""
    provider: str = ""
    memory_policy: MemoryPolicy = MemoryPolicy.PERSISTENT
    idempotency_key: str = ""
    manifest: ProfileManifest | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DiagnosticResult:
    """Result of a diagnostic invocation."""

    invocation_id: str
    status: str
    exit_code: int | None
    summary: str
    external_execution_id: str | None
    memory_before: Mapping[str, Any] | None
    memory_after: Mapping[str, Any] | None


class _DiagnosticObserver:
    """ExecutionObserver that records process identity and heartbeats."""

    def __init__(
        self,
        store: DiagnosticStore,
        invocation_id: str,
        token: int,
    ) -> None:
        self._store = store
        self._invocation_id = invocation_id
        self._token = token
        self.external_execution_id: str | None = None
        self._heartbeat_seq = 0

    async def launch_intent(self, invocation: RoleInvocation) -> None:
        self._store.update_status(
            self._invocation_id,
            status=DiagnosticState.CREATING.value,
            expected_token=self._token,
        )

    async def launch_acknowledged(
        self, invocation: RoleInvocation, external_execution_id: str
    ) -> None:
        self.external_execution_id = external_execution_id
        self._store.update_status(
            self._invocation_id,
            status=DiagnosticState.LAUNCH_ACKNOWLEDGED.value,
            external_execution_id=external_execution_id,
            expected_token=self._token,
        )

    async def heartbeat(self, invocation: RoleInvocation, activity: str) -> None:
        self._heartbeat_seq += 1


class DiagnosticService:
    """Orchestrates diagnostic one-shot invocations.

    This is the non-publishing diagnostic lane — it proves the execution
    boundary without entering the scientific pipeline.  It uses the full
    state machine (H0.6), token-guarded mutations, and owner-checked
    cleanup.
    """

    def __init__(
        self,
        *,
        store: DiagnosticStore,
        executor: OneShotExecutor,
        profile_manager: ProjectProfileManager,
        runtime_profile_manager: RuntimeProfileManager | None = None,
    ) -> None:
        self._store = store
        self._executor = executor
        self._pm = profile_manager
        self._rpm = runtime_profile_manager or RuntimeProfileManager(
            profile_manager.hermes_root
        )

    async def run_diagnostic(
        self,
        request: DiagnosticRequest,
    ) -> DiagnosticResult:
        """Run one diagnostic invocation end-to-end."""
        invocation_id = f"diag-{uuid.uuid4().hex[:12]}"
        idem_key = request.idempotency_key or invocation_id

        # 1. Idempotency check (H0.2) — duplicate returns existing.
        existing = self._store.find_by_idempotency_key(idem_key)
        if existing is not None:
            return self._result_from_invocation(existing)

        # 2. Create invocation → pending.
        manifest_sha = (
            request.manifest.manifest_sha256
            if request.manifest is not None
            else None
        )
        actual_id = self._store.create_invocation(
            invocation_id=invocation_id,
            idempotency_key=idem_key,
            project_id=request.project_id,
            role=request.role,
            profile_name=request.profile_name,
            memory_policy=request.memory_policy.value,
            manifest_sha256=manifest_sha,
            payload={
                "model": request.model,
                "provider": request.provider,
                "preloaded_skills": list(request.preloaded_skills),
                "timeout_seconds": request.timeout_seconds,
            },
        )
        if actual_id != invocation_id:
            # Race — another coordinator created it first.
            existing = self._store.get_invocation(actual_id)
            if existing is not None:
                return self._result_from_invocation(existing)

        # 3. Preflight.
        try:
            self._store.update_status(
                invocation_id,
                status=DiagnosticState.PREFLIGHT.value,
            )
        except StateTransitionError:
            pass

        # 4. Acquire profile mutex (C5) + issue fencing token (H0.6).
        token = self._store.issue_fencing_token(invocation_id)
        try:
            self._store.acquire_profile_lock(
                profile_name=request.profile_name,
                invocation_id=invocation_id,
                token=token.token,
            )
        except ProfileLockHeld:
            self._store.update_status(
                invocation_id,
                status=DiagnosticState.FAILED.value,
                summary=f"Profile {request.profile_name} is locked by another invocation.",
                expected_token=token.token,
            )
            return DiagnosticResult(
                invocation_id=invocation_id,
                status=DiagnosticState.FAILED.value,
                exit_code=None,
                summary="Profile locked.",
                external_execution_id=None,
                memory_before=None,
                memory_after=None,
            )

        # 5. Record memory-state before (C3).
        memory_before = self._record_memory(request.profile_name)

        # 5b. Create per-invocation runtime snapshot (H0.3).
        canonical_dir = self._pm.profiles_root / request.profile_name
        snapshot: RuntimeSnapshot | None = None
        if canonical_dir.is_dir():
            snapshot = self._rpm.snapshot_canonical_profile(
                canonical_profile_dir=canonical_dir,
                invocation_id=invocation_id,
                memory_policy=request.memory_policy,
            )

        # 6. Transition through the full state machine and execute.
        try:
            self._store.update_status(
                invocation_id,
                status=DiagnosticState.CREATING.value,
                expected_token=token.token,
            )
            role_invocation = self._build_invocation(invocation_id, request, snapshot)
            observer = _DiagnosticObserver(
                self._store, invocation_id, token.token
            )
            # Walk through launch_acknowledged → running before execute.
            self._store.update_status(
                invocation_id,
                status=DiagnosticState.LAUNCH_ACKNOWLEDGED.value,
                external_execution_id=f"oneshot:{invocation_id}",
                expected_token=token.token,
            )
            self._store.update_status(
                invocation_id,
                status=DiagnosticState.RUNNING.value,
                expected_token=token.token,
            )
            result = await self._executor.execute(role_invocation, observer)

            # 7. Record memory-state after (C3).
            memory_after = self._record_memory(request.profile_name)
            self._store.record_memory_state(
                invocation_id, before=memory_before, after=memory_after
            )

            # 8. Close and evaluate result independently (H0.5).
            self._store.update_status(
                invocation_id,
                status=DiagnosticState.CLOSING.value,
                expected_token=token.token,
            )
            status, summary = self._evaluate_result(
                result, request, token.token
            )

            # 8b. Promote or quarantine runtime snapshot (H0.3).
            if snapshot is not None:
                if status == DiagnosticState.SUCCEEDED.value:
                    try:
                        self._rpm.promote_snapshot(snapshot)
                    except SnapshotError as se:
                        status = DiagnosticState.FAILED.value
                        summary = f"Promotion failed: {se}"
                else:
                    try:
                        self._rpm.quarantine_snapshot(
                            snapshot,
                            reason=status,
                            diagnostic_text=summary,
                        )
                    except SnapshotError:
                        pass  # Best-effort quarantine.
            self._store.update_status(
                invocation_id,
                status=status,
                external_execution_id=result.external_execution_id,
                exit_code=result.exit_code,
                summary=summary,
                diagnostic_text=result.diagnostic_text,
                expected_token=token.token,
            )

            return DiagnosticResult(
                invocation_id=invocation_id,
                status=status,
                exit_code=result.exit_code,
                summary=summary,
                external_execution_id=result.external_execution_id,
                memory_before=memory_before,
                memory_after=memory_after,
            )
        except Exception as error:
            # Quarantine snapshot on exception (H0.3).
            if snapshot is not None:
                try:
                    self._rpm.quarantine_snapshot(
                        snapshot,
                        reason="exception",
                        diagnostic_text=str(error),
                    )
                except SnapshotError:
                    pass
            self._store.update_status(
                invocation_id,
                status=DiagnosticState.FAILED.value,
                summary=f"Exception during execution: {type(error).__name__}",
                diagnostic_text=str(error),
                expected_token=token.token,
            )
            return DiagnosticResult(
                invocation_id=invocation_id,
                status=DiagnosticState.FAILED.value,
                exit_code=None,
                summary=str(error),
                external_execution_id=None,
                memory_before=memory_before,
                memory_after=None,
            )
        finally:
            # Owner-checked release (H0.6).
            self._store.release_profile_lock(
                request.profile_name,
                expected_invocation_id=invocation_id,
                expected_token=token.token,
            )

    def cancel_diagnostic(self, invocation_id: str) -> bool:
        """Cancel a running diagnostic invocation."""
        inv = self._store.get_invocation(invocation_id)
        if inv is None:
            return False
        status = inv["status"]
        if status in (
            DiagnosticState.SUCCEEDED.value,
            DiagnosticState.FAILED.value,
            DiagnosticState.CANCELLED.value,
            DiagnosticState.TIMED_OUT.value,
            DiagnosticState.UNRESOLVED.value,
        ):
            return False
        # Transition to cancel_requested (H0.6 state machine).
        try:
            self._store.update_status(
                invocation_id,
                status=DiagnosticState.CANCEL_REQUESTED.value,
            )
        except StateTransitionError:
            return False
        external_id = inv.get("external_execution_id")
        if external_id:
            try:
                asyncio.get_event_loop().create_task(
                    self._executor.cancel(external_id)
                )
            except RuntimeError:
                pass
        self._store.update_status(
            invocation_id,
            status=DiagnosticState.CANCELLED.value,
        )
        return True

    def get_result(self, invocation_id: str) -> dict[str, Any] | None:
        """Return the current state of a diagnostic invocation."""
        return self._store.get_invocation(invocation_id)

    def list_diagnostics(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List diagnostic invocations with optional filters."""
        return self._store.list_invocations(
            project_id=project_id, status=status, limit=limit
        )

    def reconcile_nonterminal(self) -> list[dict[str, Any]]:
        """Find all non-terminal invocations for restart reconciliation (H0.6).

        Returns them without auto-relaunching — the operator or automated
        system must decide what to do with each one.
        """
        return self._store.list_nonterminal_invocations()

    # ------------------------------------------------------------------ #
    # Internal                                                           #
    # ------------------------------------------------------------------ #

    def _build_invocation(
        self,
        invocation_id: str,
        request: DiagnosticRequest,
        snapshot: RuntimeSnapshot | None = None,
    ) -> RoleInvocation:
        metadata: dict[str, Any] = dict(request.metadata)
        if request.model:
            metadata["model"] = request.model
        if request.provider:
            metadata["provider"] = request.provider
        # Set runtime_profile_dir so the executor mounts the snapshot (H0.4).
        if snapshot is not None:
            metadata["runtime_profile_dir"] = str(snapshot.snapshot_dir)
        return RoleInvocation(
            execution_id=invocation_id,
            invocation_id=invocation_id,
            run_id=f"diagnostic-{invocation_id}",
            project_id=request.project_id,
            phase="diagnostic",
            mode="oneshot",
            stage_id="diagnostic",
            role=request.role,
            profile=request.profile_name,
            workspace=request.workspace,
            task_brief=request.task_brief,
            expected_output_paths=(),
            preloaded_skills=request.preloaded_skills,
            timeout_seconds=request.timeout_seconds,
            metadata=metadata,
        )

    def _record_memory(self, profile_name: str) -> dict[str, Any]:
        """Record memory-state digests for a profile (C3)."""
        hermes_root = self._pm.hermes_root
        profile_dir = hermes_root / "profiles" / profile_name
        return OneShotExecutor.record_memory_state(profile_dir)

    def _evaluate_result(
        self,
        result: RoleExecutionResult,
        request: DiagnosticRequest,
        token: int,
    ) -> tuple[str, str]:
        """Evaluate the executor result independently of exit code (H0.5).

        Exit code 0 is insufficient — the spike proved Hermes may report
        internal failure with exit code 0.  We must validate the declared
        output independently.
        """
        if result.status is RoleExecutionStatus.CANCELLED:
            return DiagnosticState.CANCELLED.value, result.summary
        if result.status is RoleExecutionStatus.FAILED:
            return DiagnosticState.FAILED.value, result.summary
        # SUCCEEDED exit code — validate output independently.
        output_contract = DiagnosticOutputContract()
        output_path = request.workspace / output_contract.output_filename
        if not output_path.exists():
            return (
                DiagnosticState.FAILED.value,
                f"Exit code 0 but declared output {output_contract.output_filename} "
                "was not produced.",
            )
        brief_sha = hashlib.sha256(
            request.task_brief.read_bytes()
        ).hexdigest()
        findings = validate_diagnostic_output(
            output_path.read_bytes(),
            expected_brief_sha256=brief_sha,
            expected_profile=request.profile_name,
        )
        if findings:
            return (
                DiagnosticState.FAILED.value,
                "Output validation failed: " + "; ".join(findings),
            )
        return DiagnosticState.SUCCEEDED.value, result.summary

    @staticmethod
    def _result_from_invocation(inv: dict[str, Any]) -> DiagnosticResult:
        """Build a DiagnosticResult from a stored invocation record."""
        memory_before = None
        if inv.get("memory_state_before"):
            try:
                memory_before = json.loads(inv["memory_state_before"])
            except json.JSONDecodeError:
                pass
        memory_after = None
        if inv.get("memory_state_after"):
            try:
                memory_after = json.loads(inv["memory_state_after"])
            except json.JSONDecodeError:
                pass
        return DiagnosticResult(
            invocation_id=inv["invocation_id"],
            status=inv["status"],
            exit_code=inv.get("exit_code"),
            summary=inv.get("summary", ""),
            external_execution_id=inv.get("external_execution_id"),
            memory_before=memory_before,
            memory_after=memory_after,
        )


__all__ = [
    "DiagnosticRequest",
    "DiagnosticResult",
    "DiagnosticService",
]
