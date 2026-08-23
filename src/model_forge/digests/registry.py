"""Registry-driven digest construction for immutable research objects."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

from ..errors import ModelForgeError, SchemaValidationError
from ..schemas import SchemaCatalog
from .jcs import JCSCanonicalizationError, canonicalize


ByteResolver = Callable[[str], bytes]

_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_CONTRACT_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]+$")
_SCHEMA_FILE_RE = re.compile(r"^[a-z0-9-]+\.schema\.json$")
_CONSTRUCTIONS = {
    "rfc8785_sha256",
    "rfc8785_projection_sha256",
    "sha256_hex_concat",
    "sha256_referenced_bytes",
    "copy_final_event_digest",
}
_CONTRACT_FIELDS = {
    "contract_id",
    "object_kind",
    "schema_file",
    "instance_pointer",
    "digest_location",
    "construction",
    "payload_pointer",
    "excluded_json_pointers",
    "included_json_pointers",
    "binary_inputs",
    "source_json_pointer",
    "empty_source_value",
}
_BASE_CONTRACT_FIELDS = {
    "contract_id",
    "object_kind",
    "schema_file",
    "instance_pointer",
    "digest_location",
    "construction",
}


class DigestError(ModelForgeError, ValueError):
    """Base error for registry loading, construction, or verification."""

    code = "digest_error"

    def __init__(self, message: str, *, pointer: str = "") -> None:
        self.pointer = pointer
        super().__init__(self.code, message)


class DigestRegistryError(DigestError):
    """The digest registry is malformed or unsupported."""

    code = "digest_registry_invalid"


class DigestContractNotFound(DigestError):
    """No digest contract has the requested stable ID."""

    code = "digest_contract_not_found"


class DigestPointerError(DigestError):
    """A declared RFC 6901 pointer cannot be resolved exactly."""

    code = "digest_pointer_invalid"


class DigestConstructionError(DigestError):
    """A declared digest construction cannot be completed safely."""

    code = "digest_construction_failed"


class DigestMismatchError(DigestError):
    """A stored or referenced digest differs from the computed digest."""

    code = "digest_mismatch"

    def __init__(
        self,
        contract_id: str,
        expected: str,
        actual: str,
        *,
        instance_pointer: str = "",
    ) -> None:
        display_pointer = instance_pointer or "<root>"
        super().__init__(
            f"digest contract {contract_id} at {display_pointer} expected "
            f"{expected}, computed {actual}",
            pointer=instance_pointer,
        )
        self.contract_id = contract_id
        self.expected = expected
        self.actual = actual
        self.instance_pointer = instance_pointer


@dataclass(frozen=True)
class DigestLocation:
    kind: str
    json_pointer: str
    reference_schema_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class BinaryInput:
    json_pointer: str
    decoding: str


@dataclass(frozen=True)
class DigestContract:
    contract_id: str
    object_kind: str
    schema_file: str
    instance_pointer: str
    digest_location: DigestLocation
    construction: str
    payload_pointer: str | None = None
    excluded_json_pointers: tuple[str, ...] = ()
    included_json_pointers: tuple[str, ...] = ()
    binary_inputs: tuple[BinaryInput, ...] = ()
    source_json_pointer: str | None = None
    empty_source_value: str | None = None


@dataclass(frozen=True)
class _SelectedBoundary:
    pointer: str
    value: Any


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DigestRegistryError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise DigestRegistryError(f"non-finite JSON number {value} is not permitted")


def _reject_float(value: str) -> None:
    raise DigestRegistryError(
        f"floating-point JSON number {value} is outside the registry profile"
    )


def _load_registry_document(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DigestRegistryError(f"cannot read digest registry {path}: {exc}") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
            parse_float=_reject_float,
        )
    except DigestRegistryError:
        raise
    except json.JSONDecodeError as exc:
        raise DigestRegistryError(
            f"invalid digest registry JSON at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc
    if type(value) is not dict:
        raise DigestRegistryError("digest registry root must be a JSON object")
    return value


def _decode_pointer_token(token: str, pointer: str) -> str:
    position = 0
    decoded: list[str] = []
    while position < len(token):
        character = token[position]
        if character != "~":
            decoded.append(character)
            position += 1
            continue
        if position + 1 >= len(token) or token[position + 1] not in {"0", "1"}:
            raise DigestPointerError(
                f"pointer {pointer!r} contains an invalid RFC 6901 escape",
                pointer=pointer,
            )
        decoded.append("~" if token[position + 1] == "0" else "/")
        position += 2
    return "".join(decoded)


def _pointer_tokens(pointer: str, *, selector: bool = False) -> tuple[str, ...]:
    if type(pointer) is not str:
        raise DigestPointerError("JSON pointer must be a string")
    if pointer == "":
        return ()
    if not pointer.startswith("/"):
        raise DigestPointerError(
            f"pointer {pointer!r} must be empty or begin with '/'", pointer=pointer
        )
    tokens = tuple(
        _decode_pointer_token(token, pointer) for token in pointer[1:].split("/")
    )
    for token in tokens:
        if selector and "*" in token and token != "*":
            raise DigestPointerError(
                f"pointer {pointer!r} uses '*' outside a selector segment",
                pointer=pointer,
            )
    return tokens


def _list_index(token: str, pointer: str, length: int) -> int:
    if re.fullmatch(r"0|[1-9][0-9]*", token) is None:
        raise DigestPointerError(
            f"pointer {pointer!r} uses invalid array index {token!r}", pointer=pointer
        )
    index = int(token)
    if index >= length:
        raise DigestPointerError(
            f"pointer {pointer!r} array index {index} is out of range", pointer=pointer
        )
    return index


def _resolve_pointer(value: Any, pointer: str) -> Any:
    current = value
    for token in _pointer_tokens(pointer):
        if type(current) is dict:
            if token not in current:
                raise DigestPointerError(
                    f"pointer {pointer!r} does not resolve key {token!r}",
                    pointer=pointer,
                )
            current = current[token]
        elif type(current) is list:
            current = current[_list_index(token, pointer, len(current))]
        else:
            raise DigestPointerError(
                f"pointer {pointer!r} descends through a non-container",
                pointer=pointer,
            )
    return current


def _encode_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _format_pointer(tokens: Sequence[str]) -> str:
    if not tokens:
        return ""
    return "/" + "/".join(_encode_pointer_token(token) for token in tokens)


def _resolve_selector_matches(
    value: Any,
    pointer: str,
) -> list[_SelectedBoundary]:
    tokens = _pointer_tokens(pointer, selector=True)

    def visit(
        current: Any,
        offset: int,
        concrete_tokens: tuple[str, ...],
    ) -> list[_SelectedBoundary]:
        if offset == len(tokens):
            return [_SelectedBoundary(_format_pointer(concrete_tokens), current)]
        token = tokens[offset]
        if token == "*":
            if type(current) is list:
                children = tuple(
                    (str(index), child) for index, child in enumerate(current)
                )
            elif type(current) is dict:
                if not all(type(key) is str for key in current):
                    raise DigestPointerError(
                        f"selector {pointer!r} encountered a non-string object key",
                        pointer=pointer,
                    )
                keys = sorted(current, key=lambda key: key.encode("utf-16-be"))
                children = tuple((key, current[key]) for key in keys)
            else:
                raise DigestPointerError(
                    f"selector {pointer!r} applies '*' to a non-container",
                    pointer=pointer,
                )
            result: list[_SelectedBoundary] = []
            for concrete_token, child in children:
                result.extend(
                    visit(
                        child,
                        offset + 1,
                        concrete_tokens + (concrete_token,),
                    )
                )
            return result
        if type(current) is dict:
            if token not in current:
                raise DigestPointerError(
                    f"selector {pointer!r} does not resolve key {token!r}",
                    pointer=pointer,
                )
            return visit(
                current[token],
                offset + 1,
                concrete_tokens + (token,),
            )
        if type(current) is list:
            index = _list_index(token, pointer, len(current))
            return visit(
                current[index],
                offset + 1,
                concrete_tokens + (str(index),),
            )
        raise DigestPointerError(
            f"selector {pointer!r} descends through a non-container",
            pointer=pointer,
        )

    return visit(value, 0, ())


def _resolve_selector(value: Any, pointer: str) -> list[Any]:
    return [match.value for match in _resolve_selector_matches(value, pointer)]


def _remove_pointer(value: Any, pointer: str) -> None:
    tokens = _pointer_tokens(pointer)
    if not tokens:
        raise DigestPointerError("a digest contract cannot exclude its whole payload")
    parent_pointer = "/" + "/".join(
        token.replace("~", "~0").replace("/", "~1") for token in tokens[:-1]
    ) if len(tokens) > 1 else ""
    parent = _resolve_pointer(value, parent_pointer)
    final = tokens[-1]
    if type(parent) is not dict:
        raise DigestPointerError(
            f"exclusion {pointer!r} must identify an object member", pointer=pointer
        )
    if final not in parent:
        raise DigestPointerError(
            f"exclusion {pointer!r} does not identify an existing member",
            pointer=pointer,
        )
    del parent[final]


_PROJECT_VALUE = object()


def _projection_tree(pointers: Sequence[str]) -> dict[str, Any]:
    tree: dict[str, Any] = {}
    for pointer in pointers:
        tokens = _pointer_tokens(pointer)
        if not tokens:
            if len(pointers) != 1:
                raise DigestPointerError(
                    "root projection pointer cannot be combined with another pointer"
                )
            return {"": _PROJECT_VALUE}
        branch = tree
        for index, token in enumerate(tokens):
            existing = branch.get(token)
            if index == len(tokens) - 1:
                if isinstance(existing, dict) and existing:
                    raise DigestPointerError(
                        f"projection pointer {pointer!r} overlaps an included descendant",
                        pointer=pointer,
                    )
                branch[token] = _PROJECT_VALUE
            else:
                if existing is _PROJECT_VALUE:
                    raise DigestPointerError(
                        f"projection pointer {pointer!r} overlaps an included ancestor",
                        pointer=pointer,
                    )
                if existing is None:
                    existing = {}
                    branch[token] = existing
                branch = existing
    return tree


def _project(value: Any, pointers: Sequence[str]) -> Any:
    tree = _projection_tree(pointers)
    if tree == {"": _PROJECT_VALUE}:
        return copy.deepcopy(value)

    def build(source: Any, branch: Mapping[str, Any], path: str) -> dict[str, Any]:
        if type(source) is not dict:
            raise DigestPointerError(
                f"projection at {path or '/'} descends through a non-object",
                pointer=path,
            )
        result: dict[str, Any] = {}
        for key, child in branch.items():
            if key not in source:
                child_path = f"{path}/{key}" if path else f"/{key}"
                raise DigestPointerError(
                    f"projection pointer {child_path!r} does not resolve",
                    pointer=child_path,
                )
            if child is _PROJECT_VALUE:
                result[key] = copy.deepcopy(source[key])
            else:
                child_path = f"{path}/{key}" if path else f"/{key}"
                result[key] = build(source[key], child, child_path)
        return result

    return build(value, tree, "")


def _require_sha256(value: Any, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise DigestConstructionError(f"{label} must be a lowercase 64-character SHA-256")
    return value


def _require_string_list(value: Any, *, label: str) -> tuple[str, ...]:
    if type(value) is not list or not all(type(item) is str for item in value):
        raise DigestRegistryError(f"{label} must be an array of strings")
    if len(value) != len(set(value)):
        raise DigestRegistryError(f"{label} must not contain duplicates")
    return tuple(value)


def _parse_location(value: Any, contract_id: str) -> DigestLocation:
    if type(value) is not dict:
        raise DigestRegistryError(
            f"digest contract {contract_id} digest_location must be an object"
        )
    allowed = {"kind", "json_pointer", "reference_schema_files"}
    unknown = set(value) - allowed
    if unknown:
        raise DigestRegistryError(
            f"digest contract {contract_id} digest_location has unknown fields "
            f"{sorted(unknown)}"
        )
    kind = value.get("kind")
    pointer = value.get("json_pointer")
    if kind not in {"embedded", "referenced"}:
        raise DigestRegistryError(
            f"digest contract {contract_id} has unknown location kind {kind!r}"
        )
    _pointer_tokens(pointer)
    references = value.get("reference_schema_files", [])
    if kind == "referenced":
        if type(references) is not list or not references:
            raise DigestRegistryError(
                f"referenced digest contract {contract_id} must name schema files"
            )
        if len(references) != len(set(references)) or not all(
            type(item) is str and _SCHEMA_FILE_RE.fullmatch(item) for item in references
        ):
            raise DigestRegistryError(
                f"digest contract {contract_id} has invalid reference schema files"
            )
    elif "reference_schema_files" in value:
        raise DigestRegistryError(
            f"embedded digest contract {contract_id} cannot name reference schemas"
        )
    return DigestLocation(kind, pointer, tuple(references))


def _parse_contract(value: Any) -> DigestContract:
    if type(value) is not dict:
        raise DigestRegistryError("every digest contract must be an object")
    missing = _BASE_CONTRACT_FIELDS - set(value)
    unknown = set(value) - _CONTRACT_FIELDS
    if missing or unknown:
        raise DigestRegistryError(
            f"digest contract has missing fields {sorted(missing)} and unknown fields "
            f"{sorted(unknown)}"
        )
    contract_id = value["contract_id"]
    if type(contract_id) is not str or _CONTRACT_ID_RE.fullmatch(contract_id) is None:
        raise DigestRegistryError(f"invalid digest contract ID {contract_id!r}")
    object_kind = value["object_kind"]
    if type(object_kind) is not str or re.fullmatch(r"^[a-z][a-z0-9_]+$", object_kind) is None:
        raise DigestRegistryError(f"digest contract {contract_id} has invalid object_kind")
    schema_file = value["schema_file"]
    if type(schema_file) is not str or _SCHEMA_FILE_RE.fullmatch(schema_file) is None:
        raise DigestRegistryError(f"digest contract {contract_id} has invalid schema_file")
    instance_pointer = value["instance_pointer"]
    _pointer_tokens(instance_pointer, selector=True)
    construction = value["construction"]
    if construction not in _CONSTRUCTIONS:
        raise DigestRegistryError(
            f"digest contract {contract_id} has unknown construction {construction!r}"
        )
    location = _parse_location(value["digest_location"], contract_id)

    payload_pointer: str | None = None
    excluded: tuple[str, ...] = ()
    included: tuple[str, ...] = ()
    binary_inputs: tuple[BinaryInput, ...] = ()
    source_pointer: str | None = None
    empty_source: str | None = None

    specific_fields = set(value) - _BASE_CONTRACT_FIELDS
    if construction == "rfc8785_sha256":
        required = {"payload_pointer", "excluded_json_pointers"}
        if specific_fields != required:
            raise DigestRegistryError(
                f"digest contract {contract_id} must use exactly {sorted(required)}"
            )
        payload_pointer = value["payload_pointer"]
        _pointer_tokens(payload_pointer)
        excluded = _require_string_list(
            value["excluded_json_pointers"],
            label=f"digest contract {contract_id} exclusions",
        )
        for pointer in excluded:
            _pointer_tokens(pointer)
    elif construction == "rfc8785_projection_sha256":
        required = {"included_json_pointers"}
        if specific_fields != required:
            raise DigestRegistryError(
                f"digest contract {contract_id} must use exactly {sorted(required)}"
            )
        included = _require_string_list(
            value["included_json_pointers"],
            label=f"digest contract {contract_id} included pointers",
        )
        if not included:
            raise DigestRegistryError(
                f"digest contract {contract_id} must include at least one pointer"
            )
        _projection_tree(included)
    elif construction == "sha256_hex_concat":
        required = {"binary_inputs"}
        if specific_fields != required:
            raise DigestRegistryError(
                f"digest contract {contract_id} must use exactly {sorted(required)}"
            )
        raw_inputs = value["binary_inputs"]
        if type(raw_inputs) is not list or len(raw_inputs) < 2:
            raise DigestRegistryError(
                f"digest contract {contract_id} requires at least two binary inputs"
            )
        parsed_inputs: list[BinaryInput] = []
        for raw in raw_inputs:
            if type(raw) is not dict or set(raw) != {"json_pointer", "decoding"}:
                raise DigestRegistryError(
                    f"digest contract {contract_id} has malformed binary input"
                )
            _pointer_tokens(raw["json_pointer"])
            if raw["decoding"] != "lowercase_hex_32_bytes":
                raise DigestRegistryError(
                    f"digest contract {contract_id} has unsupported binary decoding"
                )
            parsed_inputs.append(BinaryInput(raw["json_pointer"], raw["decoding"]))
        binary_inputs = tuple(parsed_inputs)
    elif construction == "sha256_referenced_bytes":
        required = {"source_json_pointer"}
        if specific_fields != required:
            raise DigestRegistryError(
                f"digest contract {contract_id} must use exactly {sorted(required)}"
            )
        source_pointer = value["source_json_pointer"]
        if "*" in _pointer_tokens(source_pointer, selector=True):
            raise DigestRegistryError(
                f"digest contract {contract_id} byte source must resolve once"
            )
    else:
        required_options = (
            {"source_json_pointer"},
            {"source_json_pointer", "empty_source_value"},
        )
        if specific_fields not in required_options:
            raise DigestRegistryError(
                f"digest contract {contract_id} has invalid copy-final fields"
            )
        source_pointer = value["source_json_pointer"]
        _pointer_tokens(source_pointer, selector=True)
        if "empty_source_value" in value:
            empty_source = _require_sha256(
                value["empty_source_value"],
                label=f"digest contract {contract_id} empty source value",
            )

    return DigestContract(
        contract_id=contract_id,
        object_kind=object_kind,
        schema_file=schema_file,
        instance_pointer=instance_pointer,
        digest_location=location,
        construction=construction,
        payload_pointer=payload_pointer,
        excluded_json_pointers=excluded,
        included_json_pointers=included,
        binary_inputs=binary_inputs,
        source_json_pointer=source_pointer,
        empty_source_value=empty_source,
    )


class DigestContractRegistry:
    """Immutable lookup and execution surface for digest contracts.

    Public operations accept the complete document governed by ``schema_file``.
    The registry applies ``instance_pointer`` before running a construction.
    """

    def __init__(self, contracts: Sequence[DigestContract]) -> None:
        by_id: dict[str, DigestContract] = {}
        for contract in contracts:
            if not isinstance(contract, DigestContract):
                raise DigestRegistryError(
                    "digest registry entries must be DigestContract values"
                )
            if contract.contract_id in by_id:
                raise DigestRegistryError(
                    f"digest contract ID {contract.contract_id!r} is duplicated"
                )
            by_id[contract.contract_id] = contract
        self._contracts: Mapping[str, DigestContract] = MappingProxyType(by_id)

    @classmethod
    def load(
        cls,
        path: str | Path,
        schemas: SchemaCatalog,
    ) -> "DigestContractRegistry":
        if not isinstance(schemas, SchemaCatalog):
            raise DigestRegistryError(
                "digest registry loading requires a validated SchemaCatalog"
            )
        registry_path = Path(path)
        document = _load_registry_document(registry_path)
        required = {
            "schema_version",
            "registry_version",
            "canonicalization",
            "hash_algorithm",
            "numeric_profile",
            "contracts",
        }
        if set(document) != required:
            raise DigestRegistryError(
                "digest registry root fields differ from the required contract"
            )
        if document["canonicalization"] != "RFC8785":
            raise DigestRegistryError("digest registry canonicalization must be RFC8785")
        if document["hash_algorithm"] != "SHA-256":
            raise DigestRegistryError("digest registry hash algorithm must be SHA-256")
        if type(document["contracts"]) is not list or not document["contracts"]:
            raise DigestRegistryError("digest registry contracts must be a nonempty array")
        try:
            contracts = tuple(_parse_contract(value) for value in document["contracts"])
        except DigestPointerError as exc:
            raise DigestRegistryError(
                f"digest registry contains a malformed JSON pointer: {exc}"
            ) from exc
        except DigestConstructionError as exc:
            raise DigestRegistryError(
                f"digest registry contains an invalid construction value: {exc}"
            ) from exc
        except DigestRegistryError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise DigestRegistryError(
                f"digest registry contract parsing failed: {exc}"
            ) from exc

        ids = [contract.contract_id for contract in contracts]
        if len(ids) != len(set(ids)):
            duplicates = sorted({item for item in ids if ids.count(item) > 1})
            raise DigestRegistryError(
                f"digest contract IDs must be unique; duplicated {duplicates}"
            )

        try:
            schemas.require_valid("digest-contract-registry.schema.json", document)
        except SchemaValidationError as exc:
            raise DigestRegistryError(
                "digest registry does not satisfy "
                "digest-contract-registry.schema.json"
            ) from exc
        missing_schema_bindings: list[str] = []
        for contract in contracts:
            declared_files = (
                contract.schema_file,
                *contract.digest_location.reference_schema_files,
            )
            for schema_file in declared_files:
                if schema_file not in schemas:
                    missing_schema_bindings.append(
                        f"{contract.contract_id}:{schema_file}"
                    )
        if missing_schema_bindings:
            raise DigestRegistryError(
                "digest contracts reference schema files absent from the catalog: "
                + ", ".join(sorted(missing_schema_bindings))
            )
        return cls(contracts)

    @property
    def contracts(self) -> Mapping[str, DigestContract]:
        """Return the immutable contract mapping keyed by stable contract ID."""

        return self._contracts

    def __len__(self) -> int:
        return len(self._contracts)

    def contract(self, contract_id: str) -> DigestContract:
        try:
            return self._contracts[contract_id]
        except (KeyError, TypeError) as exc:
            raise DigestContractNotFound(
                f"unknown digest contract {contract_id!r}"
            ) from exc

    def _select_boundaries(
        self,
        contract: DigestContract,
        document: Any,
    ) -> tuple[_SelectedBoundary, ...]:
        try:
            return tuple(_resolve_selector_matches(document, contract.instance_pointer))
        except (DigestPointerError, TypeError, UnicodeError) as exc:
            raise DigestConstructionError(
                f"digest contract {contract.contract_id} could not select its "
                f"instance boundary: {exc}"
            ) from exc

    @staticmethod
    def _require_one_boundary(
        contract: DigestContract,
        boundaries: Sequence[_SelectedBoundary],
    ) -> _SelectedBoundary:
        if len(boundaries) != 1:
            raise DigestConstructionError(
                f"digest contract {contract.contract_id} selected {len(boundaries)} "
                "instances; use the all-instance operation"
            )
        return boundaries[0]

    def _compute_boundary(
        self,
        contract: DigestContract,
        boundary: Any,
        byte_resolver: ByteResolver | None,
    ) -> str:
        contract_id = contract.contract_id
        try:
            construction = contract.construction
            if construction == "rfc8785_sha256":
                payload = copy.deepcopy(
                    _resolve_pointer(boundary, contract.payload_pointer or "")
                )
                for pointer in contract.excluded_json_pointers:
                    _remove_pointer(payload, pointer)
                return hashlib.sha256(canonicalize(payload)).hexdigest()
            if construction == "rfc8785_projection_sha256":
                payload = _project(boundary, contract.included_json_pointers)
                return hashlib.sha256(canonicalize(payload)).hexdigest()
            if construction == "sha256_hex_concat":
                decoded: list[bytes] = []
                for binary_input in contract.binary_inputs:
                    digest = _require_sha256(
                        _resolve_pointer(boundary, binary_input.json_pointer),
                        label=(
                            f"digest contract {contract_id} input "
                            f"{binary_input.json_pointer}"
                        ),
                    )
                    decoded.append(bytes.fromhex(digest))
                return hashlib.sha256(b"".join(decoded)).hexdigest()
            if construction == "copy_final_event_digest":
                values = _resolve_selector(
                    boundary, contract.source_json_pointer or ""
                )
                if not values:
                    if contract.empty_source_value is None:
                        raise DigestConstructionError(
                            f"digest contract {contract_id} has no source digest"
                        )
                    return contract.empty_source_value
                return _require_sha256(
                    values[-1], label=f"digest contract {contract_id} final source"
                )
            if construction == "sha256_referenced_bytes":
                if byte_resolver is None:
                    raise DigestConstructionError(
                        f"digest contract {contract_id} requires a byte resolver"
                    )
                source = _resolve_pointer(
                    boundary, contract.source_json_pointer or ""
                )
                if type(source) is not str or not source:
                    raise DigestConstructionError(
                        f"digest contract {contract_id} source must be a nonempty URI"
                    )
                try:
                    content = byte_resolver(source)
                except Exception as exc:
                    raise DigestConstructionError(
                        f"byte resolver failed for digest contract {contract_id}"
                    ) from exc
                if type(content) is not bytes:
                    raise DigestConstructionError(
                        f"byte resolver for digest contract {contract_id} must return bytes"
                    )
                return hashlib.sha256(content).hexdigest()
            raise DigestConstructionError(
                f"digest contract {contract_id} uses unsupported construction "
                f"{construction}"
            )
        except DigestConstructionError:
            raise
        except (DigestPointerError, JCSCanonicalizationError, TypeError, UnicodeError) as exc:
            raise DigestConstructionError(
                f"digest contract {contract_id} construction failed: {exc}"
            ) from exc

    def compute_one(
        self,
        contract_id: str,
        document: Any,
        byte_resolver: ByteResolver | None = None,
    ) -> str:
        """Compute one digest after applying the declared instance selector."""

        contract = self.contract(contract_id)
        boundaries = self._select_boundaries(contract, document)
        boundary = self._require_one_boundary(contract, boundaries)
        return self._compute_boundary(contract, boundary.value, byte_resolver)

    def compute_all(
        self,
        contract_id: str,
        document: Any,
        byte_resolver: ByteResolver | None = None,
    ) -> tuple[str, ...]:
        """Compute one digest for every selected instance in deterministic order."""

        contract = self.contract(contract_id)
        boundaries = self._select_boundaries(contract, document)
        return tuple(
            self._compute_boundary(contract, boundary.value, byte_resolver)
            for boundary in boundaries
        )

    def compute(
        self,
        contract_id: str,
        document: Any,
        byte_resolver: ByteResolver | None = None,
    ) -> str:
        """Compatibility spelling for the one-instance computation."""

        return self.compute_one(contract_id, document, byte_resolver)

    def _require_match_boundary(
        self,
        contract: DigestContract,
        boundary: _SelectedBoundary,
        byte_resolver: ByteResolver | None,
        expected: str | None,
    ) -> str:
        contract_id = contract.contract_id
        boundary_value = boundary.value
        if contract.digest_location.kind == "embedded":
            if expected is not None:
                raise DigestConstructionError(
                    f"embedded digest contract {contract_id} does not accept expected=..."
                )
            try:
                embedded = _resolve_pointer(
                    boundary_value, contract.digest_location.json_pointer
                )
            except DigestPointerError as exc:
                raise DigestConstructionError(
                    f"digest contract {contract_id} could not read its embedded digest: "
                    f"{exc}"
                ) from exc
            expected_digest = _require_sha256(
                embedded,
                label=f"digest contract {contract_id} embedded digest",
            )
        else:
            if expected is None:
                raise DigestConstructionError(
                    f"referenced digest contract {contract_id} requires expected=..."
                )
            expected_digest = _require_sha256(
                expected,
                label=f"digest contract {contract_id} expected digest",
            )

        actual = self._compute_boundary(contract, boundary_value, byte_resolver)
        if actual != expected_digest:
            raise DigestMismatchError(
                contract_id,
                expected_digest,
                actual,
                instance_pointer=boundary.pointer,
            )
        return actual

    def require_match_one(
        self,
        contract_id: str,
        document: Any,
        byte_resolver: ByteResolver | None = None,
        *,
        expected: str | None = None,
    ) -> str:
        """Verify exactly one selected instance against its required digest."""

        contract = self.contract(contract_id)
        boundaries = self._select_boundaries(contract, document)
        boundary = self._require_one_boundary(contract, boundaries)
        return self._require_match_boundary(
            contract,
            boundary,
            byte_resolver,
            expected,
        )

    def require_match_all(
        self,
        contract_id: str,
        document: Any,
        byte_resolver: ByteResolver | None = None,
        *,
        expected: Sequence[str] | None = None,
    ) -> tuple[str, ...]:
        """Verify every selected instance in deterministic selector order."""

        contract = self.contract(contract_id)
        boundaries = self._select_boundaries(contract, document)
        if contract.digest_location.kind == "embedded":
            if expected is not None:
                raise DigestConstructionError(
                    f"embedded digest contract {contract_id} does not accept expected=..."
                )
            expected_values: tuple[str | None, ...] = (None,) * len(boundaries)
        else:
            if expected is None:
                raise DigestConstructionError(
                    f"referenced digest contract {contract_id} requires expected=..."
                )
            if isinstance(expected, (str, bytes, bytearray)) or not isinstance(
                expected, Sequence
            ):
                raise DigestConstructionError(
                    f"digest contract {contract_id} all-instance expected values "
                    "must be a sequence of digests"
                )
            expected_values = tuple(expected)
            if len(expected_values) != len(boundaries):
                raise DigestConstructionError(
                    f"digest contract {contract_id} selected {len(boundaries)} "
                    f"instances but received {len(expected_values)} expected digests"
                )
        return tuple(
            self._require_match_boundary(
                contract,
                boundary,
                byte_resolver,
                expected_digest,
            )
            for boundary, expected_digest in zip(
                boundaries, expected_values, strict=True
            )
        )

    def require_match(
        self,
        contract_id: str,
        document: Any,
        byte_resolver: ByteResolver | None = None,
        *,
        expected: str | None = None,
    ) -> str:
        """Compatibility spelling for one-instance verification."""

        return self.require_match_one(
            contract_id,
            document,
            byte_resolver,
            expected=expected,
        )

    def verify_one(
        self,
        contract_id: str,
        document: Any,
        byte_resolver: ByteResolver | None = None,
        *,
        expected: str | None = None,
    ) -> str:
        """Alias for one-instance verification."""

        return self.require_match_one(
            contract_id,
            document,
            byte_resolver,
            expected=expected,
        )

    def verify_all(
        self,
        contract_id: str,
        document: Any,
        byte_resolver: ByteResolver | None = None,
        *,
        expected: Sequence[str] | None = None,
    ) -> tuple[str, ...]:
        """Alias for all-instance verification."""

        return self.require_match_all(
            contract_id,
            document,
            byte_resolver,
            expected=expected,
        )

    def verify(
        self,
        contract_id: str,
        document: Any,
        byte_resolver: ByteResolver | None = None,
        *,
        expected: str | None = None,
    ) -> str:
        """Alias for one-instance verification."""

        return self.verify_one(
            contract_id,
            document,
            byte_resolver,
            expected=expected,
        )

__all__ = [
    "BinaryInput",
    "ByteResolver",
    "DigestConstructionError",
    "DigestContract",
    "DigestContractNotFound",
    "DigestContractRegistry",
    "DigestError",
    "DigestLocation",
    "DigestMismatchError",
    "DigestPointerError",
    "DigestRegistryError",
]
