"""Deterministic executor for lifecycle and failure-injection tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleInvocation,
)


OutputFactory = Callable[[RoleInvocation, int], Any]


class DeterministicFakeExecutor:
    """Write explicit test outputs without simulating scientific judgment."""

    def __init__(
        self,
        output_factory: OutputFactory | None = None,
        *,
        fail_roles: frozenset[str] = frozenset(),
    ) -> None:
        self.output_factory = output_factory or self._default_output
        self.fail_roles = fail_roles
        self.invocations: list[RoleInvocation] = []
        self.cancelled: set[str] = set()
        self.results: dict[str, RoleExecutionResult] = {}

    @staticmethod
    def _default_output(invocation: RoleInvocation, offset: int) -> dict[str, Any]:
        return {
            "development_fixture": True,
            "run_id": invocation.run_id,
            "stage_id": invocation.stage_id,
            "role": invocation.role,
            "output_offset": offset,
        }

    async def execute(
        self,
        invocation: RoleInvocation,
        observer: ExecutionObserver,
    ) -> RoleExecutionResult:
        existing = self.results.get(invocation.execution_id)
        if existing is not None:
            return existing
        self.invocations.append(invocation)
        await observer.launch_intent(invocation)
        external_id = f"fake:{invocation.execution_id}"
        await observer.launch_acknowledged(invocation, external_id)
        await observer.heartbeat(invocation, "Preparing deterministic test outputs")
        if invocation.role in self.fail_roles:
            result = RoleExecutionResult(
                RoleExecutionStatus.FAILED,
                external_id,
                1,
                f"Configured failure for {invocation.role}.",
            )
            self.results[invocation.execution_id] = result
            return result
        for offset, output_path in enumerate(invocation.expected_output_paths, start=1):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    self.output_factory(invocation, offset),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        result = RoleExecutionResult(
            RoleExecutionStatus.SUCCEEDED,
            external_id,
            0,
            "Deterministic test execution completed.",
        )
        self.results[invocation.execution_id] = result
        return result

    async def cancel(self, external_execution_id: str) -> None:
        self.cancelled.add(external_execution_id)

    async def reconcile(self, external_execution_id: str) -> RoleExecutionResult | None:
        execution_id = external_execution_id.removeprefix("fake:")
        return self.results.get(execution_id)


__all__ = ["DeterministicFakeExecutor", "OutputFactory"]
