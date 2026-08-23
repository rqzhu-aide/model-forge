"""Narrow role-executor boundary used by the run harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol


class RoleExecutionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RoleInvocation:
    execution_id: str
    invocation_id: str
    run_id: str
    project_id: str
    phase: str
    mode: str
    stage_id: str
    role: str
    profile: str
    workspace: Path
    task_brief: Path
    expected_output_paths: tuple[Path, ...]
    preloaded_skills: tuple[str, ...] = ()
    timeout_seconds: int = 14_400
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoleExecutionResult:
    status: RoleExecutionStatus
    external_execution_id: str | None
    exit_code: int | None
    summary: str
    diagnostic_text: str = ""
    #: Bounded, redacted captured stdout/stderr for durable launch logs
    #: (WP-E0).  Empty when the executor captured no stream output (e.g.
    #: a pre-launch failure).
    captured_stdout: str = ""
    captured_stderr: str = ""


class ExecutionObserver(Protocol):
    """Durable callbacks around an external launch and its heartbeat."""

    async def launch_intent(self, invocation: RoleInvocation) -> None: ...

    async def launch_acknowledged(
        self, invocation: RoleInvocation, external_execution_id: str
    ) -> None: ...

    async def heartbeat(
        self, invocation: RoleInvocation, activity: str
    ) -> None: ...


class RoleExecutor(Protocol):
    async def execute(
        self,
        invocation: RoleInvocation,
        observer: ExecutionObserver,
    ) -> RoleExecutionResult: ...

    async def cancel(self, external_execution_id: str) -> None: ...

    async def reconcile(
        self, external_execution_id: str
    ) -> RoleExecutionResult | None: ...


__all__ = [
    "ExecutionObserver",
    "RoleExecutionResult",
    "RoleExecutionStatus",
    "RoleExecutor",
    "RoleInvocation",
]
