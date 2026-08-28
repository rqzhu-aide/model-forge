from __future__ import annotations

from pathlib import Path

from model_forge.contracts.runtime import resolve_runtime_contract
from model_forge.domain.identities import ArtifactPointer, MethodIdentity
from model_forge.harness.inputs import (
    CurrentRecordReference,
    resolve_run_inputs,
)
from model_forge.specification import SpecificationPackage


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


def p2_focused_contract():
    package = SpecificationPackage.load(ARCHITECTURE)
    method = MethodIdentity("method.demo", 1, "b" * 64)
    plan = package.resolve_phase(
        package.phases.identity("P2"),
        "p2.focused_method",
        {
            "p2.selected_method": method.to_dict(),
            "p2.instructions": "Revise the focused method.",
            "p2.selected_history": [],
        },
        "current_only",
    )
    return package, method, resolve_runtime_contract(package.phases, plan)


def p5_review_contract():
    package = SpecificationPackage.load(ARCHITECTURE)
    method = MethodIdentity("method.demo", 1, "b" * 64)
    plan = package.resolve_phase(
        package.phases.identity("P5"),
        "p5.review_revision",
        {
            "p5.selected_method": method.to_dict(),
            "p5.instructions": "Revise the manuscript after review.",
            "p5.selected_history": [],
        },
        "current_only",
    )
    return package, method, resolve_runtime_contract(package.phases, plan)


def test_phase2_focused_optional_context_is_deselectable() -> None:
    """P2's theory/empirical/manuscript context is optional (if_exists): the
    researcher may deselect present records or run without them entirely."""
    _, method, contract = p2_focused_contract()
    required = {
        "p2.project_brief",
        "p2.literature_synthesis",
        "p2.literature_library",
        "p2.literature_coverage",
    }
    lookup = Lookup(
        {
            "project_brief": reference("project_brief"),
            "literature_synthesis": reference("literature_synthesis"),
            "literature_library": reference("literature_library"),
            "literature_coverage": reference("literature_coverage"),
            "theory_record": reference("theory_record", method=method),
            "empirical_synthesis": reference("empirical_synthesis", method=method),
            "manuscript": reference("manuscript", method=method),
        }
    )

    deselected = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=lookup,
        selected_context_option_ids=sorted(required),
    )
    selected = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=lookup,
        selected_context_option_ids=sorted(
            required | {"p2.theory_result", "p2.manuscript_result"}
        ),
    )

    assert deselected.passed
    assert {
        "p2.theory_result",
        "p2.empirical_result",
        "p2.manuscript_result",
    }.isdisjoint(item.contract_input_id for item in deselected.inputs)
    assert selected.passed
    assert {"p2.theory_result", "p2.manuscript_result"} <= {
        item.contract_input_id for item in selected.inputs
    }


def test_phase2_focused_optional_context_may_be_absent() -> None:
    """A focused P2 run starts cleanly when no downstream results exist."""
    _, _, contract = p2_focused_contract()
    lookup = Lookup(
        {
            "project_brief": reference("project_brief"),
            "literature_synthesis": reference("literature_synthesis"),
            "literature_library": reference("literature_library"),
            "literature_coverage": reference("literature_coverage"),
        }
    )

    result = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=lookup,
        selected_context_option_ids=[
            "p2.project_brief",
            "p2.literature_synthesis",
            "p2.literature_library",
            "p2.literature_coverage",
        ],
    )

    assert result.passed


def _p5_lookup(method: MethodIdentity, *, with_manuscript: bool) -> "Lookup":
    records = {
        "project_brief": reference("project_brief"),
        "literature_library": reference("literature_library"),
        "literature_synthesis": reference("literature_synthesis"),
        "literature_coverage": reference("literature_coverage"),
        "method_catalog": reference("method_catalog"),
        "method_record": reference("method_record", method=method),
        "theory_record": reference("theory_record", method=method),
        "empirical_evidence_index": reference("empirical_evidence_index", method=method),
        "empirical_synthesis": reference("empirical_synthesis", method=method),
        "implementation_record": reference("implementation_record", method=method),
    }
    if with_manuscript:
        records["manuscript"] = reference("manuscript", method=method)
    return Lookup(records)


_P5_ALWAYS_SELECTED = [
    "p5.project_brief",
    "p5.literature_library",
    "p5.literature_synthesis",
    "p5.literature_coverage",
    "p5.method_catalog",
    "p5.method",
    "p5.theory",
    "p5.empirical_index",
    "p5.empirical",
    "p5.implementation_record",
]


def test_phase5_review_revision_manuscript_stays_required() -> None:
    """required_in_modes keeps its execution meaning: in review_revision mode
    the review-target manuscript is mandatory — deselected or missing both
    fail.  (P5 contract 2.4.0: the gate moved from p5.current_manuscript to
    p5.review_target_manuscript; the current manuscript is now the
    situation-aware required_on_rerun input.)"""
    _, method, contract = p5_review_contract()

    deselected = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=_p5_lookup(method, with_manuscript=True),
        selected_context_option_ids=list(_P5_ALWAYS_SELECTED),
    )
    missing = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=_p5_lookup(method, with_manuscript=False),
        selected_context_option_ids=[*_P5_ALWAYS_SELECTED, "p5.review_target_manuscript"],
    )
    complete = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=_p5_lookup(method, with_manuscript=True),
        selected_context_option_ids=[
            *_P5_ALWAYS_SELECTED,
            "p5.current_manuscript",
            "p5.review_target_manuscript",
        ],
    )

    assert not deselected.passed
    assert "input.required_context_not_selected" in {
        item.code for item in deselected.findings
    }
    # With a draft present, both manuscript inputs are required in
    # review-revision: the situational slot and the review target.
    assert {"p5.current_manuscript", "p5.review_target_manuscript"} <= {
        item.object_id for item in deselected.findings
    }
    assert not missing.passed
    assert "input.required_current_record_missing" in {
        item.code for item in missing.findings
    }
    assert complete.passed


