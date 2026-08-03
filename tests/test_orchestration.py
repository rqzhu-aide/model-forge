from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from method_hub.contracts import ResolvedPhasePlan, ResolvedStage
from method_hub.domain import Sha256Digest, StableId
from method_hub.orchestration import (
    ContractSequentialOrchestrator,
    OrchestrationBinding,
    OrchestrationStatus,
    OrchestratorRegistry,
    OrchestratorRegistryError,
    StageOutcome,
    StageStatus,
    SubmissionOutcome,
    SubmissionReference,
    SubmissionStatus,
)
from method_hub.specification import SpecificationPackage


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"
METHOD = {
    "stable_id": "method.overlap_stabilized_score",
    "version": 1,
    "definition_sha256": "b274bbb26acde9604faad22d05b3f4015f75491a31b5d0f67f139a64f7a7a4f1",
}
MANIFEST_SHA256 = Sha256Digest("a" * 64)
SUBMISSION_SHA256 = Sha256Digest("b" * 64)
RUN_ID = StableId("run.orchestration.001")


@pytest.fixture(scope="module")
def specification() -> SpecificationPackage:
    return SpecificationPackage.load(ARCHITECTURE)


def _plan(
    specification: SpecificationPackage,
    phase_id: str,
    mode_id: str,
) -> ResolvedPhasePlan:
    identity = specification.phases.identity(phase_id)
    if phase_id == "P1":
        choices = {
            "p1.scope": "broad_update",
            "p1.instructions": "Update the literature basis.",
        }
    else:
        prefix = phase_id.lower()
        choices = {
            f"{prefix}.selected_method": METHOD,
            f"{prefix}.instructions": "Run the selected phase.",
        }
    return specification.resolve_phase(
        identity,
        mode_id,
        choices,
        "current_only",
    )


def _success(stage: ResolvedStage, *, reconciled: bool = False) -> StageOutcome:
    return StageOutcome(
        sequence=stage.sequence,
        stage_id=stage.stage_id,
        status=StageStatus.SUCCEEDED,
        invocation_closure_ids=tuple(
            StableId(f"closure.{stage.stage_id}.{index}")
            for index, _role in enumerate(stage.role_steps, start=1)
        ),
        reconciled=reconciled,
    )


class FakeServices:
    def __init__(
        self,
        *,
        fail_stage_id: str | None = None,
        cancel_on_check: int | None = None,
    ) -> None:
        self.fail_stage_id = fail_stage_id
        self.cancel_on_check = cancel_on_check
        self.cancellation_checks = 0
        self.stage_calls: list[ResolvedStage] = []
        self.actual_stage_launches: dict[str, int] = {}
        self.persisted_outcomes: dict[str, StageOutcome] = {}
        self.submission_calls = 0
        self.actual_submissions = 0
        self.persisted_submission: SubmissionReference | None = None

    async def cancellation_requested(self, **_kwargs) -> bool:
        self.cancellation_checks += 1
        return self.cancel_on_check == self.cancellation_checks

    async def execute_or_reconcile_stage(
        self, *, stage: ResolvedStage, **_kwargs
    ) -> StageOutcome:
        self.stage_calls.append(stage)
        persisted = self.persisted_outcomes.get(stage.stage_id)
        if persisted is not None:
            return replace(persisted, reconciled=True)
        self.actual_stage_launches[stage.stage_id] = (
            self.actual_stage_launches.get(stage.stage_id, 0) + 1
        )
        if stage.stage_id == self.fail_stage_id:
            outcome = StageOutcome(
                sequence=stage.sequence,
                stage_id=stage.stage_id,
                status=StageStatus.FAILED,
                failure_code="executor.failed",
            )
        else:
            outcome = _success(stage)
        self.persisted_outcomes[stage.stage_id] = outcome
        return outcome

    async def submit_or_reconcile(self, **_kwargs) -> SubmissionOutcome:
        self.submission_calls += 1
        if self.persisted_submission is None:
            self.actual_submissions += 1
            self.persisted_submission = SubmissionReference(
                "submission.orchestration.001",
                SUBMISSION_SHA256,
            )
        return SubmissionOutcome(
            SubmissionStatus.SUBMITTED,
            self.persisted_submission,
        )


