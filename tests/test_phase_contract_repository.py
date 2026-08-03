from __future__ import annotations

import copy
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from method_hub.contracts import PhaseContractError, PhaseContractRepository
from method_hub.digests import DigestContractRegistry
from method_hub.domain import PhaseContractIdentity, SemanticVersion, Sha256Digest
from method_hub.schemas import SchemaCatalog


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"
METHOD = {
    "stable_id": "method.kernel.probe",
    "version": 1,
    "definition_sha256": "1" * 64,
}


@pytest.fixture(scope="module")
def schemas() -> SchemaCatalog:
    return SchemaCatalog.load(ARCHITECTURE / "schemas")


@pytest.fixture(scope="module")
def digests(schemas: SchemaCatalog) -> DigestContractRegistry:
    return DigestContractRegistry.load(
        ARCHITECTURE / "contracts" / "digest-contracts.json",
        schemas,
    )


@pytest.fixture(scope="module")
def repository(
    schemas: SchemaCatalog, digests: DigestContractRegistry
) -> PhaseContractRepository:
    return PhaseContractRepository.load(ARCHITECTURE, schemas, digests)


def _choices(phase_id: str, mode_id: str) -> dict:
    if phase_id == "P1":
        return {"p1.scope": "broad_update", "p1.instructions": "Update the basis."}
    if phase_id == "P2" and mode_id == "p2.full_catalog":
        return {"p2.instructions": "Review the method catalog."}
    if phase_id == "P2":
        return {"p2.selected_method": METHOD, "p2.instructions": "Review one method."}
    prefix = phase_id.lower()
    return {
        f"{prefix}.selected_method": METHOD,
        f"{prefix}.instructions": "Run the selected research phase.",
    }


def _copy_contracts(tmp_path: Path) -> Path:
    target = tmp_path / "architecture"
    shutil.copytree(ARCHITECTURE / "contracts", target / "contracts")
    return target


def _mutate_phase_contract(
    root: Path,
    phase_id: str,
    mutation: Callable[[dict], None],
) -> None:
    aggregate_path = root / "contracts" / "phases.json"
    aggregate = json.loads(aggregate_path.read_text("utf-8"))
    contract = next(
        item for item in aggregate["contracts"] if item["phase_id"] == phase_id
    )
    mutation(contract)
    serialized = json.dumps(aggregate, indent=2)
    aggregate_path.write_text(serialized, encoding="utf-8")
    split_path = root / "contracts" / "phases" / f"{phase_id}.json"
    split_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")


def test_repository_indexes_five_phases_and_eight_modes(
    repository: PhaseContractRepository,
) -> None:
    assert len(repository) == 5
    assert repository.phase_ids == ("P1", "P2", "P3", "P4", "P5")
    assert repository.mode_ids == (
        "p1.literature_update",
        "p2.focused_method",
        "p2.full_catalog",
        "p3.theory_update",
        "p4.comprehensive",
        "p4.preliminary",
        "p5.assembly",
        "p5.review_revision",
    )


@pytest.mark.parametrize(
    ("phase_id", "mode_id", "stage_ids"),
    [
        ("P1", "p1.literature_update", ("p1.discovery", "p1.lead_synthesis")),
        (
            "P2",
            "p2.full_catalog",
            ("p2.independent_proposals", "p2.cross_review", "p2.lead_reconciliation"),
        ),
        (
            "P2",
            "p2.focused_method",
            ("p2.independent_proposals", "p2.cross_review", "p2.lead_reconciliation"),
        ),
        (
            "P3",
            "p3.theory_update",
            ("p3.theorist", "p3.analyst", "p3.lead"),
        ),
        (
            "P4",
            "p4.preliminary",
            ("p4.analyst", "p4.theorist", "p4.lead"),
        ),
        (
            "P4",
            "p4.comprehensive",
            ("p4.analyst", "p4.theorist", "p4.lead"),
        ),
        ("P5", "p5.assembly", ("p5.assembly_lead",)),
        (
            "P5",
            "p5.review_revision",
            ("p5.parallel_reviews", "p5.revision_lead"),
        ),
    ],
)
def test_all_eight_modes_resolve_exact_stage_plans(
    repository: PhaseContractRepository,
    phase_id: str,
    mode_id: str,
    stage_ids: tuple[str, ...],
) -> None:
    plan = repository.resolve(
        repository.identity(phase_id),
        mode_id,
        _choices(phase_id, mode_id),
        "current_only",
    )
    assert plan.stage_ids == stage_ids
    assert all(stage.sequence == offset for offset, stage in enumerate(plan.stages, 1))
    assert plan.output_contracts
    assert plan.validation_rules
    assert plan.publication_bindings


