"""WP-D2b tests: run preflight service (Block 3, one concern).

Covers the eight independent checks over an already-sealed run packet:
hermes executable + version, role asset digests, selected memory/session
state, run paths and permissions, free disk space, project-role state
lock ownership, task brief presence, and the expected output contract —
each with a positive and a negative case, plus lookup-by-invocation-id
and report semantics.  Uses tmp_path fixtures — no real Hermes required.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from method_hub.application.run_preflight import (
    DEFAULT_MIN_FREE_BYTES,
    FAIL,
    PASS,
    WARNING,
    PreflightCheck,
    PreflightReport,
    run_preflight,
)
from method_hub.application.run_profile_assembler import (
    HermesProbe,
    ManifestDigestError,
    RunProfileAssembler,
    RunSealError,
    RunSealStore,
    _default_hermes_probe,
)
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.configuration.skill_installer import directory_sha256
from method_hub.profiles.project_profiles import MemoryPolicy, project_role_profile_name
from method_hub.storage.database import Database
from method_hub.storage.migrations import HUB_MIGRATIONS

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources" / "team"
SKILL_BUNDLE = ROOT / "resources" / "skills"

RECORDED_VERSION = "9.9.9"


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


@pytest.fixture
def hermes_root(tmp_path: Path) -> Path:
    root = tmp_path / "hermes"
    root.mkdir()
    return root


def _make_fake_hermes(tmp_path: Path, version: str = RECORDED_VERSION) -> Path:
    """A real executable script that answers ``--version``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / "hermes"
    exe.write_text(f"#!/bin/sh\nprintf '{version}'\n", encoding="utf-8")
    exe.chmod(0o755)
    return exe


@pytest.fixture
def fake_hermes(tmp_path: Path) -> Path:
    return _make_fake_hermes(tmp_path)


@pytest.fixture
def assembler(
    tmp_path: Path,
    database: Database,
    catalog: RoleResourceCatalog,
    hermes_root: Path,
    fake_hermes: Path,
) -> RunProfileAssembler:
    """Assembler whose seal records the existing fake executable."""
    return RunProfileAssembler(
        data_root=tmp_path / "data",
        role_resources=catalog,
        database=database,
        bundle_root=SKILL_BUNDLE,
        hermes_root=hermes_root,
        hermes_binary="hermes",
        hermes_probe=lambda binary: HermesProbe(str(fake_hermes), RECORDED_VERSION),
    )


def _project_profile_dir(hermes_root: Path, project_id: str, role: str) -> Path:
    return hermes_root / "profiles" / project_role_profile_name(project_id, role)


@pytest.fixture
def project_profile(hermes_root: Path) -> Path:
    """A persistent project-role profile with promoted memory + state.db."""
    profile = _project_profile_dir(hermes_root, "proj-001", "theorist")
    memories = profile / "memories"
    memories.mkdir(parents=True)
    (memories / "MEMORY.md").write_text("# Memory\nPrior conclusion from P2.\n")
    (memories / "USER.md").write_text("# User\nResearcher.\n")
    _create_state_db(profile, rows=2)
    return profile


