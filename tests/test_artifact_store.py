from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from method_hub.domain import Sha256Digest
from method_hub.storage import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactStore,
    WorkspacePaths,
)


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(WorkspacePaths(tmp_path / "workspace", create=True))


def test_content_addressed_put_is_idempotent_and_does_not_rewrite(
    store: ArtifactStore,
) -> None:
    payload = b"stable research artifact\n"
    expected = Sha256Digest(hashlib.sha256(payload).hexdigest())

    first = store.put_bytes(payload, expected_sha256=expected)
    path = store.path_for(expected)
    fixed_time_ns = 1_700_000_000_000_000_000
    os.utime(path, ns=(fixed_time_ns, fixed_time_ns))
    second = store.put_bytes(payload)

    assert first == second
    assert first.sha256 == expected
    assert first.size == len(payload)
    assert path.stat().st_mtime_ns == fixed_time_ns
    assert store.read_bytes(expected) == payload


def test_put_rejects_bytes_that_do_not_match_expected_digest(
    store: ArtifactStore,
) -> None:
    expected = Sha256Digest("a" * 64)

    with pytest.raises(ArtifactIntegrityError) as raised:
        store.put_bytes(b"different bytes", expected_sha256=expected)

    assert raised.value.code == "artifact.digest_mismatch"
    assert not store.path_for(expected).exists()


def test_store_detects_tampering_and_refuses_to_replace_object(
    store: ArtifactStore,
) -> None:
    payload = b"original bytes"
    artifact = store.put_bytes(payload)
    store.path_for(artifact.sha256).write_bytes(b"tampered bytes")

    with pytest.raises(ArtifactIntegrityError) as verified:
        store.verify(artifact.sha256)
    with pytest.raises(ArtifactIntegrityError) as repeated_put:
        store.put_bytes(payload)

    assert verified.value.code == "artifact.digest_mismatch"
    assert repeated_put.value.code == "artifact.digest_mismatch"
    assert store.path_for(artifact.sha256).read_bytes() == b"tampered bytes"


def test_missing_artifact_has_stable_error_code(store: ArtifactStore) -> None:
    missing = Sha256Digest("0" * 64)

    with pytest.raises(ArtifactNotFoundError) as raised:
        store.read_bytes(missing)

    assert raised.value.code == "artifact.not_found"
