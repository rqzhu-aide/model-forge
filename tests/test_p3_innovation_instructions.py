"""Guard the scientific creativity and method-identity boundary in Phase 3."""
from __future__ import annotations

import pytest

from method_hub.application.default_instructions import (
    load_mode_instruction,
    load_stage_instruction,
)


_BRIEF = {
    "research_question": "When does the selected estimator improve risk?",
    "scope": "Finite-sample and asymptotic theory",
    "constraints": [],
    "decision_criteria": ["correctness", "scientific contribution"],
}


@pytest.mark.parametrize(
    "mode",
    ("p3.theory_establishment", "p3.theory_revision"),
)
def test_p3_modes_encourage_innovation_with_rigorous_status(mode: str) -> None:
    text = " ".join(load_mode_instruction(mode, _BRIEF).lower().split())
    for concept in (
        "conceptual connection", "alternative proof", "lower bound",
        "impossibility", "failure regime", "conjecture", "falsifier",
        "proof obligation",
    ):
        assert concept in text
    assert any(term in text for term in ("established", "formal support"))


@pytest.mark.parametrize(
    ("stage_id", "role"),
    (
        ("p3.theorist", "theorist"),
        ("p3.analyst", "data_analyst"),
        ("p3.lead", "research_lead"),
    ),
)
def test_p3_roles_preserve_identity_and_user_authority(
    stage_id: str, role: str
) -> None:
    text = load_stage_instruction(
        "p3.theory_establishment", _BRIEF, role=role, stage_id=stage_id
    ).lower()
    assert "calculation-defining" in text
    assert "phase 2" in text
    assert "user" in text


@pytest.mark.parametrize(
    ("stage_id", "role"),
    (
        ("p3.theorist", "theorist"),
        ("p3.analyst", "data_analyst"),
        ("p3.lead", "research_lead"),
    ),
)
def test_p3_roles_keep_conjectures_explicitly_open(
    stage_id: str, role: str
) -> None:
    text = load_stage_instruction(
        "p3.theory_establishment", _BRIEF, role=role, stage_id=stage_id
    )
    text = " ".join(text.lower().split())
    assert "conjecture" in text
    assert "open_question" in text
    assert any(term in text for term in (
        "proof obligation", "open_obligation",
        "proof or derivation obligation",
    ))