async def _execute(
    plan: ResolvedPhasePlan,
    services: FakeServices,
    orchestrator: ContractSequentialOrchestrator | None = None,
):
    selected = orchestrator or ContractSequentialOrchestrator()
    binding = selected.binding_for(plan.identity)
    return await selected.execute(
        run_id=RUN_ID,
        manifest_sha256=MANIFEST_SHA256,
        binding=binding,
        plan=plan,
        services=services,
    )


def test_stages_execute_in_contract_order(
    specification: SpecificationPackage,
) -> None:
    plan = _plan(specification, "P4", "p4.preliminary")
    services = FakeServices()

    result = asyncio.run(_execute(plan, services))

    assert [stage.stage_id for stage in services.stage_calls] == [
        "p4.analyst",
        "p4.theorist",
        "p4.lead",
    ]
    assert result.status is OrchestrationStatus.SUBMITTED
    assert services.cancellation_checks == len(plan.stages) + 1
    assert services.submission_calls == 1


def test_parallel_stage_is_delegated_once_with_same_resolved_basis(
    specification: SpecificationPackage,
) -> None:
    plan = _plan(specification, "P1", "p1.literature_update")
    services = FakeServices()

    asyncio.run(_execute(plan, services))

    parallel = plan.stages[0]
    assert parallel.execution == "parallel"
    assert len(parallel.role_steps) == 3
    assert services.stage_calls[0] is parallel
    assert services.stage_calls.count(parallel) == 1


@pytest.mark.parametrize("cancel_on_check", [2, 4])
def test_cancellation_is_checked_before_each_stage_and_submission(
    specification: SpecificationPackage,
    cancel_on_check: int,
) -> None:
    plan = _plan(specification, "P4", "p4.preliminary")
    services = FakeServices(cancel_on_check=cancel_on_check)

    result = asyncio.run(_execute(plan, services))

    assert result.status is OrchestrationStatus.CANCELLED
    assert len(services.stage_calls) == cancel_on_check - 1
    assert services.submission_calls == 0


def test_failed_stage_stops_downstream_work_without_retry(
    specification: SpecificationPackage,
) -> None:
    plan = _plan(specification, "P4", "p4.preliminary")
    services = FakeServices(fail_stage_id="p4.theorist")

    result = asyncio.run(_execute(plan, services))

    assert result.status is OrchestrationStatus.FAILED
    assert [stage.stage_id for stage in services.stage_calls] == [
        "p4.analyst",
        "p4.theorist",
    ]
    assert services.actual_stage_launches["p4.theorist"] == 1
    assert services.submission_calls == 0


def test_recovery_reconciles_completed_stages_and_submission(
    specification: SpecificationPackage,
) -> None:
    plan = _plan(specification, "P4", "p4.preliminary")
    services = FakeServices()

    first = asyncio.run(_execute(plan, services))
    recovered = asyncio.run(_execute(plan, services))

    assert first.status is recovered.status is OrchestrationStatus.SUBMITTED
    assert services.actual_stage_launches == {
        "p4.analyst": 1,
        "p4.theorist": 1,
        "p4.lead": 1,
    }
    assert services.actual_submissions == 1
    assert all(outcome.reconciled for outcome in recovered.stage_outcomes)


def test_registry_resolves_exact_binding_and_fails_closed(
    specification: SpecificationPackage,
) -> None:
    plan = _plan(specification, "P4", "p4.preliminary")
    orchestrator = ContractSequentialOrchestrator()
    binding = orchestrator.binding_for(plan.identity)
    registry = OrchestratorRegistry([orchestrator])

    assert registry.resolve(binding) is orchestrator

    unsupported = OrchestrationBinding(
        protocol_version=binding.protocol_version,
        adapter_id=binding.adapter_id,
        adapter_version=binding.adapter_version,
        workflow_id=binding.workflow_id,
        workflow_version=binding.workflow_version,
        workflow_sha256="f" * 64,
        phase_contract=binding.phase_contract,
    )
    with pytest.raises(OrchestratorRegistryError) as raised:
        registry.resolve(unsupported)
    assert raised.value.code == "orchestration.binding_not_supported"

    with pytest.raises(OrchestratorRegistryError) as duplicate:
        registry.register(orchestrator)
    assert duplicate.value.code == "orchestration.duplicate_adapter"
