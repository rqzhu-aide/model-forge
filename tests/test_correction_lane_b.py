"""K-1c Lane B: blast-radius verification + correction instruction (P5a-i).

Unit coverage for ``verify_correction_blast_radius`` (design 4a: a
correction is a patch with a verified blast radius) and the
``permitted_pointers`` extension of ``build_correction_instruction``.
Lane B integration tests land with the execution core (P5a-ii).
"""

from __future__ import annotations

from method_hub.application.correction import build_correction_instruction
from method_hub.application.correction_execution import (
    verify_correction_blast_radius,
)
from method_hub.domain.validation import make_finding


def _verify(source, corrected, correction_type, pointers, scope):
    return verify_correction_blast_radius(
        source_outputs=source,
        corrected_outputs=corrected,
        correction_type=correction_type,
        permitted_pointers=frozenset(pointers),
        output_scope=frozenset(scope),
    )


# --------------------------------------------------------------------------- #
# verify_correction_blast_radius
# --------------------------------------------------------------------------- #


def test_identical_outputs_are_clean() -> None:
    doc = {"a": 1, "b": [1, 2]}
    assert _verify({"out": doc}, {"out": doc}, "packaging", set(), {"out"}) == ()


def test_packaging_change_at_permitted_pointer_is_clean() -> None:
    source = {"out": {"created_at": None, "title": "x"}}
    corrected = {"out": {"created_at": "2026-08-19", "title": "x"}}
    assert _verify(
        source, corrected, "packaging", {"/created_at"}, {"out"}
    ) == ()


def test_packaging_change_below_permitted_pointer_is_clean() -> None:
    source = {"out": {"meta": {"created_at": None}}}
    corrected = {"out": {"meta": {"created_at": "2026-08-19"}}}
    assert _verify(source, corrected, "packaging", {"/meta"}, {"out"}) == ()


def test_packaging_change_outside_permitted_pointer_violates() -> None:
    source = {"out": {"created_at": None, "title": "x"}}
    corrected = {"out": {"created_at": "2026-08-19", "title": "CHANGED"}}
    violations = _verify(source, corrected, "packaging", {"/created_at"}, {"out"})
    assert len(violations) == 1
    assert violations[0].code == "correction.blast_radius_violated"
    assert violations[0].json_pointer == "/title"
    assert violations[0].blocks_publication is True


def test_scientific_in_scope_change_is_clean() -> None:
    source = {"out": {"claim": "weak"}}
    corrected = {"out": {"claim": "strong", "extra": [1]}}
    assert _verify(source, corrected, "scientific", set(), {"out"}) == ()


def test_out_of_scope_change_violates_for_both_types() -> None:
    source = {"scoped": {"a": 1}, "other": {"b": 2}}
    corrected = {"scoped": {"a": 9}, "other": {"b": 3}}
    for correction_type in ("packaging", "scientific"):
        violations = _verify(
            source, corrected, correction_type, {"/a"}, {"scoped"}
        )
        assert len(violations) == 1
        assert violations[0].code == "correction.blast_radius_violated"
        assert "out-of-scope" in violations[0].message


def test_array_index_paths() -> None:
    source = {"out": {"items": [1, 2, 3]}}
    corrected = {"out": {"items": [1, 9, 3]}}
    violations = _verify(source, corrected, "packaging", {"/items/0"}, {"out"})
    assert len(violations) == 1
    assert violations[0].json_pointer == "/items/1"
    assert _verify(source, corrected, "packaging", {"/items"}, {"out"}) == ()


# --------------------------------------------------------------------------- #
# build_correction_instruction permitted_pointers
# --------------------------------------------------------------------------- #


def _findings():
    return (
        make_finding("schema.required", "'created_at' is required", pointer=""),
    )


def test_packaging_instruction_lists_sorted_pointers() -> None:
    text = build_correction_instruction(
        correction_type="packaging",
        findings=_findings(),
        output_scope=("p1.theory",),
        permitted_pointers=("/created_at", "/meta"),
    )
    assert "change ONLY these" in text
    assert "  - /created_at" in text
    assert "  - /meta" in text
    assert text.index("/created_at") < text.index("/meta")  # sorted order


def test_scientific_instruction_ignores_pointers() -> None:
    text = build_correction_instruction(
        correction_type="scientific",
        findings=_findings(),
        output_scope=("p1.theory",),
        user_instruction="Downgrade the claim.",
        permitted_pointers=("/created_at",),
    )
    assert "change ONLY these" not in text
    assert "Downgrade the claim." in text
