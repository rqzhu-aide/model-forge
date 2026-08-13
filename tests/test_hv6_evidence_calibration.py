"""HV-6.P4: Evidence calibration tests.

Covers mode-aware reproducibility enforcement (preliminary may omit,
comprehensive must have) and the reclassification of
``p4.evidence_not_exactly_applicable`` to a non-blocking scientific attention
finding so evidence for previous method versions is preserved.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from method_hub.domain import MethodIdentity
from method_hub.domain.validation import (
    FindingClass,
    ValidationFinding,
    ValidationReport,
    ValidationSeverity,
    get_policy,
    make_finding,
)
from method_hub.harness.publication import (
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)
from method_hub.harness.scientific_validators import validate_phase_scientific

METHOD = MethodIdentity(
    stable_id="method.hv6.calibration",
    version=1,
    definition_sha256="a" * 64,
)
PREVIOUS_VERSION = {
    "stable_id": METHOD.stable_id.value,
    "version": 0,
    "definition_sha256": "b" * 64,
}
ARTIFACT = {
    "artifact_id": "artifact.hv6.calibration",
    "uri": "artifact://hv6/primary",
    "sha256": "c" * 64,
}


def _output(output_id: str, document: Any) -> RegisteredValidatedOutput:
    return RegisteredValidatedOutput(
        contract_output_id=output_id,
        document=document,
        artifact=RegisteredArtifactMetadata(
            artifact_id=f"artifact.{output_id.replace('.', '_')}",
            sha256="d" * 64,
            byte_length=1,
            media_type="application/json",
            storage_uri=f"memory://{output_id}",
        ),
    )


def _validate(
    mode_id: str,
    documents: dict[str, Any],
    *,
    selected_method: MethodIdentity | None = METHOD,
) -> list[ValidationFinding]:
    plan = SimpleNamespace(
        identity=SimpleNamespace(phase_id="P4"),
        mode_id=mode_id,
        publication_bindings=(),
    )
    findings: list[ValidationFinding] = []
    validate_phase_scientific(
        plan=plan,  # type: ignore[arg-type]
        outputs={key: _output(key, value) for key, value in documents.items()},
        selected_method=selected_method,
        findings=findings,
    )
    return findings


def _codes(findings: list[ValidationFinding]) -> list[str]:
    return [finding.code for finding in findings]


def _evidence(
    *,
    identity: dict[str, Any] | None = None,
    method_match: str = "exact",
    reproducibility: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "evidence_kind": "simulation",
        "method_identity": deepcopy(identity or METHOD.to_dict()),
        "applicability_at_creation": {"method_match": method_match},
        "reproducibility": (
            None
            if reproducibility is None
            else deepcopy(reproducibility)
        ),
        "scientific_outcome": {"state": "supported"},
        "created_at": "2026-08-11T13:00:00Z",
    }


def _reproducibility(*, empty: bool = False) -> dict[str, Any]:
    values = [] if empty else [ARTIFACT]
    return {
        "code_artifacts": deepcopy(values),
        "data_artifacts": deepcopy(values),
        "configuration_artifacts": deepcopy(values),
        "random_seeds": [] if empty else [7],
        "environment_artifacts": deepcopy(values),
    }


# --------------------------------------------------------------------------- #
# Reclassified code: p4.evidence_not_exactly_applicable
# --------------------------------------------------------------------------- #


def test_previous_version_evidence_is_preserved_not_blocked() -> None:
    """Evidence for a previous method version warns but never blocks."""
    findings = _validate(
        "p4.preliminary",
        {
            "p4.evidence": [
                _evidence(
                    identity=PREVIOUS_VERSION,
                    method_match="older_method_version",
                )
            ],
        },
    )

    applicable = [f for f in findings if f.code == "p4.evidence_not_exactly_applicable"]
    assert len(applicable) == 1
    finding = applicable[0]
    assert finding.blocks_publication is False
    assert finding.finding_class is FindingClass.SCIENTIFIC_ATTENTION
    assert finding.severity is ValidationSeverity.WARNING

    # The evidence item itself is retained: only non-blocking findings result
    # from the applicability assessment when identity is exact.
    exact = _validate(
        "p4.preliminary",
        {
            "p4.evidence": [
                _evidence(method_match="older_method_version"),
            ],
        },
    )
    assert _codes(exact) == ["p4.evidence_not_exactly_applicable"]
    report = ValidationReport.from_findings("r1", "run1", "scientific", exact)
    assert report.passed is True


def test_reclassified_code_has_blocks_publication_false() -> None:
    """The registry classifies the code as non-blocking scientific attention."""
    policy = get_policy("p4.evidence_not_exactly_applicable")
    assert policy.finding_class is FindingClass.SCIENTIFIC_ATTENTION
    assert policy.blocks_publication is False
    assert policy.default_severity is ValidationSeverity.WARNING

    finding = make_finding(
        "p4.evidence_not_exactly_applicable",
        "Evidence is preserved but excluded from current-method synthesis.",
        "p4.evidence",
        "/0/applicability_at_creation/method_match",
    )
    assert finding.blocks_publication is False
    assert finding.finding_class is FindingClass.SCIENTIFIC_ATTENTION


# --------------------------------------------------------------------------- #
# Mode-aware reproducibility enforcement
# --------------------------------------------------------------------------- #


def test_preliminary_protocol_may_omit_reproducibility() -> None:
    """Preliminary studies are exploratory: reproducibility may be omitted."""
    findings = _validate(
        "p4.preliminary",
        {
            "p4.evidence": [
                _evidence(reproducibility=None),
                _evidence(reproducibility=_reproducibility(empty=True)),
            ],
        },
    )

    codes = _codes(findings)
    assert "p4.reproducibility_missing" not in codes
    assert "p4.reproducibility_artifact_missing" not in codes
    assert "p4.simulation_seed_missing" not in codes


def test_comprehensive_protocol_must_have_reproducibility() -> None:
    """Comprehensive studies must provide full reproducibility metadata."""
    findings = _validate(
        "p4.comprehensive",
        {
            "p4.evidence": [
                _evidence(reproducibility=None),
                _evidence(reproducibility=_reproducibility(empty=True)),
            ],
        },
    )

    codes = _codes(findings)
    assert codes.count("p4.reproducibility_missing") == 1
    assert codes.count("p4.reproducibility_artifact_missing") == 3
    assert codes.count("p4.simulation_seed_missing") == 1

    # Every reproducibility finding blocks publication in comprehensive mode.
    blocking = [f for f in findings if f.code.startswith("p4.reproducibility") or f.code == "p4.simulation_seed_missing"]
    assert blocking
    assert all(f.blocks_publication for f in blocking)
    report = ValidationReport.from_findings("r2", "run2", "scientific", findings)
    assert report.passed is False
