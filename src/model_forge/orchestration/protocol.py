"""Engine-neutral contracts for phase orchestration.

Orchestration advances an already sealed role plan. It does not validate
scientific content, mutate formal records, or publish a run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from ..contracts import ResolvedPhasePlan, ResolvedStage
from ..domain import (
    PhaseContractIdentity,
    SemanticVersion,
    Sha256Digest,
    StableId,
)
from ..errors import ModelForgeError


NO_SCIENTIFIC_ROLE_RETRY = "no_scientific_role_retry"


class OrchestrationError(ModelForgeError, ValueError):
    """An orchestration binding, plan, or service outcome is inconsistent."""


class OrchestratorRegistryError(OrchestrationError):
    """The requested exact orchestrator cannot be resolved safely."""


class StageStatus(str, Enum):
    """Terminal state of one contract stage."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SubmissionStatus(str, Enum):
    """Result of the harness-owned immutable submission gate."""

    SUBMITTED = "submitted"
    CANCELLED = "cancelled"


class OrchestrationStatus(str, Enum):
    """Terminal result of orchestration, before validation or publication."""

    SUBMITTED = "submitted"
    FAILED = "failed"
    CANCELLED = "cancelled"


def _stable_id(value: StableId | str, field: str) -> StableId:
    if type(value) is StableId:
        return value
    if type(value) is str:
        return StableId(value)
    raise OrchestrationError(
        "orchestration.invalid_type",
        f"{field} must be a StableId or string.",
    )


def _semantic_version(
    value: SemanticVersion | str, field: str
) -> SemanticVersion:
    if type(value) is SemanticVersion:
        return value
    if type(value) is str:
        return SemanticVersion(value)
    raise OrchestrationError(
        "orchestration.invalid_type",
        f"{field} must be a SemanticVersion or string.",
    )


def _sha256(value: Sha256Digest | str, field: str) -> Sha256Digest:
    if type(value) is Sha256Digest:
        return value
    if type(value) is str:
        return Sha256Digest(value)
    raise OrchestrationError(
        "orchestration.invalid_type",
        f"{field} must be a Sha256Digest or string.",
    )