def _create_state_db(profile_dir: Path, *, rows: int = 3) -> Path:
    """Build a small real Hermes-like session store in *profile_dir*."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    db_path = profile_dir / "state.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, source TEXT)"
        )
        conn.executemany(
            "INSERT INTO sessions (id, title, source) VALUES (?, ?, ?)",
            [(f"s{i}", f"Session {i}", "cli") for i in range(rows)],
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


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
            {"output_id": "out-1", "kind": "scientific_record", "required": True},
        ],
        memory_policy=MemoryPolicy.PERSISTENT,
    )
    kwargs.update(overrides)
    return kwargs


def _report_check(report: PreflightReport, name: str) -> PreflightCheck:
    check = report.check(name)
    assert check is not None, f"missing check {name!r}"
    return check


# --------------------------------------------------------------------------- #
# Hermes executable + version (ADR-012 item 8)                                 #
# --------------------------------------------------------------------------- #


class TestHermesExecutable:
    def test_recorded_executable_still_matches(
        self, assembler: RunProfileAssembler, fake_hermes: Path
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                str(fake_hermes), RECORDED_VERSION
            ),
        )
        check = _report_check(report, "hermes_executable")
        assert check.status == PASS
        assert RECORDED_VERSION in check.detail

    def test_real_probe_matches_recorded_version(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(assembler, sealed)  # real --version subprocess
        check = _report_check(report, "hermes_executable")
        assert check.status == PASS

    def test_changed_hermes_version_detected(
        self, assembler: RunProfileAssembler, fake_hermes: Path
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                str(fake_hermes), "9.9.10"
            ),
        )
        check = _report_check(report, "hermes_executable")
        assert check.status == FAIL
        assert RECORDED_VERSION in check.detail
        assert "9.9.10" in check.detail
        assert report.passed is False

    def test_recorded_executable_missing_fails(
        self, tmp_path: Path, database: Database, catalog: RoleResourceCatalog
    ) -> None:
        # The seal records /fake/hermes, which never exists on disk.
        assembler = RunProfileAssembler(
            data_root=tmp_path / "data",
            role_resources=catalog,
            database=database,
            bundle_root=SKILL_BUNDLE,
            hermes_probe=lambda binary: HermesProbe("/fake/hermes", RECORDED_VERSION),
        )
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler,
            sealed,
            hermes_probe=lambda binary: HermesProbe("/fake/hermes", RECORDED_VERSION),
        )
        check = _report_check(report, "hermes_executable")
        assert check.status == FAIL
        assert "no longer exists" in check.detail

    def _seal_with_real_format_version(
        self, tmp_path, database, catalog, hermes_root, recorded: str, probed: str
    ) -> tuple[RunProfileAssembler, Any]:
        exe = _make_fake_hermes(tmp_path, version=probed)
        assembler = RunProfileAssembler(
            data_root=tmp_path / "data",
            role_resources=catalog,
            database=database,
            bundle_root=SKILL_BUNDLE,
            hermes_root=hermes_root,
            hermes_binary=str(exe),
            hermes_probe=lambda binary: HermesProbe(str(exe), recorded),
        )
        return assembler, assembler.seal_invocation(**_seal_kwargs())

    def test_update_check_noise_is_not_drift(
        self, tmp_path: Path, database: Database, catalog: RoleResourceCatalog,
        hermes_root: Path,
    ) -> None:
        """hermes --version embeds update-check state (upstream head hash and
        an "Update available" notice) that varies between probes without the
        binary changing; drift detection keys on the stable build identity
        (ELD pilot finding)."""
        recorded = (
            "Hermes Agent v0.19.0 (2026.7.20) · upstream 43717123\n"
            "Install directory: /home/tez/.hermes/hermes-agent\n"
            "Update available: 2763 commits behind"
        )
        probed = (
            "Hermes Agent v0.19.0 (2026.7.20) · upstream 36cb5ae5\n"
            "Install directory: /home/tez/.hermes/hermes-agent\n"
        )
        assembler, sealed = self._seal_with_real_format_version(
            tmp_path, database, catalog, hermes_root, recorded, probed
        )
        report = run_preflight(assembler, sealed)  # real subprocess probe
        check = _report_check(report, "hermes_executable")
        assert check.status == PASS
        assert "v0.19.0" in check.detail

    def test_build_version_change_is_drift(
        self, tmp_path: Path, database: Database, catalog: RoleResourceCatalog,
        hermes_root: Path,
    ) -> None:
        recorded = "Hermes Agent v0.19.0 (2026.7.20) · upstream 43717123"
        probed = "Hermes Agent v0.20.0 (2026.8.1) · upstream 36cb5ae5"
        assembler, sealed = self._seal_with_real_format_version(
            tmp_path, database, catalog, hermes_root, recorded, probed
        )
        report = run_preflight(assembler, sealed)
        check = _report_check(report, "hermes_executable")
        assert check.status == FAIL
        assert "v0.19.0" in check.detail and "v0.20.0" in check.detail


# --------------------------------------------------------------------------- #
# Role asset digests                                                           #
# --------------------------------------------------------------------------- #


class TestRoleAssets:
    def test_role_assets_match_manifest(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "role_assets")
        assert check.status == PASS
        assert "verified" in check.detail

    def test_tampered_soul_digest_detected(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        soul = sealed.run_dir / "profile" / "SOUL.md"
        soul.write_text(soul.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "role_assets")
        assert check.status == FAIL
        assert "SOUL.md" in check.detail
        assert "recorded" in check.detail and "found" in check.detail
        assert report.passed is False

    def test_tampered_skill_digest_detected(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        skill = next(
            (sealed.run_dir / "profile" / "skills").iterdir()
        )
        (skill / "SKILL.md").write_text("# altered skill content\n", encoding="utf-8")
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "role_assets")
        assert check.status == FAIL
        assert "skills/" in check.detail


# --------------------------------------------------------------------------- #
# Selected state (memory + session snapshot)                                   #
# --------------------------------------------------------------------------- #


class TestSelectedState:
    def test_memory_and_session_state_match(
        self, assembler: RunProfileAssembler, project_profile: Path
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        # The persistent seal snapshotted both memory and state.db.
        assert sealed.manifest["session_snapshot"]["sha256"]
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "selected_state")
        assert check.status == PASS
        assert "memories" in check.detail
        assert "state.db" in check.detail

    def test_fresh_memory_state_matches(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(
            **_seal_kwargs(memory_policy=MemoryPolicy.EPHEMERAL)
        )
        assert sealed.manifest["memory_snapshot"]["identity"] == "fresh"
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "selected_state")
        assert check.status == PASS

    def test_tampered_memory_detected(
        self, assembler: RunProfileAssembler, project_profile: Path
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        memories = sealed.run_dir / "profile" / "memories"
        (memories / "MEMORY.md").write_text(
            "# Memory\ntampered conclusion.\n", encoding="utf-8"
        )
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "selected_state")
        assert check.status == FAIL
        assert "memories digest mismatch" in check.detail
        assert report.passed is False

    def test_tampered_session_snapshot_detected(
        self, assembler: RunProfileAssembler, project_profile: Path
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        state_db = sealed.run_dir / "profile" / "state.db"
        state_db.write_bytes(state_db.read_bytes() + b"tampered")
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "selected_state")
        assert check.status == FAIL
        assert "state.db digest mismatch" in check.detail


# --------------------------------------------------------------------------- #
# Paths and permissions                                                        #
# --------------------------------------------------------------------------- #


class TestPathsPermissions:
    def test_layout_present_and_writable(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "paths_permissions")
        assert check.status == PASS

    def test_unwritable_outputs_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        outputs = sealed.run_dir / "outputs"
        outputs.chmod(0o500)
        try:
            report = run_preflight(
                assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                    "/x", RECORDED_VERSION
                ),
            )
        finally:
            outputs.chmod(0o700)
        check = _report_check(report, "paths_permissions")
        assert check.status == FAIL
        assert "outputs" in check.detail
        assert report.passed is False

    def test_missing_subdirectory_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        (sealed.run_dir / "logs").rmdir()
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "paths_permissions")
        assert check.status == FAIL
        assert "logs" in check.detail


# --------------------------------------------------------------------------- #
# Free space                                                                   #
# --------------------------------------------------------------------------- #


class TestFreeSpace:
    def test_sufficient_free_space_passes(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler, sealed, min_free_bytes=1, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "free_space")
        assert check.status == PASS
        assert "bytes free" in check.detail

    def test_insufficient_free_space_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler,
            sealed,
            min_free_bytes=10**18,
            hermes_probe=lambda binary: HermesProbe("/x", RECORDED_VERSION),
        )
        check = _report_check(report, "free_space")
        assert check.status == FAIL
        assert report.passed is False

    def test_default_minimum_is_512_mib(self) -> None:
        assert DEFAULT_MIN_FREE_BYTES == 512 * 1024 * 1024


# --------------------------------------------------------------------------- #
# Lock ownership                                                               #
# --------------------------------------------------------------------------- #


class TestLockOwnership:
    def _profile_name(self, assembler: RunProfileAssembler, sealed: Any) -> str:
        return sealed.manifest["state_lock"]["profile_name"]

    def test_lock_held_by_this_invocation_passes(
        self, assembler: RunProfileAssembler, database: Database
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        store = RunSealStore(database)
        profile_name = self._profile_name(assembler, sealed)
        token = store.issue_fencing_token("inv-001").token
        store.acquire_state_lock(
            profile_name=profile_name, invocation_id="inv-001", token=token
        )
        try:
            report = run_preflight(
                assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                    "/x", RECORDED_VERSION
                ),
            )
        finally:
            store.release_state_lock(
                profile_name, expected_invocation_id="inv-001", expected_token=token
            )
        check = _report_check(report, "lock_ownership")
        assert check.status == PASS
        assert "this invocation" in check.detail

    def test_foreign_lock_holder_fails(
        self, assembler: RunProfileAssembler, database: Database
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        store = RunSealStore(database)
        profile_name = self._profile_name(assembler, sealed)
        token = store.issue_fencing_token("inv-intruder").token
        store.acquire_state_lock(
            profile_name=profile_name,
            invocation_id="inv-intruder",
            token=token,
        )
        try:
            report = run_preflight(
                assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                    "/x", RECORDED_VERSION
                ),
            )
        finally:
            store.release_state_lock(profile_name)
        check = _report_check(report, "lock_ownership")
        assert check.status == FAIL
        assert "inv-intruder" in check.detail
        assert report.passed is False

    def test_expired_and_reacquired_foreign_lock_fails(
        self, assembler: RunProfileAssembler, database: Database
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        store = RunSealStore(database)
        profile_name = self._profile_name(assembler, sealed)
        # First holder acquires, then its lease expires.
        store.acquire_state_lock(
            profile_name=profile_name,
            invocation_id="inv-first",
            token=store.issue_fencing_token("inv-first").token,
        )
        with database.transaction() as conn:
            conn.execute(
                "UPDATE project_role_state_locks SET lease_expires_at = ? "
                "WHERE profile_name = ?",
                ("2000-01-01T00:00:00+00:00", profile_name),
            )
        # A foreign invocation reacquires the expired lock.
        store.acquire_state_lock(
            profile_name=profile_name,
            invocation_id="inv-second",
            token=store.issue_fencing_token("inv-second").token,
        )
        try:
            report = run_preflight(
                assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                    "/x", RECORDED_VERSION
                ),
            )
        finally:
            store.release_state_lock(profile_name)
        check = _report_check(report, "lock_ownership")
        assert check.status == FAIL
        assert "inv-second" in check.detail

    def test_no_lock_warns_but_overall_passes(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        # The seal released the lock on exit; nothing else holds it.
        assert assembler.store.state_lock_holder(
            sealed.manifest["state_lock"]["profile_name"]
        ) is None
        report = run_preflight(
            assembler, sealed, min_free_bytes=1, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "lock_ownership")
        assert check.status == WARNING
        assert report.passed is True  # warnings do not fail the run
        assert report.warnings == 1


# --------------------------------------------------------------------------- #
# Task brief                                                                   #
# --------------------------------------------------------------------------- #


class TestTaskBrief:
    def test_task_brief_present_passes(
        self, assembler: RunProfileAssembler, tmp_path: Path
    ) -> None:
        brief = tmp_path / "brief.md"
        brief.write_text("# Task\nProduce the protocol.\n", encoding="utf-8")
        sealed = assembler.seal_invocation(
            **_seal_kwargs(user_choices={"task_brief": str(brief)})
        )
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "task_brief")
        assert check.status == PASS
        assert str(brief) in check.detail

    def test_no_declared_brief_passes(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "task_brief")
        assert check.status == PASS
        assert "no task brief declared" in check.detail

    def test_missing_task_brief_fails(
        self, assembler: RunProfileAssembler, tmp_path: Path
    ) -> None:
        missing = tmp_path / "never-written.md"
        sealed = assembler.seal_invocation(
            **_seal_kwargs(user_choices={"task_brief": str(missing)})
        )
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "task_brief")
        assert check.status == FAIL
        assert "missing" in check.detail
        assert report.passed is False

    def test_symlinked_task_brief_fails(
        self, assembler: RunProfileAssembler, tmp_path: Path
    ) -> None:
        real = tmp_path / "real-brief.md"
        real.write_text("# Task\n", encoding="utf-8")
        link = tmp_path / "linked-brief.md"
        link.symlink_to(real)
        sealed = assembler.seal_invocation(
            **_seal_kwargs(user_choices={"task_brief": str(link)})
        )
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "task_brief")
        assert check.status == FAIL
        assert "symlink" in check.detail

    def test_empty_task_brief_fails(
        self, assembler: RunProfileAssembler, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty-brief.md"
        empty.write_text("", encoding="utf-8")
        sealed = assembler.seal_invocation(
            **_seal_kwargs(user_choices={"task_brief": str(empty)})
        )
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "task_brief")
        assert check.status == FAIL
        assert "empty" in check.detail


# --------------------------------------------------------------------------- #
# Expected output contract                                                     #
# --------------------------------------------------------------------------- #


class TestOutputContract:
    def test_declared_relative_outputs_pass(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(
            **_seal_kwargs(
                expected_outputs=[
                    {
                        "output_id": "out-1",
                        "relative_path": "roles/01-data_analyst/protocol.json",
                        "required": True,
                    },
                    {
                        "output_id": "out-2",
                        "relative_path": "notes.md",
                        "required": False,
                    },
                ]
            )
        )
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "output_contract")
        assert check.status == PASS
        assert "2 declared" in check.detail

    def test_path_alias_key_accepted(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(
            **_seal_kwargs(
                expected_outputs=[
                    {"output_id": "out-1", "path": "alias-output.json"},
                ]
            )
        )
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "output_contract")
        assert check.status == PASS

    def test_entries_without_declared_path_pass(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "output_contract")
        assert check.status == PASS
        assert "no declared expected output paths" in check.detail

    def test_dotdot_escape_rejected(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(
            **_seal_kwargs(
                expected_outputs=[
                    {"output_id": "out-1", "relative_path": "../escape.json"},
                ]
            )
        )
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "output_contract")
        assert check.status == FAIL
        assert "escape" in check.detail
        assert report.passed is False

    def test_absolute_output_path_rejected(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(
            **_seal_kwargs(
                expected_outputs=[
                    {"output_id": "out-1", "relative_path": "/etc/passwd"},
                ]
            )
        )
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "output_contract")
        assert check.status == FAIL
        assert "absolute" in check.detail

    def test_preexisting_expected_output_fails(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(
            **_seal_kwargs(
                expected_outputs=[
                    {"output_id": "out-1", "relative_path": "contaminated.json"},
                ]
            )
        )
        (sealed.run_dir / "outputs" / "contaminated.json").write_text(
            "{}", encoding="utf-8"
        )
        report = run_preflight(
            assembler, sealed, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        check = _report_check(report, "output_contract")
        assert check.status == FAIL
        assert "already exists" in check.detail


# --------------------------------------------------------------------------- #
# Lookup, manifest integrity, and report semantics                             #
# --------------------------------------------------------------------------- #


class TestLookupAndReport:
    def test_preflight_by_invocation_id(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler, "inv-001", min_free_bytes=1, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        assert report.invocation_id == "inv-001"
        assert report.seal_id == sealed.seal_id
        assert report.passed is True

    def test_unknown_invocation_raises(
        self, assembler: RunProfileAssembler
    ) -> None:
        with pytest.raises(RunSealError, match="No sealed run"):
            run_preflight(assembler, "inv-unknown")

    def test_tampered_manifest_detected_on_lookup(
        self, assembler: RunProfileAssembler
    ) -> None:
        assembler.seal_invocation(**_seal_kwargs())
        manifest_path = assembler.run_dir_for("inv-001") / "manifest" / "manifest.json"
        original = manifest_path.read_text(encoding="utf-8")
        manifest_path.write_text(original.replace('"phase": "P3"', '"phase": "P9"'))
        try:
            with pytest.raises(ManifestDigestError):
                run_preflight(assembler, "inv-001")
        finally:
            manifest_path.write_text(original)

    def test_report_shape_and_pass_semantics(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        report = run_preflight(
            assembler, sealed, min_free_bytes=1, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        assert len(report.checks) == 8
        assert report.failed == 0
        assert report.warnings == 1  # no lock held
        assert report.passed is True

        document = report.to_dict()
        assert document["invocation_id"] == "inv-001"
        assert document["passed"] is True
        assert document["warnings"] == ["lock_ownership"]
        assert document["failed_checks"] == []
        assert {item["name"] for item in document["checks"]} == {
            "hermes_executable",
            "role_assets",
            "selected_state",
            "paths_permissions",
            "free_space",
            "lock_ownership",
            "task_brief",
            "output_contract",
        }
        assert all(
            item["status"] in (PASS, FAIL, WARNING) for item in document["checks"]
        )

    def test_any_failed_check_fails_the_run(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        (sealed.run_dir / "profile" / "SOUL.md").write_text(
            "tampered", encoding="utf-8"
        )
        report = run_preflight(
            assembler, sealed, min_free_bytes=1, hermes_probe=lambda binary: HermesProbe(
                "/x", RECORDED_VERSION
            ),
        )
        assert report.passed is False
        document = report.to_dict()
        assert "role_assets" in document["failed_checks"]
        # A warning does not rescue a failed run.
        assert document["warnings"] == ["lock_ownership"]
