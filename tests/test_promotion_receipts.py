"""WP-E3 tests: promotion receipts and explicit retention rules (Block 5).

Receipt tests drive a full promoteable pipeline (seal with declared
outputs, real WP-E1 validation with digests, WP-E2 promotion) and verify
every receipt field against the manifest, the stored validation report,
and the promotion result, plus byte-identical deterministic rewriting
and the JCS sidecar.  Retention tests exercise each explicit rule:
running/unsealed/unvalidated/tampered evidence is never pruned, the
newest backup and the current canonical state are kept, old resolved
runs and old backups are pruned only in non-dry-run mode.  Uses
tmp_path fixtures — no real Hermes required.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from method_hub.application.output_validation import validate_run_outputs
from method_hub.application.promotion_receipts import (
    RECEIPT_DIGEST_FILE_NAME,
    RECEIPT_FILE_NAME,
    RECEIPT_FORMAT,
    RECEIPT_FORMAT_VERSION,
    PromotionReceiptError,
    write_promotion_receipt,
)
from method_hub.application.retention import (
    RETAIN_BACKUP_DAYS,
    RETAIN_COMPLETED_DAYS,
    RetentionReport,
    apply_retention,
)
from method_hub.application.run_profile_assembler import (
    HermesProbe,
    RunProfileAssembler,
    SealedRun,
)
from method_hub.application.state_promotion import (
    PromotionResult,
    PromotionTargetResult,
    promote_run_state,
)
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.digests.jcs import canonicalize
from method_hub.domain.runs import isoformat_utc, utc_now
from method_hub.profiles.project_profiles import MemoryPolicy, project_role_profile_name
from method_hub.storage.database import Database
from method_hub.storage.migrations import HUB_MIGRATIONS

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources" / "team"
SKILL_BUNDLE = ROOT / "resources" / "skills"

FAKE_HERMES = HermesProbe("/fake/hermes", "9.9.9")

_GOOD_THEORY = {
    "basis": {"assumptions": ["a1"]},
    "representations": {"statements": []},
    "invocation_id": "inv-001",
    "run_id": "inv-001",
    "method_id": "mh-1",
}


# --------------------------------------------------------------------------- #
# Fixtures and helpers                                                         #
# --------------------------------------------------------------------------- #


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "hub.sqlite3", migrations=HUB_MIGRATIONS)
    db.initialize()
    return db


@pytest.fixture
def catalog() -> RoleResourceCatalog:
    return RoleResourceCatalog.load(RESOURCE_ROOT)


@pytest.fixture
def hermes_root(tmp_path: Path) -> Path:
    root = tmp_path / "hermes"
    root.mkdir()
    return root


@pytest.fixture
def assembler(
    tmp_path: Path,
    database: Database,
    catalog: RoleResourceCatalog,
    hermes_root: Path,
) -> RunProfileAssembler:
    return RunProfileAssembler(
        data_root=tmp_path / "data",
        role_resources=catalog,
        database=database,
        bundle_root=SKILL_BUNDLE,
        hermes_root=hermes_root,
        hermes_binary="hermes",
        hermes_probe=lambda binary: FAKE_HERMES,
    )


def _canonical_dir(
    hermes_root: Path, project_id: str = "proj-001", role: str = "theorist"
) -> Path:
    return hermes_root / "profiles" / project_role_profile_name(project_id, role)


def _seal(assembler: RunProfileAssembler, **overrides: Any) -> SealedRun:
    kwargs: dict[str, Any] = dict(
        invocation_id="inv-001",
        idempotency_key="key-001",
        project_id="proj-001",
        role="theorist",
        phase="P3",
        method_identity={"method_id": "mh-1", "version": "1.0"},
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
    return assembler.seal_invocation(**kwargs)


def _setup_canonical(hermes_root: Path) -> Path:
    profile = _canonical_dir(hermes_root)
    memories = profile / "memories"
    memories.mkdir(parents=True)
    (memories / "MEMORY.md").write_text("# Memory\nPrior conclusion.\n")
    _make_state_db(profile / "state.db", [("s-1", "old session")])
    return profile


def _make_state_db(path: Path, sessions: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, content TEXT)")
    for session_id, content in sessions:
        conn.execute(
            "INSERT INTO sessions (id, content) VALUES (?, ?)",
            (session_id, content),
        )
    conn.commit()
    conn.close()


def _write_memory(sealed: SealedRun, relative: str, content: str) -> None:
    target = sealed.run_dir / "profile" / "memories" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _append_session(state_db: Path, session_id: str, content: str) -> None:
    conn = sqlite3.connect(state_db)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, content TEXT)"
    )
    conn.execute(
        "INSERT INTO sessions (id, content) VALUES (?, ?)", (session_id, content)
    )
    conn.commit()
    conn.close()


def _write_output(sealed: SealedRun, relative: str, content: str | bytes) -> None:
    target = sealed.run_dir / "outputs" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        target.write_bytes(content)
    else:
        target.write_text(content, encoding="utf-8")


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


def _record_validation(
    assembler: RunProfileAssembler,
    sealed: SealedRun,
    launch_id: str,
    verdict: str = "pass",
) -> None:
    assembler.store.record_validation_report(
        launch_id=launch_id,
        invocation_id=sealed.invocation_id,
        seal_id=sealed.seal_id,
        verdict=verdict,
        report_json=json.dumps({"verdict": verdict}),
        validated_at=isoformat_utc(utc_now()),
    )


def _simulate_run_work(sealed: SealedRun) -> None:
    _write_memory(sealed, "MEMORY.md", "# Memory\nNew conclusion from P3.\n")
    _write_memory(sealed, "NOTES.md", "# Notes\nFresh analysis.\n")
    _append_session(sealed.run_dir / "profile" / "state.db", "s-2", "new session")


def _write_all_outputs(sealed: SealedRun) -> None:
    _write_output(sealed, "p3/complete_theory.json", json.dumps(_GOOD_THEORY))
    _write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
    _write_output(sealed, "p3/fig1.pdf", b"%PDF-1.4\nfake\n")


def _promotable_run(
    assembler: RunProfileAssembler, hermes_root: Path
) -> tuple[SealedRun, Path]:
    """Canonical state + sealed persistent run + work + real validation +
    real promotion; returns the sealed run and the canonical profile dir."""
    profile = _setup_canonical(hermes_root)
    sealed = _seal(assembler)
    _simulate_run_work(sealed)
    _write_all_outputs(sealed)
    _close_launch(assembler, sealed)
    report = validate_run_outputs(assembler, sealed)
    assert report.passed is True
    result = promote_run_state(assembler, sealed)
    assert result.promoted is True
    return sealed, profile


def _future(sealed: SealedRun, days: float) -> datetime:
    return datetime.fromisoformat(sealed.sealed_at) + timedelta(days=days)


# --------------------------------------------------------------------------- #
# Receipts                                                                     #
# --------------------------------------------------------------------------- #


class TestReceipts:
    def test_receipt_contains_every_required_field_matching_records(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed, _ = _promotable_run(assembler, hermes_root)
        promotion_row = assembler.store.find_promotion_record_by_invocation(
            sealed.invocation_id
        )
        assert promotion_row is not None
        launch = assembler.store.find_launch_record_by_invocation(
            sealed.invocation_id
        )
        assert launch is not None
        report_row = assembler.store.get_validation_report(launch["launch_id"])
        assert report_row is not None
        report_doc = json.loads(report_row["report_json"])

        result = _promotion_result_from(assembler, sealed)
        receipt_path = write_promotion_receipt(assembler, result)

        assert receipt_path == sealed.run_dir / "manifest" / RECEIPT_FILE_NAME
        document = json.loads(receipt_path.read_text(encoding="utf-8"))

        # Receipt format identity.
        assert document["format"] == RECEIPT_FORMAT
        assert document["format_version"] == RECEIPT_FORMAT_VERSION

        # Run identity from the sealed manifest / promotion result.
        assert document["seal_id"] == sealed.seal_id
        assert document["invocation_id"] == sealed.invocation_id
        assert document["project_id"] == sealed.project_id
        assert document["role"] == sealed.role
        assert document["phase"] == sealed.manifest["phase"] == "P3"

        # Input snapshot identity straight from the immutable manifest.
        assert document["input_snapshot"]["memory_identity"] == (
            sealed.manifest["memory_snapshot"]["identity"]
        )
        assert document["input_snapshot"]["session_sha256"] == (
            sealed.manifest["session_snapshot"]["sha256"]
        )
        assert len(document["input_snapshot"]["session_sha256"]) == 64

        # Validation evidence from the WP-E1 report for the invocation.
        assert document["validation"]["verdict"] == report_row["verdict"] == "pass"
        assert document["validation"]["launch_id"] == launch["launch_id"]
        assert document["validation"]["validated_at"] == report_row["validated_at"]
        assert document["validation"]["output_digests"] == report_doc["digests"]
        assert set(document["validation"]["output_digests"]) == {
            "p3/complete_theory.json",
            "p3/notes.json",
            "p3/fig1.pdf",
        }

        # Promoted state / previous current state / backups per target.
        by_name = {target.name: target for target in result.targets}
        assert {item["target"] for item in document["promoted_state"]} == set(by_name)
        for item in document["promoted_state"]:
            target = by_name[item["target"]]
            assert item["before_digest"] == target.before_digest
            assert item["after_digest"] == target.after_digest
        assert document["previous_current_state"] == {
            name: target.before_digest for name, target in by_name.items()
        }
        assert document["backup_locations"] == {
            name: target.backup_path for name, target in by_name.items()
        }
        assert document["promoted_at"] == promotion_row["promoted_at"]

        # The promoted state really landed: after digest != before digest.
        for item in document["promoted_state"]:
            assert item["after_digest"] != item["before_digest"]
        assert all(
            Path(path).exists()
            for path in document["backup_locations"].values()
            if path is not None
        )

    def test_receipt_is_byte_identical_and_idempotent(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed, _ = _promotable_run(assembler, hermes_root)
        result = _promotion_result_from(assembler, sealed)
        receipt_path = write_promotion_receipt(assembler, result)
        first_bytes = receipt_path.read_bytes()
        first_mtime = receipt_path.stat().st_mtime_ns

        # A second call returns the existing receipt without rewriting.
        assert write_promotion_receipt(assembler, result) == receipt_path
        assert receipt_path.read_bytes() == first_bytes
        assert receipt_path.stat().st_mtime_ns == first_mtime

        # Deterministic: a rewrite after deletion is byte identical.
        digest_path = receipt_path.with_name(RECEIPT_DIGEST_FILE_NAME)
        digest_bytes = digest_path.read_bytes()
        receipt_path.unlink()
        digest_path.unlink()
        rewritten = write_promotion_receipt(assembler, result)
        assert rewritten == receipt_path
        assert receipt_path.read_bytes() == first_bytes
        assert digest_path.read_bytes() == digest_bytes

    def test_receipt_digest_sidecar_verifies(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed, _ = _promotable_run(assembler, hermes_root)
        receipt_path = write_promotion_receipt(
            assembler, _promotion_result_from(assembler, sealed)
        )
        document = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected = hashlib.sha256(canonicalize(document)).hexdigest()
        sidecar = receipt_path.with_name(RECEIPT_DIGEST_FILE_NAME).read_text(
            encoding="utf-8"
        ).strip()
        assert sidecar == expected
        assert len(sidecar) == 64

    def test_receipt_refuses_without_a_validation_report(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        # A succeeded launch with NO validation report cannot produce a receipt.
        profile = _setup_canonical(hermes_root)
        sealed = _seal(assembler)
        _simulate_run_work(sealed)
        _close_launch(assembler, sealed)
        result = PromotionResult(
            seal_id=sealed.seal_id,
            invocation_id=sealed.invocation_id,
            project_id=sealed.project_id,
            role=sealed.role,
            promoted=True,
            promoted_at=isoformat_utc(utc_now()),
            memory_before_inventory=(),
            runtime_after_inventory=(),
            targets=(),
        )
        with pytest.raises(PromotionReceiptError):
            write_promotion_receipt(assembler, result)


def _promotion_result_from(
    assembler: RunProfileAssembler, sealed: SealedRun
) -> PromotionResult:
    """Rebuild a PromotionResult from the stored promotion row.

    The receipt reads the promotion outcome from the record, so the test
    compares against the DB row (the ground truth written by WP-E2).
    """
    record = assembler.store.find_promotion_record_by_invocation(
        sealed.invocation_id
    )
    assert record is not None
    before = json.loads(record["before_digest"])
    after = json.loads(record["after_digest"])
    backups = json.loads(record["backup_paths"])
    targets = tuple(
        PromotionTargetResult(
            name=name,
            before_digest=before.get(name),
            after_digest=after.get(name),
            backup_path=backups.get(name),
        )
        for name in sorted(before)
    )
    return PromotionResult(
        seal_id=record["seal_id"],
        invocation_id=record["invocation_id"],
        project_id=record["project_id"],
        role=record["role"],
        promoted=True,
        promoted_at=record["promoted_at"],
        memory_before_inventory=(),
        runtime_after_inventory=(),
        targets=targets,
    )


# --------------------------------------------------------------------------- #
# Retention                                                                   #
# --------------------------------------------------------------------------- #


class TestRetentionRunDirs:
    def test_keeps_a_run_with_a_running_launch(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed = _seal(assembler)
        assembler.store.create_launch_record(
            launch_id="launch-001",
            seal_id=sealed.seal_id,
            invocation_id=sealed.invocation_id,
            launched_at=isoformat_utc(utc_now()),
        )  # stays 'running' forever

        report = apply_retention(
            assembler, now=_future(sealed, 400), dry_run=False
        )
        entry = _entry(report, sealed.run_dir)
        assert entry.decision == "keep"
        assert entry.rule == "run_running"
        assert sealed.run_dir.exists()

    def test_keeps_an_unsealed_run_directory(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        stray = assembler.runs_root / "mystery-dir"
        stray.mkdir(parents=True)
        (stray / "junk.txt").write_text("no seal here\n")

        report = apply_retention(
            assembler,
            now=datetime(2030, 1, 1, tzinfo=timezone.utc),
            dry_run=False,
        )
        entry = _entry(report, stray)
        assert entry.decision == "keep"
        assert entry.rule == "run_unsealed"
        assert stray.exists()

    def test_keeps_an_unvalidated_run_even_when_very_old(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed = _seal(assembler)
        _close_launch(assembler, sealed)  # terminal launch, no validation report

        report = apply_retention(
            assembler, now=_future(sealed, 400), dry_run=False
        )
        entry = _entry(report, sealed.run_dir)
        assert entry.decision == "keep"
        assert entry.rule == "run_unresolved"
        assert sealed.run_dir.exists()

    def test_prunes_an_old_promoted_run_only_in_non_dry_run(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed, _ = _promotable_run(assembler, hermes_root)
        old_now = _future(sealed, RETAIN_COMPLETED_DAYS + 1)

        dry = apply_retention(assembler, now=old_now, dry_run=True)
        entry = _entry(dry, sealed.run_dir)
        assert entry.decision == "prune"
        assert entry.rule == "run_expired"
        assert entry.deleted is False
        assert sealed.run_dir.exists()  # dry run touches nothing

        wet = apply_retention(assembler, now=old_now, dry_run=False)
        entry = _entry(wet, sealed.run_dir)
        assert entry.decision == "prune"
        assert entry.deleted is True
        assert not sealed.run_dir.exists()

    def test_injectable_completed_window_keeps_a_young_run(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed, _ = _promotable_run(assembler, hermes_root)
        old_now = _future(sealed, RETAIN_COMPLETED_DAYS + 1)
        report = apply_retention(
            assembler, now=old_now, dry_run=False, completed_days=365
        )
        entry = _entry(report, sealed.run_dir)
        assert entry.decision == "keep"
        assert entry.rule == "run_young"
        assert sealed.run_dir.exists()

    def test_prunes_an_old_run_whose_validation_failed(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        sealed = _seal(assembler)
        _simulate_run_work(sealed)
        launch_id = _close_launch(assembler, sealed)
        _record_validation(assembler, sealed, launch_id, verdict="fail")

        report = apply_retention(
            assembler, now=_future(sealed, RETAIN_COMPLETED_DAYS + 1),
            dry_run=False,
        )
        entry = _entry(report, sealed.run_dir)
        assert entry.decision == "prune"
        assert entry.rule == "run_expired"
        assert "validation failed" in entry.reason
        assert not sealed.run_dir.exists()

    def test_reports_a_tampered_manifest_without_pruning_it(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed, _ = _promotable_run(assembler, hermes_root)
        manifest_path = sealed.run_dir / "manifest" / "manifest.json"
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        document["phase"] = "P9-TAMPERED"  # still valid JSON, digest no longer matches
        manifest_path.write_text(
            json.dumps(document, indent=2, sort_keys=True), encoding="utf-8"
        )

        report = apply_retention(
            assembler, now=_future(sealed, 400), dry_run=False
        )
        entry = _entry(report, sealed.run_dir)
        assert entry.decision == "keep"
        assert entry.rule == "run_tampered_manifest"
        assert "verification failed" in entry.reason
        assert sealed.run_dir.exists()


class TestRetentionBackups:
    def test_keeps_current_canonical_state_and_newest_backup_but_prunes_old_ones(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        backup_old = profile / "memories.bak-20260101T000000000000-00000001"
        backup_old.mkdir()
        (backup_old / "MEMORY.md").write_text("old memory\n")
        backup_newest = profile / "memories.bak-20260201T000000000000-00000002"
        backup_newest.mkdir()
        (backup_newest / "MEMORY.md").write_text("newer memory\n")
        db_backup_old = profile / "state.db.bak-20260101T000000000000-00000003"
        shutil.copy2(profile / "state.db", db_backup_old)
        db_backup_newest = profile / "state.db.bak-20260201T000000000000-00000004"
        shutil.copy2(profile / "state.db", db_backup_newest)

        now = datetime(2026, 6, 1, tzinfo=timezone.utc)

        # Dry run reports but deletes nothing.
        dry = apply_retention(assembler, now=now, dry_run=True)
        assert {e.path for e in dry.entries if e.decision == "prune"} == {
            str(backup_old),
            str(db_backup_old),
        }
        assert backup_old.exists() and db_backup_old.exists()

        wet = apply_retention(assembler, now=now, dry_run=False)
        by_path = {entry.path: entry for entry in wet.entries}

        # Old backups beyond the window are pruned and recorded as deleted.
        assert by_path[str(backup_old)].decision == "prune"
        assert by_path[str(backup_old)].rule == "backup_expired"
        assert by_path[str(backup_old)].deleted is True
        assert by_path[str(db_backup_old)].decision == "prune"
        assert not backup_old.exists()
        assert not db_backup_old.exists()

        # The newest backup of each canonical target is never pruned.
        newest_entry = by_path[str(backup_newest)]
        assert newest_entry.decision == "keep"
        assert newest_entry.rule == "backup_newest"
        assert backup_newest.exists()

        # The current canonical project-role state is untouched.
        assert (profile / "memories" / "MEMORY.md").read_text() == (
            "# Memory\nPrior conclusion.\n"
        )
        conn = sqlite3.connect(profile / "state.db")
        rows = conn.execute("SELECT content FROM sessions").fetchall()
        conn.close()
        assert rows == [("old session",)]

    def test_keeps_a_backup_within_the_window(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        young = profile / "memories.bak-20260401T000000000000-00000004"
        young.mkdir()
        (young / "MEMORY.md").write_text("recent\n")
        newest = profile / "memories.bak-20260501T000000000000-00000005"
        newest.mkdir()
        (newest / "MEMORY.md").write_text("newest\n")

        report = apply_retention(
            assembler,
            now=datetime(2026, 6, 1, tzinfo=timezone.utc),
            dry_run=False,
        )
        assert _entry(report, young).decision == "keep"
        assert _entry(report, young).rule == "backup_young"
        assert _entry(report, newest).rule == "backup_newest"
        assert young.exists() and newest.exists()

    def test_injectable_backup_window(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        old = profile / "memories.bak-20260101T000000000000-00000006"
        old.mkdir()
        (old / "MEMORY.md").write_text("old\n")
        newest = profile / "memories.bak-20260501T000000000000-00000007"
        newest.mkdir()
        (newest / "MEMORY.md").write_text("newest\n")
        now = datetime(2026, 6, 1, tzinfo=timezone.utc)

        wide = apply_retention(assembler, now=now, dry_run=False, backup_days=365)
        assert _entry(wide, old).decision == "keep"
        assert _entry(wide, newest).decision == "keep"

        narrow = apply_retention(assembler, now=now, dry_run=False, backup_days=30)
        assert _entry(narrow, old).decision == "prune"
        assert _entry(narrow, newest).decision == "keep"
        assert not old.exists()
        assert newest.exists()


class TestRetentionReport:
    def test_report_to_dict_records_candidates_and_decisions(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed = _seal(assembler)
        assembler.store.create_launch_record(
            launch_id="launch-001",
            seal_id=sealed.seal_id,
            invocation_id=sealed.invocation_id,
            launched_at=isoformat_utc(utc_now()),
        )
        report = apply_retention(assembler, dry_run=True)
        assert isinstance(report, RetentionReport)
        document = report.to_dict()
        assert document["dry_run"] is True
        assert document["now"].endswith("Z")
        run_entry = next(
            item
            for item in document["entries"]
            if item["path"] == str(sealed.run_dir)
        )
        assert set(run_entry) == {
            "path",
            "rule",
            "age_days",
            "decision",
            "reason",
            "deleted",
        }
        assert run_entry["rule"] == "run_running"
        assert run_entry["decision"] == "keep"
        assert run_entry["age_days"] is not None
        assert run_entry["deleted"] is False
        assert report.prune_paths == ()
        assert str(sealed.run_dir) in report.kept_paths


def _entry(report: RetentionReport, path: Path):
    matches = [entry for entry in report.entries if entry.path == str(path)]
    assert len(matches) == 1, f"expected exactly one entry for {path}"
    return matches[0]
