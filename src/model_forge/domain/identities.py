"""Schema-aligned value objects shared across the contract kernel."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..errors import DomainValidationError


_STABLE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_SEMANTIC_VERSION = re.compile(r"^[1-9][0-9]*\.[0-9]+\.[0-9]+$")
_ARTIFACT_URI = re.compile(r"^(artifact|generation|run)://[^\s]+$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_MEDIA_TYPE = re.compile(r"^[A-Za-z0-9!#$&^_.+\-]+/[A-Za-z0-9!#$&^_.+\-]+$")
#: Canonical set of declared phase ids. Every layer derives its guard sets
#: from this single source; the pydantic Literal in api/models.py is the one
#: deliberate duplication (types must stay literal).
PHASE_IDS = frozenset({"P1", "P2", "P3", "P4", "P5"})

#: The single architecture schema_version. Every document the runtime
#: authors carries this exact value; bump it in lockstep with the schema
#: package consts.
SCHEMA_VERSION = "1.0.0"
_PHASE_IDS = PHASE_IDS


def _error(code: str, field: str, message: str) -> DomainValidationError:
    return DomainValidationError(code, f"{field}: {message}", field=field)


def _require_string(value: Any, field: str) -> str:
    if type(value) is not str:
        raise _error("domain.invalid_type", field, "must be a string")
    return value


def _require_mapping(value: Any, type_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error("domain.invalid_type", type_name, "must be a JSON object")
    for key in value:
        if type(key) is not str:
            raise _error(
                "domain.invalid_key_type",
                type_name,
                "must contain only string keys",
            )
    return value


def _require_keys(
    value: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    type_name: str,
) -> None:
    actual = frozenset(value)
    missing = sorted(required - actual)
    unknown = sorted(actual - required - optional)
    if missing:
        raise _error(
            "domain.missing_field",
            type_name,
            f"missing required field(s): {', '.join(missing)}",
        )
    if unknown:
        raise _error(
            "domain.unknown_field",
            type_name,
            f"contains unknown field(s): {', '.join(unknown)}",
        )


@dataclass(frozen=True, slots=True)
class StableId:
    """Opaque stable identifier matching ``common-definitions/stableId``."""

    value: str

    def __post_init__(self) -> None:
        value = _require_string(self.value, "stable_id")
        if not 2 <= len(value) <= 160 or _STABLE_ID.fullmatch(value) is None:
            raise _error(
                "domain.invalid_stable_id",
                "stable_id",
                "must match ^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$ and contain 2 to 160 characters",
            )

    @classmethod
    def from_dict(cls, value: Any) -> StableId:
        return cls(_require_string(value, "stable_id"))

    def to_dict(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Sha256Digest:
    """Lowercase 64-character SHA-256 hexadecimal digest."""

    value: str

    def __post_init__(self) -> None:
        value = _require_string(self.value, "sha256")
        if _SHA256.fullmatch(value) is None:
            raise _error(
                "domain.invalid_sha256",
                "sha256",
                "must contain exactly 64 lowercase hexadecimal characters",
            )

    @classmethod
    def from_dict(cls, value: Any) -> Sha256Digest:
        return cls(_require_string(value, "sha256"))

    def to_dict(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SemanticVersion:
    """Phase-contract semantic version in ``major.minor.patch`` form."""

    value: str

    def __post_init__(self) -> None:
        value = _require_string(self.value, "contract_version")
        if _SEMANTIC_VERSION.fullmatch(value) is None:
            raise _error(
                "domain.invalid_semantic_version",
                "contract_version",
                "must match ^[1-9][0-9]*\\.[0-9]+\\.[0-9]+$",
            )

    @property
    def major(self) -> int:
        return int(self.value.split(".", 2)[0])

    @property
    def minor(self) -> int:
        return int(self.value.split(".", 2)[1])

    @property
    def patch(self) -> int:
        return int(self.value.split(".", 2)[2])

    @classmethod
    def from_dict(cls, value: Any) -> SemanticVersion:
        return cls(_require_string(value, "contract_version"))

    def to_dict(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class MethodIdentity:
    """Exact stable method and calculation-defining version identity."""

    stable_id: StableId
    version: int
    definition_sha256: Sha256Digest

    def __post_init__(self) -> None:
        if type(self.stable_id) is str:
            object.__setattr__(self, "stable_id", StableId(self.stable_id))
        elif type(self.stable_id) is not StableId:
            raise _error(
                "domain.invalid_type", "stable_id", "must be a StableId"
            )
        if type(self.version) is not int or self.version < 1:
            raise _error(
                "domain.invalid_method_version",
                "version",
                "must be a positive integer and must not be a Boolean",
            )
        if type(self.definition_sha256) is str:
            object.__setattr__(
                self,
                "definition_sha256",
                Sha256Digest(self.definition_sha256),
            )
        elif type(self.definition_sha256) is not Sha256Digest:
            raise _error(
                "domain.invalid_type",
                "definition_sha256",
                "must be a Sha256Digest",
            )

    @classmethod
    def from_dict(cls, value: Any) -> MethodIdentity:
        mapping = _require_mapping(value, "MethodIdentity")
        _require_keys(
            mapping,
            required=frozenset({"stable_id", "version", "definition_sha256"}),
            type_name="MethodIdentity",
        )
        version = mapping["version"]
        if type(version) is not int or version < 1:
            raise _error(
                "domain.invalid_method_version",
                "version",
                "must be a positive integer and must not be a Boolean",
            )
        return cls(
            stable_id=StableId.from_dict(mapping["stable_id"]),
            version=version,
            definition_sha256=Sha256Digest.from_dict(
                mapping["definition_sha256"]
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_id": self.stable_id.to_dict(),
            "version": self.version,
            "definition_sha256": self.definition_sha256.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ArtifactPointer:
    """Immutable logical artifact reference and exact-byte digest."""

    artifact_id: StableId
    uri: str
    sha256: Sha256Digest
    path: str | None = None
    media_type: str | None = None
    locator: str | None = None

    def __post_init__(self) -> None:
        if type(self.artifact_id) is str:
            object.__setattr__(self, "artifact_id", StableId(self.artifact_id))
        elif type(self.artifact_id) is not StableId:
            raise _error(
                "domain.invalid_type", "artifact_id", "must be a StableId"
            )
        _validate_artifact_uri(self.uri)
        if type(self.sha256) is str:
            object.__setattr__(self, "sha256", Sha256Digest(self.sha256))
        elif type(self.sha256) is not Sha256Digest:
            raise _error("domain.invalid_type", "sha256", "must be a Sha256Digest")
        if self.path is not None:
            _validate_relative_path(self.path)
        if self.media_type is not None:
            media_type = _require_string(self.media_type, "media_type")
            if _MEDIA_TYPE.fullmatch(media_type) is None:
                raise _error(
                    "domain.invalid_media_type",
                    "media_type",
                    "must be a syntactically valid type/subtype value",
                )
        if self.locator is not None:
            _require_string(self.locator, "locator")

    @classmethod
    def from_dict(cls, value: Any) -> ArtifactPointer:
        mapping = _require_mapping(value, "ArtifactPointer")
        _require_keys(
            mapping,
            required=frozenset({"artifact_id", "uri", "sha256"}),
            optional=frozenset({"path", "media_type", "locator"}),
            type_name="ArtifactPointer",
        )
        return cls(
            artifact_id=StableId.from_dict(mapping["artifact_id"]),
            uri=_require_string(mapping["uri"], "uri"),
            sha256=Sha256Digest.from_dict(mapping["sha256"]),
            path=(
                _require_string(mapping["path"], "path")
                if "path" in mapping
                else None
            ),
            media_type=(
                _require_string(mapping["media_type"], "media_type")
                if "media_type" in mapping
                else None
            ),
            locator=(
                _require_string(mapping["locator"], "locator")
                if "locator" in mapping
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "artifact_id": self.artifact_id.to_dict(),
            "uri": self.uri,
            "sha256": self.sha256.to_dict(),
        }
        if self.path is not None:
            result["path"] = self.path
        if self.media_type is not None:
            result["media_type"] = self.media_type
        if self.locator is not None:
            result["locator"] = self.locator
        return result


@dataclass(frozen=True, slots=True)
class PhaseContractIdentity:
    """Exact phase-contract identity selected by a run command."""

    phase_id: str
    contract_version: SemanticVersion
    phase_contract_sha256: Sha256Digest

    def __post_init__(self) -> None:
        phase_id = _require_string(self.phase_id, "phase_id")
        if phase_id not in _PHASE_IDS:
            raise _error(
                "domain.invalid_phase_id",
                "phase_id",
                "must be one of P1, P2, P3, P4, or P5",
            )
        if type(self.contract_version) is str:
            object.__setattr__(
                self,
                "contract_version",
                SemanticVersion(self.contract_version),
            )
        elif type(self.contract_version) is not SemanticVersion:
            raise _error(
                "domain.invalid_type",
                "contract_version",
                "must be a SemanticVersion",
            )
        if type(self.phase_contract_sha256) is str:
            object.__setattr__(
                self,
                "phase_contract_sha256",
                Sha256Digest(self.phase_contract_sha256),
            )
        elif type(self.phase_contract_sha256) is not Sha256Digest:
            raise _error(
                "domain.invalid_type",
                "phase_contract_sha256",
                "must be a Sha256Digest",
            )

    @classmethod
    def from_dict(cls, value: Any) -> PhaseContractIdentity:
        mapping = _require_mapping(value, "PhaseContractIdentity")
        _require_keys(
            mapping,
            required=frozenset(
                {"phase_id", "contract_version", "phase_contract_sha256"}
            ),
            type_name="PhaseContractIdentity",
        )
        return cls(
            phase_id=_require_string(mapping["phase_id"], "phase_id"),
            contract_version=SemanticVersion.from_dict(mapping["contract_version"]),
            phase_contract_sha256=Sha256Digest.from_dict(
                mapping["phase_contract_sha256"]
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "contract_version": self.contract_version.to_dict(),
            "phase_contract_sha256": self.phase_contract_sha256.to_dict(),
        }


def _validate_artifact_uri(value: Any) -> str:
    uri = _require_string(value, "uri")
    if _ARTIFACT_URI.fullmatch(uri) is None:
        raise _error(
            "domain.unsupported_artifact_uri",
            "uri",
            "must use artifact://, generation://, or run:// and contain no whitespace",
        )
    return uri


def _validate_relative_path(value: Any) -> str:
    path = _require_string(value, "path")
    if not path:
        raise _error("domain.unsafe_path", "path", "must not be empty")
    if path.startswith(("/", "\\")) or _WINDOWS_DRIVE.match(path):
        raise _error(
            "domain.unsafe_path", "path", "must be a backend-relative path"
        )
    if "\x00" in path or any(ord(character) < 32 for character in path):
        raise _error(
            "domain.unsafe_path", "path", "must not contain control characters"
        )
    components = re.split(r"[/\\]", path)
    if ".." in components:
        raise _error(
            "domain.unsafe_path",
            "path",
            "must not contain parent-directory traversal",
        )
    return path
