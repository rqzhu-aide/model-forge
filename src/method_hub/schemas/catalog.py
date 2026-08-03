"""Deterministic local catalog for the architecture JSON Schemas."""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urljoin, urlsplit

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable

from ..errors import SchemaCatalogError, SchemaValidationError
from ..json_io import load_json


_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"


def _pointer(parts: Iterable[Any]) -> str:
    tokens = []
    for part in parts:
        token = str(part).replace("~", "~0").replace("/", "~1")
        tokens.append(token)
    return "" if not tokens else "/" + "/".join(tokens)


def _walk_resource_refs(
    resource: Resource,
    base_uri: str = "",
) -> Iterable[tuple[str, str]]:
    """Yield live references with the base URI of their schema resource.

    Resource.subresources follows the active JSON Schema dialect, so
    reference-looking values in annotations such as examples are not treated
    as executable schema references. Each nested $id establishes the scope
    used by its own references and descendants.
    """

    resource_id = resource.id()
    scope = urljoin(base_uri, resource_id) if resource_id is not None else base_uri
    contents = resource.contents
    if isinstance(contents, Mapping):
        for keyword in ("$ref", "$dynamicRef"):
            reference = contents.get(keyword)
            if type(reference) is str:
                yield scope, reference
    for child in resource.subresources():
        yield from _walk_resource_refs(child, scope)


@dataclass(frozen=True, slots=True, order=True)
class ValidationIssue:
    """One stable and sortable schema-validation diagnostic."""

    code: str
    json_pointer: str
    schema_pointer: str
    message: str

    @property
    def instance_pointer(self) -> str:
        return self.json_pointer

    @property
    def pointer(self) -> str:
        return self.json_pointer

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "json_pointer": self.json_pointer,
            "schema_pointer": self.schema_pointer,
            "message": self.message,
        }


