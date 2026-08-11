"""WP-E1 tests: post-execution output validation of supervised runs.

Covers the post-quiescence validator: the raw-output inventory captured
before judgment, the seven named checks (inventory, safe paths, schema,
nonempty scientific fields, companions, identity, phase consistency), the
refusal to validate a ``running`` launch, digest recording, and the
``run_validation_reports`` sibling table.  Outputs are written directly
after sealing (validation does not require a real launch), following the
stub-hermes pattern of ``test_run_launcher.py`` for the assembler fixtures.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from method_hub.application.output_validation import (
    LaunchNotClosedError,
    OutputValidationReport,
    validate_run_outputs,
)
from method_hub.application.run_profile_assembler import (
    HermesProbe,
    RunProfileAssembler,
    RunSealError,
    SealedRun,
)
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.domain.runs import isoformat_utc, utc_now
from method_hub.profiles.project_profiles import MemoryPolicy
from method_hub.storage.database import Database
from method_hub.storage.migrations import HUB_MIGRATIONS

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources" / "team"
SKILL_BUNDLE = ROOT / "resources" / "skills"

STUB_VERSION = "0.0.1"

_GOOD_THEORY = {
    "basis": {"assumptions": ["a1"]},
    "representations": {"statements": []},
    "invocation_id": "inv-001",
    "run_id": "inv-001",
    "method_id": "mh-1",
}


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "hub.sqlite3", migrations=HUB_MIGRATIONS)
    db.initialize()
    return db


@pytest.fixture
def catalog() -> RoleResourceCatalog:
    return RoleResourceCatalog.load(RESOURCE_ROOT)


def _stub_probe(binary: str) -> HermesProbe:
    return HermesProbe(binary, STUB_VERSION)


@pytest.fixture
def assembler(
    tmp_path: Path,
    database: Database,
    catalog: RoleResourceCatalog,
) -> RunProfileAssembler:
    return RunProfileAssembler(
        data_root=tmp_path / "data",
        role_resources=catalog,
        database=database,
        bundle_root=SKILL_BUNDLE,
        hermes_root=tmp_path / "hermes",
        hermes_binary="stub-hermes",
        hermes_probe=_stub_probe,
    )


def _seal_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(
        invocation_id="inv-001",
        idempotency_key="key-001",
        project_id="proj-001",
        role="theorist",
        phase="P3",
        method_identity={"method_id": "mh-1", "version": "1.0"},
        user_choices={"mode": "headless", "context_policy": "strict"},
        selected_context_references=[
            {"context_id": "ctx-1", "record_id": "rec-1"},
        ],
        expected_outputs=[
            {
                "output_id": "p3.complete_theory",
                "kind": "scientific_record",
                "required": True,
                "relative_path": "p3/complete_theory.json",
                "required_fields": ["basis", "representations"],
                "companions": ["fig1.pdf"],
            },
            {
                "output_id": "p3.notes",
                "kind": "scientific_record",
                "required": False,
                "relative_path": "p3/notes.json",
            },
        ],
        memory_policy=MemoryPolicy.PERSISTENT,
    )
    kwargs.update(overrides)
    return kwargs


def _seal(assembler: RunProfileAssembler, **overrides: Any) -> SealedRun:
    return assembler.seal_invocation(**_seal_kwargs(**overrides))


def _close_launch(
    assembler: RunProfileAssembler,
    sealed: SealedRun,
    status: str = "succeeded",
    launch_id: str = "launch-001",
) -> str:
    now = isoformat_utc(utc_now())
    assembler.store.create_launch_record(
        launch_id=launch_id,
        seal_id=sealed.seal_id,
        invocation_id=sealed.invocation_id,
        launched_at=now,
    )
    assembler.store.close_launch_record(
        launch_id,
        status=status,
        external_execution_id="ext-001",
        exit_code=0,
        closed_at=isoformat_utc(utc_now()),
    )
    return launch_id


def _write_output(
    sealed: SealedRun,
    relative: str,
    content: str | bytes,
) -> Path:
    target = sealed.run_dir / "outputs" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")
    return target


def _valid_outputs(sealed: SealedRun) -> None:
    _write_output(
        sealed,
        "p3/complete_theory.json",
        json.dumps(_GOOD_THEORY),
    )
    _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
    _write_output(sealed, "p3/fig1.pdf", b"%PDF-1.4\n% fake figure\n")


# --------------------------------------------------------------------------- #
# Happy path                                                                   #
# --------------------------------------------------------------------------- #


class TestAllValidPass:
    def test_all_valid_run_passes_and_records_report(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _valid_outputs(sealed)
        launch_id = _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert isinstance(report, OutputValidationReport)
        assert report.passed is True
        assert report.verdict == "pass"
        assert report.launch_id == launch_id
        assert report.invocation_id == "inv-001"
        for name in (
            "inventory",
            "safe_paths",
            "schema",
            "nonempty_scientific_fields",
            "companions",
            "identity",
            "phase_consistency",
        ):
            check = report.check(name)
            assert check is not None, name
            assert check.status == "pass", (name, check.detail)

        # Raw inventory was captured: every output file is listed with a digest.
        inventory_paths = {entry.relative_path for entry in report.raw_inventory}
        assert inventory_paths == {
            "p3/complete_theory.json",
            "p3/notes.json",
            "p3/fig1.pdf",
        }
        # The verdict landed in the sibling table; the seal registry is untouched.
        stored = assembler.store.get_validation_report(launch_id)
        assert stored is not None
        assert stored["verdict"] == "pass"
        stored_doc = json.loads(stored["report_json"])
        assert stored_doc["verdict"] == "pass"
        assert stored_doc["format"] == "method-hub.output-validation-report"
        assert assembler.store.get_seal(sealed.seal_id)["seal_id"] == sealed.seal_id

    def test_digests_recorded_match_bytes_on_disk(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _valid_outputs(sealed)
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        for relative in (
            "p3/complete_theory.json",
            "p3/notes.json",
            "p3/fig1.pdf",
        ):
            on_disk = hashlib.sha256(
                (sealed.run_dir / "outputs" / relative).read_bytes()
            ).hexdigest()
            assert report.digests[relative] == on_disk
        # The companion digest is recorded in the report.
        assert report.digests["p3/fig1.pdf"] == hashlib.sha256(
            b"%PDF-1.4\n% fake figure\n"
        ).hexdigest()


class TestLaunchStateRefusal:
    def test_refuses_to_validate_a_running_launch(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _valid_outputs(sealed)
        now = isoformat_utc(utc_now())
        assembler.store.create_launch_record(
            launch_id="launch-running",
            seal_id=sealed.seal_id,
            invocation_id=sealed.invocation_id,
            launched_at=now,
        )

        with pytest.raises(LaunchNotClosedError, match="not closed"):
            validate_run_outputs(assembler, sealed.invocation_id)

        # Nothing was recorded for a refused validation.
        assert assembler.store.get_validation_report("launch-running") is None

    def test_refuses_without_any_launch_record(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _valid_outputs(sealed)

        with pytest.raises(LaunchNotClosedError, match="No launch record"):
            validate_run_outputs(assembler, sealed)

    def test_failed_launch_is_terminal_and_still_validates(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _valid_outputs(sealed)
        _close_launch(assembler, sealed, status="failed", launch_id="launch-failed")

        report = validate_run_outputs(assembler, sealed.invocation_id)

        assert report.passed is True
        assert report.launch_id == "launch-failed"
        assert assembler.store.get_validation_report("launch-failed")["verdict"] == "pass"


# --------------------------------------------------------------------------- #
# Failing checks                                                               #
# --------------------------------------------------------------------------- #


class TestInventoryFailures:
    def test_missing_declared_output_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("inventory")
        assert check is not None and check.status == "fail"
        assert "missing" in check.detail and "p3.complete_theory" in check.detail

    def test_undeclared_extra_file_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _valid_outputs(sealed)
        _write_output(sealed, "surprise.txt", "not declared anywhere")
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("inventory")
        assert check is not None and check.status == "fail"
        assert "undeclared file" in check.detail and "surprise.txt" in check.detail

    def test_symlinked_declared_output_fails(
        self, assembler: RunProfileAssembler, tmp_path: Path
    ) -> None:
        sealed = _seal(assembler)
        _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps(_GOOD_THEORY), encoding="utf-8")
        link = sealed.run_dir / "outputs" / "p3" / "complete_theory.json"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(outside)
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("inventory")
        assert check is not None and check.status == "fail"
        assert "symlink" in check.detail

    def test_undeclared_symlink_in_outputs_fails(
        self, assembler: RunProfileAssembler, tmp_path: Path
    ) -> None:
        sealed = _seal(assembler)
        _valid_outputs(sealed)
        outside = tmp_path / "outside.txt"
        outside.write_text("sneaky", encoding="utf-8")
        link = sealed.run_dir / "outputs" / "sneaky.txt"
        link.symlink_to(outside)
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("inventory")
        assert check is not None and check.status == "fail"
        assert "undeclared symlink" in check.detail

    def test_empty_declared_output_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _write_output(sealed, "p3/complete_theory.json", "")
        _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        _write_output(sealed, "p3/fig1.pdf", b"x")
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("inventory")
        assert check is not None and check.status == "fail"
        assert "empty" in check.detail


class TestSafePathsFailures:
    def test_declared_path_escaping_outputs_fails_safe_paths(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(
            assembler,
            expected_outputs=[
                {
                    "output_id": "esc",
                    "relative_path": "../escape.json",
                },
            ],
        )
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("safe_paths")
        assert check is not None and check.status == "fail"
        assert "escape" in check.detail


class TestSchemaFailures:
    def test_malformed_json_fails_schema(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _write_output(sealed, "p3/complete_theory.json", "{not json")
        _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        _write_output(sealed, "p3/fig1.pdf", b"x")
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("schema")
        assert check is not None and check.status == "fail"
        assert "not strict JSON" in check.detail

    def test_missing_required_field_fails_schema(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        doc = dict(_GOOD_THEORY)
        del doc["basis"]
        _write_output(sealed, "p3/complete_theory.json", json.dumps(doc))
        _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        _write_output(sealed, "p3/fig1.pdf", b"x")
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("schema")
        assert check is not None and check.status == "fail"
        assert "missing required field" in check.detail and "basis" in check.detail


class TestNonemptyFieldFailures:
    @pytest.mark.parametrize(
        "empty_value",
        [None, "", [], {}],
        ids=["null", "empty-string", "empty-array", "empty-object"],
    )
    def test_required_field_present_but_empty_fails(
        self, assembler: RunProfileAssembler, empty_value: Any
    ) -> None:
        sealed = _seal(
            assembler,
            expected_outputs=[
                {
                    "output_id": "p3.complete_theory",
                    "kind": "scientific_record",
                    "required": True,
                    "relative_path": "p3/complete_theory.json",
                    "required_fields": ["basis", "representations"],
                },
            ],
        )
        _write_output(
            sealed,
            "p3/complete_theory.json",
            json.dumps({"basis": empty_value, "representations": {"statements": []}}),
        )
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("nonempty_scientific_fields")
        assert check is not None and check.status == "fail"
        assert "basis" in check.detail


class TestIdentityFailures:
    def test_wrong_invocation_id_in_output_json_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        doc = dict(_GOOD_THEORY)
        doc["invocation_id"] = "inv-999"
        _write_output(sealed, "p3/complete_theory.json", json.dumps(doc))
        _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        _write_output(sealed, "p3/fig1.pdf", b"x")
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("identity")
        assert check is not None and check.status == "fail"
        assert "invocation_id mismatch" in check.detail
        assert "inv-999" in check.detail

    def test_wrong_method_id_in_output_json_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        doc = dict(_GOOD_THEORY)
        doc["method_id"] = "mh-other"
        _write_output(sealed, "p3/complete_theory.json", json.dumps(doc))
        _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        _write_output(sealed, "p3/fig1.pdf", b"x")
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        check = report.check("identity")
        assert check is not None and check.status == "fail"
        assert "method_id mismatch" in check.detail


class TestCompanionFailures:
    def test_missing_companion_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _write_output(sealed, "p3/complete_theory.json", json.dumps(_GOOD_THEORY))
        _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        assert report.passed is False
        check = report.check("companions")
        assert check is not None and check.status == "fail"
        assert "fig1.pdf" in check.detail

    def test_empty_companion_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _write_output(sealed, "p3/complete_theory.json", json.dumps(_GOOD_THEORY))
        _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        _write_output(sealed, "p3/fig1.pdf", b"")
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        check = report.check("companions")
        assert check is not None and check.status == "fail"
        assert "empty" in check.detail


# --------------------------------------------------------------------------- #
# Phase consistency                                                            #
# --------------------------------------------------------------------------- #


class TestPhaseConsistency:
    def test_phase_without_validator_is_skipped_not_failed(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(
            assembler,
            phase="run",
            expected_outputs=[
                {"output_id": "out-1", "relative_path": "out-1.json"},
            ],
        )
        _write_output(sealed, "out-1.json", json.dumps({"ok": True}))
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        check = report.check("phase_consistency")
        assert check is not None and check.status == "skipped"
        assert "no phase-specific validator" in check.detail
        # Skipped checks do not fail the overall verdict.
        assert report.passed is True

    def test_unbound_output_ids_skip_phase_validator(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(
            assembler,
            phase="P3",
            expected_outputs=[
                {"output_id": "out-1", "relative_path": "out-1.json"},
            ],
        )
        _write_output(sealed, "out-1.json", json.dumps({"ok": True}))
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        check = report.check("phase_consistency")
        assert check is not None and check.status == "skipped"
        assert "cannot bind" in check.detail
        assert report.passed is True

    def test_phase_validator_findings_fail_the_check(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        doc = dict(_GOOD_THEORY)
        doc["basis"] = []  # P3: no basis entries documented
        _write_output(sealed, "p3/complete_theory.json", json.dumps(doc))
        _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        _write_output(sealed, "p3/fig1.pdf", b"x")
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)

        check = report.check("phase_consistency")
        assert check is not None and check.status == "fail"
        assert "p3.no_assumptions_documented" in check.detail
        assert report.passed is False


# --------------------------------------------------------------------------- #
# Invocation-id lookup and validation by id                                    #
# --------------------------------------------------------------------------- #


class TestLookupByInvocationId:
    def test_validate_by_invocation_id_string(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _valid_outputs(sealed)
        _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed.invocation_id)

        assert report.passed is True
        assert report.seal_id == sealed.seal_id

    def test_unknown_invocation_id_raises(
        self, assembler: RunProfileAssembler
    ) -> None:
        with pytest.raises(RunSealError, match="No sealed run"):
            validate_run_outputs(assembler, "inv-does-not-exist")

    def test_validation_changes_no_run_state(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = _seal(assembler)
        _valid_outputs(sealed)
        launch_id = _close_launch(assembler, sealed)
        before = assembler.store.get_launch_record(launch_id)
        seal_before = assembler.store.get_seal(sealed.seal_id)
        outputs_before = sorted(
            str(path.relative_to(sealed.run_dir))
            for path in (sealed.run_dir / "outputs").rglob("*")
            if path.is_file()
        )

        report = validate_run_outputs(assembler, sealed)

        after = assembler.store.get_launch_record(launch_id)
        seal_after = assembler.store.get_seal(sealed.seal_id)
        outputs_after = sorted(
            str(path.relative_to(sealed.run_dir))
            for path in (sealed.run_dir / "outputs").rglob("*")
            if path.is_file()
        )
        assert report.passed is True
        assert before == after
        assert seal_before == seal_after
        assert outputs_before == outputs_after
