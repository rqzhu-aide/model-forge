"""Operational run types and lifecycle rules for the greenfield harness.

These types describe execution state. Scientific authority remains in formal
generations and authority events, not in a :class:`RunRecord`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping

from ..errors import DomainValidationError
from .identities import PhaseContractIdentity, StableId


class RunStatus(StrEnum):
    CREATED = "created"
    PREPARING = "preparing"
    PREPARED = "prepared"
    RUNNING = "running"
    CANCELLATION_REQUESTED = "cancellation_requested"
    CANCELLED = "cancelled"
    SUBMITTED = "submitted"
    VALIDATING = "validating"
    PROMOTING = "promoting"
    PUBLISHED = "published"
    FAILED = "failed"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.CANCELLED,
        RunStatus.PUBLISHED,
        RunStatus.FAILED,
        RunStatus.REJECTED,
        RunStatus.CONFLICTED,
    }
)

_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset(
        {RunStatus.PREPARING, RunStatus.CANCELLATION_REQUESTED, RunStatus.FAILED}
    ),
    RunStatus.PREPARING: frozenset(
        {RunStatus.PREPARED, RunStatus.CANCELLATION_REQUESTED, RunStatus.FAILED}
    ),
    RunStatus.PREPARED: frozenset(
        {RunStatus.RUNNING, RunStatus.CANCELLATION_REQUESTED, RunStatus.FAILED}
    ),
    RunStatus.RUNNING: frozenset(
        {RunStatus.SUBMITTED, RunStatus.CANCELLATION_REQUESTED, RunStatus.FAILED}
    ),
    RunStatus.CANCELLATION_REQUESTED: frozenset({RunStatus.CANCELLED}),
    RunStatus.SUBMITTED: frozenset(
        {RunStatus.VALIDATING, RunStatus.REJECTED, RunStatus.FAILED}
    ),
    RunStatus.VALIDATING: frozenset(
        {
            RunStatus.PROMOTING,
            RunStatus.REJECTED,
            RunStatus.CONFLICTED,
            RunStatus.FAILED,
        }
    ),
    RunStatus.PROMOTING: frozenset(
        {RunStatus.PUBLISHED, RunStatus.CONFLICTED, RunStatus.FAILED}
    ),
    RunStatus.CANCELLED: frozenset(),
    RunStatus.PUBLISHED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.REJECTED: frozenset(),
    RunStatus.CONFLICTED: frozenset(),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise DomainValidationError(
            "run.naive_datetime", "Run timestamps must include a timezone.", field="time"
        )
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def require_transition(current: RunStatus, target: RunStatus) -> None:
    """Reject an execution-state transition not defined by the harness contract."""

    if target not in _TRANSITIONS[current]:
        raise DomainValidationError(
            "run.invalid_transition",
            f"Run state cannot change from {current.value!r} to {target.value!r}.",
            field="status",
        )


def _frozen_json(value: Mapping[str, Any]) -> Mapping[str, Any]:
    def freeze(item: Any) -> Any:
        if type(item) is dict:
            return MappingProxyType({key: freeze(child) for key, child in item.items()})
        if type(item) is list:
            return tuple(freeze(child) for child in item)
        return copy.deepcopy(item)

    return freeze(dict(value))


def thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_json(child) for key, child in value.items()}
    if type(value) is tuple:
        return [thaw_json(child) for child in value]
    return copy.deepcopy(value)


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Resolved user intent before the normative RunCommand is sealed."""

    project_id: StableId
    phase_contract: PhaseContractIdentity
    mode: StableId
    choice_values: Mapping[str, Any]
    context_policy: str
    user_id: StableId
    idempotency_key: str
    selected_current_input_ids: tuple[str, ...] = ()
    wall_time_limit_seconds: int = 14_400
    network_policy: str = "approved_resources"

    def __post_init__(self) -> None:
        if type(self.project_id) is str:
            object.__setattr__(self, "project_id", StableId(self.project_id))
        if type(self.mode) is str:
            object.__setattr__(self, "mode", StableId(self.mode))
        if type(self.user_id) is str:
            object.__setattr__(self, "user_id", StableId(self.user_id))
        if not isinstance(self.phase_contract, PhaseContractIdentity):
            raise DomainValidationError(
                "run.invalid_contract_identity",
                "phase_contract must be a PhaseContractIdentity.",
                field="phase_contract",
            )
        if self.context_policy not in {
            "current_only",
            "current_plus_selected_history",
        }:
            raise DomainValidationError(
                "run.invalid_context_policy",
                "context_policy is not supported.",
                field="context_policy",
            )
        if type(self.idempotency_key) is not str or not 8 <= len(self.idempotency_key) <= 200:
            raise DomainValidationError(
                "run.invalid_idempotency_key",
                "idempotency_key must contain 8 to 200 characters.",
                field="idempotency_key",
            )
        if type(self.wall_time_limit_seconds) is not int or self.wall_time_limit_seconds < 1:
            raise DomainValidationError(
                "run.invalid_wall_time",
                "wall_time_limit_seconds must be a positive integer.",
                field="wall_time_limit_seconds",
            )
        if self.network_policy not in {"none", "approved_resources", "user_authorized"}:
            raise DomainValidationError(
                "run.invalid_network_policy",
                "network_policy is not supported.",
                field="network_policy",
            )
        selected = tuple(self.selected_current_input_ids)
        if any(type(item) is not str or not item.strip() for item in selected):
            raise DomainValidationError(
                "run.invalid_current_input_selection",
                "Selected current input IDs must be nonempty strings.",
                field="selected_current_input_ids",
            )
        if len(set(selected)) != len(selected):
            raise DomainValidationError(
                "run.duplicate_current_input_selection",
                "Selected current input IDs must be unique.",
                field="selected_current_input_ids",
            )
        object.__setattr__(self, "selected_current_input_ids", selected)
        object.__setattr__(self, "choice_values", _frozen_json(self.choice_values))

