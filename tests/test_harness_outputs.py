from __future__ import annotations

import json
from pathlib import Path

from method_hub.harness.outputs import (
    build_output_plan,
    validate_role_outputs,
)
from method_hub.harness.task_briefs import (
    _extract_conditional_requirements,
    _render_schema_constraints,
    render_task_brief,
)
from method_hub.specification import SpecificationPackage


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "architecture"


def p4_plan():
    package = SpecificationPackage.load(ARCHITECTURE)
    identity = package.phases.identity("P4")
    plan = package.resolve_phase(
        identity,
        "p4.preliminary",
        {
            "p4.selected_method": {
                "stable_id": "method.demo",
                "version": 1,
                "definition_sha256": "a" * 64,
            },
            "p4.instructions": "Run the prespecified preliminary assessment.",
            "p4.selected_history": [],
        },
        "current_only",
    )
    return package, plan


def test_output_plan_preserves_p4_role_order_and_ownership() -> None:
    _, plan = p4_plan()
    output_plan = build_output_plan(plan)
    analyst = output_plan.for_stage_role("p4.analyst", "data_analyst")
    theorist = output_plan.for_stage_role("p4.theorist", "theorist")
    lead = output_plan.for_stage_role("p4.lead", "research_lead")
    assert [item.contract_output_id for item in analyst] == [
        "p4.protocol",
        "p4.evidence",
        "p4.analyst_synthesis",
        "p4.analyst_handoff",
    ]
    assert len(theorist) == 2
    assert len(lead) == 5
    assert len({item.relative_path for item in output_plan.specs}) == len(
        output_plan.specs
    )


def test_missing_role_outputs_are_reported_without_publication(tmp_path: Path) -> None:
    package, plan = p4_plan()
    output_plan = build_output_plan(plan)
    result = validate_role_outputs(
        schema_catalog=package.schemas,
        run_root=tmp_path,
        output_plan=output_plan,
        stage=plan.stages[0],
        role="data_analyst",
    )
    assert result.passed is False
    assert {item.code for item in result.findings} == {"output.required_missing"}
    assert len(result.findings) == 4


def test_duplicate_key_output_is_rejected_as_strict_json(tmp_path: Path) -> None:
    package, plan = p4_plan()
    output_plan = build_output_plan(plan)
    spec = output_plan.for_stage_role("p4.analyst", "data_analyst")[0]
    path = tmp_path.joinpath(*spec.relative_path.split("/"))
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version":"1.0.0","schema_version":"1.0.0"}\n')
    result = validate_role_outputs(
        schema_catalog=package.schemas,
        run_root=tmp_path,
        output_plan=output_plan,
        stage=plan.stages[0],
        role="data_analyst",
    )
    finding = next(
        item for item in result.findings if item.object_id == "p4.protocol"
    )
    assert finding.code == "json.duplicate_key"


def test_task_brief_states_manual_and_parallel_boundaries() -> None:
    package = SpecificationPackage.load(ARCHITECTURE)
    identity = package.phases.identity("P1")
    plan = package.resolve_phase(
        identity,
        "p1.literature_update",
        {
            "p1.scope": "broad_update",
            "p1.instructions": "Update literature relevant to the research question.",
            "p1.selected_history": [],
        },
        "current_only",
    )
    output_plan = build_output_plan(plan)
    stage = plan.stages[0]
    step = stage.step_for("theorist")
    brief = render_task_brief(
        run_id="run.demo",
        project_id="project.demo",
        plan=plan,
        stage=stage,
        role="theorist",
        input_paths={item: f"context/{item}.json" for item in step.input_ids},
        output_plan=output_plan,
        phase_instruction="Update literature relevant to the research question.",
        same_group_roles=stage.roles,
    )
    assert "common frozen basis" in brief
    assert "Do not start another role, rerun, phase" in brief
    assert "negative, null, contradictory, or inconclusive" in brief
    assert json.dumps(dict(plan.choice_values), ensure_ascii=False, indent=2) in brief


def test_conditional_fields_render_else_prohibitions() -> None:
    package = SpecificationPackage.load(ARCHITECTURE)
    schema = package.schemas.get("attention-item.schema.json")
    entries = {
        entry["field"]: entry
        for entry in _extract_conditional_requirements(schema)
    }

    # if/then requirement: publication fields required for formal_generation
    for field in ("publication_receipt_id", "published_at"):
        entry = entries[field]
        assert entry["condition"] == "`authority_at_creation` is `formal_generation`"
        # else prohibition: same fields forbidden when the condition does not hold
        assert entry["prohibited_when"] == (
            "`authority_at_creation` is not `formal_generation`"
        )

    # plain if/then requirements (no else) keep working
    reason = entries["disposition_reason"]
    assert reason["condition"] is not None
    assert reason["condition"].startswith("`disposition` is one of")
    assert reason["prohibited_when"] is None
    rerun = entries["rerun_question"]
    assert rerun["condition"] == (
        "`severity` is one of (`reassessment_required`, `blocking`); "
        "AND `disposition` is `open`"
    )

    rendered = _render_schema_constraints("attention-item.schema.json", package.schemas)
    assert "always provide these fields" not in rendered
    assert (
        "- `publication_receipt_id` — required only when: "
        "`authority_at_creation` is `formal_generation`; do NOT include when: "
        "`authority_at_creation` is not `formal_generation`" in rendered
    )
    assert (
        "- `published_at` — required only when: "
        "`authority_at_creation` is `formal_generation`; do NOT include when: "
        "`authority_at_creation` is not `formal_generation`" in rendered
    )
