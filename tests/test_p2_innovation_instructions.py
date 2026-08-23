"""Regression tests for bounded innovation in Phase 2 full-catalog runs."""
from __future__ import annotations

from model_forge.application.default_instructions import (
    load_mode_instruction,
    load_stage_instruction,
)


_BRIEF = {
    "research_question": "Does X improve Y?",
    "scope": "Simulation study",
    "constraints": ["time budget 10h"],
    "decision_criteria": ["convergence", "bias"],
}


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def test_p2_full_catalog_encourages_bounded_complementary_innovation() -> None:
    mode_text = _normalized(load_mode_instruction("p2.full_catalog", _BRIEF))
    assert "mechanism-level alternatives" in mode_text
    assert "complementary scientific, mathematical, and" in mode_text
    assert "validity, relevance, and feasibility take priority" in mode_text
    assert "no genuinely useful new option" in mode_text

    proposals = {
        role: _normalized(
            load_stage_instruction(
                "p2.full_catalog",
                _BRIEF,
                role=role,
                stage_id="p2.independent_proposals",
            )
        )
        for role in ("theorist", "data_analyst")
    }
    assert "mathematical mechanism" in proposals["theorist"]
    assert "empirical or computational mechanism" in proposals["data_analyst"]
    for text in proposals.values():
        assert "closest formal phase 1 work" in text
        assert "no-new-option conclusion" in text

    reconciliation = _normalized(
        load_stage_instruction(
            "p2.full_catalog",
            _BRIEF,
            role="research_lead",
            stage_id="p2.lead_reconciliation",
        )
    )
    assert "balanced portfolio" in reconciliation
    assert "high-risk, high-value" in reconciliation
    assert "do not retain a weak" in reconciliation
    assert "no genuinely useful new option" in reconciliation

    for mode in ("p2.focused_method", "p2.researcher_proposal"):
        mode_text = _normalized(load_mode_instruction(mode, _BRIEF))
        assert "balanced portfolio" not in mode_text
