"""Capability broker: manifest-authorized file access for role invocations.

The broker materializes frozen inputs and skill bundles into the role workspace,
verifying content digests on every read and recording every access.  The role
agent never sees a path outside its workspace — no artifact store path, no DB
path, no ambient project files.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..harness.execution_records import FrozenInputPath
from ..storage.artifacts import ArtifactStore


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class CapabilityBrokerError(RuntimeError):
    """A capability broker operation failed."""


class CapabilityBroker:
    """Materialize manifest-declared inputs inside the role workspace.

    All writes are confined to the role root (``workspace/inputs/``,
    ``workspace/skills/``).  Every materialized file is verified against its
    declared SHA-256 digest.  Every read is appended to an access log that
    becomes part of the role invocation closure record.
    """

    def materialize_context(
        self,
        *,
        workspace: Path,
        frozen_inputs: Mapping[str, FrozenInputPath],
        skill_manifest: dict[str, Any] | None = None,
        access_log_path: Path | None = None,
    ) -> dict[str, Path]:
        """Write frozen inputs and skill bundles into the workspace.

        Returns a mapping of ``input_id`` → materialized file path inside
        ``workspace/inputs/``.
        """
        inputs_dir = workspace / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)

        result: dict[str, Path] = {}
        for input_id, frozen in frozen_inputs.items():
            dest = self._safe_join(inputs_dir, frozen.path.name)
            self._copy_verified(frozen.path, dest, frozen.sha256, frozen.artifact_id, access_log_path)
            result[input_id] = dest

        if skill_manifest is not None:
            skills_dir = workspace / "skills"
            skills_dir.mkdir(parents=True, exist_ok=True)
            skills = skill_manifest.get("skills", {})
            if isinstance(skills, dict):
                for skill_id, bundle in skills.items():
                    if not isinstance(bundle, dict):
                        continue
                    content_sha = str(bundle.get("content_sha256", ""))
                    skill_file = skills_dir / f"{skill_id}.json"
                    skill_file.write_text(
                        json.dumps(bundle, indent=2) + "\n", encoding="utf-8"
                    )
                    self._verify_digest(skill_file, content_sha)
                    self._log_access(
                        access_log_path,
                        artifact_id=skill_id,
                        sha256=content_sha,
                        byte_length=skill_file.stat().st_size,
                        path=str(skill_file),
                    )

        return result

    def read_artifact(
        self,
        *,
        workspace: Path,
        artifact_id: str,
        expected_sha256: str,
        artifacts: ArtifactStore,
        access_log_path: Path | None = None,
    ) -> Path:
        """Materialize one artifact on demand, verifying its digest."""
        inputs_dir = workspace / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        dest = self._safe_join(inputs_dir, f"{artifact_id}.json")
        data = artifacts.read_bytes(expected_sha256)
        dest.write_bytes(data)
        self._verify_digest(dest, expected_sha256)
        self._log_access(
            access_log_path,
            artifact_id=artifact_id,
            sha256=expected_sha256,
            byte_length=len(data),
            path=str(dest),
        )
        return dest

    # -- internals --------------------------------------------------------

    @staticmethod
    def _safe_join(base: Path, name: str) -> Path:
        """Join ``name`` to ``base``, rejecting traversal attempts."""
        if not name or name.startswith("/"):
            raise CapabilityBrokerError(f"Unsafe artifact name: {name!r}")
        candidate = (base / name).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError as exc:
            raise CapabilityBrokerError(
                f"Path {name!r} escapes the workspace"
            ) from exc
        if candidate.is_symlink():
            raise CapabilityBrokerError(
                f"Path {name!r} is a symlink — rejected"
            )
        return candidate

    @staticmethod
    def _copy_verified(
        src: Path,
        dest: Path,
        expected_sha256: str,
        artifact_id: str,
        access_log_path: Path | None,
    ) -> None:
        """Copy ``src`` to ``dest``, verifying digest and logging access."""
        resolved = src.resolve()
        if resolved.is_symlink():
            raise CapabilityBrokerError(
                f"Source {src!s} is a symlink — rejected"
            )
        if not resolved.is_file():
            raise CapabilityBrokerError(
                f"Source {src!s} is not a regular file"
            )
        data = resolved.read_bytes()
        dest.write_bytes(data)
        CapabilityBroker._verify_digest(dest, expected_sha256)
        CapabilityBroker._log_access(
            access_log_path,
            artifact_id=artifact_id,
            sha256=expected_sha256,
            byte_length=len(data),
            path=str(dest),
        )

    @staticmethod
    def _verify_digest(path: Path, expected_sha256: str) -> None:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha256:
            raise CapabilityBrokerError(
                f"Digest mismatch for {path!s}: expected {expected_sha256}, got {actual}"
            )

    @staticmethod
    def _log_access(
        access_log_path: Path | None,
        *,
        artifact_id: str,
        sha256: str,
        byte_length: int,
        path: str,
    ) -> None:
        if access_log_path is None:
            return
        entry = {
            "artifact_id": artifact_id,
            "sha256": sha256,
            "byte_length": byte_length,
            "materialized_path": path,
            "timestamp": _utc_now_iso(),
        }
        with open(access_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


__all__ = ["CapabilityBroker", "CapabilityBrokerError"]