@dataclass(frozen=True, slots=True)
class RunEvent:
    run_id: StableId
    sequence: int
    status: RunStatus
    recorded_at: datetime
    message: str
    stage_id: str | None = None
    role: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.run_id) is str:
            object.__setattr__(self, "run_id", StableId(self.run_id))
        if type(self.sequence) is not int or self.sequence < 1:
            raise DomainValidationError(
                "run.invalid_event_sequence",
                "Run event sequence must be a positive integer.",
                field="sequence",
            )
        if not isinstance(self.status, RunStatus):
            object.__setattr__(self, "status", RunStatus(self.status))
        if type(self.message) is not str or not self.message.strip():
            raise DomainValidationError(
                "run.invalid_event_message",
                "Run event message must be nonempty.",
                field="message",
            )
        object.__setattr__(self, "details", _frozen_json(self.details))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "run_id": str(self.run_id),
            "sequence": self.sequence,
            "status": self.status.value,
            "recorded_at": isoformat_utc(self.recorded_at),
            "message": self.message,
            "details": thaw_json(self.details),
        }
        if self.stage_id is not None:
            result["stage_id"] = self.stage_id
        if self.role is not None:
            result["role"] = self.role
        return result


@dataclass(frozen=True, slots=True)
class RunRecord:
    """Researcher-facing operational projection of one controlled run."""

    run_id: StableId
    project_id: StableId
    phase: str
    mode: str
    status: RunStatus
    command_id: StableId
    manifest_sha256: str | None
    created_at: datetime
    updated_at: datetime
    cancellation_requested: bool = False
    current_stage_id: str | None = None
    current_role: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    publication_receipt_id: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "project_id": str(self.project_id),
            "phase": self.phase,
            "mode": self.mode,
            "status": self.status.value,
            "command_id": str(self.command_id),
            "manifest_sha256": self.manifest_sha256,
            "created_at": isoformat_utc(self.created_at),
            "updated_at": isoformat_utc(self.updated_at),
            "cancellation_requested": self.cancellation_requested,
            "current_stage_id": self.current_stage_id,
            "current_role": self.current_role,
            "error": (
                {"code": self.error_code, "message": self.error_message}
                if self.error_code and self.error_message
                else None
            ),
            "publication_receipt_id": self.publication_receipt_id,
        }


__all__ = [
    "RunEvent",
    "RunRecord",
    "RunRequest",
    "RunStatus",
    "TERMINAL_RUN_STATUSES",
    "isoformat_utc",
    "require_transition",
    "thaw_json",
    "utc_now",
]