def test_p4_digest_matches_command_and_manifest_examples(
    repository: PhaseContractRepository,
) -> None:
    identity = repository.identity("P4")
    command = json.loads(
        (ARCHITECTURE / "examples" / "run-command.example.json").read_text("utf-8")
    )
    manifest = json.loads(
        (ARCHITECTURE / "examples" / "run-manifest.example.json").read_text("utf-8")
    )
    assert identity.contract_version.value == command["phase_contract_version"]
    assert identity.phase_contract_sha256.value == command["phase_contract_sha256"]
    assert identity.phase_contract_sha256.value == manifest["phase_contract_sha256"]


def test_role_specific_reads_and_outputs_are_explicit(
    repository: PhaseContractRepository,
) -> None:
    plan = repository.resolve(
        repository.identity("P5"),
        "p5.review_revision",
        _choices("P5", "p5.review_revision"),
        "current_only",
    )
    review = plan.stages[0]
    assert review.step_for("outside_reviewer").input_ids == ("p5.review_packet",)
    assert review.step_for("outside_reviewer").output_ids == ("p5.outside_review",)
    assert review.step_for("theorist").input_ids != review.step_for(
        "data_analyst"
    ).input_ids


def test_p5_review_packet_is_mode_scoped(
    repository: PhaseContractRepository,
) -> None:
    assembly = repository.resolve(
        repository.identity("P5"),
        "p5.assembly",
        _choices("P5", "p5.assembly"),
        "current_only",
    )
    review = repository.resolve(
        repository.identity("P5"),
        "p5.review_revision",
        _choices("P5", "p5.review_revision"),
        "current_only",
    )
    assert assembly.prepared_contexts == ()
    assert tuple(item["context_id"] for item in review.prepared_contexts) == (
        "p5.review_packet",
    )


def test_focused_p2_requires_exact_selected_method(
    repository: PhaseContractRepository,
) -> None:
    with pytest.raises(PhaseContractError) as captured:
        repository.resolve(
            repository.identity("P2"),
            "p2.focused_method",
            {"p2.instructions": "Review one method."},
            "current_only",
        )
    assert captured.value.code == "phase_contract.missing_choice"

    with pytest.raises(PhaseContractError) as captured:
        repository.resolve(
            repository.identity("P2"),
            "p2.focused_method",
            {
                "p2.selected_method": {**METHOD, "version": True},
                "p2.instructions": "Review one method.",
            },
            "current_only",
        )
    assert captured.value.code == "phase_contract.invalid_choice_value"


@pytest.mark.parametrize(
    ("choices", "code"),
    [
        (
            {"p1.scope": "unsupported", "p1.instructions": "Search."},
            "phase_contract.invalid_choice_value",
        ),
        (
            {"p1.scope": "broad_update", "p1.instructions": "   "},
            "phase_contract.invalid_choice_value",
        ),
        (
            {
                "p1.scope": "broad_update",
                "p1.instructions": "Search.",
                "p1.unknown": True,
            },
            "phase_contract.unknown_choice",
        ),
    ],
)
def test_invalid_choice_values_fail_closed(
    repository: PhaseContractRepository,
    choices: dict,
    code: str,
) -> None:
    with pytest.raises(PhaseContractError) as captured:
        repository.resolve(
            repository.identity("P1"),
            "p1.literature_update",
            choices,
            "current_only",
        )
    assert captured.value.code == code


