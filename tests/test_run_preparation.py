from __future__ import annotations

from pathlib import Path

from model_forge.contracts.runtime import resolve_runtime_contract
from model_forge.domain import ArtifactPointer
from model_forge.harness.inputs import (
    CurrentRecordReference,
    InputResolutionResult,
    ResolvedRunInput,
)
from model_forge.harness.outputs import build_output_plan
from model_forge.harness.preparation import build_prepared_run_recipe
from model_forge.orchestration import ContractSequentialOrchestrator
from model_forge.specification import SpecificationPackage


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def test_recipe_freezes_orchestration_profiles_and_parallel_group() -> None:
    specification = SpecificationPackage.load(ARCHITECTURE)
    identity = specification.phases.identity("P1")
    plan = specification.resolve_phase(
        identity,
        "p1.literature_update",
        {"p1.scope": "broad_update", "p1.instructions": "Update the basis."},
        "current_only",
    )
    runtime = resolve_runtime_contract(specification.phases, plan)
    pointer = ArtifactPointer(
        artifact_id="artifact.project_brief",
        uri="artifact://sha256/" + "a" * 64,
        sha256="a" * 64,
        media_type="application/json",
    )
    inputs = InputResolutionResult(
        inputs=(
            ResolvedRunInput(
                contract_input_id="p1.project_brief",
                record=CurrentRecordReference(
                    record_id="record.project_brief",
                    generation_id="generation.project_brief",
                    generation_number=1,
                    record_type="project_brief",
                    artifact=pointer,
                ),
                purpose="Define the research question.",
            ),
        ),
        selected_history=(),
        findings=(),
    )
    orchestrator = ContractSequentialOrchestrator()
    binding = orchestrator.binding_for(identity)
    command = {
        "command_id": "command.example",
        "project_id": "project.example",
        "content_sha256": "b" * 64,
        "idempotency_key": "request-example",
        "resource_constraints": {
            "wall_time_limit_seconds": 3600,
            "network_policy": "approved_resources",
        },
    }
    recipe = build_prepared_run_recipe(
        run_id="run.example",
        command=command,
        contract=runtime,
        inputs=inputs,
        output_plan=build_output_plan(plan),
        profiles={
            "research_lead": "lead",
            "theorist": "theory",
            "data_analyst": "analysis",
        },
        binding=binding,
    )

    assert recipe.document["stages"][0]["execution"] == "parallel"
    assert [item["role"] for item in recipe.document["stages"][0]["roles"]] == [
        "research_lead",
        "theorist",
        "data_analyst",
    ]
    assert recipe.document["orchestration_binding"]["retry_policy"] == (
        "no_scientific_role_retry"
    )
    assert len(recipe.sha256) == 64
