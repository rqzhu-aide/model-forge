"""Immutable filesystem content-addressed artifact storage."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..domain import Sha256Digest
from .errors import (
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactWriteError,
    WorkspacePathError,
)
from .paths import WorkspacePaths


_CHUNK_SIZE = 256 * 1024


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Verified identity and physical location of one stored byte object."""

    sha256: Sha256Digest
    size: int
    relative_path: str


class ArtifactStore:
    """Store exact bytes once under their SHA-256 content identity."""

    __slots__ = ("_paths", "_namespace")

    def __init__(
        self,
        paths: WorkspacePaths,
        namespace: str = "artifacts/objects",
    ) -> None:
        if not isinstance(paths, WorkspacePaths):
            raise TypeError("paths must be a WorkspacePaths instance")
        namespace_root = paths.ensure_directory(namespace)
        self._paths = paths
        self._namespace = namespace_root.relative_to(paths.root).as_posix()

    @property
    def workspace(self) -> WorkspacePaths:
        return self._paths

    @property
    def namespace(self) -> str:
        return self._namespace

    def put_bytes(
        self,
        payload: bytes | bytearray | memoryview,
        *,
        expected_sha256: str | Sha256Digest | None = None,
    ) -> StoredArtifact:
        """Publish bytes immutably, returning the existing object on repeats."""

        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("payload must be bytes-like")
        data = bytes(payload)
        digest = Sha256Digest(hashlib.sha256(data).hexdigest())
        expected = _digest(expected_sha256) if expected_sha256 is not None else None
        if expected is not None and expected != digest:
            raise ArtifactIntegrityError(
                "artifact.digest_mismatch",
                "Supplied artifact bytes do not match the expected SHA-256 digest.",
                sha256=str(expected),
            )

        try:
            return self.verify(digest)
        except ArtifactNotFoundError:
            pass

        relative = self._relative_path(digest)
        parent_relative = relative.rsplit("/", 1)[0]
        parent = self._paths.ensure_directory(parent_relative)
        target = self._paths.for_write(relative)
        temporary = parent / f".{digest}.{uuid.uuid4().hex}.tmp"
        descriptor: int | None = None
        try:
            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(temporary, flags, 0o600)
            view = memoryview(data)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise OSError("artifact staging write made no progress")
                written += count
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            _verify_file(temporary, digest, return_bytes=False)

            try:
                os.link(temporary, target)
            except FileExistsError:
                return self.verify(digest)
            except OSError as error:
                raise ArtifactWriteError(
                    f"Artifact could not be published without overwriting {target}."
                ) from error
            return self.verify(digest)
        except ArtifactIntegrityError:
            raise
        except ArtifactWriteError:
            raise
        except OSError as error:
            raise ArtifactWriteError(
                f"Artifact could not be staged under {parent}."
            ) from error
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def verify(self, sha256: str | Sha256Digest) -> StoredArtifact:
        """Verify the exact bytes at one content address."""

        digest = _digest(sha256)
        relative = self._relative_path(digest)
        try:
            path = self._paths.for_read(relative)
        except WorkspacePathError as error:
            if error.code == "workspace.path_missing":
                raise ArtifactNotFoundError(str(digest)) from error
            raise ArtifactIntegrityError(
                "artifact.unsafe_location",
                "The content-addressed artifact location is unsafe.",
                sha256=str(digest),
            ) from error
        size = _verify_file(path, digest, return_bytes=False)
        assert isinstance(size, int)
        return StoredArtifact(digest, size, relative)

    def read_bytes(self, sha256: str | Sha256Digest) -> bytes:
        """Return bytes only after verifying their content identity."""

        digest = _digest(sha256)
        relative = self._relative_path(digest)
        try:
            path = self._paths.for_read(relative)
        except WorkspacePathError as error:
            if error.code == "workspace.path_missing":
                raise ArtifactNotFoundError(str(digest)) from error
            raise ArtifactIntegrityError(
                "artifact.unsafe_location",
                "The content-addressed artifact location is unsafe.",
                sha256=str(digest),
            ) from error
        payload = _verify_file(path, digest, return_bytes=True)
        assert isinstance(payload, bytes)
        return payload

    def path_for(self, sha256: str | Sha256Digest) -> Path:
        """Return the contained physical location for a digest without reading it."""

        return self._paths.for_write(self._relative_path(_digest(sha256)))

    def _relative_path(self, digest: Sha256Digest) -> str:
        value = str(digest)
        return f"{self._namespace}/sha256/{value[:2]}/{value[2:]}"


def _digest(value: str | Sha256Digest) -> Sha256Digest:
    if isinstance(value, Sha256Digest):
        return value
    if type(value) is str:
        return Sha256Digest(value)
    raise TypeError("sha256 must be a Sha256Digest or lowercase hexadecimal string")


def _verify_file(
    path: Path,
    expected: Sha256Digest,
    *,
    return_bytes: bool,
) -> bytes | int:
    try:
        before = path.lstat()
    except FileNotFoundError as error:
        raise ArtifactNotFoundError(str(expected)) from error
    except OSError as error:
        raise ArtifactIntegrityError(
            "artifact.unreadable",
            "The stored artifact cannot be inspected.",
            sha256=str(expected),
        ) from error
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ArtifactIntegrityError(
            "artifact.unsafe_location",
            "The stored artifact is not a regular file.",
            sha256=str(expected),
        )

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ArtifactIntegrityError(
            "artifact.unreadable",
            "The stored artifact cannot be opened safely.",
            sha256=str(expected),
        ) from error
    chunks: list[bytes] | None = [] if return_bytes else None
    digest = hashlib.sha256()
    size = 0
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
            raise ArtifactIntegrityError(
                "artifact.changed_during_read",
                "The stored artifact changed while it was opened.",
                sha256=str(expected),
            )
        while True:
            chunk = os.read(descriptor, _CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
            if chunks is not None:
                chunks.append(chunk)
    finally:
        os.close(descriptor)

    try:
        after = path.lstat()
    except OSError as error:
        raise ArtifactIntegrityError(
            "artifact.changed_during_read",
            "The stored artifact disappeared while it was read.",
            sha256=str(expected),
        ) from error
    if not os.path.samestat(before, after):
        raise ArtifactIntegrityError(
            "artifact.changed_during_read",
            "The stored artifact changed while it was read.",
            sha256=str(expected),
        )
    if digest.hexdigest() != str(expected):
        raise ArtifactIntegrityError(
            "artifact.digest_mismatch",
            "Stored artifact bytes do not match their content address.",
            sha256=str(expected),
        )
    if chunks is not None:
        return b"".join(chunks)
    return size
