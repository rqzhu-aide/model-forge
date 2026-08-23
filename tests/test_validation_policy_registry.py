"""Tests for the HV-2 validation policy registry.

Tests exercise:
1. Registry completeness — every _finding(...) literal is registered
2. Per-class policy behavior (6 classes)
3. Fail-closed default for unregistered codes
4. passed() uses blocks_publication, not severity
5. make_finding applies registry policy
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from model_forge.domain.validation import (
    FindingClass,
    FindingPolicy,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    all_registered_codes,
    get_policy,
    make_finding,
    registry_version,
)


# --------------------------------------------------------------------------- #
# HV-2.1: Registry completeness                                               #
# --------------------------------------------------------------------------- #

def _extract_finding_literals(source: str) -> set[str]:
    """Extract finding code string literals from validator source files."""
    codes: set[str] = set()
    # Match _finding("code", ...) and make_finding("code", ...)
    for match in re.finditer(r'(?:_finding|make_finding)\(\s*"([^"]+)"', source):
        code = match.group(1)
        # Skip non-code pN.* constants (mode names, output ids, etc.)
        if code in (
            "p2.focused_method", "p3.theory_revision", "p3.theory_establishment",
            "p5.review_revision", "p5.assembly", "p4.preliminary", "p4.comprehensive",
            "p1.literature_update", "p2.full_catalog", "p2.independent_proposals",
            "p2.researcher_proposal", "p3.complete_theory",
        ):
            continue
        codes.add(code)
    # Also match ValidationFinding(code="...", ...) patterns
    for match in re.finditer(r'ValidationFinding\(\s*code="([^"]+)"', source):
        codes.add(match.group(1))
    # Match code="..." in kwargs
    for match in re.finditer(r'code="([^"]+)"', source):
        code = match.group(1)
        if not code.startswith("__"):
            codes.add(code)
    return codes


def test_registry_covers_all_scientific_validator_codes() -> None:
    """Every finding code literal in scientific_validators.py must be registered."""
    source = Path("src/model_forge/harness/scientific_validators.py").read_text()
    literals = _extract_finding_literals(source)
    # Remove known non-code constants
    literals.discard("p3.complete_theory")
    literals.discard("p3.theory_revision")
    registered = all_registered_codes()
    unregistered = literals - registered
    # Dynamic codes (schema.*, json.*) are handled by default fail-closed.
    unregistered = {c for c in unregistered if not c.startswith("schema.") and not c.startswith("json.") and not c.startswith("p2.{")}
    assert not unregistered, f"Unregistered codes: {sorted(unregistered)}"


def test_registry_covers_all_submission_validator_codes() -> None:
    """Every finding code literal in submission_validation.py must be registered."""
    source = Path("src/model_forge/harness/submission_validation.py").read_text()
    literals = _extract_finding_literals(source)
    registered = all_registered_codes()
    unregistered = literals - registered
    unregistered = {c for c in unregistered if not c.startswith("schema.") and not c.startswith("json.")}
    assert not unregistered, f"Unregistered codes: {sorted(unregistered)}"


def test_registry_covers_all_output_codes() -> None:
    """Every finding code literal in outputs.py must be registered."""
    source = Path("src/model_forge/harness/outputs.py").read_text()
    literals = _extract_finding_literals(source)
    registered = all_registered_codes()
    unregistered = literals - registered
    unregistered = {c for c in unregistered if not c.startswith("schema.") and not c.startswith("json.")}
    assert not unregistered, f"Unregistered codes: {sorted(unregistered)}"


def test_registry_covers_all_input_codes() -> None:
    """Every finding code literal in inputs.py must be registered."""
    source = Path("src/model_forge/harness/inputs.py").read_text()
    literals = _extract_finding_literals(source)
    registered = all_registered_codes()
    unregistered = literals - registered
    unregistered = {c for c in unregistered if not c.startswith("schema.") and not c.startswith("json.")}
    assert not unregistered, f"Unregistered codes: {sorted(unregistered)}"


# --------------------------------------------------------------------------- #
# HV-2.2: Fail-closed default for unregistered codes                          #
# --------------------------------------------------------------------------- #

def test_unregistered_code_defaults_to_blocking() -> None:
    """Unknown codes must receive the fail-closed default."""
    policy = get_policy("totally.unknown.code")
    assert policy.blocks_publication is True
    assert policy.default_severity is ValidationSeverity.ERROR
    assert policy.finding_class is FindingClass.INTEGRITY_BLOCKER


def test_make_finding_for_unregistered_code_blocks() -> None:
    """make_finding for unknown code should produce a blocking finding."""
    f = make_finding("unknown.typo.code", "test message", "obj")
    assert f.blocks_publication is True
    assert f.severity is ValidationSeverity.ERROR


# --------------------------------------------------------------------------- #
# HV-2.3: Per-class policy behavior                                           #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("code", "expected_class"),
    [
        # Integrity blocker
        ("submission.digest_mismatch", FindingClass.INTEGRITY_BLOCKER),
        ("submission.project_mismatch", FindingClass.INTEGRITY_BLOCKER),
        ("output.unsafe_path", FindingClass.INTEGRITY_BLOCKER),
        # Correctable contract error
        ("submission.required_output_missing", FindingClass.CORRECTABLE_CONTRACT_ERROR),
        ("output.required_missing", FindingClass.CORRECTABLE_CONTRACT_ERROR),
        ("json.duplicate_key", FindingClass.CORRECTABLE_CONTRACT_ERROR),
        # Scientific claim blocker
        ("p5.claim_without_evidence", FindingClass.SCIENTIFIC_CLAIM_BLOCKER),
        ("p3.established_statement_unsupported", FindingClass.SCIENTIFIC_CLAIM_BLOCKER),
        ("p2.canonical_definition_empty", FindingClass.SCIENTIFIC_CLAIM_BLOCKER),
    ],
)
def test_finding_codes_have_correct_class(
    code: str, expected_class: FindingClass
) -> None:
    """Each registered code must map to its correct FindingClass."""
    policy = get_policy(code)
    assert policy.finding_class is expected_class, (
        f"{code}: expected {expected_class}, got {policy.finding_class}"
    )


def test_integrity_blockers_all_block_and_error() -> None:
    """Integrity blockers must be ERROR severity and block publication."""
    codes = [
        "submission.digest_mismatch",
        "submission.project_mismatch",
        "output.unsafe_path",
        "p2.mathematical_digest_unchanged",
    ]
    for code in codes:
        policy = get_policy(code)
        assert policy.blocks_publication is True, f"{code} should block"
        assert policy.default_severity is ValidationSeverity.ERROR, f"{code} should be ERROR"


def test_correctable_errors_allow_deterministic_repair() -> None:
    """Correctable contract errors should allow deterministic repair."""
    codes = [
        "submission.required_output_missing",
        "output.required_missing",
    ]
    for code in codes:
        policy = get_policy(code)
        assert policy.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR
        assert policy.blocks_publication is True  # still blocks until corrected
        assert policy.deterministic_repair_allowed is True


def test_scientific_claim_blockers_block() -> None:
    """Scientific claim blockers must block publication."""
    codes = [
        "p5.claim_without_evidence",
        "p3.established_statement_unsupported",
        "p4.simulation_seed_missing",
    ]
    for code in codes:
        policy = get_policy(code)
        assert policy.blocks_publication is True
        assert policy.default_severity is ValidationSeverity.ERROR
        assert policy.finding_class is FindingClass.SCIENTIFIC_CLAIM_BLOCKER


# --------------------------------------------------------------------------- #
# HV-2.4: passed() uses blocks_publication, not severity                      #
# --------------------------------------------------------------------------- #

def test_passed_true_when_no_blocking_findings() -> None:
    """Report with only non-blocking findings should pass."""
    non_blocking = ValidationFinding(
        code="test.info",
        message="advisory",
        severity=ValidationSeverity.WARNING,
        blocks_publication=False,
        finding_class=FindingClass.SCIENTIFIC_ATTENTION,
    )
    report = ValidationReport.from_findings("r1", "run1", "test", [non_blocking])
    assert report.passed is True


def test_passed_false_when_any_blocking_finding() -> None:
    """Report with any blocking finding should not pass."""
    blocking = make_finding("submission.digest_mismatch", "mismatch", "obj")
    non_blocking = ValidationFinding(
        code="test.info",
        message="advisory",
        severity=ValidationSeverity.WARNING,
        blocks_publication=False,
        finding_class=FindingClass.SCIENTIFIC_ATTENTION,
    )
    report = ValidationReport.from_findings("r1", "run1", "test", [blocking, non_blocking])
    assert report.passed is False


def test_passed_false_with_blocking_warning() -> None:
    """A WARNING that blocks should still fail the report."""
    blocking_warning = ValidationFinding(
        code="test.warn_block",
        message="blocks despite being a warning",
        severity=ValidationSeverity.WARNING,
        blocks_publication=True,
        finding_class=FindingClass.INTEGRITY_BLOCKER,
    )
    report = ValidationReport.from_findings("r1", "run1", "test", [blocking_warning])
    assert report.passed is False


# --------------------------------------------------------------------------- #
# HV-2.6: Policy versioning                                                    #
# --------------------------------------------------------------------------- #

def test_policy_version_is_string() -> None:
    """The registry must expose a version string."""
    version = registry_version()
    assert isinstance(version, str)
    assert len(version) > 0


# --------------------------------------------------------------------------- #
# HV-2: make_finding applies registry policy                                  #
# --------------------------------------------------------------------------- #

def test_make_finding_sets_all_policy_fields() -> None:
    """make_finding must populate finding_class, blocks_publication, correction_class."""
    f = make_finding("submission.required_output_missing", "test", "obj", "/path")
    assert f.code == "submission.required_output_missing"
    assert f.severity is ValidationSeverity.ERROR
    assert f.blocks_publication is True
    assert f.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR
    assert f.correction_class == "packaging"
    assert f.json_pointer == "/path"
    assert f.object_id == "obj"


def test_finding_to_dict_includes_policy_fields() -> None:
    """ValidationFinding.to_dict() must include finding_class and blocks_publication."""
    f = make_finding("p5.claim_without_evidence", "no evidence", "claim.1")
    d = f.to_dict()
    assert "finding_class" in d
    assert d["finding_class"] == "scientific_claim_blocker"
    assert "blocks_publication" in d
    assert d["blocks_publication"] is True
    assert "correction_class" in d


# --------------------------------------------------------------------------- #
# Registry counts                                                              #
# --------------------------------------------------------------------------- #

def test_registry_has_substantial_coverage() -> None:
    """The registry should have at least 100 registered codes."""
    codes = all_registered_codes()
    assert len(codes) >= 100, f"Only {len(codes)} codes registered; expected >=100"


def test_registry_has_all_three_blocking_classes() -> None:
    """The registry must have codes in all 3 blocking classes."""
    classes_found: set[FindingClass] = set()
    for code in all_registered_codes():
        policy = get_policy(code)
        classes_found.add(policy.finding_class)
    assert FindingClass.INTEGRITY_BLOCKER in classes_found
    assert FindingClass.CORRECTABLE_CONTRACT_ERROR in classes_found
    assert FindingClass.SCIENTIFIC_CLAIM_BLOCKER in classes_found
