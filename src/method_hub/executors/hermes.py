"""Hermes Kanban adapter for one already-frozen role invocation.

This adapter deliberately does not orchestrate research. It submits one exact
role task, waits for its terminal Hermes state, and reports that state to the
harness. A rootless OCI wrapper remains required before this adapter is treated
as release-safe execution.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)


@dataclass(frozen=True, slots=True)
class HermesSettings:
    executable: str = "hermes"
    board_slug: str = "method-hub"
    hermes_home: Path | None = None
    poll_interval_seconds: float = 5.0
    command_timeout_seconds: int = 30
    output_limit_bytes: int = 1_048_576


class HermesExecutionError(RuntimeError):
    pass


class HermesKanbanExecutor:
    def __init__(self, settings: HermesSettings) -> None:
        self.settings = settings

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        if self.settings.hermes_home is not None:
            environment["HERMES_HOME"] = str(self.settings.hermes_home.resolve())
        return environment

    def _run(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.settings.command_timeout_seconds,
            env=self._environment(),
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        size = len(completed.stdout.encode("utf-8")) + len(
            completed.stderr.encode("utf-8")
        )
        if size > self.settings.output_limit_bytes:
            raise HermesExecutionError("Hermes command output exceeded the configured limit.")
        return completed

    @staticmethod
    def _payload(value: Any) -> dict[str, Any]:
        if type(value) is dict and type(value.get("task")) is dict:
            return value["task"]
        if type(value) is dict and type(value.get("data")) is dict:
            return value["data"]
        if type(value) is dict:
            return value
        raise HermesExecutionError("Hermes returned a non-object task response.")

    def _create(self, invocation: RoleInvocation) -> str:
        body = (
            f"Read the complete task brief at {invocation.task_brief}. "
            f"Work only on run {invocation.run_id}, stage {invocation.stage_id}, "
            f"and role {invocation.role}. Write only the declared output files "
            "inside this task workspace. Do not start another phase or role."
        )
        title = f"{invocation.phase} {invocation.stage_id} {invocation.role} [{invocation.run_id}]"
        command = [
            self.settings.executable,
            "kanban",
            "--board",
            self.settings.board_slug,
            "create",
            title,
            "--assignee",
            invocation.profile,
            "--workspace",
            f"dir:{invocation.workspace.resolve()}",
            "--body",
            body,
            "--idempotency-key",
            f"method-hub:{invocation.invocation_id}",
            "--max-runtime",
            f"{invocation.timeout_seconds}s",
            "--max-retries",
            "0",
        ]
        for skill in invocation.preloaded_skills:
            command.extend(("--skill", skill))
        command.append("--json")
        completed = self._run(command)
        if completed.returncode != 0:
            raise HermesExecutionError(
                (completed.stderr or completed.stdout).strip()
                or "Hermes task creation failed."
            )
        try:
            payload = self._payload(json.loads(completed.stdout or "{}"))
        except json.JSONDecodeError as error:
            raise HermesExecutionError("Hermes task creation returned invalid JSON.") from error
        task_id = payload.get("id") or payload.get("task_id")
        if type(task_id) is not str or not task_id:
            raise HermesExecutionError("Hermes task creation did not return a task ID.")
        return task_id

    def _show(self, task_id: str) -> dict[str, Any]:
        completed = self._run(
            [
                self.settings.executable,
                "kanban",
                "--board",
                self.settings.board_slug,
                "show",
                task_id,
                "--json",
            ]
        )
        if completed.returncode != 0:
            raise HermesExecutionError(
                (completed.stderr or completed.stdout).strip()
                or f"Could not inspect Hermes task {task_id}."
            )
        try:
            return self._payload(json.loads(completed.stdout or "{}"))
        except json.JSONDecodeError as error:
            raise HermesExecutionError(f"Hermes task {task_id} returned invalid JSON.") from error

    async def execute(
        self,
        invocation: RoleInvocation,
        observer: ExecutionObserver,
    ) -> RoleExecutionResult:
        await observer.launch_intent(invocation)
        try:
            task_id = await asyncio.to_thread(self._create, invocation)
            await observer.launch_acknowledged(invocation, task_id)
            deadline = time.monotonic() + invocation.timeout_seconds
            while True:
                payload = await asyncio.to_thread(self._show, task_id)
                status = str(payload.get("status", "")).lower()
                await observer.heartbeat(invocation, f"Hermes task status: {status or 'unknown'}")
                if status == "done":
                    return RoleExecutionResult(
                        RoleExecutionStatus.SUCCEEDED,
                        task_id,
                        0,
                        "Hermes role task completed.",
                    )
                if status in {"blocked", "failed", "cancelled", "archived"}:
                    mapped = (
                        RoleExecutionStatus.CANCELLED
                        if status in {"cancelled", "archived"}
                        else RoleExecutionStatus.FAILED
                    )
                    return RoleExecutionResult(
                        mapped,
                        task_id,
                        1,
                        f"Hermes role task ended with status {status}.",
                        str(payload.get("reason") or payload.get("message") or ""),
                    )
                if time.monotonic() >= deadline:
                    await self.cancel(task_id)
                    return RoleExecutionResult(
                        RoleExecutionStatus.FAILED,
                        task_id,
                        None,
                        "Hermes role task exceeded its frozen time limit.",
                    )
                await asyncio.sleep(self.settings.poll_interval_seconds)
        except (OSError, subprocess.SubprocessError, HermesExecutionError) as error:
            return RoleExecutionResult(
                RoleExecutionStatus.FAILED,
                None,
                None,
                "Hermes role execution failed.",
                str(error),
            )

    async def cancel(self, external_execution_id: str) -> None:
        def archive() -> None:
            self._run(
                [
                    self.settings.executable,
                    "kanban",
                    "--board",
                    self.settings.board_slug,
                    "archive",
                    external_execution_id,
                ]
            )

        await asyncio.to_thread(archive)

    async def reconcile(self, external_execution_id: str) -> RoleExecutionResult | None:
        try:
            payload = await asyncio.to_thread(self._show, external_execution_id)
        except (OSError, subprocess.SubprocessError, HermesExecutionError):
            return None
        status = str(payload.get("status", "")).lower()
        if status == "done":
            return RoleExecutionResult(
                RoleExecutionStatus.SUCCEEDED,
                external_execution_id,
                0,
                "Existing Hermes task completed.",
            )
        if status in {"blocked", "failed", "cancelled", "archived"}:
            mapped = (
                RoleExecutionStatus.CANCELLED
                if status in {"cancelled", "archived"}
                else RoleExecutionStatus.FAILED
            )
            return RoleExecutionResult(
                mapped,
                external_execution_id,
                1,
                f"Existing Hermes task ended with status {status}.",
            )
        return None


__all__ = ["HermesExecutionError", "HermesKanbanExecutor", "HermesSettings"]
