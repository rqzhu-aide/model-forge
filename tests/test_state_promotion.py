"""WP-E2 tests: allowlisted memory/session state promotion (Block 5).

Covers the full ``promote_run_state`` protocol: the four gates (succeeded
launch, passing WP-E1 validation, non-ephemeral non-read-only policy, state
lock); memory-before and runtime-after digest inventories; allowlisted
staging (never SOUL, skills, base configuration, secrets, logs, or caches);
the atomic replace with last-known-good preservation; the Block 5 checkpoint
(injected failure at every promotion step leaves the previous canonical state
byte-identical); lock exclusion; and first-promotion with no pre-existing
canonical memories.  Uses tmp_path fixtures — no real Hermes required.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from model_forge.application import state_promotion
from model_forge.application.output_validation import validate_run_outputs
from model_forge.application.run_profile_assembler import (
    HermesProbe,
    RunProfileAssembler,
    RunSealError,
    SealedRun,
    StateLockHeld,
)
from model_forge.application.state_promotion import (
    LaunchNotSucceededError,
    MemoryPolicyNotPromotableError,
    PromotionResult,
    PromotionStagingError,
    PromotionTargetResult,
    ValidationNotPassedError,
    promote_run_state,
)
from model_forge.configuration.resources import RoleResourceCatalog
from model_forge.domain.runs import isoformat_utc, utc_now
from model_forge.profiles.project_profiles import MemoryPolicy, project_role_profile_name
from model_forge.storage.database import Database
from model_forge.storage.migrations import HUB_MIGRATIONS

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources" / "team"
SKILL_BUNDLE = ROOT / "resources" / "skills"

FAKE_HERMES = HermesProbe("/fake/hermes", "9.9.9")


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


def _canonical_dir(hermes_root: Path, project_id: str = "proj-001", role: str = "theorist") -> Path:
    return hermes_root / "profiles" / project_role_profile_name(project_id, role)


def _seal_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(
        invocation_id="inv-001",
        idempotency_key="key-001",
        project_id="proj-001",
        role="theorist",
        phase="P3",
        method_identity={"method_id": "mf-1", "version": "1.0"},
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


def _seal(assembler: RunProfileAssembler, **overrides: Any) -> SealedRun:
    return assembler.seal_invocation(**_seal_kwargs(**overrides))


def _make_state_db(path: Path, sessions: list[tuple[str, str]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, content TEXT)")
    for session_id, content in sessions or [("s-1", "old session")]:
        conn.execute(
            "INSERT INTO sessions (id, content) VALUES (?, ?)",
            (session_id, content),
        )
    conn.commit()
    conn.close()


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


def _write_memory(sealed: SealedRun, relative: str, content: str) -> Path:
    target = sealed.run_dir / "profile" / "memories" / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


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


def _setup_canonical(hermes_root: Path) -> Path:
    """A canonical project-role profile with memory and a session store."""
    profile = _canonical_dir(hermes_root)
    memories = profile / "memories"
    memories.mkdir(parents=True)
    (memories / "MEMORY.md").write_text("# Memory\nPrior conclusion.\n")
    _make_state_db(profile / "state.db", [("s-1", "old session")])
    return profile


def _simulate_run_work(sealed: SealedRun) -> None:
    """Simulate Hermes having written new memory and session state."""
    _write_memory(sealed, "MEMORY.md", "# Memory\nNew conclusion from P3.\n")
    _write_memory(sealed, "NOTES.md", "# Notes\nFresh analysis.\n")
    _append_session(sealed.run_dir / "profile" / "state.db", "s-2", "new session")


def _snapshot_tree(root: Path) -> dict[str, str]:
    """Full structural + content snapshot: byte-for-byte comparable."""
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = "symlink:" + os.readlink(path)
        elif path.is_dir():
            snapshot[relative + "/"] = "dir"
        elif path.is_file():
            snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def _assert_clean_failed_promotion(
    profile: Path, before: dict[str, str], assembler: RunProfileAssembler
) -> None:
    """A refused/failed promotion changed NOTHING on disk or in the DB."""
    assert _snapshot_tree(profile) == before
    leftovers = [
        path.name
        for path in profile.iterdir()
        if path.name.startswith(".promotion-staging-")
        or ".bak-" in path.name
    ]
    assert leftovers == []
    assert assembler.store.list_promotion_records() == []


def _promotable_run(
    assembler: RunProfileAssembler, hermes_root: Path
) -> tuple[SealedRun, Path, dict[str, str]]:
    """Canonical state + sealed persistent run + execution + green gates."""
    profile = _setup_canonical(hermes_root)
    before = _snapshot_tree(profile)
    sealed = _seal(assembler)
    _simulate_run_work(sealed)
    launch_id = _close_launch(assembler, sealed)
    _record_validation(assembler, sealed, launch_id)
    return sealed, profile, before


# --------------------------------------------------------------------------- #
# (a) Happy path                                                              #
# --------------------------------------------------------------------------- #


class TestHappyPath:
    def test_promotion_replaces_memory_and_session_with_backups_and_record(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed, profile, _ = _promotable_run(assembler, hermes_root)
        run_memories = sealed.run_dir / "profile" / "memories"
        run_state_db = sealed.run_dir / "profile" / "state.db"

        result = promote_run_state(assembler, sealed)

        assert isinstance(result, PromotionResult)
        assert result.promoted is True
        assert result.seal_id == sealed.seal_id
        assert result.invocation_id == "inv-001"
        assert result.project_id == "proj-001"
        assert result.role == "theorist"

        # Inventories: memory-before from canonical, runtime-after from run.
        before_paths = {e.relative_path for e in result.memory_before_inventory}
        assert before_paths == {"MEMORY.md"}
        after_paths = {e.relative_path for e in result.runtime_after_inventory}
        assert after_paths == {"MEMORY.md", "NOTES.md", "state.db"}
        assert all(e.sha256 for e in result.runtime_after_inventory)

        # Both targets promoted with before/after digests and backups.
        by_name = {t.name: t for t in result.targets}
        assert set(by_name) == {"memories", "state.db"}
        for target in result.targets:
            assert isinstance(target, PromotionTargetResult)
            assert target.before_digest is not None
            assert target.after_digest is not None
            assert target.after_digest != target.before_digest
            assert target.backup_path is not None
            assert Path(target.backup_path).is_dir() or Path(target.backup_path).is_file()

        # Canonical memories/ now byte-for-byte equal the run memories.
        assert _snapshot_tree(profile / "memories") == _snapshot_tree(run_memories)
        assert (profile / "memories" / "MEMORY.md").read_text() == (
            "# Memory\nNew conclusion from P3.\n"
        )
        # Canonical state.db replaced by the run's session store.
        assert (
            hashlib.sha256((profile / "state.db").read_bytes()).hexdigest()
            == hashlib.sha256(run_state_db.read_bytes()).hexdigest()
        )

        # Backups preserve the last known good state.
        backups = sorted(profile.glob("*.bak-*"))
        backup_names = [path.name for path in backups]
        assert any(name.startswith("memories.bak-") for name in backup_names)
        assert any(name.startswith("state.db.bak-") for name in backup_names)
        memories_backup = next(
            path for path in backups if path.name.startswith("memories.bak-")
        )
        assert (memories_backup / "MEMORY.md").read_text() == (
            "# Memory\nPrior conclusion.\n"
        )
        state_backup = next(
            path for path in backups if path.name.startswith("state.db.bak-")
        )
        conn = sqlite3.connect(state_backup)
        rows = conn.execute("SELECT content FROM sessions").fetchall()
        conn.close()
        assert rows == [("old session",)]

        # Promotion record proves what happened.
        record = assembler.store.find_promotion_record_by_invocation("inv-001")
        assert record is not None
        assert record["status"] == "succeeded"
        assert record["seal_id"] == sealed.seal_id
        assert record["invocation_id"] == "inv-001"
        before_json = json.loads(record["before_digest"])
        after_json = json.loads(record["after_digest"])
        backups_json = json.loads(record["backup_paths"])
        assert before_json["memories"] == by_name["memories"].before_digest
        assert after_json["state.db"] == by_name["state.db"].after_digest
        assert backups_json["memories"] == by_name["memories"].backup_path

        # to_dict round-trips the essentials.
        document = result.to_dict()
        assert document["promoted"] is True
        assert document["targets"][0]["name"] in ("memories", "state.db")

    def test_promote_by_invocation_id_string(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed, profile, _ = _promotable_run(assembler, hermes_root)
        result = promote_run_state(assembler, sealed.invocation_id)
        assert result.promoted is True
        assert result.invocation_id == sealed.invocation_id
        assert (profile / "memories" / "MEMORY.md").read_text() == (
            "# Memory\nNew conclusion from P3.\n"
        )

    def test_promotion_without_run_session_keeps_only_memory_target(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _canonical_dir(hermes_root)
        (profile / "memories").mkdir(parents=True)
        (profile / "memories" / "MEMORY.md").write_text("old\n")
        sealed = _seal(assembler)
        _write_memory(sealed, "MEMORY.md", "new\n")
        # No state.db anywhere: a first run that never wrote sessions.
        assert not (sealed.run_dir / "profile" / "state.db").exists()
        launch_id = _close_launch(assembler, sealed)
        _record_validation(assembler, sealed, launch_id)

        result = promote_run_state(assembler, sealed)

        assert {t.name for t in result.targets} == {"memories"}
        assert (profile / "memories" / "MEMORY.md").read_text() == "new\n"
        assert not (profile / "state.db").exists()


# --------------------------------------------------------------------------- #
# (b) Gate matrix                                                             #
# --------------------------------------------------------------------------- #


class TestGateMatrix:
    def test_failed_launch_promotes_nothing(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        before = _snapshot_tree(profile)
        sealed = _seal(assembler)
        _simulate_run_work(sealed)
        launch_id = _close_launch(assembler, sealed, status="failed")
        _record_validation(assembler, sealed, launch_id)  # even a pass report

        with pytest.raises(LaunchNotSucceededError):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)

    def test_cancelled_launch_promotes_nothing(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        before = _snapshot_tree(profile)
        sealed = _seal(assembler)
        launch_id = _close_launch(assembler, sealed, status="cancelled")
        _record_validation(assembler, sealed, launch_id)

        with pytest.raises(LaunchNotSucceededError):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)

    def test_running_launch_promotes_nothing(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        before = _snapshot_tree(profile)
        sealed = _seal(assembler)
        assembler.store.create_launch_record(
            launch_id="launch-001",
            seal_id=sealed.seal_id,
            invocation_id=sealed.invocation_id,
            launched_at=isoformat_utc(utc_now()),
        )  # stays 'running'

        with pytest.raises(LaunchNotSucceededError):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)

    def test_failing_validation_promotes_nothing(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        before = _snapshot_tree(profile)
        sealed = _seal(assembler)
        _simulate_run_work(sealed)
        launch_id = _close_launch(assembler, sealed)
        _record_validation(assembler, sealed, launch_id, verdict="fail")

        with pytest.raises(ValidationNotPassedError):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)

    def test_missing_validation_report_promotes_nothing(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        before = _snapshot_tree(profile)
        sealed = _seal(assembler)
        _simulate_run_work(sealed)
        _close_launch(assembler, sealed)
        # No validation report recorded at all.

        with pytest.raises(ValidationNotPassedError):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)

    def test_ephemeral_reviewer_run_promotes_nothing(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        before = _snapshot_tree(profile)
        # The outside reviewer is always ephemeral per WP-D1.
        sealed = _seal(assembler, role="outside_reviewer", invocation_id="inv-001")
        assert sealed.manifest["memory_snapshot"]["policy"] == "ephemeral"
        launch_id = _close_launch(assembler, sealed)
        _record_validation(assembler, sealed, launch_id)

        with pytest.raises(MemoryPolicyNotPromotableError):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)

    def test_read_only_run_promotes_nothing(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        before = _snapshot_tree(profile)
        sealed = _seal(assembler, memory_policy=MemoryPolicy.READ_ONLY)
        assert sealed.manifest["memory_snapshot"]["policy"] == "read_only"
        launch_id = _close_launch(assembler, sealed)
        _record_validation(assembler, sealed, launch_id)

        with pytest.raises(MemoryPolicyNotPromotableError):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)

    def test_unknown_seal_refuses(self, assembler: RunProfileAssembler) -> None:
        with pytest.raises(RunSealError):
            promote_run_state(assembler, "inv-does-not-exist")


# --------------------------------------------------------------------------- #
# (c) Allowlist                                                               #
# --------------------------------------------------------------------------- #


class TestAllowlist:
    def test_only_memories_and_state_db_are_promoted(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        # Canonical profile carries role assets and secrets next to state.
        profile = _setup_canonical(hermes_root)
        (profile / "SOUL.md").write_text("canonical soul\n")
        skills = profile / "skills" / "marker-skill"
        skills.mkdir(parents=True)
        (skills / "SKILL.md").write_text("canonical skill\n")
        (profile / ".env").write_text("CANONICAL_SECRET=1\n")
        (profile / "auth.json").write_text('{"token": "canonical"}\n')
        before = _snapshot_tree(profile)

        sealed = _seal(assembler)
        # Plant disallowed material in the RUN profile: SOUL edits, a
        # modified skill, secrets, and stray caches at profile and memory
        # depth.
        run_profile = sealed.run_dir / "profile"
        (run_profile / "SOUL.md").write_text("run soul\n")
        run_skill = next((run_profile / "skills").glob("*/SKILL.md"))
        run_skill.write_text("run skill\n")
        (run_profile / ".env").write_text("RUN_SECRET=1\n")
        (run_profile / "cache" / "junk.tmp").write_text("cache junk\n")
        _write_memory(sealed, "MEMORY.md", "new memory\n")
        _write_memory(sealed, ".env", "EVIL_SECRET=1\n")
        launch_id = _close_launch(assembler, sealed)
        _record_validation(assembler, sealed, launch_id)

        result = promote_run_state(assembler, sealed)
        assert result.promoted is True

        # Canonical role assets and secrets are byte-identical.
        assert (profile / "SOUL.md").read_text() == "canonical soul\n"
        assert (skills / "SKILL.md").read_text() == "canonical skill\n"
        assert (profile / ".env").read_text() == "CANONICAL_SECRET=1\n"
        assert (profile / "auth.json").read_text() == '{"token": "canonical"}\n'

        # Canonical memories carry only the allowlisted run memory; no
        # secret, cache, SOUL, or skill material leaked in.
        memory_files = {
            path.relative_to(profile / "memories").as_posix()
            for path in (profile / "memories").rglob("*")
            if path.is_file()
        }
        assert memory_files == {"MEMORY.md"}
        assert (profile / "memories" / "MEMORY.md").read_text() == "new memory\n"
        assert not any(
            part in {".env", "cache", "SOUL.md", "skills"}
            for path in (profile / "memories").rglob("*")
            for part in path.relative_to(profile / "memories").parts
        )
        # The rest of the canonical profile is untouched apart from
        # memories/ and state.db (backups are new siblings).
        after = _snapshot_tree(profile)
        for relative, digest in before.items():
            if relative.startswith("memories/") or relative == "state.db":
                continue
            assert after.get(relative) == digest, relative

    def test_run_memory_symlink_refuses_promotion(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        before = _snapshot_tree(profile)
        sealed = _seal(assembler)
        _write_memory(sealed, "MEMORY.md", "new\n")
        link = sealed.run_dir / "profile" / "memories" / "escape.md"
        link.symlink_to("/etc/hostname")
        launch_id = _close_launch(assembler, sealed)
        _record_validation(assembler, sealed, launch_id)

        with pytest.raises(PromotionStagingError):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)


# --------------------------------------------------------------------------- #
# (d) The Block 5 checkpoint: injected failure at every promotion step         #
# --------------------------------------------------------------------------- #


class TestBlock5Checkpoint:
    @pytest.mark.parametrize(
        ("step_name", "target"),
        [
            ("_backup_target", "memories"),
            ("_backup_target", "state.db"),
            ("_move_into_place", "memories"),
            ("_move_into_place", "state.db"),
            ("_verify_replacement", "memories"),
            ("_verify_replacement", "state.db"),
        ],
    )
    def test_injected_step_failure_leaves_previous_state_byte_identical(
        self,
        assembler: RunProfileAssembler,
        hermes_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        step_name: str,
        target: str,
    ) -> None:
        sealed, profile, before = _promotable_run(assembler, hermes_root)

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError(f"injected failure in {step_name} for {target}")

        monkeypatch.setattr(state_promotion, step_name, _boom)

        with pytest.raises(RuntimeError, match="injected failure"):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)

    def test_injected_record_write_failure_rolls_back_completed_swap(
        self,
        assembler: RunProfileAssembler,
        hermes_root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sealed, profile, before = _promotable_run(assembler, hermes_root)

        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("injected failure writing the promotion record")

        monkeypatch.setattr(assembler.store, "record_promotion", _boom)

        with pytest.raises(RuntimeError, match="injected failure"):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)


# --------------------------------------------------------------------------- #
# (e) Lock                                                                    #
# --------------------------------------------------------------------------- #


class TestStateLock:
    def test_promotion_while_another_invocation_holds_the_lock_changes_nothing(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        sealed, profile, before = _promotable_run(assembler, hermes_root)
        with assembler.state_lock("proj-001", "theorist", "inv-holder"):
            with pytest.raises(StateLockHeld):
                promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)


# --------------------------------------------------------------------------- #
# (f) First promotion                                                         #
# --------------------------------------------------------------------------- #


class TestFirstPromotion:
    def test_first_promotion_with_no_canonical_memories_succeeds(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        # No canonical profile exists yet: this is the very first promotion.
        profile = _canonical_dir(hermes_root)
        assert not profile.exists()

        sealed = _seal(assembler)  # first run: clean memory at seal time
        _write_memory(sealed, "MEMORY.md", "first memory\n")
        _append_session(sealed.run_dir / "profile" / "state.db", "s-1", "first session")
        launch_id = _close_launch(assembler, sealed)
        _record_validation(assembler, sealed, launch_id)

        result = promote_run_state(assembler, sealed)

        assert result.promoted is True
        assert result.memory_before_inventory == ()
        assert {t.name for t in result.targets} == {"memories", "state.db"}
        by_name = {t.name: t for t in result.targets}
        assert by_name["memories"].before_digest is None
        assert by_name["memories"].backup_path is None
        assert by_name["state.db"].before_digest is None
        assert by_name["state.db"].backup_path is None

        assert (profile / "memories" / "MEMORY.md").read_text() == "first memory\n"
        assert (
            hashlib.sha256((profile / "state.db").read_bytes()).hexdigest()
            == hashlib.sha256(
                (sealed.run_dir / "profile" / "state.db").read_bytes()
            ).hexdigest()
        )
        # No backups on a first promotion; only the promoted targets exist.
        assert list(profile.glob("*.bak-*")) == []
        record = assembler.store.find_promotion_record_by_invocation("inv-001")
        assert record is not None
        assert json.loads(record["before_digest"]) == {
            "memories": None,
            "state.db": None,
        }


# --------------------------------------------------------------------------- #
# Composition with the real WP-E1 validator                                   #
# --------------------------------------------------------------------------- #

_GOOD_THEORY = {
    "basis": {"assumptions": ["a1"]},
    "representations": {"statements": []},
    "invocation_id": "inv-001",
    "run_id": "inv-001",
    "method_id": "mf-1",
}


class TestRealValidatorComposition:
    def _seal_with_outputs(self, assembler: RunProfileAssembler) -> SealedRun:
        return _seal(
            assembler,
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
        )

    def _write_output(self, sealed: SealedRun, relative: str, content: str | bytes) -> None:
        target = sealed.run_dir / "outputs" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")

    def test_promotes_after_a_real_passing_wp1_report(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        sealed = self._seal_with_outputs(assembler)
        _write_memory(sealed, "MEMORY.md", "validated memory\n")
        self._write_output(
            sealed, "p3/complete_theory.json", json.dumps(_GOOD_THEORY)
        )
        self._write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        self._write_output(sealed, "p3/fig1.pdf", b"%PDF-1.4\nfake\n")
        launch_id = _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)
        assert report.passed is True
        result = promote_run_state(assembler, sealed)
        assert result.promoted is True
        assert (profile / "memories" / "MEMORY.md").read_text() == "validated memory\n"
        assert assembler.store.find_promotion_record_by_invocation(
            "inv-001"
        ) is not None

    def test_refuses_when_the_real_wp1_report_fails(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _setup_canonical(hermes_root)
        before = _snapshot_tree(profile)
        sealed = self._seal_with_outputs(assembler)
        _simulate_run_work(sealed)
        # Missing required field: validation fails even with exit code 0.
        self._write_output(
            sealed, "p3/complete_theory.json", json.dumps({"basis": {}})
        )
        self._write_output(sealed, "p3/notes.json", json.dumps({"note": "ok"}))
        self._write_output(sealed, "p3/fig1.pdf", b"%PDF-1.4\nfake\n")
        launch_id = _close_launch(assembler, sealed)

        report = validate_run_outputs(assembler, sealed)
        assert report.passed is False
        with pytest.raises(ValidationNotPassedError):
            promote_run_state(assembler, sealed)
        _assert_clean_failed_promotion(profile, before, assembler)
