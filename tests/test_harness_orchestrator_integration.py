from __future__ import annotations

import asyncio
from pathlib import Path

from method_hub.orchestration import (
    ContractSequentialOrchestrator,
    OrchestrationStatus,
)

from test_stage_execution_service import Fixture


def test_contract_orchestrator_advances_harness_stages_then_submits(
    tmp_path: Path,
) -> None:
    fixture = Fixture(tmp_path)
    orchestrator = ContractSequentialOrchestrator()

    result = asyncio.run(
        orchestrator.execute(
            run_id=fixture.context.run_id,
            manifest_sha256=fixture.context.manifest_sha256,
            binding=orchestrator.binding_for(fixture.plan.identity),
            plan=fixture.plan,
            services=fixture.services,
        )
    )

    assert result.status is OrchestrationStatus.SUBMITTED
    assert [item.status.value for item in result.stage_outcomes] == [
        "succeeded",
        "succeeded",
    ]
    assert fixture.repository.get_submission("run.stage_test") is not None
