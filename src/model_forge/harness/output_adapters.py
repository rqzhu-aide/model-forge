"""Output adapters: extract structured content from role workspace files.

The existing ``validate_role_outputs`` handles structural acceptance (path
safety, JSON shape, schema conformance).  The adapter layer adds:

1. Linked-artifact binding — companion files (PDFs, markdown, code) adjacent
   to the structured output are read, digested, and registered.
2. Field normalization passthrough — structured content is passed through
   unchanged; the adapter does not alter scientific content.
3. Negative-finding preservation — "method failed under condition X" is a
   valid scientific outcome and passes through without modification.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..storage.artifacts import ArtifactStore
from .outputs import OutputSpec, ValidatedOutput


@dataclass(frozen=True, slots=True)
class LinkedArtifact:
    """A companion artifact bound to a structured output."""

    source_path: str
    sha256: str
    byte_length: int
    media_type: str


@dataclass(frozen=True, slots=True)
class AdaptedOutput:
    """Structured output ready for formal-record binding."""

    contract_output_id: str
    output_id: str
    document: Any
    sha256: str
    byte_length: int
    linked_artifacts: tuple[LinkedArtifact, ...] = ()


class OutputAdapter(Protocol):
    """Extract structured output from one role's workspace files."""

    def adapt(
        self,
        *,
        spec: OutputSpec,
        workspace: Path,
        validated: ValidatedOutput,
    ) -> AdaptedOutput: ...


_MEDIA_TYPE_MAP: dict[str, str] = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".tex": "application/x-tex",
    ".py": "text/x-python",
    ".r": "text/x-r",
    ".csv": "text/csv",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".html": "text/html",
}


class DefaultOutputAdapter:
    """Default adapter: bind companion files as linked artifacts."""

    def adapt(
        self,
        *,
        spec: OutputSpec,
        workspace: Path,
        validated: ValidatedOutput,
    ) -> AdaptedOutput:
        output_stem = validated.path.stem
        output_dir = validated.path.parent
        linked: list[LinkedArtifact] = []

        # Scan for companion files with the same stem but different extension
        if output_dir.is_dir():
            for sibling in sorted(output_dir.iterdir()):
                if (
                    sibling.is_file()
                    and not sibling.is_symlink()
                    and sibling.stem == output_stem
                    and sibling != validated.path
                ):
                    suffix = sibling.suffix.lower()
                    if suffix in _MEDIA_TYPE_MAP:
                        try:
                            relative = str(sibling.relative_to(workspace.resolve()))
                        except ValueError:
                            # R31: the sibling is not inside the workspace;
                            # skip it instead of crashing the scan.
                            continue
                        if sibling.stat().st_mtime < validated.path.stat().st_mtime:
                            # R31: predates the current output - a stale
                            # leftover from a prior attempt.
                            continue
                        data = sibling.read_bytes()
                        linked.append(
                            LinkedArtifact(
                                source_path=relative,
                                sha256=hashlib.sha256(data).hexdigest(),
                                byte_length=len(data),
                                media_type=_MEDIA_TYPE_MAP[suffix],
                            )
                        )

        return AdaptedOutput(
            contract_output_id=spec.contract_output_id,
            output_id=spec.output_id,
            document=validated.document,
            sha256=validated.sha256,
            byte_length=validated.byte_length,
            linked_artifacts=tuple(linked),
        )


def preserve_raw_output(
    workspace: Path,
    run_id: str,
    role: str,
    artifacts: ArtifactStore,
) -> str:
    """Copy the entire role workspace into the immutable artifact store.

    Called even when validation fails.  Failed output never becomes current,
    but is preserved for debugging and audit.  Returns the artifact SHA-256.
    """
    import io
    import tarfile

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        tar.add(str(workspace.resolve()), arcname=f"{run_id}/{role}")

    data = buffer.getvalue()

    # Use put_bytes when the store provides it; genuine failures inside
    # put_bytes propagate (R30).
    put_bytes = getattr(artifacts, "put_bytes", None)
    if callable(put_bytes):
        stored = put_bytes(data)
        return str(stored.sha256)
    # Fallback: store via the artifact hash directly
    sha256 = hashlib.sha256(data).hexdigest()
    artifacts_path = artifacts._paths.root / "raw-outputs" / sha256[:2] / sha256[2:4] / f"{sha256}.tar.gz"
    artifacts_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts_path.write_bytes(data)
    return sha256


__all__ = [
    "AdaptedOutput",
    "DefaultOutputAdapter",
    "LinkedArtifact",
    "OutputAdapter",
    "preserve_raw_output",
]
