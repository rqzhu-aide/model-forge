from __future__ import annotations

import json
from pathlib import Path

import pytest

from method_hub.contracts import (
    ResolvedPhasePlan,
    ResolvedRoleStep,
    ResolvedStage,
)
from method_hub.domain import PhaseContractIdentity
from method_hub.domain.validation import FindingClass
from method_hub.harness.outputs import (
    OutputPlan,
    build_output_plan,
    validate_role_outputs,
)
from method_hub.harness.task_briefs import (
    _extract_conditional_requirements,
    _load_schema_example,
    _render_schema_constraints,
    render_task_brief,
)
from method_hub.schemas import SchemaCatalog
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
    # Every record-authoring brief carries the math-format convention.
    assert "delimited LaTeX" in brief
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


def test_task_brief_layers_mode_stage_and_verbatim_researcher_direction() -> None:
    custom = "  Preserve capitalization EXACTLY.\nSecond line stays verbatim.  "
    stage = ResolvedStage(
        sequence=1,
        stage_id="p2.independent_proposals",
        execution="parallel",
        objective="Evaluate the proposal independently.",
        role_steps=(
            ResolvedRoleStep(
                role="theorist",
                input_ids=(),
                output_ids=(),
            ),
        ),
        writes=(),
        handoff_required=True,
        isolation_rule=None,
    )
    plan = ResolvedPhasePlan(
        identity=PhaseContractIdentity(
            phase_id="P2",
            contract_version="1.0.0",
            phase_contract_sha256="a" * 64,
        ),
        mode_id="p2.researcher_proposal",
        choice_values={
            "p2.instructions": custom,
            "p2.researcher_method_spec": "A fully specified candidate method.",
            "p2.selected_history": [],
        },
        context_policy="current_only",
        stages=(stage,),
        output_contracts=(),
        prepared_contexts=(),
        validation_rules=(),
        publication_bindings=(),
        promotion={},
    )
    brief = render_task_brief(
        run_id="run.layered",
        project_id="project.layered",
        plan=plan,
        stage=stage,
        role="theorist",
        input_paths={},
        output_plan=OutputPlan(specs=()),
        phase_instruction=custom,
        mode_instruction="MODE LAYER",
        stage_role_instruction="STAGE ROLE LAYER",
        researcher_instruction=custom,
        researcher_method_spec="A fully specified candidate method.",
    )

    assert "## Immutable instruction boundary" in brief
    assert "## Mode directive\n\nMODE LAYER" in brief
    assert "## Stage-role assignment\n\nSTAGE ROLE LAYER" in brief
    assert custom in brief
    assert brief.index("## Mode directive") < brief.index("## Stage-role assignment")
    assert brief.index("## Stage-role assignment") < brief.index("## Researcher direction")


def _neutral_schema_document(
    catalog: SchemaCatalog,
    schema_file: str,
) -> tuple[str, dict[str, object]]:
    rendered = _load_schema_example(schema_file, catalog)
    assert rendered is not None
    assert "truncated" not in rendered.lower()
    document = json.loads(rendered)
    assert isinstance(document, dict)
    return rendered, document


def _at_path(document: dict[str, object], path: tuple[str, ...]) -> object:
    value: object = document
    for part in path:
        assert isinstance(value, dict)
        value = value[part]
    return value


def _has_placeholder(value: object) -> bool:
    if isinstance(value, str):
        return value.startswith("<") and value.endswith(">")
    if isinstance(value, dict):
        return any(_has_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_placeholder(item) for item in value)
    return False


def test_runtime_schema_examples_do_not_leak_golden_scientific_content() -> None:
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    rendered: dict[str, str] = {}
    documents: dict[str, dict[str, object]] = {}
    for schema_file in (
        "method.schema.json",
        "handoff.schema.json",
        "review-issue.schema.json",
    ):
        text, document = _neutral_schema_document(catalog, schema_file)
        rendered[schema_file] = text
        documents[schema_file] = document

    combined = "\n".join(rendered.values()).lower()
    for fixture_content in (
        "overlap-stabilized",
        "average treatment effect",
        "orthogonal score",
        "propensity",
        "cross-fit",
        "simulation",
        "monte carlo",
        "rmse",
        "variance normalization",
    ):
        assert fixture_content not in combined

    disposition = documents["review-issue.schema.json"]["disposition"]
    assert disposition != "fixed"
    assert disposition == "<one of: open | fixed | partially_fixed | deferred | rejected>"


