"""Role-execution adapters. Executors never receive formal publication access."""

from .development import SchemaExampleFakeExecutor
from .fake import DeterministicFakeExecutor
from .hermes import HermesKanbanExecutor, HermesSettings
from .protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleExecutor,
    RoleInvocation,
)

__all__ = [
    "DeterministicFakeExecutor",
    "ExecutionObserver",
    "HermesKanbanExecutor",
    "HermesSettings",
    "RoleExecutionResult",
    "RoleExecutionStatus",
    "RoleExecutor",
    "RoleInvocation",
    "SchemaExampleFakeExecutor",
]
