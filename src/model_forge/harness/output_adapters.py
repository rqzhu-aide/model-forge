"""Raw-output preservation for role workspaces.

``validate_role_outputs`` handles structural acceptance (path safety, JSON
shape, schema conformance).  This module preserves the entire role workspace
into the immutable artifact store — including on failure — so the agent's
original bytes are always recoverable for debugging and audit.

The decorative companion-artifact adapt path (``DefaultOutputAdapter`` and
friends) was deleted 2026-09-02 (audit finding F8; Tez decision: option 1,
delete): its result was discarded at the only production call site and had
no consumers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..storage.artifacts import ArtifactStore


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
    "preserve_raw_output",
]
