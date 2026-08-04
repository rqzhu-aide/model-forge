"""WP-D2c: Block 3 seal-determinism checkpoint (test package).

Checkpoint (architecture/plans/next-block-local-hermes-execution-closure.md,
Block 3): "two preparations from the same sealed basis produce equivalent
manifests and run-profile content, apart from declared invocation
identifiers and timestamps."

Two invocations are sealed from an IDENTICAL basis -- same project, role,
phase, method identity, user choices, context references, expected
outputs and memory policy; the same canonical project-role profile
(memory + state.db); the same FAKE_HERMES probe -- with different
invocation_id and idempotency_key, and the prepared run packets are
compared:

* profile/ trees must be byte-identical, file by file.  A profile file
  that embeds the invocation id FAILS this test -- that is a report,
  never a silent normalization.
* the two manifests must be deep-equal after removing ONLY the
  declared-varying fields enumerated in DECLARED_VARYING_MANIFEST_FIELDS
  below.
* a negative control (one changed basis element) must produce manifests
  that differ beyond the declared-varying fields, proving the comparison
  can detect drift.

This package is tests only.  If an assertion ever fails, the
nondeterminism must be fixed at its source in the assembler -- never
normalized away inside this test.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from method_hub.application.run_profile_assembler import (
    HermesProbe,
    RunProfileAssembler,
    SealedRun,
)
from method_hub.application.session_snapshots import SESSION_SNAPSHOT_PROCEDURE
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
# Declared-varying fields (the checkpoint's explicit exception list)          #
# --------------------------------------------------------------------------- #

#: Manifest document fields removed from the equivalence comparison, with the
#: reason each one legitimately varies between two seals of the same basis.
#: Everything else in the manifest must be deep-equal.  ``run_dir`` is not a
#: top-level field: it lives inside ``working_roots``, which is why that whole
#: record is removed.  Two further declared-varying values are not manifest
#: document fields at all and are asserted separately: ``idempotency_key``
#: (a SealedRun attribute, never recorded in the document) and
#: ``manifest_sha256`` (the digest of the whole document, so it embeds every
#: varying field by construction).
DECLARED_VARYING_MANIFEST_FIELDS: dict[str, str] = {
    "seal_id": "random per-seal identifier (uuid4), declared varying",
    "invocation_id": "declared invocation identifier",
    "sealed_at": "declared timestamp",
    "working_roots": "every value embeds run_dir, which embeds the "
    "invocation id (run_dir is not a top-level manifest field)",
    "state_lock": "fencing token is per-invocation sequencing state (S5.7), "
    "not basis content; profile_name is basis-identical and is asserted "
    "equal separately",
}


# --------------------------------------------------------------------------- #
# Fixtures (same patterns as tests/test_run_profile_assembler.py)             #
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
def project_profile(hermes_root: Path) -> Path:
    """The canonical project-role profile: memory AND a state.db.

    Both invocations snapshot this exact profile, so any nondeterminism
    in the memory copy or the SQLite session backup shows up as a byte
    difference in profile/ or a digest difference in the manifest.
    """
    profile = hermes_root / "profiles" / project_role_profile_name("proj-001", "theorist")
    memories = profile / "memories"
    memories.mkdir(parents=True)
    (memories / "MEMORY.md").write_text("# Memory\nPrior conclusion from P2.\n")
    (memories / "USER.md").write_text("# User\nResearcher.\n")
    _create_state_db(profile, rows=3)
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


def _create_state_db(profile_dir: Path, *, rows: int = 3) -> Path:
    """Build a small real Hermes-like session store in *profile_dir*.

    Mirrors the Hermes schema shape (``sessions`` + ``messages`` tables;
    see ~/.hermes/profiles/*/state.db) in default rollback-journal mode.
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


def _file_map(root: Path) -> dict[str, bytes]:
    """Relative path -> bytes for every regular file under *root*."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }


def _strip_declared_varying(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in manifest.items()
        if key not in DECLARED_VARYING_MANIFEST_FIELDS
    }


# --------------------------------------------------------------------------- #
# The Block 3 checkpoint                                                      #
# --------------------------------------------------------------------------- #


class TestSealDeterminism:
    def test_run_profile_trees_byte_identical_across_seals(
        self, assembler: RunProfileAssembler, project_profile: Path
    ) -> None:
        """profile/ is byte-identical; no file embeds the invocation id.

        The only files anywhere in the run directory that differ between
        the two seals are the manifest document and its digest sidecar,
        which legitimately record the declared-varying fields.
        """
        first = assembler.seal_invocation(**_seal_kwargs())
        second = assembler.seal_invocation(
            **_seal_kwargs(invocation_id="inv-002", idempotency_key="key-002")
        )

        first_files = _file_map(first.run_dir)
        second_files = _file_map(second.run_dir)

        # Same file set in both run directories.
        assert set(first_files) == set(second_files)

        # profile/ must be byte-identical, file by file.
        profile_rel = sorted(
            relative
            for relative in first_files
            if (first.run_dir / relative).is_relative_to(first.run_dir / "profile")
        )
        assert profile_rel, "expected profile/ files to compare"
        differing_profile = [
            relative
            for relative in profile_rel
            if first_files[relative] != second_files[relative]
        ]
        assert differing_profile == [], (
            "profile/ files differ between two seals of the same basis "
            f"(a REPORT, not something to normalize): {differing_profile}"
        )

        # No profile file embeds either invocation id (there should be none).
        for relative in profile_rel:
            payload = first_files[relative]
            assert first.invocation_id.encode() not in payload, (
                f"profile file {relative!r} embeds invocation id "
                f"{first.invocation_id!r}"
            )
            assert second.invocation_id.encode() not in payload, (
                f"profile file {relative!r} embeds invocation id "
                f"{second.invocation_id!r}"
            )

        # The complete run-directory diff is exactly the manifest pair:
        # the declared-varying fields live only there.
        differing = sorted(
            relative
            for relative in first_files
            if first_files[relative] != second_files[relative]
        )
        assert differing == ["manifest/manifest.json", "manifest/manifest.sha256"], (
            f"unexpected differing files between the two run directories: "
            f"{differing}"
        )

        # The snapshotted session store is byte-identical and its recorded
        # digest matches the copied bytes in both run profiles.
        state_db = first_files["profile/state.db"]
        assert state_db == second_files["profile/state.db"]
        expected_digest = hashlib.sha256(state_db).hexdigest()
        assert first.manifest["session_snapshot"]["sha256"] == expected_digest
        assert second.manifest["session_snapshot"]["sha256"] == expected_digest
        # Memory snapshot identity ties to the byte-identical copies too.
        memory_identity = directory_sha256(first.run_dir / "profile" / "memories")
        assert first.manifest["memory_snapshot"]["identity"] == memory_identity
        assert (
            second.manifest["memory_snapshot"]["identity"]
            == directory_sha256(second.run_dir / "profile" / "memories")
        )

    def test_manifests_equivalent_after_declared_varying_fields_removed(
        self, assembler: RunProfileAssembler, project_profile: Path
    ) -> None:
        """The raw manifests differ; after removing ONLY the declared-
        varying fields they are deep-equal, field by field."""
        first = assembler.seal_invocation(**_seal_kwargs())
        second = assembler.seal_invocation(
            **_seal_kwargs(invocation_id="inv-002", idempotency_key="key-002")
        )
        manifest_a = dict(first.manifest)
        manifest_b = dict(second.manifest)

        # The comparison is meaningful: the raw manifests DO differ, in
        # exactly the declared fields.
        assert manifest_a != manifest_b
        assert manifest_a["invocation_id"] == "inv-001"
        assert manifest_b["invocation_id"] == "inv-002"
        assert manifest_a["seal_id"] != manifest_b["seal_id"]
        assert manifest_a["working_roots"]["run_dir"] != manifest_b["working_roots"]["run_dir"]
        for root_key in (
            "run_dir",
            "profile",
            "workspace",
            "inputs",
            "outputs",
            "logs",
            "manifest",
        ):
            assert manifest_a["working_roots"][root_key] != manifest_b["working_roots"][root_key]
        assert isinstance(manifest_a["sealed_at"], str) and manifest_a["sealed_at"]
        assert isinstance(manifest_b["sealed_at"], str) and manifest_b["sealed_at"]

        # Declared-varying values that live outside the manifest document.
        assert first.idempotency_key == "key-001"
        assert second.idempotency_key == "key-002"
        assert first.idempotency_key != second.idempotency_key
        assert "idempotency_key" not in manifest_a
        assert "manifest_sha256" not in manifest_a
        assert first.manifest_sha256 != second.manifest_sha256

        # Equivalent core: deep-equal after removing ONLY the exception list.
        core_a = _strip_declared_varying(manifest_a)
        core_b = _strip_declared_varying(manifest_b)
        assert core_a == core_b
        # Every field the checkpoint names explicitly must be present and equal.
        assert core_a["project_id"] == core_b["project_id"] == "proj-001"
        assert core_a["role"] == core_b["role"] == "theorist"
        assert core_a["phase"] == core_b["phase"] == "P3"
        assert core_a["method_identity"] == core_b["method_identity"]
        assert core_a["user_choices"] == core_b["user_choices"]
        assert core_a["selected_context_references"] == core_b["selected_context_references"]
        assert core_a["expected_outputs"] == core_b["expected_outputs"]
        assert core_a["role_definition"]["asset_digests"] == core_b["role_definition"][
            "asset_digests"
        ]
        assert core_a["memory_snapshot"] == core_b["memory_snapshot"]
        assert core_a["memory_snapshot"]["identity"] != "fresh"
        assert core_a["session_snapshot"] == core_b["session_snapshot"]
        assert core_a["hermes"] == core_b["hermes"] == {
            "executable": "/fake/hermes",
            "version": "9.9.9",
        }

        # session_snapshot.source is the canonical state.db path under the
        # shared Hermes root -- it does NOT embed the invocation id, so it
        # legitimately stays inside the comparison (checked explicitly per
        # the WP-D2c brief).
        session_source_a = core_a["session_snapshot"]["source"]
        assert session_source_a == core_b["session_snapshot"]["source"]
        assert "inv-001" not in session_source_a
        assert "inv-002" not in session_source_a
        assert core_a["session_snapshot"]["procedure"] == SESSION_SNAPSHOT_PROCEDURE

        # memory_snapshot.source is the shared project-role memories path,
        # likewise free of the invocation id.
        memory_source_a = core_a["memory_snapshot"]["source"]
        assert memory_source_a == core_b["memory_snapshot"]["source"]
        assert "inv-001" not in memory_source_a

        # state_lock.profile_name is basis-identical; only the per-invocation
        # fencing token is declared-varying bookkeeping (removed above).
        assert (
            manifest_a["state_lock"]["profile_name"]
            == manifest_b["state_lock"]["profile_name"]
            == project_role_profile_name("proj-001", "theorist")
        )

        # Manifest digest sidecars: each verifies against its own document
        # (so the difference is exactly the declared fields), and the two
        # sidecars differ.
        for sealed in (first, second):
            recomputed = hashlib.sha256(
                canonicalize(json.loads(
                    (sealed.run_dir / "manifest" / "manifest.json").read_text(
                        encoding="utf-8"
                    )
                ))
            ).hexdigest()
            sidecar = (
                sealed.run_dir / "manifest" / "manifest.sha256"
            ).read_text(encoding="utf-8").strip()
            assert recomputed == sidecar == sealed.manifest_sha256

    def test_negative_control_basis_drift_is_detected(
        self, assembler: RunProfileAssembler, project_profile: Path
    ) -> None:
        """One changed basis element must produce a manifest that differs
        beyond the declared-varying fields (the comparison can detect
        drift), while profile/ stays byte-identical."""
        first = assembler.seal_invocation(**_seal_kwargs())
        drifted = assembler.seal_invocation(
            **_seal_kwargs(
                invocation_id="inv-003",
                idempotency_key="key-003",
                user_choices={"mode": "interactive", "context_policy": "strict"},
            )
        )

        core_a = _strip_declared_varying(dict(first.manifest))
        core_c = _strip_declared_varying(dict(drifted.manifest))
        assert core_a != core_c
        # The drift is exactly the changed basis element, nothing else.
        diff_keys = sorted(
            key
            for key in set(core_a) | set(core_c)
            if core_a.get(key) != core_c.get(key)
        )
        assert diff_keys == ["user_choices"]

        # profile/ content is unaffected by user choices: still byte-identical.
        files_a = _file_map(first.run_dir)
        files_c = _file_map(drifted.run_dir)
        profile_rel = sorted(
            relative
            for relative in files_a
            if (first.run_dir / relative).is_relative_to(first.run_dir / "profile")
        )
        assert all(files_a[relative] == files_c[relative] for relative in profile_rel)
