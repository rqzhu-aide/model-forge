"""Stable exceptions raised by the greenfield contract kernel."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


class MethodHubError(Exception):
    """Base exception with a stable machine-readable error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class DomainValidationError(MethodHubError, ValueError):
    """A domain value does not satisfy its architecture schema contract."""

    def __init__(self, code: str, message: str, *, field: str = "") -> None:
        self.field = field
        super().__init__(code, message)


class JsonLoadError(MethodHubError, ValueError):
    """A JSON document could not be read without weakening JSON semantics."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        source: str = "<memory>",
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.source = source
        self.line = line
        self.column = column
        super().__init__(code, message)


class SchemaCatalogError(MethodHubError):
    """The schema catalog itself is incomplete, ambiguous, or invalid."""


class SchemaValidationError(MethodHubError, ValueError):
    """A document failed validation against one named schema."""

    def __init__(self, schema_ref: str, issues: Sequence[Any]) -> None:
        self.schema_ref = schema_ref
        self.issues = tuple(issues)
        count = len(self.issues)
        if count:
            first = self.issues[0]
            pointer = getattr(first, "json_pointer", "") or "/"
            detail = (
                f" First issue: {getattr(first, 'code', 'schema.invalid')} "
                f"at {pointer}: {getattr(first, 'message', 'invalid document')}."
            )
        else:
            detail = ""
        super().__init__(
            "schema.invalid_document",
            f"{schema_ref} rejected the document with {count} issue(s).{detail}",
        )
