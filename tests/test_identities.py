from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from model_forge.domain import (
    ArtifactPointer,
    MethodIdentity,
    PhaseContractIdentity,
    SemanticVersion,
    Sha256Digest,
    StableId,
)
from model_forge.errors import DomainValidationError
from model_forge.json_io import JsonLoadError, loads_json


DIGEST = "a" * 64


def test_method_identity_round_trip_is_exact_and_frozen() -> None:
    raw = {
        "stable_id": "mth_overlap-score",
        "version": 2,
        "definition_sha256": DIGEST,
    }
    identity = MethodIdentity.from_dict(raw)
    assert identity.to_dict() == raw
    with pytest.raises(FrozenInstanceError):
        identity.version = 3  # type: ignore[misc]


def test_composite_identities_accept_exact_schema_scalars_directly() -> None:
    method = MethodIdentity(  # type: ignore[arg-type]
        stable_id="mth_direct.001",
        version=1,
        definition_sha256=DIGEST,
    )
    pointer = ArtifactPointer(  # type: ignore[arg-type]
        artifact_id="art_direct.001",
        uri="artifact://art_direct.001",
        sha256=DIGEST,
    )
    phase = PhaseContractIdentity(  # type: ignore[arg-type]
        phase_id="P3",
        contract_version="2.0.0",
        phase_contract_sha256=DIGEST,
    )

    assert method.to_dict()["stable_id"] == "mth_direct.001"
    assert pointer.to_dict()["artifact_id"] == "art_direct.001"
    assert phase.to_dict()["contract_version"] == "2.0.0"


@pytest.mark.parametrize("version", [True, False, 0, -1, 1.0, "1"])
def test_method_identity_rejects_invalid_or_boolean_version(version: object) -> None:
    with pytest.raises(DomainValidationError) as raised:
        MethodIdentity.from_dict(
            {
                "stable_id": "mth_valid",
                "version": version,
                "definition_sha256": DIGEST,
            }
        )
    assert raised.value.code == "domain.invalid_method_version"


@pytest.mark.parametrize(
    "value",
    ["A_method", "m", "mth space", "mth/one", "mth__one", "mth-"],
)
def test_stable_id_matches_the_architecture_pattern(value: str) -> None:
    with pytest.raises(DomainValidationError) as raised:
        StableId(value)
    assert raised.value.code == "domain.invalid_stable_id"


@pytest.mark.parametrize("value", ["A" * 64, "a" * 63, "a" * 65, "g" * 64])
def test_sha256_digest_is_exact_lowercase_hex(value: str) -> None:
    with pytest.raises(DomainValidationError) as raised:
        Sha256Digest(value)
    assert raised.value.code == "domain.invalid_sha256"


def test_artifact_pointer_round_trip_preserves_only_present_optional_fields() -> None:
    raw = {
        "artifact_id": "art_proof.001",
        "uri": "run://run_001/artifact/art_proof.001",
        "path": "artifacts/primary/proof.md",
        "sha256": DIGEST,
        "media_type": "text/markdown",
        "locator": "Theorem 1",
    }
    assert ArtifactPointer.from_dict(raw).to_dict() == raw

    required_only = {
        "artifact_id": "art_proof.002",
        "uri": "artifact://art_proof.002",
        "sha256": DIGEST,
    }
    assert ArtifactPointer.from_dict(required_only).to_dict() == required_only


@pytest.mark.parametrize(
    "path",
    [
        "/absolute/file.json",
        "\\absolute\\file.json",
        "C:\\absolute\\file.json",
        "safe/../secret.json",
        "safe\\..\\secret.json",
        "bad\x00name.json",
    ],
)
def test_artifact_pointer_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(DomainValidationError) as raised:
        ArtifactPointer.from_dict(
            {
                "artifact_id": "art_safe.001",
                "uri": "artifact://art_safe.001",
                "path": path,
                "sha256": DIGEST,
            }
        )
    assert raised.value.code == "domain.unsafe_path"


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.test/artifact",
        "file:///tmp/artifact",
        "record://method/current",
        "run://",
        "artifact://contains space",
    ],
)
def test_artifact_pointer_rejects_unsupported_uri(uri: str) -> None:
    with pytest.raises(DomainValidationError) as raised:
        ArtifactPointer.from_dict(
            {"artifact_id": "art_safe.001", "uri": uri, "sha256": DIGEST}
        )
    assert raised.value.code == "domain.unsupported_artifact_uri"


def test_phase_contract_identity_round_trip() -> None:
    raw = {
        "phase_id": "P4",
        "contract_version": "2.0.0",
        "phase_contract_sha256": DIGEST,
    }
    identity = PhaseContractIdentity.from_dict(raw)
    assert identity.to_dict() == raw
    assert identity.contract_version == SemanticVersion("2.0.0")


@pytest.mark.parametrize("value", ["0.1.0", "1", "1.0", "v1.0.0", "1.0.0-beta"])
def test_semantic_version_matches_phase_contract_schema(value: str) -> None:
    with pytest.raises(DomainValidationError):
        SemanticVersion(value)


def test_from_dict_rejects_missing_and_unknown_fields() -> None:
    with pytest.raises(DomainValidationError) as missing:
        MethodIdentity.from_dict(
            {"stable_id": "mth_valid", "definition_sha256": DIGEST}
        )
    assert missing.value.code == "domain.missing_field"

    with pytest.raises(DomainValidationError) as unknown:
        MethodIdentity.from_dict(
            {
                "stable_id": "mth_valid",
                "version": 1,
                "definition_sha256": DIGEST,
                "name": "not part of identity",
            }
        )
    assert unknown.value.code == "domain.unknown_field"


@pytest.mark.parametrize(
    "document,code",
    [
        ('{"a": 1, "a": 2}', "json.duplicate_key"),
        ('{"x": NaN}', "json.non_finite_number"),
        ('{"x": Infinity}', "json.non_finite_number"),
        ('{"x": -Infinity}', "json.non_finite_number"),
        ('{"x": 1e400}', "json.non_finite_number"),
    ],
)
def test_json_loader_rejects_ambiguous_or_non_finite_json(
    document: str, code: str
) -> None:
    with pytest.raises(JsonLoadError) as raised:
        loads_json(document)
    assert raised.value.code == code


def test_json_loader_accepts_nested_unique_objects() -> None:
    assert loads_json('{"a": {"b": 1}, "items": [true, null]}') == {
        "a": {"b": 1},
        "items": [True, None],
    }
