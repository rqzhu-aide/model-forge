"""Role-execution adapters. Executors never receive formal publication access."""

from .bubblewrap import BubblewrapExecutor, BubblewrapSettings
from .development import SchemaExampleFakeExecutor
from .fake import DeterministicFakeExecutor
from .hermes import (
    HermesKanbanExecutor,
    HermesSettings,
    profile_exists,
    profile_home,
    resolve_hermes_root,
)
from .oneshot import OneShotExecutor, OneShotExecutorSettings
from .protocol import (
    ExecutionObserver,
    RoleExecutionResult,
    RoleExecutionStatus,
    RoleExecutor,
    RoleInvocation,
)

__all__ = [
    "BubblewrapExecutor",
    "BubblewrapSettings",
    "DeterministicFakeExecutor",
    "ExecutionObserver",
    "HermesKanbanExecutor",
    "HermesSettings",
    "OneShotExecutor",
    "OneShotExecutorSettings",
    "RoleExecutionResult",
    "RoleExecutionStatus",
    "RoleExecutor",
    "RoleInvocation",
    "SchemaExampleFakeExecutor",
    "profile_exists",
    "profile_home",
    "resolve_hermes_root",
]
