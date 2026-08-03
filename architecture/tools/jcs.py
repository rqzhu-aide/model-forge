"""Restricted RFC 8785 JSON canonicalization for architecture fixtures.

The reference deliberately supports only integers that are exactly representable
by interoperable IEEE 754 implementations. Binary floating-point values are
rejected until a separately tested ECMAScript number serializer is supplied.
"""

from __future__ import annotations

import json
from typing import Any


MAX_SAFE_INTEGER = 9_007_199_254_740_991


class JCSCanonicalizationError(ValueError):
    """Base error for values outside the supported JCS input domain."""


class JCSUnsupportedNumber(JCSCanonicalizationError):
    """Raised when the restricted reference cannot serialize a JSON number."""


class JCSInvalidUnicode(JCSCanonicalizationError):
    """Raised when a string contains a lone UTF-16 surrogate."""


def _validate_string(value: str) -> None:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise JCSInvalidUnicode("JCS strings must contain Unicode scalar values")


def _utf16_sort_key(value: str) -> bytes:
    _validate_string(value)
    return value.encode("utf-16-be")


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        _validate_string(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise JCSUnsupportedNumber(
                "integer is outside the interoperable IEEE 754 safe range"
            )
        return str(value)
    if isinstance(value, float):
        raise JCSUnsupportedNumber(
            "binary64 serialization is not implemented by this restricted reference"
        )
    if isinstance(value, list):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise JCSCanonicalizationError("JSON object keys must be strings")
        members = []
        for key in sorted(value, key=_utf16_sort_key):
            members.append(_serialize(key) + ":" + _serialize(value[key]))
        return "{" + ",".join(members) + "}"
    raise JCSCanonicalizationError(
        f"unsupported JSON value type: {type(value).__name__}"
    )


def canonicalize(value: Any) -> bytes:
    """Return UTF-8 RFC 8785 bytes for the supported JSON value subset."""
    return _serialize(value).encode("utf-8")
