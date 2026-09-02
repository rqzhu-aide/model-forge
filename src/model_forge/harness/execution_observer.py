"""Repository-backed callbacks around one external role launch."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from ..executors import ExecutionObserver, RoleExecutor, RoleInvocation
from ..storage.repository import HubRepository
from .execution_records import RoleExecutionInfrastructureError, deterministic_id

logger = logging.getLogger(__name__)


class RepositoryExecutionObserver(ExecutionObserver):
    def __init__(
        self,
        *,
        repository: HubRepository,
        executor: RoleExecutor,
        invocation_document: Mapping[str, Any],
        invocation_sha256: str,
    ) -> None:
        self.repository = repository
        self.executor = executor
        self.invocation_document = dict(invocation_document)
        self.invocation_sha256 = invocation_sha256
        self.heartbeat_offset = 0
        self.external_execution_id: str | None = None
        self.cancel_sent = False

    async def launch_intent(self, invocation: RoleInvocation) -> None:
        try:
            self.repository.get_or_create_execution(
                invocation.execution_id,
                invocation.invocation_id,
                invocation.run_id,
                self.invocation_sha256,
                self.invocation_document,
            )
        except RoleExecutionInfrastructureError:
            raise
        except Exception as error:
            raise RoleExecutionInfrastructureError(
                f"Harness bookkeeping for execution "
                f"{invocation.execution_id} failed: "
                f"{type(error).__name__}: {error}"
            ) from error

    async def launch_acknowledged(
        self, invocation: RoleInvocation, external_execution_id: str
    ) -> None:
        self.external_execution_id = external_execution_id
        try:
            self.repository.acknowledge_execution(
                invocation.execution_id,
                external_execution_id,
                {
                    "execution_id": invocation.execution_id,
                    "invocation_id": invocation.invocation_id,
                    "external_execution_id": external_execution_id,
                },
            )
        except RoleExecutionInfrastructureError:
            raise
        except Exception as error:
            raise RoleExecutionInfrastructureError(
                f"Harness bookkeeping for execution "
                f"{invocation.execution_id} failed: "
                f"{type(error).__name__}: {error}"
            ) from error

    async def heartbeat(self, invocation: RoleInvocation, activity: str) -> None:
        # Heartbeat rows are diagnostics, written at the highest frequency
        # of any bookkeeping in the system (once per executor poll over a
        # 30-75 minute run).  A transient repository failure here must NOT
        # propagate: in the local_hermes poll loop a raise lands in the
        # executor's tree-kill ``finally`` and terminates the healthy agent
        # process (audit 2026-09-02, F3).  Log and continue instead; the
        # strict close path is where infrastructure failures must surface.
        self.heartbeat_offset += 1
        heartbeat_id = deterministic_id(
            "heartbeat",
            invocation.execution_id,
            self.heartbeat_offset,
            activity,
        )
        try:
            self.repository.append_execution_heartbeat(
                invocation.execution_id,
                heartbeat_id,
                {
                    "execution_id": invocation.execution_id,
                    "activity": activity,
                    "offset": self.heartbeat_offset,
                },
            )
        except Exception as error:
            logger.warning(
                "Execution heartbeat bookkeeping failed for execution %s; "
                "continuing best-effort: %s: %s",
                invocation.execution_id,
                type(error).__name__,
                error,
            )
        cancellation_requested = False
        try:
            cancellation_requested = self.repository.cancellation_requested(
                invocation.run_id
            )
        except Exception as error:
            logger.warning(
                "Cancellation poll failed for execution %s; "
                "continuing best-effort: %s: %s",
                invocation.execution_id,
                type(error).__name__,
                error,
            )
        if (
            not self.cancel_sent
            and self.external_execution_id is not None
            and cancellation_requested
        ):
            self.cancel_sent = True
            await self.executor.cancel(self.external_execution_id)


__all__ = ["RepositoryExecutionObserver"]
