"""Immutable value records and deterministic identities for role execution."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..contracts import ResolvedStage
from ..digests.jcs import canonicalize
from ..executors import RoleExecutionStatus
from ..storage import ArtifactStore
from .execution_context import RunExecutionContext
from .outputs import OutputSpec


class RoleLifecycleError(RuntimeError):
    """A frozen role invocation cannot be executed or reconciled safely."""


class RoleExecutionPending(RoleLifecycleError):
    """An acknowledged external execution has not reached a terminal state."""

    def __init__(
        self, message: str, *, external_execution_id: str | None = None
    ) -> None:
        super().__init__(message)
        self.external_execution_id = external_execution_id


class RoleExecutionInfrastructureError(RoleLifecycleError):
    """Harness-side bookkeeping failed; the execution outcome is unknown.

    Raised when an observer/persistence call (not the executor's domain
    logic) fails, so the failure must NOT be sealed into a durable FAILED
    closure. The run stays `running` and a later pass reconciles.
    """


@dataclass(frozen=True, slots=True)
class FrozenInputPath:
    input_id: str
    artifact_id: str
    sha256: str
    path: Path
    media_type: str = "application/json"


@dataclass(frozen=True, slots=True)
class SealedRoleOutput:
    contract_output_id: str
    output_id: str
    artifact_id: str
    sha256: str
    size: int
    media_type: str
    storage_relative_path: str

    def artifact_pointer(self, run_id: str) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "uri": f"run://{run_id}/artifact/{self.artifact_id}",
            "path": self.storage_relative_path,
            "sha256": self.sha256,
            "media_type": self.media_type,
        }


@dataclass(frozen=True, slots=True)
class RoleClosureResult:
    role: str
    status: RoleExecutionStatus
    execution_id: str
    invocation_id: str
    invocation_sha256: str
    closure_id: str | None
    closure_sha256: str | None
    closure_artifact_id: str | None
    outputs: tuple[SealedRoleOutput, ...]
    closed_at: str | None
    failure_code: str | None = None
    reconciled: bool = False

    def output_inputs(self, *, artifacts: ArtifactStore) -> dict[str, FrozenInputPath]:
        result: dict[str, FrozenInputPath] = {}
        for output in self.outputs:
            stored = artifacts.verify(output.sha256)
            result[output.contract_output_id] = FrozenInputPath(
                input_id=output.contract_output_id,
                artifact_id=output.artifact_id,
                sha256=output.sha256,
                path=artifacts.workspace.for_read(stored.relative_path),
                media_type=output.media_type,
            )
        return result


def deterministic_id(kind: str, *values: Any) -> str:
    digest = hashlib.sha256(canonicalize(list(values))).hexdigest()
    return f"{kind}.{digest}"


def document_sha256(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonicalize(dict(document))).hexdigest()


def _identity_basis(
    run_id: Any,
    manifest_sha256: Any,
    stage: ResolvedStage,
    role: str,
    identity_suffix: str = "",
) -> tuple[Any, ...]:
    basis = (
        str(run_id),
        str(manifest_sha256),
        stage.sequence,
        stage.stage_id,
        role,
    )
    if identity_suffix:
        basis = (*basis, identity_suffix)
    return basis


def _identity_ids(basis: tuple[Any, ...]) -> tuple[str, str, str]:
    return (
        deterministic_id("invocation", *basis),
        deterministic_id("execution", *basis),
        deterministic_id("closure", *basis),
    )


def role_identity(
    context: RunExecutionContext, stage: ResolvedStage, role: str
) -> tuple[str, str, str]:
    return _identity_ids(
        _identity_basis(
            context.run_id,
            context.manifest_sha256,
            stage,
            role,
            context.identity_suffix,
        )
    )


def correction_role_identity(
    run_id: str,
    manifest_sha256: str,
    stage: ResolvedStage,
    role: str,
    correction_command_id: str,
) -> tuple[str, str, str]:
    """Identity family for a correction re-invocation of one stage role.

    Provably agrees with ``role_identity`` for a context whose
    ``identity_suffix`` is ``f"correction.{correction_command_id}"``: both
    funnels share ``_identity_basis``/``_identity_ids`` and the suffix is
    appended last.
    """
    return _identity_ids(
        _identity_basis(
            run_id,
            manifest_sha256,
            stage,
            role,
            f"correction.{correction_command_id}",
        )
    )


def output_artifact_id(
    context: RunExecutionContext, spec: OutputSpec, sha256: str
) -> str:
    return deterministic_id(
        "artifact",
        str(context.project_id),
        str(context.run_id),
        spec.contract_output_id,
        sha256,
    )


def closure_artifact_id(closure_id: str) -> str:
    return deterministic_id("artifact", closure_id)


def immutable_write(path: Path, payload: bytes) -> None:
    """Create exact bytes once and reject a conflicting prior file."""

    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if existing != payload:
            raise RoleLifecycleError(f"Frozen file {path} already has different bytes.")
        return
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        view = memoryview(payload)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("frozen file write made no progress")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
    except FileExistsError:
        if path.read_bytes() != payload:
            raise RoleLifecycleError(
                f"Frozen file {path} won a race with different bytes."
            ) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


__all__ = [
    "FrozenInputPath",
    "RoleClosureResult",
    "RoleExecutionInfrastructureError",
    "RoleExecutionPending",
    "RoleLifecycleError",
    "SealedRoleOutput",
    "closure_artifact_id",
    "correction_role_identity",
    "deterministic_id",
    "document_sha256",
    "immutable_write",
    "output_artifact_id",
    "role_identity",
]
