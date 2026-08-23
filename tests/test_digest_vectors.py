from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from model_forge.digests import (
    JCSCanonicalizationError,
    JCSInvalidUnicode,
    JCSUnsupportedNumber,
    canonicalize,
)


ARCHITECTURE = Path(__file__).resolve().parents[1] / "architecture"


def _vectors() -> dict:
    return json.loads(
        (ARCHITECTURE / "examples" / "digest-vectors.example.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.mark.parametrize("vector", _vectors()["accepted_vectors"])
def test_accepted_architecture_vectors(vector: dict) -> None:
    encoded = canonicalize(vector["input"])
    assert encoded.decode("utf-8") == vector["canonical_json"]
    assert hashlib.sha256(encoded).hexdigest() == vector["sha256"]


@pytest.mark.parametrize("vector", _vectors()["rejected_vectors"])
def test_rejected_architecture_vectors(vector: dict) -> None:
    assert vector["error_code"] == "unsupported_number"
    with pytest.raises(JCSUnsupportedNumber):
        canonicalize(vector["input"])


def test_lone_surrogate_is_rejected() -> None:
    with pytest.raises(JCSInvalidUnicode):
        canonicalize({"value": "\ud800"})


@pytest.mark.parametrize(
    "value",
    [
        ("not", "a JSON array"),
        {1: "non-string key"},
        object(),
    ],
)
def test_non_json_values_are_rejected(value: object) -> None:
    with pytest.raises(JCSCanonicalizationError):
        canonicalize(value)


def test_boolean_is_not_serialized_as_integer() -> None:
    assert canonicalize([True, False, 1, 0]) == b"[true,false,1,0]"