_NEW_SCHEMA_GUIDANCE = (
    (
        "empirical-protocol.schema.json",
        {"protocol_id", "claim_tests", "estimand", "metrics", "protocol_status"},
        {"phase": "P4", "protocol_status": "prespecified"},
        (("mode",), ("p4.preliminary", "p4.comprehensive")),
    ),
    (
        "manuscript-package.schema.json",
        {"record_id", "manuscript_artifact", "sections_present", "claim_support_index"},
        {"phase": "P5", "record_type": "manuscript"},
        (("manuscript_kind",), ("assembly_candidate", "revised_candidate")),
    ),
    (
        "review-finding.schema.json",
        {"issue_id", "finding_type", "evidence_basis", "requested_resolution"},
        {"status": "open", "authority_at_creation": "run_local_candidate"},
        (("severity",), ("blocking", "major", "minor")),
    ),
    (
        "review-report.schema.json",
        {"report_id", "overall_assessment", "prioritized_issues", "novelty_search_boundary"},
        {"reviewer_role": "outside_reviewer", "authority_at_creation": "run_local_candidate"},
        (("novelty_search_boundary", "assessment_status"), ("bounded", "provisional", "not_assessed")),
    ),
    (
        "theory-record.schema.json",
        {"record_id", "theory_scope", "assumptions", "statements", "empirical_implications"},
        {"phase": "P3", "record_type": "theory_record"},
        (("development_mode",), ("p3.theory_establishment", "p3.theory_revision")),
    ),
)


@pytest.mark.parametrize(
    ("schema_file", "expected_keys", "expected_constants", "enum_guidance"),
    _NEW_SCHEMA_GUIDANCE,
)
def test_new_scientific_schemas_yield_neutral_structural_guidance(
    schema_file: str,
    expected_keys: set[str],
    expected_constants: dict[str, str],
    enum_guidance: tuple[tuple[str, ...], tuple[str, ...]],
) -> None:
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    _, document = _neutral_schema_document(catalog, schema_file)

    assert expected_keys <= document.keys()
    assert _has_placeholder(document)


# ---------------------------------------------------------------------------
# ADR-015: harness-owned-field findings route to operational failure (K5-1b)
# ---------------------------------------------------------------------------


def _write_output(tmp_path: Path, spec, document: dict) -> None:
    path = tmp_path.joinpath(*spec.relative_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_harness_owned_field_failure_is_operational_not_correctable(
    tmp_path: Path,
) -> None:
    package, plan = p4_plan()
    output_plan = build_output_plan(plan)
    stage = next(s for s in plan.stages if s.stage_id == "p4.analyst")
    spec = next(
        s
        for s in output_plan.for_stage_role("p4.analyst", "data_analyst")
        if s.schema_file == "handoff.schema.json"
    )
    document = json.loads(
        (ARCHITECTURE / "examples" / "handoff.example.json").read_text()
    )
    # from_role is harness-owned; the enum violation cannot be agent-fixed
    # because the harness re-populates the field at every close (ADR-015).
    document["from_role"] = "bogus_role"
    _write_output(tmp_path, spec, document)
    result = validate_role_outputs(
        schema_catalog=package.schemas,
        run_root=tmp_path,
        output_plan=output_plan,
        stage=stage,
        role="data_analyst",
    )
    finding = next(
        f
        for f in result.findings
        if f.object_id == spec.contract_output_id and f.code == "schema.enum"
    )
    assert finding.finding_class == FindingClass.OPERATIONAL_FAILURE
    assert finding.correction_class == "none"
    assert finding.blocks_publication is True
    assert "harness" in finding.message.lower()
    assert "from_role" in finding.message


def test_agent_owned_field_failure_stays_correctable(tmp_path: Path) -> None:
    package, plan = p4_plan()
    output_plan = build_output_plan(plan)
    stage = next(s for s in plan.stages if s.stage_id == "p4.analyst")
    spec = next(
        s
        for s in output_plan.for_stage_role("p4.analyst", "data_analyst")
        if s.schema_file == "handoff.schema.json"
    )
    document = json.loads(
        (ARCHITECTURE / "examples" / "handoff.example.json").read_text()
    )
    document["completed_work"] = 123  # agent-owned content field
    _write_output(tmp_path, spec, document)
    result = validate_role_outputs(
        schema_catalog=package.schemas,
        run_root=tmp_path,
        output_plan=output_plan,
        stage=stage,
        role="data_analyst",
    )
    finding = next(
        f
        for f in result.findings
        if f.object_id == spec.contract_output_id and f.code.startswith("schema.")
    )
    assert finding.finding_class == FindingClass.CORRECTABLE_CONTRACT_ERROR


def test_broadcast_handoff_output_validates_in_role_validation(
    tmp_path: Path,
) -> None:
    package, plan = p4_plan()
    output_plan = build_output_plan(plan)
    stage = next(s for s in plan.stages if s.stage_id == "p4.analyst")
    spec = next(
        s
        for s in output_plan.for_stage_role("p4.analyst", "data_analyst")
        if s.schema_file == "handoff.schema.json"
    )
    document = json.loads(
        (ARCHITECTURE / "examples" / "handoff.example.json").read_text()
    )
    document.pop("to_role", None)  # broadcast form (ADR-015)
    _write_output(tmp_path, spec, document)
    result = validate_role_outputs(
        schema_catalog=package.schemas,
        run_root=tmp_path,
        output_plan=output_plan,
        stage=stage,
        role="data_analyst",
    )
    assert not [
        f
        for f in result.findings
        if f.object_id == spec.contract_output_id
    ]
