"""Fail-closed RFC 8785 canonicalization for the greenfield runtime.

The first runtime version deliberately accepts only integers in the exact
interoperable IEEE 754 safe range. Floating-point values are rejected until a
separately verified ECMAScript number serializer is available.
"""

from __future__ import annotations

import json
from typing import Any


MAX_SAFE_INTEGER = 9_007_199_254_740_991


class JCSCanonicalizationError(ValueError):
    """Base error for a value outside the supported canonical JSON domain."""


class JCSUnsupportedNumber(JCSCanonicalizationError):
    """A number cannot be represented by the restricted runtime profile."""


class JCSInvalidUnicode(JCSCanonicalizationError):
    """A string is not a sequence of Unicode scalar values."""


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
    if type(value) is str:
        _validate_string(value)
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if type(value) is int:
        if abs(value) > MAX_SAFE_INTEGER:
            raise JCSUnsupportedNumber(
                "integer is outside the interoperable IEEE 754 safe range"
            )
        return str(value)
    if isinstance(value, float):
        raise JCSUnsupportedNumber(
            "binary64 serialization is not implemented by the restricted runtime"
        )
    if type(value) is list:
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    if type(value) is dict:
        if not all(type(key) is str for key in value):
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


__all__ = [
    "JCSCanonicalizationError",
    "JCSInvalidUnicode",
    "JCSUnsupportedNumber",
    "MAX_SAFE_INTEGER",
    "canonicalize",
]
