"""Canonical JSON sealing for application-owned operational documents."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from ..digests.jcs import canonicalize


def canonical_sha256(document: Any) -> str:
    return hashlib.sha256(canonicalize(document)).hexdigest()


def seal_field(document: dict[str, Any], field: str) -> dict[str, Any]:
    if field in document:
        raise ValueError(f"Document already contains sealed field {field!r}.")
    result = copy.deepcopy(document)
    result[field] = canonical_sha256(result)
    return result


def json_bytes(document: Any) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


__all__ = ["canonical_sha256", "json_bytes", "seal_field"]
