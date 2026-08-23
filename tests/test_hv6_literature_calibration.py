"""HV-6.P1 literature calibration: origin-aware provenance policy.

Researcher-supplied and imported-library sources legitimately lack search
records. ``p1.search_provenance_missing`` is therefore reclassified from
INTEGRITY_BLOCKER (ERROR, blocks publication) to SCIENTIFIC_ATTENTION
(WARNING, does not block publication). A source without search provenance
still surfaces a warning for reviewer attention, but it no longer blocks
the P1 publication.

Tests exercise:
1. A source with search provenance passes without any warning.
2. A source without search provenance passes, but carries a WARNING.
3. The reclassified code is SCIENTIFIC_ATTENTION: severity WARNING,
   blocks_publication=False.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from model_forge.domain.validation import (
    FindingClass,
    ValidationReport,
    ValidationSeverity,
    get_policy,
    make_finding,
)
from model_forge.harness.publication import (
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)
from model_forge.harness.scientific_validators import validate_phase_scientific


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


def _validate_p1(documents: dict[str, Any]) -> list:
    """Run the P1 scientific validators and return findings."""
    plan = SimpleNamespace(
        identity=SimpleNamespace(phase_id="P1"),
        mode_id="p1.literature_update",
        publication_bindings=(),
    )
    findings: list = []
    validate_phase_scientific(
        plan=plan,  # type: ignore[arg-type]
        outputs={key: _output(key, value) for key, value in documents.items()},
        selected_method=None,
        findings=findings,
    )
    return findings


def _source(*, provenance: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    source: dict[str, Any] = {
        "source_id": "source.calibration.001",
        "identifiers": [{"kind": "doi", "value": "10.1000/calibration"}],
        "title": "Calibration fixture",
        "authors": ["A. Author"],
        "year": 2026,
    }
    if provenance is not None:
        source["search_provenance"] = provenance
    return source


def _report(findings: list) -> ValidationReport:
    return ValidationReport.from_findings("report.hv6.p1", "run.hv6.p1", "P1", findings)


# --------------------------------------------------------------------------- #
# 1. Source with search provenance: passes without warning                     #
# --------------------------------------------------------------------------- #


def test_source_with_search_provenance_passes_without_warning() -> None:
    provenance = [
        {
            "run_id": "run.p1.001",
            "role": "research_lead",
            "search_source": "arXiv",
            "query": "MCMC convergence diagnostics",
            "searched_at": "2026-08-01T00:00:00Z",
        }
    ]
    findings = _validate_p1(
        {"p1.source_changes": [_source(provenance=provenance)]}
    )
    codes = [finding.code for finding in findings]
    assert "p1.search_provenance_missing" not in codes
    assert _report(findings).passed is True


# --------------------------------------------------------------------------- #
# 2. Source without search provenance: warns but does not block                #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "provenance",
    [
        None,  # key omitted entirely
        [],  # present but empty
    ],
)
def test_source_without_search_provenance_warns_but_does_not_block(
    provenance: list[dict[str, Any]] | None,
) -> None:
    findings = _validate_p1(
        {"p1.source_changes": [_source(provenance=provenance)]}
    )
    warning = next(
        f for f in findings if f.code == "p1.search_provenance_missing"
    )
    assert warning.severity is ValidationSeverity.WARNING
    assert warning.blocks_publication is False
    # A warning-only report still passes.
    assert _report(findings).passed is True


# --------------------------------------------------------------------------- #
# 3. Reclassified policy: SCIENTIFIC_ATTENTION, WARNING, non-blocking          #
# --------------------------------------------------------------------------- #


def test_search_provenance_missing_is_non_blocking_warning() -> None:
    policy = get_policy("p1.search_provenance_missing")
    assert policy.finding_class is FindingClass.SCIENTIFIC_ATTENTION
    assert policy.default_severity is ValidationSeverity.WARNING
    assert policy.blocks_publication is False

    # make_finding (the validator path) must apply the registry policy.
    finding = make_finding(
        "p1.search_provenance_missing",
        "Source lacks a search record.",
        "p1.source_changes",
    )
    assert finding.severity is ValidationSeverity.WARNING
    assert finding.blocks_publication is False
    assert finding.finding_class is FindingClass.SCIENTIFIC_ATTENTION
