from __future__ import annotations

from pathlib import Path

from method_hub.specification import SpecificationPackage


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def test_specification_package_loads_complete_contract_kernel() -> None:
    package = SpecificationPackage.load(ARCHITECTURE)
    assert package.architecture_root == ARCHITECTURE.resolve()
    assert len(package.schemas) == 37
    assert len(package.digests) == 37
    assert len(package.phases) == 5
    assert len(package.phases.mode_ids) == 8


def test_specification_package_resolves_without_prose_inference() -> None:
    package = SpecificationPackage.load(ARCHITECTURE)
    identity = package.phases.identity("P2")
    plan = package.resolve_phase(
        identity,
        "p2.full_catalog",
        {"p2.instructions": "Develop the current method catalog."},
        "current_only",
    )
    assert plan.identity == identity
    assert plan.mode_id == "p2.full_catalog"
    assert plan.stage_ids == (
        "p2.independent_proposals",
        "p2.cross_review",
        "p2.lead_reconciliation",
    )
    assert tuple(binding["binding_id"] for binding in plan.publication_bindings) == (
        "p2.append_attention_items",
        "p2.upsert_method_records",
        "p2.rebuild_method_catalog",
        "p2.replace_phase_decision",
    )
