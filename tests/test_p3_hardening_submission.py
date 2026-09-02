"""Regression tests for the P3 sweep, lane B (audit 2026-08-31, P-I pins).

Covers R20 (unreadable sealed submission payloads are operational
failures), R21 (schema_file/failing_property on run-submission schema
findings), R27 (promote-time re-validation failure is a PublicationError),
R28 (isinstance guard on declared method identity), and R36 (messageless
StopIteration on a missing .instructions choice).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from model_forge.application.run_coordinator import RunCoordinator
from model_forge.domain.validation import FindingClass
from model_forge.harness.execution_records import document_sha256
from model_forge.harness.publication import PublicationError
from model_forge.harness.submission_validation import (
    _validate_phase_semantics,
    validate_submission,
)
from model_forge.schemas import SchemaCatalog


class _StubRepository:
    """Minimal repository stub: no attempt row, one sealed submission row."""

    def __init__(self, row):
        self._row = row

    def get_latest_submission_attempt(self, run_id):
        return None

    def get_submission(self, run_id):
        return self._row


def test_unreadable_submission_payload_is_operational() -> None:
    """R20: a corrupt sealed payload is operational, not correctable."""
    repository = _StubRepository(
        {"payload_json": "{not json", "submission_sha256": "0" * 64}
    )
    result = validate_submission(
        repository=repository,
        artifacts=SimpleNamespace(),
        schemas=SimpleNamespace(),
        project_id="p",
        run_id="r",
        plan=SimpleNamespace(),
        output_plan=SimpleNamespace(),
        selected_method=None,
    )
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.code == "submission.payload_unreadable"
    assert finding.finding_class == FindingClass.OPERATIONAL_FAILURE
    assert finding.correction_class == "none"


def test_run_submission_schema_finding_reclassifies_harness_owned() -> None:
    """R21: run-submission schema findings reclassify harness-owned fields."""
    schemas = SchemaCatalog.load(
        Path(__file__).resolve().parents[1] / "architecture" / "schemas"
    )
    submission = {
        # schema_version deliberately omitted: it is harness-owned, so the
        # schema.required finding must reclassify to operational_failure.
        "submission_id": "sub-1",
        "run_id": "r",
        "project_id": "p",
        "phase": "PX",
        "mode": "m",
        "manifest_binding": {},
        "closure_chain": [],
        "lead_closure": {},
        "submitted_artifacts": [],
        "submitted_at": "2026-09-01T00:00:00Z",
    }
    unhashed = dict(submission)
    submission["submission_sha256"] = document_sha256(unhashed)
    repository = _StubRepository(
        {
            "payload_json": json.dumps(submission),
            "submission_sha256": submission["submission_sha256"],
        }
    )
    plan = SimpleNamespace(
        identity=SimpleNamespace(phase_id="PX"),
        mode_id="m",
        publication_bindings=(),
    )
    output_plan = SimpleNamespace(by_contract_id=lambda: {})
    result = validate_submission(
        repository=repository,
        artifacts=SimpleNamespace(),
        schemas=schemas,
        project_id="p",
        run_id="r",
        plan=plan,
        output_plan=output_plan,
        selected_method=None,
    )
    assert any(
        finding.code == "schema.required"
        and finding.finding_class == FindingClass.OPERATIONAL_FAILURE
        for finding in result.findings
    )


def test_promote_revalidation_failure_is_classified() -> None:
    """R27: promote-time re-validation failure raises PublicationError."""
    coordinator = RunCoordinator.__new__(RunCoordinator)
    coordinator.repository = SimpleNamespace(
        get_publication_receipt_for_run=lambda run_id: None
    )
    coordinator._publication_plan = lambda run_id: (
        SimpleNamespace(passed=False),
        None,
        None,
        None,
        None,
    )
    with pytest.raises(PublicationError) as excinfo:
        coordinator._promote("r")
    assert excinfo.value.code == "publication.revalidation_failed"


def test_phase_semantics_guards_non_object_identity() -> None:
    """R28: a non-object declared method identity yields a finding."""
    plan = SimpleNamespace(
        identity=SimpleNamespace(phase_id="P3"),
        publication_bindings=[
            {
                "target": {"record_type": "theory_record"},
                "output_ids": ["output.x"],
            }
        ],
    )
    selected_method = SimpleNamespace(
        to_dict=lambda: {
            "stable_id": "m",
            "version": 1,
            "definition_sha256": "d",
        }
    )
    outputs = {
        "output.x": SimpleNamespace(document={"method_identity": "not-an-object"})
    }
    findings = []
    _validate_phase_semantics(
        plan=plan,
        outputs=outputs,
        selected_method=selected_method,
        findings=findings,
    )
    assert len(findings) == 1
    assert findings[0].code == "submission.method_identity_mismatch"


def test_execution_components_reports_missing_instructions() -> None:
    """R36: a missing .instructions choice raises a messageful ValueError."""
    coordinator = RunCoordinator.__new__(RunCoordinator)
    soul_sha256 = hashlib.sha256("s".encode("utf-8")).hexdigest()
    coordinator._load_recipe = lambda run_id: SimpleNamespace(
        document={
            "role_resources": {
                "role": {
                    "soul_text": "s",
                    "soul_sha256": soul_sha256,
                    "skills": [],
                }
            }
        }
    )
    coordinator._plan_from_recipe = lambda recipe: SimpleNamespace(
        choice_values={"other.choice": "x"},
        stages=(),
        output_contracts=[],
    )
    with pytest.raises(ValueError, match="instructions"):
        coordinator._execution_components("r")
