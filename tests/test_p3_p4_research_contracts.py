from __future__ import annotations

import json
from pathlib import Path

import pytest

from model_forge.application.default_instructions import (
    load_mode_instruction,
    load_stage_instruction,
)
from model_forge.schemas import SchemaCatalog


ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = ROOT / "architecture"
BRIEF = {
    "research_question": "When does the estimator improve risk?",
    "scope": "Theory and simulation",
    "constraints": ["fixed compute budget"],
    "decision_criteria": ["validity", "falsifiability"],
}


def _phase(phase_id: str) -> dict:
    path = ARCHITECTURE / "contracts" / "phases" / f"{phase_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _output(document: dict, output_id: str) -> dict:
    return next(
        item
        for item in document["run_local_outputs"]
        if item["output_id"] == output_id
    )


def test_p3_outputs_use_statement_level_theory_schema() -> None:
    p3 = _phase("P3")
    for output_id in ("p3.theory_candidate", "p3.complete_theory"):
        assert _output(p3, output_id)["schema_uri"].endswith(
            "/theory-record.schema.json"
        )

    schema = json.loads(
        (ARCHITECTURE / "schemas" / "theory-record.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert {
        "primary_artifact",
        "development_mode",
        "assumptions",
        "statements",
        "empirical_implications",
    } <= set(schema["required"])
    assert {
        "statement_id",
        "quantifiers",
        "regime",
        "assumption_ids",
        "status",
        "justification",
        "depends_on_statement_ids",
        "empirical_implication_ids",
    } <= set(schema["$defs"]["theoryStatement"]["required"])


def test_p4_scopes_do_not_encode_a_preliminary_chronology() -> None:
    p4 = _phase("P4")
    comprehensive = next(
        mode
        for mode in p4["run_modes"]
        if mode["mode_id"] == "p4.comprehensive"
    )
    assert "preliminary" not in " ".join(
        comprehensive["entry_conditions"]
    ).lower()
    input_ids = {item["input_id"] for item in p4["required_inputs"]}
    assert "p4.prior_implementation" not in input_ids
    assert "p4.prior_evidence" not in input_ids
    assert _output(p4, "p4.protocol")["schema_uri"].endswith(
        "/empirical-protocol.schema.json"
    )


def test_empirical_protocol_requires_prespecified_decision_fields() -> None:
    schema = json.loads(
        (
            ARCHITECTURE
            / "schemas"
            / "empirical-protocol.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert {
        "claim_tests",
        "estimand",
        "data_or_simulation_unit",
        "baselines",
        "tuning_budget",
        "metrics",
        "repetitions_and_uncertainty",
        "multiplicity",
        "stopping_rules",
        "leakage_checks",
        "decision_thresholds",
        "deviations",
    } <= set(schema["required"])
    catalog = SchemaCatalog.load(ARCHITECTURE / "schemas")
    assert "theory-record.schema.json" in catalog
    assert "empirical-protocol.schema.json" in catalog


def test_p3_mode_instructions_distinguish_establishment_and_revision() -> None:
    establishment = load_mode_instruction("p3.theory_establishment", BRIEF)
    revision = load_mode_instruction("p3.theory_revision", BRIEF)
    assert establishment != revision
    establishment_text = " ".join(establishment.lower().split())
    revision_text = " ".join(revision.lower().split())
    assert "method class" in establishment_text
    assert "properties meaningful for that class" in establishment_text
    assert "weakened" in revision_text
    assert "retracted" in revision_text


def test_p4_mode_instructions_define_scope_independently_of_time() -> None:
    preliminary = load_mode_instruction("p4.preliminary", BRIEF)
    comprehensive = load_mode_instruction("p4.comprehensive", BRIEF)
    assert preliminary != comprehensive
    preliminary_text = " ".join(preliminary.lower().split())
    comprehensive_text = " ".join(comprehensive.lower().split())
    assert "small set of decisive" in preliminary_text
    assert "preliminary describes scientific scope, not chronology" in preliminary_text
    assert "may be the first empirical run" in comprehensive_text
    assert "prior preliminary run is not required" in comprehensive_text


@pytest.mark.parametrize(
    ("mode", "stage_id", "role", "terms"),
    [
        (
            "p3.theory_establishment",
            "p3.theorist",
            "theorist",
            ("establishment", "revision"),
        ),
        (
            "p3.theory_revision",
            "p3.analyst",
            "data_analyst",
            ("establishment", "revision"),
        ),
        (
            "p3.theory_revision",
            "p3.lead",
            "research_lead",
            ("establishment", "revision"),
        ),
        (
            "p4.preliminary",
            "p4.analyst",
            "data_analyst",
            ("preliminary", "comprehensive"),
        ),
        (
            "p4.comprehensive",
            "p4.theorist",
            "theorist",
            ("preliminary", "comprehensive"),
        ),
        (
            "p4.comprehensive",
            "p4.lead",
            "research_lead",
            ("preliminary", "comprehensive"),
        ),
    ],
)
def test_stage_instructions_preserve_scope_branches(
    mode: str, stage_id: str, role: str, terms: tuple[str, str]
) -> None:
    text = load_stage_instruction(mode, BRIEF, role=role, stage_id=stage_id)
    assert all(term in text.lower() for term in terms)