def test_selected_history_agrees_with_context_policy(
    repository: PhaseContractRepository,
) -> None:
    history = {
        "artifact_id": "artifact.history.one",
        "uri": "artifact://history/one",
        "sha256": "2" * 64,
    }
    base = _choices("P3", "p3.theory_update")
    with_history = {**base, "p3.selected_history": [history]}
    plan = repository.resolve(
        repository.identity("P3"),
        "p3.theory_update",
        with_history,
        "current_plus_selected_history",
    )
    assert plan.choice_values["p3.selected_history"][0]["artifact_id"] == history[
        "artifact_id"
    ]
    with pytest.raises(PhaseContractError) as captured:
        repository.resolve(
            repository.identity("P3"),
            "p3.theory_update",
            with_history,
            "current_only",
        )
    assert captured.value.code == "phase_contract.history_forbidden"
    with pytest.raises(PhaseContractError) as captured:
        repository.resolve(
            repository.identity("P3"),
            "p3.theory_update",
            base,
            "current_plus_selected_history",
        )
    assert captured.value.code == "phase_contract.history_required"


def test_identity_version_digest_and_mode_must_match_exactly(
    repository: PhaseContractRepository,
) -> None:
    expected = repository.identity("P4")
    cases = [
        (
            PhaseContractIdentity(
                "P4", SemanticVersion("3.0.0"), expected.phase_contract_sha256
            ),
            "p4.preliminary",
            "phase_contract.version_mismatch",
        ),
        (
            PhaseContractIdentity(
                "P4", expected.contract_version, Sha256Digest("f" * 64)
            ),
            "p4.preliminary",
            "phase_contract.digest_mismatch",
        ),
        (expected, "p4.unknown", "phase_contract.mode_not_found"),
    ]
    for identity, mode, code in cases:
        with pytest.raises(PhaseContractError) as captured:
            repository.resolve(
                identity,
                mode,
                _choices("P4", "p4.preliminary"),
                "current_only",
            )
        assert captured.value.code == code


def test_resolved_plan_is_deeply_immutable(
    repository: PhaseContractRepository,
) -> None:
    plan = repository.resolve(
        repository.identity("P4"),
        "p4.preliminary",
        _choices("P4", "p4.preliminary"),
        "current_only",
    )
    with pytest.raises(TypeError):
        plan.choice_values["p4.instructions"] = "Changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        plan.publication_bindings[0]["operation"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        plan.validation_rules[0]["severity"] = "advisory"  # type: ignore[index]


def test_history_choice_must_be_an_optional_artifact_pointer_list(
    tmp_path: Path,
    schemas: SchemaCatalog,
    digests: DigestContractRegistry,
) -> None:
    root = _copy_contracts(tmp_path)

    def mutation(contract: dict) -> None:
        contract["optional_context_policy"]["history_choice_id"] = "p3.instructions"

    _mutate_phase_contract(root, "P3", mutation)
    with pytest.raises(PhaseContractError) as captured:
        PhaseContractRepository.load(root, schemas, digests)
    assert captured.value.code == "phase_contract.invalid_history_choice"


def test_required_input_modes_must_exist(
    tmp_path: Path,
    schemas: SchemaCatalog,
    digests: DigestContractRegistry,
) -> None:
    root = _copy_contracts(tmp_path)

    def mutation(contract: dict) -> None:
        current_manuscript = next(
            item
            for item in contract["required_inputs"]
            if item["input_id"] == "p5.current_manuscript"
        )
        current_manuscript["required_in_modes"] = ["p5.does_not_exist"]

    _mutate_phase_contract(root, "P5", mutation)
    with pytest.raises(PhaseContractError) as captured:
        PhaseContractRepository.load(root, schemas, digests)
    assert captured.value.code == "phase_contract.invalid_input_mode_scope"


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("unknown", "phase_contract.unknown_blocking_validator"),
        ("advisory", "phase_contract.nonblocking_promotion_validator"),
    ],
)
def test_promotion_blockers_must_resolve_to_blocking_rules(
    tmp_path: Path,
    schemas: SchemaCatalog,
    digests: DigestContractRegistry,
    case: str,
    expected_code: str,
) -> None:
    case_root = tmp_path / case
    case_root.mkdir()
    root = _copy_contracts(case_root)

    def mutation(contract: dict) -> None:
        if case == "unknown":
            contract["promotion"]["blocking_validator_ids"] = [
                "p3.validator.does_not_exist"
            ]
        else:
            blocking_id = contract["promotion"]["blocking_validator_ids"][0]
            rule = next(
                item
                for item in contract["validation_rules"]
                if item["validator_id"] == blocking_id
            )
            rule["severity"] = "advisory"

    _mutate_phase_contract(root, "P3", mutation)
    with pytest.raises(PhaseContractError) as captured:
        PhaseContractRepository.load(root, schemas, digests)
    assert captured.value.code == expected_code


