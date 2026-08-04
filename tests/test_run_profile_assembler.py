"""WP-D1 + WP-D2a tests: run-profile assembler core (Block 3, first half).

Covers: project-role state lock conflict and stale-owner rejection;
run directory layout; byte-for-byte profile assembly with recorded
digests; fresh vs persistent memory policy (reviewer always fresh);
credential exclusion everywhere in the run directory; the immutable
manifest with every required field and a stable digest; idempotent
double-sealing; and the verified SQLite session snapshot procedure
(read-only online backup, busy-source abort with seal rollback, empty
session state for fresh policy and the outside reviewer).  Uses
tmp_path fixtures — no real Hermes required.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from method_hub.application.run_profile_assembler import (
    MANIFEST_FORMAT,
    MANIFEST_FORMAT_VERSION,
    RUN_DIR_LAYOUT,
    SECRET_FILE_NAMES,
    HermesProbe,
    ManifestDigestError,
    RunProfileAssembler,
    RunSealError,
    RunSealStore,
    SealedRun,
    SessionSnapshotBusy,
    SessionSnapshotError,
    StateFencingError,
    StateLockHeld,
    _copy_tree_excluding,
    resolve_memory_policy,
)
from method_hub.application.session_snapshots import (
    SESSION_SNAPSHOT_EMPTY,
    SESSION_SNAPSHOT_PROCEDURE,
    snapshot_session_db,
)
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.configuration.skill_installer import directory_sha256
from method_hub.digests.jcs import canonicalize
from method_hub.profiles.project_profiles import (
    MemoryPolicy,
    project_role_profile_name,
)
from method_hub.storage.database import Database
from method_hub.storage.migrations import HUB_MIGRATIONS

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


def _project_profile_dir(hermes_root: Path, project_id: str, role: str) -> Path:
    return hermes_root / "profiles" / project_role_profile_name(project_id, role)


@pytest.fixture
def project_profile(hermes_root: Path) -> Path:
    """A persistent project-role profile with promoted memory and secrets."""
    profile = _project_profile_dir(hermes_root, "proj-001", "theorist")
    memories = profile / "memories"
    memories.mkdir(parents=True)
    (memories / "MEMORY.md").write_text("# Memory\nPrior conclusion from P2.\n")
    (memories / "USER.md").write_text("# User\nResearcher.\n")
    # SOUL-adjacent secret material that must never be copied.
    (profile / ".env").write_text("PROVIDER_KEY=super-secret\n")
    (profile / "auth.json").write_text('{"token": "super-secret"}\n')
    credential_pool = profile / "credential_pool"
    credential_pool.mkdir()
    (credential_pool / "pool.txt").write_text("secret-pool\n")
    (memories / "credentials.json").write_text('{"api_key": "super-secret"}\n')
    return profile


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


def _all_paths(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


# --------------------------------------------------------------------------- #
# Lock conflict and stale-owner rejection                                     #
# --------------------------------------------------------------------------- #


class TestStateLock:
    def test_second_writer_is_rejected(self, assembler: RunProfileAssembler) -> None:
        profile_name = project_role_profile_name("proj-001", "theorist")
        with assembler.state_lock("proj-001", "theorist", "inv-holder"):
            with pytest.raises(StateLockHeld) as excinfo:
                with assembler.state_lock("proj-001", "theorist", "inv-intruder"):
                    pass  # pragma: no cover
            assert excinfo.value.holder_invocation_id == "inv-holder"
            assert excinfo.value.profile_name == profile_name

    def test_seal_rejected_while_another_owner_holds_state(
        self, assembler: RunProfileAssembler, database: Database
    ) -> None:
        store = RunSealStore(database)
        profile_name = project_role_profile_name("proj-001", "theorist")
        token = store.issue_fencing_token("inv-holder").token
        store.acquire_state_lock(
            profile_name=profile_name,
            invocation_id="inv-holder",
            token=token,
        )
        try:
            with pytest.raises(StateLockHeld):
                assembler.seal_invocation(**_seal_kwargs(invocation_id="inv-002"))
        finally:
            store.release_state_lock(profile_name)

    def test_stale_owner_cannot_release_or_renew(
        self, assembler: RunProfileAssembler, database: Database
    ) -> None:
        store = RunSealStore(database)
        profile_name = project_role_profile_name("proj-001", "theorist")
        holder_token = store.issue_fencing_token("inv-holder").token
        store.acquire_state_lock(
            profile_name=profile_name,
            invocation_id="inv-holder",
            token=holder_token,
        )
        # A stale owner (old token) cannot release the current lock.
        stale_token = holder_token - 1
        store.release_state_lock(
            profile_name,
            expected_invocation_id="inv-holder",
            expected_token=stale_token,
        )
        assert store.state_lock_holder(profile_name) == "inv-holder"
        # A stale owner cannot renew either.
        with pytest.raises(StateFencingError):
            store.renew_state_lease(
                profile_name,
                invocation_id="inv-holder",
                expected_token=stale_token,
            )
        # Wrong invocation cannot renew.
        with pytest.raises(StateFencingError):
            store.renew_state_lease(
                profile_name,
                invocation_id="inv-intruder",
                expected_token=holder_token,
            )
        store.release_state_lock(
            profile_name,
            expected_invocation_id="inv-holder",
            expected_token=holder_token,
        )
        assert store.state_lock_holder(profile_name) is None

    def test_stale_fencing_token_rejected(
        self, assembler: RunProfileAssembler, database: Database
    ) -> None:
        store = RunSealStore(database)
        first = store.issue_fencing_token("inv-001")
        second = store.issue_fencing_token("inv-001")
        assert second.token == first.token + 1
        store.validate_fencing_token("inv-001", second.token)
        with pytest.raises(StateFencingError):
            store.validate_fencing_token("inv-001", first.token)


# --------------------------------------------------------------------------- #
# Directory layout                                                            #
# --------------------------------------------------------------------------- #


class TestDirectoryLayout:
    def test_seal_creates_expected_layout(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        run_dir = sealed.run_dir
        assert run_dir.is_dir()
        assert run_dir.parent == assembler.runs_root
        for name in RUN_DIR_LAYOUT:
            assert (run_dir / name).is_dir(), f"missing {name}/"
        assert (run_dir / "manifest" / "manifest.json").is_file()
        assert (run_dir / "manifest" / "manifest.sha256").is_file()
        # Under the Method Hub data root, never the Hermes root.
        assert assembler.runs_root.is_relative_to(
            assembler._data_root  # type: ignore[attr-defined]
        )

    def test_run_dir_collision_without_seal_rejected(
        self, assembler: RunProfileAssembler, tmp_path: Path
    ) -> None:
        run_dir = assembler.run_dir_for("inv-collision")
        run_dir.mkdir(parents=True)
        with pytest.raises(RunSealError):
            assembler.seal_invocation(
                **_seal_kwargs(invocation_id="inv-collision")
            )

    def test_unknown_role_rejected(self, assembler: RunProfileAssembler) -> None:
        with pytest.raises(RunSealError):
            assembler.seal_invocation(**_seal_kwargs(role="not_a_role"))


# --------------------------------------------------------------------------- #
# Profile assembly — byte-for-byte with recorded digests                      #
# --------------------------------------------------------------------------- #


class TestProfileAssembly:
    def test_profile_matches_role_definition_byte_for_byte(
        self, assembler: RunProfileAssembler, catalog: RoleResourceCatalog
    ) -> None:
        resource = catalog.role("theorist")
        sealed = assembler.seal_invocation(**_seal_kwargs())
        profile = sealed.run_dir / "profile"

        assert (profile / "SOUL.md").read_text(encoding="utf-8") == resource.soul_text
        config = resource.base_configuration
        assert (
            profile / config.file_name
        ).read_text(encoding="utf-8") == config.content
        guidance = resource.library_guidance
        assert (
            profile / guidance.file_name
        ).read_text(encoding="utf-8") == guidance.content

        for skill in resource.recommended_skills:
            installed = profile / "skills" / skill.skill_id
            source = SKILL_BUNDLE / skill.skill_id
            assert installed.is_dir()
            assert directory_sha256(installed) == directory_sha256(source)

        digests = sealed.manifest["role_definition"]["asset_digests"]
        assert digests["SOUL.md"] == hashlib.sha256(resource.soul_text.encode()).hexdigest()
        assert digests[config.file_name] == config.sha256
        assert digests[guidance.file_name] == guidance.sha256
        for skill in resource.recommended_skills:
            assert digests[f"skills/{skill.skill_id}"] == directory_sha256(
                SKILL_BUNDLE / skill.skill_id
            )

    def test_custom_skills_declared_never_fabricated(
        self, assembler: RunProfileAssembler, catalog: RoleResourceCatalog
    ) -> None:
        resource = catalog.role("theorist")
        assert resource.custom_skills
        sealed = assembler.seal_invocation(**_seal_kwargs())
        declared = sealed.manifest["role_definition"]["custom_skills"]
        assert {item["skill_id"] for item in declared} == {
            skill.skill_id for skill in resource.custom_skills
        }
        assert all(item["copied"] is False for item in declared)
        # No fabricated content: nothing was written for custom skills.
        profile_skills = sealed.run_dir / "profile" / "skills"
        installed = {p.name for p in profile_skills.iterdir()}
        assert not (installed & {skill.skill_id for skill in resource.custom_skills})

    def test_missing_recommended_skill_bundle_rejected(
        self, tmp_path: Path, database: Database, catalog: RoleResourceCatalog
    ) -> None:
        assembler = RunProfileAssembler(
            data_root=tmp_path / "data",
            role_resources=catalog,
            database=database,
            bundle_root=tmp_path / "empty-bundle",
            hermes_probe=lambda binary: FAKE_HERMES,
        )
        with pytest.raises(RunSealError):
            assembler.seal_invocation(**_seal_kwargs())


# --------------------------------------------------------------------------- #
# Memory snapshot policy                                                      #
# --------------------------------------------------------------------------- #


class TestMemorySnapshot:
    def test_persistent_memory_copied_from_latest_promoted(
        self, assembler: RunProfileAssembler, project_profile: Path
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        memories = sealed.run_dir / "profile" / "memories"
        assert (memories / "MEMORY.md").read_text(encoding="utf-8").startswith(
            "# Memory"
        )
        snapshot = sealed.manifest["memory_snapshot"]
        assert snapshot["policy"] == "persistent"
        assert snapshot["identity"] != "fresh"
        assert snapshot["digest"] == directory_sha256(memories)

    def test_fresh_mode_gets_clean_memory(
        self, assembler: RunProfileAssembler, project_profile: Path
    ) -> None:
        sealed = assembler.seal_invocation(
            **_seal_kwargs(memory_policy=MemoryPolicy.EPHEMERAL)
        )
        memories = sealed.run_dir / "profile" / "memories"
        assert list(memories.iterdir()) == []
        snapshot = sealed.manifest["memory_snapshot"]
        assert snapshot["policy"] == "ephemeral"
        assert snapshot["identity"] == "fresh"
        assert snapshot["source"] is None

    def test_first_run_gets_clean_memory_even_when_persistent(
        self, tmp_path: Path, database: Database, catalog: RoleResourceCatalog
    ) -> None:
        # No hermes_root, no project profile: first run.
        assembler = RunProfileAssembler(
            data_root=tmp_path / "data",
            role_resources=catalog,
            database=database,
            bundle_root=SKILL_BUNDLE,
            hermes_probe=lambda binary: FAKE_HERMES,
        )
        sealed = assembler.seal_invocation(**_seal_kwargs())
        snapshot = sealed.manifest["memory_snapshot"]
        assert snapshot["policy"] == "persistent"
        assert snapshot["identity"] == "fresh"
        assert list((sealed.run_dir / "profile" / "memories").iterdir()) == []

    def test_reviewer_always_defaults_to_fresh(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        # Give the reviewer project-role memory; it must be ignored.
        reviewer = _project_profile_dir(hermes_root, "proj-001", "outside_reviewer")
        (reviewer / "memories").mkdir(parents=True)
        (reviewer / "memories" / "MEMORY.md").write_text("# Reviewer memory\n")
        sealed = assembler.seal_invocation(
            **_seal_kwargs(
                invocation_id="inv-review",
                idempotency_key="key-review",
                role="outside_reviewer",
                memory_policy=MemoryPolicy.PERSISTENT,
            )
        )
        assert resolve_memory_policy("outside_reviewer", MemoryPolicy.PERSISTENT) is (
            MemoryPolicy.EPHEMERAL
        )
        snapshot = sealed.manifest["memory_snapshot"]
        assert snapshot["policy"] == "ephemeral"
        assert snapshot["identity"] == "fresh"
        assert list((sealed.run_dir / "profile" / "memories").iterdir()) == []

    def test_session_snapshot_empty_without_canonical_store(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        assert "session_snapshot" in sealed.manifest
        # No canonical project-role state.db exists: empty session state.
        assert sealed.manifest["session_snapshot"] == {
            "procedure": "none",
            "identity": "fresh",
        }


# --------------------------------------------------------------------------- #
# Credential hygiene                                                          #
# --------------------------------------------------------------------------- #


class TestCredentialHygiene:
    def test_no_secret_files_anywhere_in_run_directory(
        self, assembler: RunProfileAssembler, project_profile: Path
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        for path in _all_paths(sealed.run_dir):
            assert path.name not in SECRET_FILE_NAMES, (
                f"secret file leaked into run directory: {path}"
            )
            assert "super-secret" not in path.read_text(
                encoding="utf-8", errors="ignore"
            )
        # The project profile still holds its secrets; only the run dir is clean.
        assert (project_profile / ".env").exists()

    def test_secret_files_excluded_from_skill_copy(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "skill"
            dest = Path(tmp) / "out"
            src.mkdir(parents=True)
            (src / "SKILL.md").write_text("# skill\n")
            (src / ".env").write_text("KEY=secret\n")
            (src / "references").mkdir()
            (src / "references" / "auth.json").write_text("{}")
            (src / "credential_pool").mkdir()
            (src / "credential_pool" / "pool.txt").write_text("secret")
            _copy_tree_excluding(src, dest)
            copied = {p.relative_to(dest).as_posix() for p in _all_paths(dest)}
            assert copied == {"SKILL.md"}


# --------------------------------------------------------------------------- #
# Manifest completeness and stable digest                                     #
# --------------------------------------------------------------------------- #


class TestManifest:
    REQUIRED_TOP_LEVEL = (
        "format",
        "format_version",
        "invocation_id",
        "seal_id",
        "project_id",
        "phase",
        "role",
        "method_identity",
        "user_choices",
        "selected_context_references",
        "role_definition",
        "memory_snapshot",
        "session_snapshot",
        "state_lock",
        "working_roots",
        "hermes",
        "expected_outputs",
        "sealed_at",
    )

    def test_manifest_has_every_required_field(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        manifest = sealed.manifest
        assert manifest["format"] == MANIFEST_FORMAT
        assert manifest["format_version"] == MANIFEST_FORMAT_VERSION
        for key in self.REQUIRED_TOP_LEVEL:
            assert key in manifest, f"manifest missing {key!r}"
        role_def = manifest["role_definition"]
        assert role_def["revision"] == "1.0.0"
        assert role_def["asset_digests"]
        assert manifest["memory_snapshot"]["identity"]
        for root_key in (
            "run_dir",
            "profile",
            "workspace",
            "inputs",
            "outputs",
            "logs",
            "manifest",
        ):
            assert root_key in manifest["working_roots"]
        assert manifest["hermes"] == {"executable": "/fake/hermes", "version": "9.9.9"}
        assert manifest["expected_outputs"][0]["output_id"] == "out-1"
        assert manifest["method_identity"]["method_id"] == "mh-1"

    def test_manifest_digest_is_stable_and_verifiable(
        self, assembler: RunProfileAssembler
    ) -> None:
        first = assembler.seal_invocation(**_seal_kwargs())
        manifest_path = first.run_dir / "manifest" / "manifest.json"
        sidecar = (first.run_dir / "manifest" / "manifest.sha256").read_text(
            encoding="utf-8"
        ).strip()
        recomputed = hashlib.sha256(
            canonicalize(json.loads(manifest_path.read_text(encoding="utf-8")))
        ).hexdigest()
        assert recomputed == sidecar == first.manifest_sha256

        # Deterministic core: two preparations from the same basis produce
        # the same digest apart from declared invocation identifiers and
        # timestamps (Block 3 checkpoint).
        second = assembler.seal_invocation(
            **_seal_kwargs(
                invocation_id="inv-002",
                idempotency_key="key-002",
            )
        )

        def core(document: dict) -> str:
            identity_keys = {
                "invocation_id",
                "seal_id",
                "sealed_at",
                "working_roots",
                "state_lock",
            }
            return hashlib.sha256(
                canonicalize(
                    {k: v for k, v in document.items() if k not in identity_keys}
                )
            ).hexdigest()

        assert core(dict(first.manifest)) == core(dict(second.manifest))

    def test_manifest_immutable_and_reconstructable(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        # Tampering is detectable on reconstruction.
        manifest_path = sealed.run_dir / "manifest" / "manifest.json"
        original = manifest_path.read_text(encoding="utf-8")
        manifest_path.write_text(original.replace('"phase": "P3"', '"phase": "P9"'))
        record = assembler.store.find_by_idempotency_key("key-001")
        with pytest.raises(ManifestDigestError):
            assembler._reconstruct(record)  # type: ignore[attr-defined]
        manifest_path.write_text(original)

    def test_seal_record_is_immutable_in_database(
        self, assembler: RunProfileAssembler, database: Database
    ) -> None:
        assembler.seal_invocation(**_seal_kwargs())
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as conn:
                conn.execute(
                    "UPDATE run_profile_seals SET run_dir = '/evil' "
                    "WHERE idempotency_key = 'key-001'"
                )
        with pytest.raises(sqlite3.IntegrityError):
            with database.transaction() as conn:
                conn.execute(
                    "DELETE FROM run_profile_seals WHERE idempotency_key = 'key-001'"
                )


# --------------------------------------------------------------------------- #
# Idempotency                                                                 #
# --------------------------------------------------------------------------- #


class TestIdempotency:
    def test_double_seal_returns_existing_record(
        self, assembler: RunProfileAssembler
    ) -> None:
        first = assembler.seal_invocation(**_seal_kwargs())
        second = assembler.seal_invocation(**_seal_kwargs())
        assert isinstance(second, SealedRun)
        assert second.seal_id == first.seal_id
        assert second.run_dir == first.run_dir
        assert second.manifest_sha256 == first.manifest_sha256
        # Exactly one run directory exists.
        run_dirs = list(assembler.runs_root.iterdir())
        assert len(run_dirs) == 1
        assert run_dirs[0].name == "inv-001"

    def test_idempotency_is_keyed_not_invocation(
        self, assembler: RunProfileAssembler
    ) -> None:
        assembler.seal_invocation(**_seal_kwargs())
        # Same key, different invocation id: still the same seal.
        second = assembler.seal_invocation(
            **_seal_kwargs(invocation_id="inv-other")
        )
        assert second.invocation_id == "inv-001"
        assert len(list(assembler.runs_root.iterdir())) == 1

    def test_seal_record_listed_and_queryable(
        self, assembler: RunProfileAssembler
    ) -> None:
        assembler.seal_invocation(**_seal_kwargs())
        assert assembler.store.find_by_invocation_id("inv-001") is not None
        seals = assembler.store.list_seals(project_id="proj-001", role="theorist")
        assert len(seals) == 1
        assert seals[0]["manifest_sha256"]


# --------------------------------------------------------------------------- #
# Hermes probe                                                                #
# --------------------------------------------------------------------------- #


class TestHermesProbe:
    def test_probe_recorded_in_manifest(
        self, assembler: RunProfileAssembler
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        assert sealed.manifest["hermes"] == {
            "executable": "/fake/hermes",
            "version": "9.9.9",
        }

    def test_missing_binary_probe_is_lenient(
        self, tmp_path: Path, database: Database, catalog: RoleResourceCatalog
    ) -> None:
        assembler = RunProfileAssembler(
            data_root=tmp_path / "data",
            role_resources=catalog,
            database=database,
            bundle_root=SKILL_BUNDLE,
            hermes_binary="definitely-not-a-real-hermes-binary",
        )
        sealed = assembler.seal_invocation(**_seal_kwargs())
        assert sealed.manifest["hermes"]["executable"] is None
        assert sealed.manifest["hermes"]["version"] is None


# --------------------------------------------------------------------------- #
# Seal rollback (validator fix)                                                #
# --------------------------------------------------------------------------- #


class TestSealRollback:
    def test_failed_seal_rolls_back_run_directory_and_allows_retry(
        self,
        assembler: RunProfileAssembler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An injected mid-seal failure must not leave an orphan run directory
        that permanently blocks retrying the same invocation id."""
        def _boom(*args: Any, **kwargs: Any) -> None:
            raise RunSealError("injected assembly failure")

        monkeypatch.setattr(assembler, "_assemble_profile", _boom)
        with pytest.raises(RunSealError, match="injected assembly failure"):
            assembler.seal_invocation(**_seal_kwargs())

        run_dir = assembler.run_dir_for("inv-001")
        assert not run_dir.exists(), "failed seal left an orphan run directory"

        monkeypatch.undo()
        sealed = assembler.seal_invocation(**_seal_kwargs())
        assert sealed.run_dir == run_dir
        assert run_dir.is_dir()


