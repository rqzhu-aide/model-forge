from __future__ import annotations

import asyncio
from pathlib import Path

from method_hub.executors.fake import DeterministicFakeExecutor
from method_hub.executors.protocol import RoleExecutionStatus, RoleInvocation


class Observer:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def launch_intent(self, invocation: RoleInvocation) -> None:
        self.events.append("intent")

    async def launch_acknowledged(
        self, invocation: RoleInvocation, external_execution_id: str
    ) -> None:
        self.events.append("ack")

    async def heartbeat(self, invocation: RoleInvocation, activity: str) -> None:
        self.events.append("heartbeat")


def invocation(tmp_path: Path) -> RoleInvocation:
    return RoleInvocation(
        execution_id="execution.demo",
        invocation_id="invocation.demo",
        run_id="run.demo",
        project_id="project.demo",
        phase="P4",
        mode="p4.preliminary",
        stage_id="p4.analyst",
        role="data_analyst",
        profile="analyst",
        workspace=tmp_path,
        task_brief=tmp_path / "task.md",
        expected_output_paths=(tmp_path / "output.json",),
    )


def test_fake_executor_is_idempotent(tmp_path: Path) -> None:
    executor = DeterministicFakeExecutor()
    observer = Observer()
    role_invocation = invocation(tmp_path)
    first = asyncio.run(executor.execute(role_invocation, observer))
    second = asyncio.run(executor.execute(role_invocation, observer))
    assert first == second
    assert first.status == RoleExecutionStatus.SUCCEEDED
    assert len(executor.invocations) == 1
    assert observer.events == ["intent", "ack", "heartbeat"]
    assert (tmp_path / "output.json").is_file()