class SchemaCatalog:
    """Immutable filename and exact-$id index of local Draft 2020-12 schemas."""

    def __init__(
        self,
        *,
        directory: Path,
        schemas_by_name: Mapping[str, dict[str, Any]],
        names_by_id: Mapping[str, str],
        registry: Registry,
    ) -> None:
        self.directory = directory
        self._schemas_by_name = MappingProxyType(dict(schemas_by_name))
        self._names_by_id = MappingProxyType(dict(names_by_id))
        self._registry = registry
        self._format_checker = FormatChecker()

    @classmethod
    def load(cls, directory: str | Path) -> SchemaCatalog:
        schema_directory = Path(directory).resolve()
        if not schema_directory.is_dir():
            raise SchemaCatalogError(
                "schema.directory_not_found",
                f"Schema directory does not exist: {schema_directory}",
            )

        paths = sorted(schema_directory.glob("*.schema.json"), key=lambda p: p.name)
        if not paths:
            raise SchemaCatalogError(
                "schema.catalog_empty",
                f"No *.schema.json files found in {schema_directory}",
            )

        schemas_by_name: dict[str, dict[str, Any]] = {}
        names_by_id: dict[str, str] = {}
        for path in paths:
            document = load_json(path)
            if type(document) is not dict:
                raise SchemaCatalogError(
                    "schema.invalid_document_type",
                    f"{path.name} must contain one JSON object.",
                )
            if document.get("$schema") != _DRAFT_2020_12:
                raise SchemaCatalogError(
                    "schema.unsupported_dialect",
                    f"{path.name} must declare exactly {_DRAFT_2020_12!r}.",
                )
            schema_id = document.get("$id")
            if type(schema_id) is not str or not _absolute_uri(schema_id):
                raise SchemaCatalogError(
                    "schema.invalid_id",
                    f"{path.name} must declare an absolute string $id.",
                )
            if schema_id in names_by_id:
                raise SchemaCatalogError(
                    "schema.duplicate_id",
                    f"{path.name} repeats $id {schema_id!r} from {names_by_id[schema_id]}.",
                )
            try:
                Draft202012Validator.check_schema(document)
            except SchemaError as error:
                raise SchemaCatalogError(
                    "schema.invalid_schema",
                    f"{path.name} is not a valid Draft 2020-12 schema: {error.message}",
                ) from error
            schemas_by_name[path.name] = document
            names_by_id[schema_id] = path.name

        registry: Registry = Registry()
        for schema_id, name in sorted(names_by_id.items()):
            registry = registry.with_resource(
                schema_id,
                Resource.from_contents(schemas_by_name[name]),
            )
        registry = registry.crawl()
        cls._require_registered_refs(schemas_by_name, registry)
        return cls(
            directory=schema_directory,
            schemas_by_name=schemas_by_name,
            names_by_id=names_by_id,
            registry=registry,
        )

    @staticmethod
    def _require_registered_refs(
        schemas_by_name: Mapping[str, dict[str, Any]],
        registry: Registry,
    ) -> None:
        for name in sorted(schemas_by_name):
            document = schemas_by_name[name]
            resource = Resource.from_contents(document)
            for scope, reference in _walk_resource_refs(resource):
                try:
                    registry.resolver(scope).lookup(reference)
                except Unresolvable as error:
                    raise SchemaCatalogError(
                        "schema.unregistered_reference",
                        f"{name} has unresolved reference {reference!r} "
                        f"in scope {scope!r}.",
                    ) from error

    @property
    def schema_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._schemas_by_name))

    @property
    def schema_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._names_by_id))

    def __len__(self) -> int:
        return len(self._schemas_by_name)

    def __contains__(self, schema_ref: object) -> bool:
        return (
            type(schema_ref) is str
            and (
                schema_ref in self._schemas_by_name
                or schema_ref in self._names_by_id
            )
        )

    def get(self, schema_ref: str) -> dict[str, Any]:
        name = self._resolve_name(schema_ref)
        return copy.deepcopy(self._schemas_by_name[name])

    def resolve(self, schema_ref: str) -> dict[str, Any]:
        """Return an isolated schema copy by exact filename or exact ``$id``."""

        return self.get(schema_ref)

    def validate(
        self, schema_ref: str, document: Any
    ) -> tuple[ValidationIssue, ...]:
        name = self._resolve_name(schema_ref)
        validator = Draft202012Validator(
            self._schemas_by_name[name],
            registry=self._registry,
            format_checker=self._format_checker,
        )
        try:
            raw_errors = tuple(validator.iter_errors(document))
        except Exception as error:
            raise SchemaCatalogError(
                "schema.validation_failed",
                f"Could not validate with {schema_ref}: {error}",
            ) from error
        issues = [
            ValidationIssue(
                code=f"schema.{error.validator or 'invalid'}",
                json_pointer=_pointer(error.absolute_path),
                schema_pointer=_pointer(error.absolute_schema_path),
                message=error.message,
            )
            for error in raw_errors
        ]
        return tuple(
            sorted(
                issues,
                key=lambda issue: (
                    issue.json_pointer,
                    issue.schema_pointer,
                    issue.code,
                    issue.message,
                ),
            )
        )

    def require_valid(self, schema_ref: str, document: Any) -> None:
        issues = self.validate(schema_ref, document)
        if issues:
            raise SchemaValidationError(schema_ref, issues)

    def _resolve_name(self, schema_ref: str) -> str:
        if type(schema_ref) is not str:
            raise SchemaCatalogError(
                "schema.invalid_reference_type",
                "Schema reference must be an exact filename or $id string.",
            )
        if schema_ref in self._schemas_by_name:
            return schema_ref
        if schema_ref in self._names_by_id:
            return self._names_by_id[schema_ref]
        raise SchemaCatalogError(
            "schema.unknown",
            f"Unknown schema reference: {schema_ref!r}.",
        )


def _absolute_uri(value: str) -> bool:
    parsed = urlsplit(value)
    return bool(parsed.scheme and not parsed.fragment)
