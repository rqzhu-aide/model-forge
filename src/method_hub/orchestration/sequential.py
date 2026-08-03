"""Simple contract-stage orchestrator used by the first implementation."""

from __future__ import annotations

import hashlib

from ..contracts import ResolvedPhasePlan
from ..domain import PhaseContractIdentity, SemanticVersion, Sha256Digest, StableId
from .protocol import (
    NO_SCIENTIFIC_ROLE_RETRY,
    OrchestrationBinding,
    OrchestrationError,
    OrchestrationResult,
    OrchestrationServices,
    OrchestrationStatus,
    StageOutcome,
    StageStatus,
    SubmissionOutcome,
    SubmissionStatus,
    require_stage_outcome_matches,
)


_WORKFLOW_DEFINITION = b"method-hub.contract-stage-sequential.v1"
CONTRACT_SEQUENTIAL_WORKFLOW_SHA256 = Sha256Digest(
    hashlib.sha256(_WORKFLOW_DEFINITION).hexdigest()
)


class ContractSequentialOrchestrator:
    """Advance contract stages in order without scientific retries.

    A whole ``ResolvedStage`` is delegated to the harness service. Therefore a
    parallel stage retains one frozen group-start basis and is never decomposed
    into independently scheduled role calls by this adapter.
    """

    adapter_id = StableId("orchestrator.contract_sequential")
    adapter_version = SemanticVersion("1.0.0")
    protocol_version = SemanticVersion("1.0.0")
    workflow_id = StableId("workflow.contract_stage_sequence")
    workflow_version = SemanticVersion("1.0.0")

    def __init__(
        self,
        workflow_sha256: Sha256Digest | str = CONTRACT_SEQUENTIAL_WORKFLOW_SHA256,
    ) -> None:
        self._workflow_sha256 = (
            workflow_sha256
            if type(workflow_sha256) is Sha256Digest
            else Sha256Digest(workflow_sha256)
        )

    @property
    def workflow_sha256(self) -> Sha256Digest:
        return self._workflow_sha256

    def binding_for(
        self, phase_contract: PhaseContractIdentity
    ) -> OrchestrationBinding:
        """Construct the exact supported binding for one phase contract."""

        return OrchestrationBinding(
            protocol_version=self.protocol_version,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            workflow_id=self.workflow_id,
            workflow_version=self.workflow_version,
            workflow_sha256=self.workflow_sha256,
            phase_contract=phase_contract,
            retry_policy=NO_SCIENTIFIC_ROLE_RETRY,
        )

    def supports(self, binding: OrchestrationBinding) -> bool:
        return (
            binding.protocol_version == self.protocol_version
            and binding.adapter_id == self.adapter_id
            and binding.adapter_version == self.adapter_version
            and binding.workflow_id == self.workflow_id
            and binding.workflow_version == self.workflow_version
            and binding.workflow_sha256 == self.workflow_sha256
            and binding.retry_policy == NO_SCIENTIFIC_ROLE_RETRY
        )

    async def execute(
        self,
        *,
        run_id: StableId,
        manifest_sha256: Sha256Digest,
        binding: OrchestrationBinding,
        plan: ResolvedPhasePlan,
        services: OrchestrationServices,
    ) -> OrchestrationResult:
        run_id = run_id if type(run_id) is StableId else StableId(run_id)
        manifest_sha256 = (
            manifest_sha256
            if type(manifest_sha256) is Sha256Digest
            else Sha256Digest(manifest_sha256)
        )
        self._require_plan_binding(binding, plan)
        self._require_ordered_stages(plan)

        outcomes: list[StageOutcome] = []
        for stage in plan.stages:
            if await services.cancellation_requested(
                run_id=run_id, manifest_sha256=manifest_sha256
            ):
                return self._result(
                    run_id,
                    manifest_sha256,
                    binding,
                    OrchestrationStatus.CANCELLED,
                    outcomes,
                )

            outcome = await services.execute_or_reconcile_stage(
                run_id=run_id,
                manifest_sha256=manifest_sha256,
                stage=stage,
            )
            if type(outcome) is not StageOutcome:
                raise OrchestrationError(
                    "orchestration.invalid_service_outcome",
                    "Stage service must return a StageOutcome.",
                )
            require_stage_outcome_matches(stage, outcome)
            outcomes.append(outcome)

            if outcome.status is StageStatus.FAILED:
                return self._result(
                    run_id,
                    manifest_sha256,
                    binding,
                    OrchestrationStatus.FAILED,
                    outcomes,
                )
            if outcome.status is StageStatus.CANCELLED:
                return self._result(
                    run_id,
                    manifest_sha256,
                    binding,
                    OrchestrationStatus.CANCELLED,
                    outcomes,
                )

        if await services.cancellation_requested(
            run_id=run_id, manifest_sha256=manifest_sha256
        ):
            return self._result(
                run_id,
                manifest_sha256,
                binding,
                OrchestrationStatus.CANCELLED,
                outcomes,
            )

        submission = await services.submit_or_reconcile(
            run_id=run_id,
            manifest_sha256=manifest_sha256,
            stage_outcomes=tuple(outcomes),
        )
        if type(submission) is not SubmissionOutcome:
            raise OrchestrationError(
                "orchestration.invalid_service_outcome",
                "Submission service must return a SubmissionOutcome.",
            )
        if submission.status is SubmissionStatus.CANCELLED:
            return self._result(
                run_id,
                manifest_sha256,
                binding,
                OrchestrationStatus.CANCELLED,
                outcomes,
            )
        return OrchestrationResult(
            run_id=run_id,
            manifest_sha256=manifest_sha256,
            binding=binding,
            status=OrchestrationStatus.SUBMITTED,
            stage_outcomes=tuple(outcomes),
            submission=submission.reference,
        )

    def _require_plan_binding(
        self, binding: OrchestrationBinding, plan: ResolvedPhasePlan
    ) -> None:
        if not self.supports(binding):
            raise OrchestrationError(
                "orchestration.binding_not_supported",
                "The sequential adapter does not support the exact frozen binding.",
            )
        if binding.phase_contract != plan.identity:
            raise OrchestrationError(
                "orchestration.phase_contract_mismatch",
                "The resolved plan identity differs from the frozen orchestration binding.",
            )

    @staticmethod
    def _require_ordered_stages(plan: ResolvedPhasePlan) -> None:
        sequences = tuple(stage.sequence for stage in plan.stages)
        if not sequences or sequences != tuple(sorted(set(sequences))):
            raise OrchestrationError(
                "orchestration.invalid_stage_plan",
                "The resolved stage plan must contain unique increasing sequences.",
            )

    @staticmethod
    def _result(
        run_id: StableId,
        manifest_sha256: Sha256Digest,
        binding: OrchestrationBinding,
        status: OrchestrationStatus,
        outcomes: list[StageOutcome],
    ) -> OrchestrationResult:
        return OrchestrationResult(
            run_id=run_id,
            manifest_sha256=manifest_sha256,
            binding=binding,
            status=status,
            stage_outcomes=tuple(outcomes),
        )


__all__ = [
    "CONTRACT_SEQUENTIAL_WORKFLOW_SHA256",
    "ContractSequentialOrchestrator",
]
