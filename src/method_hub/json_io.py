"""Strict JSON input helpers used by schemas and contract registries."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .errors import JsonLoadError


def _object_without_duplicates(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise JsonLoadError(
                "json.duplicate_key",
                f"Duplicate object key {key!r} is not permitted.",
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise JsonLoadError(
        "json.non_finite_number",
        f"Non-finite JSON number {value!r} is not permitted.",
    )


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise JsonLoadError(
            "json.non_finite_number",
            f"JSON number {value!r} is outside the finite numeric domain.",
        )
    return parsed


def loads_json(
    document: str | bytes | bytearray,
    *,
    source: str = "<memory>",
) -> Any:
    """Parse one JSON value while rejecting duplicate keys and non-finite numbers."""

    if isinstance(document, (bytes, bytearray)):
        try:
            text = bytes(document).decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise JsonLoadError(
                "json.invalid_utf8",
                "JSON input is not valid UTF-8.",
                source=source,
                line=error.start,
            ) from error
    elif type(document) is str:
        text = document
    else:
        raise JsonLoadError(
            "json.invalid_input_type",
            "JSON input must be text or UTF-8 bytes.",
            source=source,
        )

    try:
        return json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except JsonLoadError as error:
        if error.source == "<memory>" and source != "<memory>":
            raise JsonLoadError(
                error.code,
                error.message,
                source=source,
                line=error.line,
                column=error.column,
            ) from error
        raise
    except json.JSONDecodeError as error:
        raise JsonLoadError(
            "json.decode_error",
            error.msg,
            source=source,
            line=error.lineno,
            column=error.colno,
        ) from error


def load_json(path: str | Path) -> Any:
    """Read and strictly parse one UTF-8 JSON file."""

    source = str(path)
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise JsonLoadError(
            "json.read_error",
            f"Could not read JSON document: {error}.",
            source=source,
        ) from error
    return loads_json(raw, source=source)