@pytest.mark.parametrize(
    ("case", "phase_id", "expected_code"),
    [
        ("missing_target", "P3", "phase_contract.publication_coverage_mismatch"),
        ("bundle_components", "P5", "phase_contract.invalid_bundle_components"),
        ("duplicate_target", "P3", "phase_contract.duplicate_publication_target"),
        (
            "inapplicable_mode",
            "P5",
            "phase_contract.mode_inapplicable_publication_output",
        ),
    ],
)
def test_invalid_publication_graphs_fail_closed(
    tmp_path: Path,
    schemas: SchemaCatalog,
    digests: DigestContractRegistry,
    case: str,
    phase_id: str,
    expected_code: str,
) -> None:
    case_root = tmp_path / case
    case_root.mkdir()
    root = _copy_contracts(case_root)

    def mutation(contract: dict) -> None:
        bindings = contract["publication_bindings"]
        if case == "missing_target":
            contract["publication_bindings"] = [
                binding
                for binding in bindings
                if binding["binding_id"] != "p3.replace_theory_record"
            ]
        elif case == "bundle_components":
            bundle = next(
                binding
                for binding in bindings
                if binding["binding_id"] == "p5.publish_assembly_manuscript"
            )
            bundle["components"][0]["output_id"] = "p5.decision"
        elif case == "duplicate_target":
            duplicate = copy.deepcopy(
                next(
                    binding
                    for binding in bindings
                    if binding["binding_id"] == "p3.replace_theory_record"
                )
            )
            duplicate["binding_id"] = "p3.replace_theory_record_again"
            bindings.append(duplicate)
        else:
            assembly = next(
                binding
                for binding in bindings
                if binding["binding_id"] == "p5.publish_assembly_manuscript"
            )
            assembly["applicable_modes"].append("p5.review_revision")

    _mutate_phase_contract(root, phase_id, mutation)
    with pytest.raises(PhaseContractError) as captured:
        PhaseContractRepository.load(root, schemas, digests)
    assert captured.value.code == expected_code


def test_shared_and_role_specific_reads_cannot_be_mixed(
    tmp_path: Path,
    schemas: SchemaCatalog,
    digests: DigestContractRegistry,
) -> None:
    root = _copy_contracts(tmp_path)

    def mutation(contract: dict) -> None:
        review = next(
            stage
            for stage in contract["role_stages"]
            if stage["stage_id"] == "p5.parallel_reviews"
        )
        review["reads"] = ["p5.method"]

    _mutate_phase_contract(root, "P5", mutation)
    with pytest.raises(PhaseContractError) as captured:
        PhaseContractRepository.load(root, schemas, digests)
    assert captured.value.code == "phase_contract.mixed_stage_reads"


def test_split_aggregate_mutation_is_rejected(
    tmp_path: Path,
    schemas: SchemaCatalog,
    digests: DigestContractRegistry,
) -> None:
    root = _copy_contracts(tmp_path)
    p4_path = root / "contracts" / "phases" / "P4.json"
    p4 = json.loads(p4_path.read_text("utf-8"))
    p4["name"] = "Mutated Phase 4"
    p4_path.write_text(json.dumps(p4), encoding="utf-8")
    with pytest.raises(PhaseContractError) as captured:
        PhaseContractRepository.load(root, schemas, digests)
    assert captured.value.code == "phase_contract.split_aggregate_mismatch"


def test_duplicate_phase_ids_are_rejected(
    tmp_path: Path,
    schemas: SchemaCatalog,
    digests: DigestContractRegistry,
) -> None:
    root = _copy_contracts(tmp_path)
    aggregate_path = root / "contracts" / "phases.json"
    aggregate = json.loads(aggregate_path.read_text("utf-8"))
    aggregate["contracts"].append(copy.deepcopy(aggregate["contracts"][0]))
    aggregate_path.write_text(json.dumps(aggregate), encoding="utf-8")
    with pytest.raises(PhaseContractError) as captured:
        PhaseContractRepository.load(root, schemas, digests)
    assert captured.value.code == "phase_contract.duplicate_id"
