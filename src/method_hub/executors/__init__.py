"""Role-execution adapters. Executors never receive formal publication access."""

from .development import SchemaExampleFakeExecutor
from .fake import DeterministicFakeExecutor
from .hermes import (
    HermesKanbanExecutor,
    HermesSettings,
    profile_exists,
    profile_home,
    resolve_hermes_root,
)
from .local_hermes import LocalHermesExecutor, LocalHermesExecutorSettings
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
    "LocalHermesExecutor",
    "LocalHermesExecutorSettings",
    "RoleExecutionResult",
    "RoleExecutionStatus",
    "RoleExecutor",
    "RoleInvocation",
    "SchemaExampleFakeExecutor",
    "profile_exists",
    "profile_home",
    "resolve_hermes_root",
]
