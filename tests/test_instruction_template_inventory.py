"""Regression test: all stage+role instruction templates exist and render.

Guards against accidental deletion or renaming of the stage+role-specific
instruction template files under ``resources/instructions/``.
"""
from __future__ import annotations

import pytest

from method_hub.application.default_instructions import (
    load_instruction,
    stage_template_exists,
)


# Minimal brief payload for rendering.
_BRIEF = {
    "research_question": "Does X improve Y?",
    "scope": "Simulation study",
    "constraints": ["time budget 10h"],
    "decision_criteria": ["convergence", "bias"],
}

# ---------------------------------------------------------------------------
# Expected stage+role template inventory.
# Each tuple: (mode, stage_id, role)
# ---------------------------------------------------------------------------
_EXPECTED_STAGE_ROLE_TEMPLATES: list[tuple[str, str, str]] = [
    # P1 - Literature
    ("p1.literature_update", "p1.discovery", "theorist"),
    ("p1.literature_update", "p1.discovery", "data_analyst"),
    ("p1.literature_update", "p1.discovery", "research_lead"),
    ("p1.literature_update", "p1.lead_synthesis", "research_lead"),
    # P2 - Methods (mode-agnostic; used by both full_catalog and focused_method)
    ("p2.full_catalog", "p2.independent_proposals", "theorist"),
    ("p2.full_catalog", "p2.independent_proposals", "data_analyst"),
    ("p2.full_catalog", "p2.independent_proposals", "research_lead"),
    ("p2.full_catalog", "p2.cross_review", "theorist"),
    ("p2.full_catalog", "p2.cross_review", "data_analyst"),
    ("p2.full_catalog", "p2.lead_reconciliation", "research_lead"),
    # P3 - Theory
    ("p3.theory_establishment", "p3.theorist", "theorist"),
    ("p3.theory_establishment", "p3.analyst", "data_analyst"),
    ("p3.theory_establishment", "p3.lead", "research_lead"),
    # P4 - Evidence
    ("p4.preliminary", "p4.analyst", "data_analyst"),
    ("p4.preliminary", "p4.theorist", "theorist"),
    ("p4.preliminary", "p4.lead", "research_lead"),
    # P5 - Manuscript
    ("p5.assembly", "p5.assembly_lead", "research_lead"),
    ("p5.review_revision", "p5.parallel_reviews", "theorist"),
    ("p5.review_revision", "p5.parallel_reviews", "data_analyst"),
    ("p5.review_revision", "p5.parallel_reviews", "outside_reviewer"),
    ("p5.review_revision", "p5.revision_lead", "research_lead"),
]


@pytest.mark.parametrize(
    ("mode", "stage_id", "role"),
    _EXPECTED_STAGE_ROLE_TEMPLATES,
    ids=[f"{s}.{r}" for _, s, r in _EXPECTED_STAGE_ROLE_TEMPLATES],
)
def test_stage_role_template_exists(mode: str, stage_id: str, role: str) -> None:
    """Every expected stage+role template file must exist on disk."""
    assert stage_template_exists(mode, role, stage_id), (
        f"Missing stage+role template for mode={mode!r} "
        f"stage={stage_id!r} role={role!r}"
    )


@pytest.mark.parametrize(
    ("mode", "stage_id", "role"),
    _EXPECTED_STAGE_ROLE_TEMPLATES,
    ids=[f"{s}.{r}" for _, s, r in _EXPECTED_STAGE_ROLE_TEMPLATES],
)
def test_stage_role_template_renders(mode: str, stage_id: str, role: str) -> None:
    """Every stage+role template must render without StrictUndefined errors."""
    text = load_instruction(mode, _BRIEF, role=role, stage_id=stage_id)
    assert "research_question" not in text or "Does X improve Y?" in text
    assert len(text) > 50  # sanity: not empty or trivially short
