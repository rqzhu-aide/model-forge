from __future__ import annotations

from pathlib import Path

from method_hub.contracts.runtime import resolve_runtime_contract
from method_hub.domain.identities import ArtifactPointer, MethodIdentity
from method_hub.harness.inputs import (
    CurrentRecordReference,
    resolve_run_inputs,
)
from method_hub.specification import SpecificationPackage


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


class Lookup:
    def __init__(self, records: dict[str, CurrentRecordReference]) -> None:
        self.records = records

    def current_record(
        self,
        *,
        project_id: str,
        record_type: str,
        method_identity: MethodIdentity | None,
        match_policy: str,
    ) -> CurrentRecordReference | None:
        return self.records.get(record_type)


def pointer(name: str) -> ArtifactPointer:
    return ArtifactPointer(
        artifact_id=f"artifact.{name}",
        uri=f"artifact://artifact.{name}",
        sha256="a" * 64,
        media_type="application/json",
    )


def reference(
    record_type: str,
    *,
    method: MethodIdentity | None = None,
) -> CurrentRecordReference:
    return CurrentRecordReference(
        record_id=f"record.{record_type}",
        generation_id=f"generation.{record_type}.001",
        generation_number=1,
        record_type=record_type,
        artifact=pointer(record_type),
        method_identity=method,
    )


def p4_contract():
    package = SpecificationPackage.load(ARCHITECTURE)
    method = MethodIdentity("method.demo", 1, "b" * 64)
    plan = package.resolve_phase(
        package.phases.identity("P4"),
        "p4.preliminary",
        {
            "p4.selected_method": method.to_dict(),
            "p4.instructions": "Run a focused preliminary evaluation.",
            "p4.selected_history": [],
        },
        "current_only",
    )
    return package, method, resolve_runtime_contract(package.phases, plan)


def p1_contract():
    package = SpecificationPackage.load(ARCHITECTURE)
    plan = package.resolve_phase(
        package.phases.identity("P1"),
        "p1.literature_update",
        {
            "p1.scope": "broad_update",
            "p1.instructions": "Update the literature basis.",
            "p1.selected_history": [],
        },
        "current_only",
    )
    return resolve_runtime_contract(package.phases, plan)


def test_phase4_can_start_without_phase3_or_prior_phase4() -> None:
    _, method, contract = p4_contract()
    lookup = Lookup(
        {
            "project_brief": reference("project_brief"),
            "literature_synthesis": reference("literature_synthesis"),
            "method_catalog": reference("method_catalog"),
            "method_record": reference("method_record", method=method),
        }
    )
    result = resolve_run_inputs(
        project_id="project.demo", contract=contract, lookup=lookup
    )
    assert result.passed
    assert "p4.current_theory" not in {
        item.contract_input_id for item in result.inputs
    }


def test_phase4_rejects_partial_prior_package() -> None:
    _, method, contract = p4_contract()
    lookup = Lookup(
        {
            "project_brief": reference("project_brief"),
            "literature_synthesis": reference("literature_synthesis"),
            "method_catalog": reference("method_catalog"),
            "method_record": reference("method_record", method=method),
            "empirical_evidence_index": reference(
                "empirical_evidence_index", method=method
            ),
        }
    )
    result = resolve_run_inputs(
        project_id="project.demo", contract=contract, lookup=lookup
    )
    assert not result.passed
    assert "input.p4_prior_package_incomplete" in {
        item.code for item in result.findings
    }


def test_exact_method_mismatch_is_rejected() -> None:
    _, method, contract = p4_contract()
    old_method = MethodIdentity("method.demo", 2, "c" * 64)
    lookup = Lookup(
        {
            "project_brief": reference("project_brief"),
            "literature_synthesis": reference("literature_synthesis"),
            "method_catalog": reference("method_catalog"),
            "method_record": reference("method_record", method=old_method),
        }
    )
    result = resolve_run_inputs(
        project_id="project.demo", contract=contract, lookup=lookup
    )
    assert not result.passed
    assert "input.method_identity_mismatch" in {item.code for item in result.findings}

def test_optional_current_input_is_included_only_when_selected() -> None:
    _, method, contract = p4_contract()
    lookup = Lookup(
        {
            "project_brief": reference("project_brief"),
            "literature_synthesis": reference("literature_synthesis"),
            "method_catalog": reference("method_catalog"),
            "method_record": reference("method_record", method=method),
            "theory_record": reference("theory_record", method=method),
        }
    )
    required = {
        "p4.project_brief",
        "p4.literature_synthesis",
        "p4.method_catalog",
        "p4.method",
    }

    without_theory = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=lookup,
        selected_context_option_ids=sorted(required),
    )
    with_theory = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=lookup,
        selected_context_option_ids=sorted(required | {"p4.current_theory"}),
    )

    assert without_theory.passed
    assert "p4.current_theory" not in {
        item.contract_input_id for item in without_theory.inputs
    }
    assert with_theory.passed
    assert "p4.current_theory" in {
        item.contract_input_id for item in with_theory.inputs
    }


def test_unknown_and_deselected_required_inputs_are_rejected() -> None:
    _, method, contract = p4_contract()
    lookup = Lookup(
        {
            "project_brief": reference("project_brief"),
            "literature_synthesis": reference("literature_synthesis"),
            "method_catalog": reference("method_catalog"),
            "method_record": reference("method_record", method=method),
        }
    )

    unknown = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=lookup,
        selected_context_option_ids=["p4.not_declared"],
    )
    deselected_required = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=lookup,
        selected_context_option_ids=[
            "p4.project_brief",
            "p4.literature_synthesis",
            "p4.method_catalog",
        ],
    )

    assert not unknown.passed
    assert {item.code for item in unknown.findings} == {
        "input.unknown_context_selection"
    }
    assert not deselected_required.passed
    assert "input.required_context_not_selected" in {
        item.code for item in deselected_required.findings
    }
    assert "p4.method" in {
        item.object_id for item in deselected_required.findings
    }


def test_phase1_rerun_package_must_be_complete_or_absent() -> None:
    contract = p1_contract()
    first_run = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=Lookup({"project_brief": reference("project_brief")}),
    )
    partial_rerun = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=Lookup(
            {
                "project_brief": reference("project_brief"),
                "literature_library": reference("literature_library"),
            }
        ),
    )
    complete_rerun = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=Lookup(
            {
                "project_brief": reference("project_brief"),
                "literature_library": reference("literature_library"),
                "literature_synthesis": reference("literature_synthesis"),
                "literature_coverage": reference("literature_coverage"),
            }
        ),
    )

    assert first_run.passed
    assert partial_rerun.passed is False
    assert {
        item.object_id
        for item in partial_rerun.findings
        if item.code == "input.required_current_record_missing"
    } == {"p1.current_synthesis", "p1.current_coverage"}
    assert complete_rerun.passed
    assert {
        item.contract_input_id for item in complete_rerun.inputs
    } == {
        "p1.project_brief",
        "p1.current_library",
        "p1.current_synthesis",
        "p1.current_coverage",
    }
