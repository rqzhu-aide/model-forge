from __future__ import annotations

from pathlib import Path

from method_hub.domain import MethodIdentity
from method_hub.projections import build_phase_configuration
from method_hub.specification import SpecificationPackage


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def test_phase_four_is_launchable_without_phase_three_when_basis_is_ready() -> None:
    specification = SpecificationPackage.load(ARCHITECTURE)
    method = MethodIdentity(
        stable_id="method.example",
        version=2,
        definition_sha256="a" * 64,
    )
    view = build_phase_configuration(
        repository=specification.phases,
        project_id="project.example",
        phase_id="P4",
        selected_mode="p4.preliminary",
        selected_method=method,
    )

    assert view["actions"][0]["enabled"] is True
    assert [stage["roles"] for stage in view["stage_plan"]] == [
        ["data_analyst"],
        ["theorist"],
        ["research_lead"],
    ]
    assert "No later phase or rerun starts automatically" in view["actions"][0][
        "consequence_summary"
    ]


def test_method_bound_phase_is_disabled_until_researcher_selects_method() -> None:
    specification = SpecificationPackage.load(ARCHITECTURE)
    view = build_phase_configuration(
        repository=specification.phases,
        project_id="project.example",
        phase_id="P3",
    )

    assert view["actions"][0]["enabled"] is False
    assert view["actions"][0]["reason_code"] == "run.method_required"


def test_phase_two_plan_preserves_parallel_groups() -> None:
    specification = SpecificationPackage.load(ARCHITECTURE)
    view = build_phase_configuration(
        repository=specification.phases,
        project_id="project.example",
        phase_id="P2",
        selected_mode="p2.full_catalog",
    )

    assert [stage["execution"] for stage in view["stage_plan"]] == [
        "parallel",
        "parallel",
        "serial",
    ]

def test_run_action_identity_covers_input_digest_and_authority_head() -> None:
    specification = SpecificationPackage.load(ARCHITECTURE)
    input_basis = {
        "option_id": "p1.project_brief",
        "required": True,
        "artifact_pointer": {
            "artifact_id": "artifact.project_brief",
            "sha256": "a" * 64,
        },
    }
    authority_head = {
        "authority_sequence": 4,
        "authority_root_sha256": "b" * 64,
        "current_revision": 3,
    }

    baseline = build_phase_configuration(
        repository=specification.phases,
        project_id="project.example",
        phase_id="P1",
        current_inputs=[input_basis],
        authority_head=authority_head,
    )
    changed_input = build_phase_configuration(
        repository=specification.phases,
        project_id="project.example",
        phase_id="P1",
        current_inputs=[
            {
                **input_basis,
                "artifact_pointer": {
                    **input_basis["artifact_pointer"],
                    "sha256": "c" * 64,
                },
            }
        ],
        authority_head=authority_head,
    )
    changed_head = build_phase_configuration(
        repository=specification.phases,
        project_id="project.example",
        phase_id="P1",
        current_inputs=[input_basis],
        authority_head={**authority_head, "authority_sequence": 5},
    )

    baseline_id = baseline["actions"][0]["descriptor_id"]
    assert changed_input["actions"][0]["descriptor_id"] != baseline_id
    assert changed_head["actions"][0]["descriptor_id"] != baseline_id
