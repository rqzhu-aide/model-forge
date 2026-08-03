"""Diagnostic execution service: run Hermes one-shot invocations for verification.

This service orchestrates the complete diagnostic lane:

1. Create a diagnostic invocation record.
2. Acquire a profile mutex (C5).
3. Record memory-state digests (C3).
4. Issue a fencing token (S5.7).
5. Execute via OneShotExecutor.
6. Record terminal state and release locks.

It never enters submission, validation, or publication.
"""

from __future__ import annotations

import asyncio
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
    """ExecutionObserver that writes heartbeats to the diagnostic store."""

    def __init__(
        self,
        store: DiagnosticStore,
        invocation_id: str,
    ) -> None:
        self._store = store
        self._invocation_id = invocation_id
        self.external_execution_id: str | None = None
        self._heartbeat_seq = 0

    async def launch_intent(self, invocation: RoleInvocation) -> None:
        self._store.update_status(
            self._invocation_id,
            status="running",
        )

    async def launch_acknowledged(
        self, invocation: RoleInvocation, external_execution_id: str
    ) -> None:
        self.external_execution_id = external_execution_id
        self._store.update_status(
            self._invocation_id,
            status="running",
            external_execution_id=external_execution_id,
        )

    async def heartbeat(self, invocation: RoleInvocation, activity: str) -> None:
        # Heartbeats are recorded via the update_status call's timestamp.
        # In a production system, these would go to a heartbeats table.
        pass


class DiagnosticService:
    """Orchestrates diagnostic one-shot invocations.

    This is the non-publishing diagnostic lane — it proves the execution
    boundary without entering the scientific pipeline.
    """

    def __init__(
        self,
        *,
        store: DiagnosticStore,
        executor: OneShotExecutor,
        profile_manager: ProjectProfileManager,
    ) -> None:
        self._store = store
        self._executor = executor
        self._pm = profile_manager

    async def run_diagnostic(
        self,
        request: DiagnosticRequest,
    ) -> DiagnosticResult:
        """Run one diagnostic invocation end-to-end."""
        invocation_id = f"diag-{uuid.uuid4().hex[:12]}"

        # 1. Create the invocation record.
        self._store.create_invocation(
            invocation_id=invocation_id,
            project_id=request.project_id,
            role=request.role,
            profile_name=request.profile_name,
            memory_policy=request.memory_policy.value,
            payload={
                "model": request.model,
                "provider": request.provider,
                "preloaded_skills": list(request.preloaded_skills),
                "timeout_seconds": request.timeout_seconds,
            },
        )

        # 2. Acquire the profile mutex (C5).
        try:
            self._store.acquire_profile_lock(
                profile_name=request.profile_name,
                invocation_id=invocation_id,
            )
        except ProfileLockHeld:
            self._store.update_status(
                invocation_id,
                status="failed",
                summary=f"Profile {request.profile_name} is locked by another invocation.",
            )
            return DiagnosticResult(
                invocation_id=invocation_id,
                status="failed",
                exit_code=None,
                summary="Profile locked.",
                external_execution_id=None,
                memory_before=None,
                memory_after=None,
            )

        # 3. Record memory-state before (C3).
        memory_before = self._record_memory(request.profile_name)

        # 4. Issue fencing token (S5.7).
        token = self._store.issue_fencing_token(invocation_id)

        try:
            # 5. Build the RoleInvocation and execute.
            role_invocation = self._build_invocation(invocation_id, request)
            observer = _DiagnosticObserver(self._store, invocation_id)
            result = await self._executor.execute(role_invocation, observer)

            # 6. Record memory-state after (C3).
            memory_after = self._record_memory(request.profile_name)
            self._store.record_memory_state(
                invocation_id, before=memory_before, after=memory_after
            )

            # Map the executor result to a diagnostic status.
            status = self._map_status(result)
            self._store.update_status(
                invocation_id,
                status=status,
                external_execution_id=result.external_execution_id,
                exit_code=result.exit_code,
                summary=result.summary,
                diagnostic_text=result.diagnostic_text,
            )

            return DiagnosticResult(
                invocation_id=invocation_id,
                status=status,
                exit_code=result.exit_code,
                summary=result.summary,
                external_execution_id=result.external_execution_id,
                memory_before=memory_before,
                memory_after=memory_after,
            )
        except Exception as error:
            self._store.update_status(
                invocation_id,
                status="failed",
                summary=f"Exception during execution: {type(error).__name__}",
                diagnostic_text=str(error),
            )
            return DiagnosticResult(
                invocation_id=invocation_id,
                status="failed",
                exit_code=None,
                summary=str(error),
                external_execution_id=None,
                memory_before=memory_before,
                memory_after=None,
            )
        finally:
            self._store.release_profile_lock(request.profile_name)

    def cancel_diagnostic(self, invocation_id: str) -> bool:
        """Cancel a running diagnostic invocation."""
        inv = self._store.get_invocation(invocation_id)
        if inv is None:
            return False
        if inv["status"] not in ("running", "pending"):
            return False
        external_id = inv.get("external_execution_id")
        if external_id:
            asyncio.get_event_loop().create_task(
                self._executor.cancel(external_id)
            )
        self._store.update_status(invocation_id, status="cancelled")
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

    # ------------------------------------------------------------------ #
    # Internal                                                           #
    # ------------------------------------------------------------------ #

    def _build_invocation(
        self, invocation_id: str, request: DiagnosticRequest
    ) -> RoleInvocation:
        metadata: dict[str, Any] = dict(request.metadata)
        if request.model:
            metadata["model"] = request.model
        if request.provider:
            metadata["provider"] = request.provider
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
        from ..profiles.project_profiles import _sha256_file

        hermes_root = self._pm.hermes_root
        profile_dir = hermes_root / "profiles" / profile_name
        return OneShotExecutor.record_memory_state(profile_dir)

    @staticmethod
    def _map_status(result: RoleExecutionResult) -> str:
        if result.status is RoleExecutionStatus.SUCCEEDED:
            return "succeeded"
        if result.status is RoleExecutionStatus.CANCELLED:
            return "cancelled"
        return "failed"


__all__ = [
    "DiagnosticRequest",
    "DiagnosticResult",
    "DiagnosticService",
]
