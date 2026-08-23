"""Stable errors raised by greenfield storage primitives."""

from __future__ import annotations

from ..errors import ModelForgeError


class StorageError(ModelForgeError):
    """Base class for storage failures with stable error codes."""


class WorkspacePathError(StorageError, ValueError):
    """A workspace-relative path is unsafe or cannot be resolved safely."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


class ArtifactNotFoundError(StorageError, FileNotFoundError):
    """A content-addressed artifact is absent."""

    def __init__(self, sha256: str) -> None:
        self.sha256 = sha256
        super().__init__(
            "artifact.not_found",
            f"No artifact is stored for SHA-256 {sha256}.",
        )


class ArtifactIntegrityError(StorageError):
    """Stored or supplied artifact bytes do not match their identity."""

    def __init__(self, code: str, message: str, *, sha256: str) -> None:
        self.sha256 = sha256
        super().__init__(code, message)


class ArtifactWriteError(StorageError):
    """An artifact could not be staged or published immutably."""

    def __init__(self, message: str) -> None:
        super().__init__("artifact.write_failed", message)


class DatabaseConfigurationError(StorageError, ValueError):
    """A database path or connection setting is unsafe or unsupported."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)


class DatabaseMigrationError(StorageError):
    """The database schema cannot be advanced by the configured migrations."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message)