# --------------------------------------------------------------------------- #
# Session snapshot procedure (WP-D2a)                                          #
# --------------------------------------------------------------------------- #


def _create_state_db(profile_dir: Path, *, rows: int = 3) -> Path:
    """Build a small real Hermes-like session store in *profile_dir*.

    Mirrors the real Hermes schema shape (``sessions`` + ``messages``
    tables; see ~/.hermes/profiles/*/state.db) in default rollback-journal
    mode so a busy source can be produced by holding a write lock.
    """
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
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, "
            "session_id TEXT, content TEXT)"
        )
        conn.executemany(
            "INSERT INTO messages (session_id, content) VALUES (?, ?)",
            [("s0", f"conversation content {i}") for i in range(2)],
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


class TestSessionSnapshot:
    def test_snapshot_copies_all_rows_and_passes_integrity(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _project_profile_dir(hermes_root, "proj-001", "theorist")
        source = _create_state_db(profile, rows=4)
        sealed = assembler.seal_invocation(**_seal_kwargs())

        copy = sealed.run_dir / "profile" / "state.db"
        assert copy.is_file()
        # Raw db/wal/shm files are never copied into the run directory.
        for sidecar in ("state.db-wal", "state.db-shm"):
            assert not list(sealed.run_dir.rglob(sidecar)), sidecar

        with sqlite3.connect(f"{copy.as_uri()}?mode=ro", uri=True) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
            assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 4
            assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
        with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True) as src:
            expected = src.execute(
                "SELECT id, title FROM sessions ORDER BY id"
            ).fetchall()
        with sqlite3.connect(f"{copy.as_uri()}?mode=ro", uri=True) as dst:
            copied = dst.execute(
                "SELECT id, title FROM sessions ORDER BY id"
            ).fetchall()
        assert copied == expected

        record = sealed.manifest["session_snapshot"]
        assert record["procedure"] == SESSION_SNAPSHOT_PROCEDURE
        assert record["source"] == str(source)
        assert record["quiescent"] is True
        assert record["sha256"] == hashlib.sha256(copy.read_bytes()).hexdigest()
        assert record["bytes"] == copy.stat().st_size

    def test_manifest_digest_matches_copy_on_disk(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _project_profile_dir(hermes_root, "proj-001", "theorist")
        _create_state_db(profile, rows=2)
        sealed = assembler.seal_invocation(**_seal_kwargs())
        copy = sealed.run_dir / "profile" / "state.db"
        record = sealed.manifest["session_snapshot"]
        assert record["sha256"] == hashlib.sha256(copy.read_bytes()).hexdigest()

    def test_busy_source_fails_fast_and_seal_rolls_back(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _project_profile_dir(hermes_root, "proj-001", "theorist")
        source = _create_state_db(profile, rows=2)
        holder = sqlite3.connect(source)
        try:
            holder.execute("BEGIN EXCLUSIVE")
            holder.execute(
                "INSERT INTO sessions (id, title, source) "
                "VALUES ('s-live', 'pending', 'cli')"
            )
            with pytest.raises(SessionSnapshotBusy, match="busy"):
                assembler.seal_invocation(**_seal_kwargs())
        finally:
            holder.rollback()
            holder.close()

        # WP-D1 rollback removed the partial run directory.
        run_dir = assembler.run_dir_for("inv-001")
        assert not run_dir.exists(), "busy seal left an orphan run directory"
        # Recoverable: once the writer releases, the same invocation seals.
        sealed = assembler.seal_invocation(**_seal_kwargs())
        assert sealed.run_dir == run_dir
        assert run_dir.is_dir()

    def test_outside_reviewer_always_gets_empty_session_state(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _project_profile_dir(hermes_root, "proj-001", "outside_reviewer")
        _create_state_db(profile, rows=2)
        sealed = assembler.seal_invocation(
            **_seal_kwargs(
                invocation_id="inv-review",
                idempotency_key="key-review",
                role="outside_reviewer",
                memory_policy=MemoryPolicy.PERSISTENT,
            )
        )
        assert sealed.manifest["session_snapshot"] == dict(SESSION_SNAPSHOT_EMPTY)
        assert not (sealed.run_dir / "profile" / "state.db").exists()

    def test_fresh_policy_gets_empty_session_state(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _project_profile_dir(hermes_root, "proj-001", "theorist")
        _create_state_db(profile, rows=2)
        sealed = assembler.seal_invocation(
            **_seal_kwargs(
                invocation_id="inv-fresh",
                idempotency_key="key-fresh",
                memory_policy=MemoryPolicy.EPHEMERAL,
            )
        )
        assert sealed.manifest["session_snapshot"] == dict(SESSION_SNAPSHOT_EMPTY)
        assert not (sealed.run_dir / "profile" / "state.db").exists()

    def test_quiescence_flag_false_when_wal_sidecars_present(
        self, assembler: RunProfileAssembler, hermes_root: Path
    ) -> None:
        profile = _project_profile_dir(hermes_root, "proj-001", "theorist")
        profile.mkdir(parents=True, exist_ok=True)
        db_path = profile / "state.db"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT)"
            )
            conn.execute("INSERT INTO sessions VALUES ('s1', 'Session 1')")
            conn.commit()
            # Keep the connection open so state.db-wal/-shm exist at
            # snapshot time; the online backup still reads committed state.
            assert (profile / "state.db-wal").exists()
            sealed = assembler.seal_invocation(**_seal_kwargs())
            record = sealed.manifest["session_snapshot"]
            assert record["procedure"] == SESSION_SNAPSHOT_PROCEDURE
            assert record["quiescent"] is False
            copy = sealed.run_dir / "profile" / "state.db"
            with sqlite3.connect(f"{copy.as_uri()}?mode=ro", uri=True) as verify:
                assert (
                    verify.execute("SELECT count(*) FROM sessions").fetchone()[0]
                    == 1
                )
        finally:
            conn.close()

    def test_snapshot_procedure_direct(self, tmp_path: Path) -> None:
        source = _create_state_db(tmp_path / "src", rows=3)
        dest = tmp_path / "out" / "state.db"
        snapshot = snapshot_session_db(source, dest)
        assert snapshot.procedure == SESSION_SNAPSHOT_PROCEDURE
        assert snapshot.quiescent is True
        assert snapshot.sha256 == hashlib.sha256(dest.read_bytes()).hexdigest()
        assert snapshot.bytes_count == dest.stat().st_size
        # A second snapshot into the same destination is refused.
        with pytest.raises(SessionSnapshotError):
            snapshot_session_db(source, dest)
