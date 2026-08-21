"""Regression test: all stage+role instruction templates exist and render.

Guards against accidental deletion or renaming of the stage+role-specific
instruction template files under ``resources/instructions/``.
"""
from __future__ import annotations

import pytest

from method_hub.application.default_instructions import (
    load_instruction,
    load_mode_instruction,
    load_stage_instruction,
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
    # P2 - Methods (each template branches on the frozen mode)
    *[
        (mode, stage_id, role)
        for mode in (
            "p2.full_catalog",
            "p2.focused_method",
            "p2.researcher_proposal",
        )
        for stage_id, role in (
            ("p2.independent_proposals", "theorist"),
            ("p2.independent_proposals", "data_analyst"),
            ("p2.cross_review", "theorist"),
            ("p2.cross_review", "data_analyst"),
            ("p2.lead_reconciliation", "research_lead"),
        )
    ],
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


_P2_STAGE_ROLES = (
    ("p2.independent_proposals", "theorist"),
    ("p2.independent_proposals", "data_analyst"),
    ("p2.cross_review", "theorist"),
    ("p2.cross_review", "data_analyst"),
    ("p2.lead_reconciliation", "research_lead"),
)


@pytest.mark.parametrize((
    "stage_id", "role"
), _P2_STAGE_ROLES)
def test_p2_stage_role_directives_are_distinct_by_mode(
    stage_id: str, role: str
) -> None:
    rendered = {
        mode: load_stage_instruction(
            mode, _BRIEF, role=role, stage_id=stage_id
        )
        for mode in (
            "p2.full_catalog",
            "p2.focused_method",
            "p2.researcher_proposal",
        )
    }
    assert len(set(rendered.values())) == 3
    assert "full" in rendered["p2.full_catalog"].lower()
    assert "selected stable method" in rendered["p2.focused_method"].lower()
    assert "researcher" in rendered["p2.researcher_proposal"].lower()


def test_p2_mode_directives_are_distinct_and_domain_general() -> None:
    rendered = {
        mode: load_mode_instruction(mode, _BRIEF)
        for mode in (
            "p2.full_catalog",
            "p2.focused_method",
            "p2.researcher_proposal",
        )
    }
    assert len(set(rendered.values())) == 3
    researcher = rendered["p2.researcher_proposal"].lower()
    assert "method class" in researcher
    assert "invariant measure" not in researcher
    assert "ergodic" not in researcher
    assert "per-sweep" not in researcher
    focused = rendered["p2.focused_method"].lower()
    assert "editorial change" in focused
    assert "mathematical change" in focused
    assert "advance the version by" in focused


_NONCONFLICTING_MODE_ROLE_CASES = (
    *[
        (mode, stage_id, role, expected_output)
        for mode in ("p3.theory_establishment", "p3.theory_revision")
        for stage_id, role, expected_output in (
            ("p3.theorist", "theorist", "p3.theory_candidate"),
            ("p3.analyst", "data_analyst", "p3.analyst_audit"),
            ("p3.lead", "research_lead", "p3.complete_theory"),
        )
    ],
    *[
        (mode, stage_id, role, expected_output)
        for mode in ("p4.preliminary", "p4.comprehensive")
        for stage_id, role, expected_output in (
            ("p4.analyst", "data_analyst", "p4.protocol"),
            ("p4.theorist", "theorist", "p4.theory_audit"),
            ("p4.lead", "research_lead", "p4.empirical_index_candidate"),
        )
    ],
    *[
        ("p5.review_revision", stage_id, role, expected_output)
        for stage_id, role, expected_output in (
            ("p5.parallel_reviews", "theorist", "p5.theory_audit"),
            ("p5.parallel_reviews", "data_analyst", "p5.empirical_audit"),
            ("p5.parallel_reviews", "outside_reviewer", "p5.outside_review"),
            ("p5.revision_lead", "research_lead", "p5.review_issues"),
        )
    ],
)

_STAGE_OUTPUT_IDS = {
    "p3": (
        "p3.theory_candidate",
        "p3.analyst_audit",
        "p3.complete_theory",
    ),
    "p4": (
        "p4.protocol",
        "p4.evidence",
        "p4.theory_audit",
        "p4.empirical_index_candidate",
    ),
    "p5": (
        "p5.theory_audit",
        "p5.empirical_audit",
        "p5.outside_review",
        "p5.review_issues",
        "p5.manuscript_candidate",
    ),
}


@pytest.mark.parametrize(
    ("mode", "stage_id", "role", "expected_output"),
    _NONCONFLICTING_MODE_ROLE_CASES,
)
def test_mode_directive_leaves_production_to_stage_role_assignment(
    mode: str,
    stage_id: str,
    role: str,
    expected_output: str,
) -> None:
    mode_text = load_mode_instruction(mode, _BRIEF, role=role)
    stage_text = load_stage_instruction(
        mode, _BRIEF, role=role, stage_id=stage_id
    )

    normalized_mode = " ".join(mode_text.lower().split())
    assert "stage-role assignment" in normalized_mode
    assert mode_text == load_mode_instruction(mode, _BRIEF)
    assert expected_output in stage_text
    phase = mode.split(".", 1)[0]
    for output_id in _STAGE_OUTPUT_IDS[phase]:
        assert output_id not in mode_text