@dataclass(frozen=True, slots=True)
class OrchestrationBinding:
    """Exact adapter and workflow definition frozen into a run manifest."""

    protocol_version: SemanticVersion
    adapter_id: StableId
    adapter_version: SemanticVersion
    workflow_id: StableId
    workflow_version: SemanticVersion
    workflow_sha256: Sha256Digest
    phase_contract: PhaseContractIdentity
    retry_policy: str = NO_SCIENTIFIC_ROLE_RETRY

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "protocol_version",
            _semantic_version(self.protocol_version, "protocol_version"),
        )
        object.__setattr__(self, "adapter_id", _stable_id(self.adapter_id, "adapter_id"))
        object.__setattr__(
            self,
            "adapter_version",
            _semantic_version(self.adapter_version, "adapter_version"),
        )
        object.__setattr__(
            self, "workflow_id", _stable_id(self.workflow_id, "workflow_id")
        )
        object.__setattr__(
            self,
            "workflow_version",
            _semantic_version(self.workflow_version, "workflow_version"),
        )
        object.__setattr__(
            self,
            "workflow_sha256",
            _sha256(self.workflow_sha256, "workflow_sha256"),
        )
        if type(self.phase_contract) is not PhaseContractIdentity:
            raise OrchestrationError(
                "orchestration.invalid_type",
                "phase_contract must be a PhaseContractIdentity.",
            )
        if self.retry_policy != NO_SCIENTIFIC_ROLE_RETRY:
            raise OrchestrationError(
                "orchestration.retry_policy_not_supported",
                "Only no_scientific_role_retry is permitted.",
            )


    @classmethod
    def from_dict(cls, value: Any) -> "OrchestrationBinding":
        if not isinstance(value, Mapping):
            raise OrchestrationError(
                "orchestration.invalid_binding",
                "Orchestration binding must be a JSON object.",
            )
        expected = {
            "protocol_version",
            "adapter_id",
            "adapter_version",
            "workflow_id",
            "workflow_version",
            "workflow_sha256",
            "phase_contract",
            "retry_policy",
        }
        if set(value) != expected:
            raise OrchestrationError(
                "orchestration.invalid_binding",
                "Orchestration binding fields do not match the frozen contract.",
            )
        return cls(
            protocol_version=str(value["protocol_version"]),
            adapter_id=str(value["adapter_id"]),
            adapter_version=str(value["adapter_version"]),
            workflow_id=str(value["workflow_id"]),
            workflow_version=str(value["workflow_version"]),
            workflow_sha256=str(value["workflow_sha256"]),
            phase_contract=PhaseContractIdentity.from_dict(value["phase_contract"]),
            retry_policy=str(value["retry_policy"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": str(self.protocol_version),
            "adapter_id": str(self.adapter_id),
            "adapter_version": str(self.adapter_version),
            "workflow_id": str(self.workflow_id),
            "workflow_version": str(self.workflow_version),
            "workflow_sha256": str(self.workflow_sha256),
            "phase_contract": self.phase_contract.to_dict(),
            "retry_policy": self.retry_policy,
        }

@dataclass(frozen=True, slots=True)
class StageOutcome:
    """Harness-sealed result for one complete serial or parallel stage."""

    sequence: int
    stage_id: StableId
    status: StageStatus
    invocation_closure_ids: tuple[StableId, ...] = ()
    failure_code: str | None = None
    reconciled: bool = False

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 1:
            raise OrchestrationError(
                "orchestration.invalid_stage_outcome",
                "Stage outcome sequence must be a positive integer.",
            )
        object.__setattr__(self, "stage_id", _stable_id(self.stage_id, "stage_id"))
        try:
            status = StageStatus(self.status)
        except (TypeError, ValueError) as error:
            raise OrchestrationError(
                "orchestration.invalid_stage_outcome",
                f"Unknown stage status {self.status!r}.",
            ) from error
        object.__setattr__(self, "status", status)
        closures = tuple(
            _stable_id(value, "invocation_closure_ids")
            for value in self.invocation_closure_ids
        )
        if len(set(closures)) != len(closures):
            raise OrchestrationError(
                "orchestration.invalid_stage_outcome",
                "Invocation closure IDs must be unique within a stage outcome.",
            )
        object.__setattr__(self, "invocation_closure_ids", closures)
        if type(self.reconciled) is not bool:
            raise OrchestrationError(
                "orchestration.invalid_stage_outcome",
                "reconciled must be a Boolean.",
            )
        if status is StageStatus.SUCCEEDED and not closures:
            raise OrchestrationError(
                "orchestration.invalid_stage_outcome",
                "A successful stage must cite at least one invocation closure.",
            )
        if status is StageStatus.FAILED:
            if type(self.failure_code) is not str or not self.failure_code.strip():
                raise OrchestrationError(
                    "orchestration.invalid_stage_outcome",
                    "A failed stage must include a non-empty failure code.",
                )
        elif self.failure_code is not None:
            raise OrchestrationError(
                "orchestration.invalid_stage_outcome",
                "Only a failed stage may include a failure code.",
            )


@dataclass(frozen=True, slots=True)
class SubmissionReference:
    """Immutable reference returned by the harness submission service."""

    submission_id: StableId
    submission_sha256: Sha256Digest

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "submission_id", _stable_id(self.submission_id, "submission_id")
        )
        object.__setattr__(
            self,
            "submission_sha256",
            _sha256(self.submission_sha256, "submission_sha256"),
        )


@dataclass(frozen=True, slots=True)
class SubmissionOutcome:
    """Outcome of the cancellation-fenced submission operation."""

    status: SubmissionStatus
    reference: SubmissionReference | None = None

    def __post_init__(self) -> None:
        try:
            status = SubmissionStatus(self.status)
        except (TypeError, ValueError) as error:
            raise OrchestrationError(
                "orchestration.invalid_submission_outcome",
                f"Unknown submission status {self.status!r}.",
            ) from error
        object.__setattr__(self, "status", status)
        if status is SubmissionStatus.SUBMITTED:
            if type(self.reference) is not SubmissionReference:
                raise OrchestrationError(
                    "orchestration.invalid_submission_outcome",
                    "A submitted outcome must contain a submission reference.",
                )
        elif self.reference is not None:
            raise OrchestrationError(
                "orchestration.invalid_submission_outcome",
                "A cancelled submission outcome cannot contain a reference.",
            )


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Result returned before any submission validation or publication."""

    run_id: StableId
    manifest_sha256: Sha256Digest
    binding: OrchestrationBinding
    status: OrchestrationStatus
    stage_outcomes: tuple[StageOutcome, ...]
    submission: SubmissionReference | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _stable_id(self.run_id, "run_id"))
        object.__setattr__(
            self,
            "manifest_sha256",
            _sha256(self.manifest_sha256, "manifest_sha256"),
        )
        if type(self.binding) is not OrchestrationBinding:
            raise OrchestrationError(
                "orchestration.invalid_type",
                "binding must be an OrchestrationBinding.",
            )
        try:
            status = OrchestrationStatus(self.status)
        except (TypeError, ValueError) as error:
            raise OrchestrationError(
                "orchestration.invalid_result",
                f"Unknown orchestration status {self.status!r}.",
            ) from error
        object.__setattr__(self, "status", status)
        outcomes = tuple(self.stage_outcomes)
        if any(type(outcome) is not StageOutcome for outcome in outcomes):
            raise OrchestrationError(
                "orchestration.invalid_result",
                "stage_outcomes must contain only StageOutcome values.",
            )
        object.__setattr__(self, "stage_outcomes", outcomes)
        if status is OrchestrationStatus.SUBMITTED:
            if type(self.submission) is not SubmissionReference:
                raise OrchestrationError(
                    "orchestration.invalid_result",
                    "A submitted result must contain a submission reference.",
                )
            if any(outcome.status is not StageStatus.SUCCEEDED for outcome in outcomes):
                raise OrchestrationError(
                    "orchestration.invalid_result",
                    "A submitted result may contain only successful stage outcomes.",
                )
        elif self.submission is not None:
            raise OrchestrationError(
                "orchestration.invalid_result",
                "A non-submitted result cannot contain a submission reference.",
            )
        if status is OrchestrationStatus.FAILED and (
            not outcomes or outcomes[-1].status is not StageStatus.FAILED
        ):
            raise OrchestrationError(
                "orchestration.invalid_result",
                "A failed result must end with a failed stage outcome.",
            )


class OrchestrationServices(Protocol):
    """Narrow harness operations available to an orchestrator."""

    async def cancellation_requested(
        self, *, run_id: StableId, manifest_sha256: Sha256Digest
    ) -> bool:
        """Return the durable cancellation-fence state."""

    async def execute_or_reconcile_stage(
        self,
        *,
        run_id: StableId,
        manifest_sha256: Sha256Digest,
        stage: ResolvedStage,
    ) -> StageOutcome:
        """Execute a whole stage once or return its durable prior outcome."""

    async def submit_or_reconcile(
        self,
        *,
        run_id: StableId,
        manifest_sha256: Sha256Digest,
        stage_outcomes: tuple[StageOutcome, ...],
    ) -> SubmissionOutcome:
        """Assemble or recover immutable submission under its durable gate."""


class PhaseOrchestrator(Protocol):
    """Replaceable coordinator for one sealed phase plan."""

    @property
    def adapter_id(self) -> StableId: ...

    @property
    def adapter_version(self) -> SemanticVersion: ...

    def supports(self, binding: OrchestrationBinding) -> bool: ...

    async def execute(
        self,
        *,
        run_id: StableId,
        manifest_sha256: Sha256Digest,
        binding: OrchestrationBinding,
        plan: ResolvedPhasePlan,
        services: OrchestrationServices,
    ) -> OrchestrationResult: ...


def require_stage_outcome_matches(
    stage: ResolvedStage, outcome: StageOutcome
) -> None:
    """Fail closed when a service returns an outcome for another stage."""

    if outcome.sequence != stage.sequence or str(outcome.stage_id) != stage.stage_id:
        raise OrchestrationError(
            "orchestration.stage_outcome_mismatch",
            f"Stage {stage.stage_id!r} sequence {stage.sequence} received an outcome "
            f"for {outcome.stage_id!s} sequence {outcome.sequence}.",
        )
    if outcome.status is StageStatus.SUCCEEDED:
        expected_closure_count = len(stage.role_steps)
        if len(outcome.invocation_closure_ids) != expected_closure_count:
            raise OrchestrationError(
                "orchestration.stage_outcome_mismatch",
                f"Successful stage {stage.stage_id!r} requires "
                f"{expected_closure_count} invocation closure(s), but received "
                f"{len(outcome.invocation_closure_ids)}.",
            )


__all__ = [
    "NO_SCIENTIFIC_ROLE_RETRY",
    "OrchestrationBinding",
    "OrchestrationError",
    "OrchestrationResult",
    "OrchestrationServices",
    "OrchestrationStatus",
    "OrchestratorRegistryError",
    "PhaseOrchestrator",
    "StageOutcome",
    "StageStatus",
    "SubmissionOutcome",
    "SubmissionReference",
    "SubmissionStatus",
    "require_stage_outcome_matches",
]
