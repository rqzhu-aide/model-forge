"""Repository-backed callbacks around one external role launch."""

from __future__ import annotations

from typing import Any, Mapping

from ..executors import ExecutionObserver, RoleExecutor, RoleInvocation
from ..storage.repository import HubRepository
from .execution_records import RoleExecutionInfrastructureError, deterministic_id


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
        except RoleExecutionInfrastructureError:
            raise
        except Exception as error:
            raise RoleExecutionInfrastructureError(
                f"Harness bookkeeping for execution "
                f"{invocation.execution_id} failed: "
                f"{type(error).__name__}: {error}"
            ) from error
        try:
            cancellation_requested = self.repository.cancellation_requested(
                invocation.run_id
            )
        except RoleExecutionInfrastructureError:
            raise
        except Exception as error:
            raise RoleExecutionInfrastructureError(
                f"Harness bookkeeping for execution "
                f"{invocation.execution_id} failed: "
                f"{type(error).__name__}: {error}"
            ) from error
        if (
            not self.cancel_sent
            and self.external_execution_id is not None
            and cancellation_requested
        ):
            self.cancel_sent = True
            await self.executor.cancel(self.external_execution_id)


__all__ = ["RepositoryExecutionObserver"]