def test_phase5_assembly_manuscript_is_situation_aware() -> None:
    """P5 contract 2.4.0: p5.current_manuscript is required_on_rerun — absent
    on the first assembly run (no draft to continue), mandatory on a rerun
    (an established draft must be continued, not silently restarted)."""
    package = SpecificationPackage.load(ARCHITECTURE)
    method = MethodIdentity("method.demo", 1, "b" * 64)
    plan = package.resolve_phase(
        package.phases.identity("P5"),
        "p5.assembly",
        {
            "p5.selected_method": method.to_dict(),
            "p5.instructions": "Write the manuscript.",
            "p5.selected_history": [],
        },
        "current_only",
    )
    contract = resolve_runtime_contract(package.phases, plan)

    first_run = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=_p5_lookup(method, with_manuscript=False),
        selected_context_option_ids=list(_P5_ALWAYS_SELECTED),
    )
    rerun = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=_p5_lookup(method, with_manuscript=True),
        selected_context_option_ids=list(_P5_ALWAYS_SELECTED),
    )
    rerun_selected = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=_p5_lookup(method, with_manuscript=True),
        selected_context_option_ids=[*_P5_ALWAYS_SELECTED, "p5.current_manuscript"],
    )

    # First assembly: no draft exists, and none is demanded.
    assert first_run.passed
    # Rerun: the established draft is required — deselecting it fails.
    assert not rerun.passed
    assert "p5.current_manuscript" in {
        item.object_id for item in rerun.findings
    }
    # Rerun with the draft selected resolves it as an input.
    assert rerun_selected.passed
    assert "p5.current_manuscript" in {
        item.contract_input_id for item in rerun_selected.inputs
    }


# --------------------------------------------------------------------------- #
# SD-1: researcher seed channel
# --------------------------------------------------------------------------- #


def _seed_reference(method: MethodIdentity) -> CurrentRecordReference:
    return CurrentRecordReference(
        record_id="seed.p5.current_manuscript.abc123",
        generation_id="seed",
        generation_number=0,
        record_type="manuscript",
        artifact=pointer("seed-manuscript"),
        method_identity=method,
        size_bytes=1234,
    )


def p5_contract():
    package = SpecificationPackage.load(ARCHITECTURE)
    method = MethodIdentity("method.demo", 1, "b" * 64)
    plan = package.resolve_phase(
        package.phases.identity("P5"),
        "p5.assembly",
        {
            "p5.selected_method": method.to_dict(),
            "p5.instructions": "Write the manuscript.",
            "p5.selected_history": [],
        },
        "current_only",
    )
    return package, method, resolve_runtime_contract(package.phases, plan)


def test_seed_fills_absent_rerun_slot_with_provenance() -> None:
    """A seeded draft turns a first assembly into a continuation run: the
    manuscript input resolves with researcher_seed provenance even though no
    published manuscript record exists."""
    _, method, contract = p5_contract()
    result = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=_p5_lookup(method, with_manuscript=False),
        selected_context_option_ids=[*_P5_ALWAYS_SELECTED, "p5.current_manuscript"],
        seed_records={"p5.current_manuscript": _seed_reference(method)},
    )
    assert result.passed
    seeded = next(
        item
        for item in result.inputs
        if item.contract_input_id == "p5.current_manuscript"
    )
    assert seeded.origin == "researcher_seed"
    assert seeded.record.record_id.startswith("seed.")
    # Every other input keeps the published-state provenance.
    assert all(
        item.origin == "current_record"
        for item in result.inputs
        if item.contract_input_id != "p5.current_manuscript"
    )


def test_seed_overrides_published_record_for_the_run() -> None:
    _, method, contract = p5_contract()
    result = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=_p5_lookup(method, with_manuscript=True),
        selected_context_option_ids=[*_P5_ALWAYS_SELECTED, "p5.current_manuscript"],
        seed_records={"p5.current_manuscript": _seed_reference(method)},
    )
    assert result.passed
    seeded = next(
        item
        for item in result.inputs
        if item.contract_input_id == "p5.current_manuscript"
    )
    assert seeded.origin == "researcher_seed"
    assert seeded.record.generation_id == "seed"


def test_unknown_seed_input_rejected() -> None:
    _, method, contract = p5_contract()
    result = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=_p5_lookup(method, with_manuscript=False),
        selected_context_option_ids=list(_P5_ALWAYS_SELECTED),
        seed_records={"p5.not_an_input": _seed_reference(method)},
    )
    assert not result.passed
    assert {item.code for item in result.findings} == {"input.unknown_seed"}


def test_required_seed_must_stay_selected() -> None:
    """A seed makes the rerun slot required; deselecting it still fails."""
    _, method, contract = p5_contract()
    result = resolve_run_inputs(
        project_id="project.demo",
        contract=contract,
        lookup=_p5_lookup(method, with_manuscript=False),
        selected_context_option_ids=list(_P5_ALWAYS_SELECTED),
        seed_records={"p5.current_manuscript": _seed_reference(method)},
    )
    assert not result.passed
    assert "p5.current_manuscript" in {item.object_id for item in result.findings}
