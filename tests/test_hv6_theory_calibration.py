"""HV-6.P3 theory calibration tests.

Honest-negative statement statuses (``contradicted``, ``incomplete``,
``untested``, ``retracted``, ``conditional``) must be accepted by the P3
validators when their documentation obligations are met. They must not be
treated as scientific failures. Only an ``established`` statement without
proof remains a scientific claim blocker.

Registry expectations (HV-2):
- Documentation obligations on honest-negative statuses are structural
  requirements -> ``CORRECTABLE_CONTRACT_ERROR``.
- ``p3.established_statement_unsupported`` remains a
  ``SCIENTIFIC_CLAIM_BLOCKER``.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

from method_hub.domain import MethodIdentity
from method_hub.domain.validation import (
    FindingClass,
    ValidationFinding,
    get_policy,
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
ARTIFACT = {
    "artifact_id": "artifact.hv6.primary",
    "uri": "artifact://hv6/primary",
    "sha256": "c" * 64,
}

HONEST_NEGATIVE_CODES = {
    "p3.conditional_statement_without_assumption",
    "p3.contradiction_without_evidence",
    "p3.incomplete_statement_without_obligation",
    "p3.untested_statement_without_obligation",
    "p3.retracted_statement_without_reason",
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


def _validate(documents: dict[str, Any]) -> list[ValidationFinding]:
    plan = SimpleNamespace(
        identity=SimpleNamespace(phase_id="P3"),
        mode_id="p3.theory_establishment",
        publication_bindings=(),
    )
    findings: list[ValidationFinding] = []
    validate_phase_scientific(
        plan=plan,  # type: ignore[arg-type]
        outputs={key: _output(key, value) for key, value in documents.items()},
        selected_method=METHOD,
        findings=findings,
    )
    return findings


def _codes(findings: list[ValidationFinding]) -> list[str]:
    return [finding.code for finding in findings]


def _theory_record(
    *,
    status: str = "established",
    justification: dict[str, Any] | None = None,
    assumption_ids: list[str] | None = None,
) -> dict[str, Any]:
    """A fully valid P3 theory record with one statement.

    Mutations are applied by the caller so each test isolates a single
    status/documentation axis.
    """
    return {
        "method_identity": deepcopy(METHOD.to_dict()),
        "development_mode": "p3.theory_establishment",
        "basis": [{"record_id": "record.method.001"}],
        "primary_artifact": deepcopy(ARTIFACT),
        "representations": [
            {
                "information_layer": "primary_artifact",
                "artifact": deepcopy(ARTIFACT),
            }
        ],
        "assumptions": [
            {
                "assumption_id": "assumption.regularity.001",
                "used_by_statement_ids": ["statement.main.001"],
            }
        ],
        "statements": [
            {
                "statement_id": "statement.main.001",
                "statement_type": "theorem",
                "status": status,
                "assumption_ids": deepcopy(
                    assumption_ids
                    if assumption_ids is not None
                    else ["assumption.regularity.001"]
                ),
                "depends_on_statement_ids": [],
                "empirical_implication_ids": ["implication.main.001"],
                "justification": deepcopy(
                    justification
                    if justification is not None
                    else {
                        "kind": "proof",
                        "summary": "A complete proof is in the primary artifact.",
                        "artifacts": [deepcopy(ARTIFACT)],
                    }
                ),
            }
        ],
        "empirical_implications": [
            {
                "implication_id": "implication.main.001",
                "statement_ids": ["statement.main.001"],
            }
        ],
        "scientific_outcome": {"state": "supported"},
    }


# --------------------------------------------------------------------------- #
# Blockers keep blocking: established without proof                           #
# --------------------------------------------------------------------------- #


def test_established_statement_without_proof_still_blocks() -> None:
    theory = _theory_record()
    theory["statements"][0]["justification"] = {
        "kind": "proof",
        "summary": "Proof is sketched but no artifact is attached.",
        "artifacts": [],
    }

    findings = _validate({"p3.complete_theory": theory})

    assert "p3.established_statement_unsupported" in _codes(findings)
    policy = get_policy("p3.established_statement_unsupported")
    assert policy.finding_class is FindingClass.SCIENTIFIC_CLAIM_BLOCKER
    assert policy.blocks_publication is True


# --------------------------------------------------------------------------- #
# Honest negatives are accepted when documented                               #
# --------------------------------------------------------------------------- #


def test_contradicted_statement_with_evidence_passes() -> None:
    theory = _theory_record(
        status="contradicted",
        justification={
            "kind": "counterexample",
            "summary": "A boundary construction contradicts the stated rate.",
            "artifacts": [deepcopy(ARTIFACT)],
        },
    )

    assert _validate({"p3.complete_theory": theory}) == []


def test_conditional_statement_with_assumption_reference_passes() -> None:
    theory = _theory_record(
        status="conditional",
        justification={
            "kind": "derivation",
            "summary": "The result holds conditional on the assumption.",
            "artifacts": [deepcopy(ARTIFACT)],
        },
    )

    assert _validate({"p3.complete_theory": theory}) == []


def test_untested_statement_with_open_obligation_passes() -> None:
    theory = _theory_record(
        status="untested",
        justification={
            "kind": "open_obligation",
            "summary": "The statement remains untested.",
            "open_obligation": "Provide a proof or a counterexample in a future generation.",
        },
    )

    assert _validate({"p3.complete_theory": theory}) == []


def test_retracted_statement_with_reason_passes() -> None:
    theory = _theory_record(
        status="retracted",
        justification={
            "kind": "counterexample",
            "summary": (
                "A boundary construction invalidates the claim; "
                "it is superseded by statement.main.002."
            ),
            "artifacts": [deepcopy(ARTIFACT)],
        },
    )

    assert _validate({"p3.complete_theory": theory}) == []


def test_incomplete_statement_with_open_obligation_passes() -> None:
    theory = _theory_record(
        status="incomplete",
        justification={
            "kind": "open_obligation",
            "summary": "Only the sufficiency direction is proven.",
            "open_obligation": "Prove necessity in a future generation.",
        },
    )

    assert _validate({"p3.complete_theory": theory}) == []


# --------------------------------------------------------------------------- #
# Missing documentation still fails, as a correctable structural error        #
# --------------------------------------------------------------------------- #


def test_incomplete_statement_without_obligation_fails() -> None:
    theory = _theory_record(
        status="incomplete",
        justification={
            "kind": "proof",
            "summary": "Only the sufficiency direction is proven.",
            "artifacts": [deepcopy(ARTIFACT)],
        },
    )

    findings = _validate({"p3.complete_theory": theory})

    assert "p3.incomplete_statement_without_obligation" in _codes(findings)
    policy = get_policy("p3.incomplete_statement_without_obligation")
    assert policy.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR
    # Still blocks until corrected, but as a structural/packaging issue.
    assert policy.blocks_publication is True


# --------------------------------------------------------------------------- #
# HV-2 registry classification                                                #
# --------------------------------------------------------------------------- #


def test_honest_negative_codes_are_correctable_contract_errors() -> None:
    """Documentation obligations on honest negatives are structural, not claims."""
    for code in HONEST_NEGATIVE_CODES:
        policy = get_policy(code)
        assert policy.finding_class is FindingClass.CORRECTABLE_CONTRACT_ERROR, (
            f"{code} must be a correctable contract error, got {policy.finding_class}"
        )


def test_established_unsupported_remains_scientific_claim_blocker() -> None:
    policy = get_policy("p3.established_statement_unsupported")
    assert policy.finding_class is FindingClass.SCIENTIFIC_CLAIM_BLOCKER
    assert policy.blocks_publication is True
