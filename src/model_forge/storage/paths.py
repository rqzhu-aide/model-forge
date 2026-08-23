"""Contained filesystem paths for backend-owned greenfield storage."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Final

from .errors import WorkspacePathError


_WINDOWS_DRIVE: Final = re.compile(r"^[A-Za-z]:")
_REPARSE_POINT: Final = getattr(
    stat,
    "FILE_ATTRIBUTE_REPARSE_POINT",
    0x400 if os.name == "nt" else 0,
)


def _is_link_or_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        _REPARSE_POINT
        and getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _absolute(path: str | os.PathLike[str], *, label: str) -> Path:
    try:
        value = os.fspath(path)
    except TypeError as error:
        raise WorkspacePathError(
            "workspace.invalid_path_type",
            f"{label} must be a filesystem path.",
        ) from error
    if type(value) is bytes:
        raise WorkspacePathError(
            "workspace.invalid_path_type",
            f"{label} must be a text path, not bytes.",
        )
    if not value or "\x00" in value:
        raise WorkspacePathError(
            "workspace.invalid_path",
            f"{label} must be nonempty and contain no NUL character.",
        )
    return Path(os.path.abspath(os.path.expanduser(value)))


def _relative_parts(path: str | os.PathLike[str]) -> tuple[str, ...]:
    try:
        value = os.fspath(path)
    except TypeError as error:
        raise WorkspacePathError(
            "workspace.invalid_path_type",
            "Workspace paths must be text paths.",
        ) from error
    if type(value) is bytes:
        raise WorkspacePathError(
            "workspace.invalid_path_type",
            "Workspace paths must be text paths, not bytes.",
        )
    if not value or "\x00" in value:
        raise WorkspacePathError(
            "workspace.unsafe_path",
            "Workspace paths must be nonempty and contain no NUL character.",
        )

    portable = value.replace("\\", "/")
    if (
        portable.startswith("/")
        or portable.startswith("//")
        or _WINDOWS_DRIVE.match(portable)
    ):
        raise WorkspacePathError(
            "workspace.unsafe_path",
            f"Workspace path must be relative: {value!r}.",
        )
    parts = tuple(portable.split("/"))
    if any(part in {"", ".", ".."} or ":" in part for part in parts):
        raise WorkspacePathError(
            "workspace.unsafe_path",
            f"Workspace path contains an unsafe component: {value!r}.",
        )
    return parts


class WorkspacePaths:
    """Resolve paths beneath one trusted workspace without following links.

    The class accepts only portable relative paths. Existing components are
    inspected with ``lstat`` and symbolic links or Windows reparse points are
    rejected. Directory creation proceeds one component at a time and verifies
    the object that won each creation race.
    """

    __slots__ = ("_root",)

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        create: bool = False,
    ) -> None:
        candidate = _absolute(root, label="Workspace root")
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            if not create:
                raise WorkspacePathError(
                    "workspace.root_missing",
                    f"Workspace root does not exist: {candidate}.",
                ) from None
            try:
                parent = candidate.parent.resolve(strict=True)
            except OSError as error:
                raise WorkspacePathError(
                    "workspace.root_parent_unavailable",
                    f"Workspace root parent is unavailable: {candidate.parent}.",
                ) from error
            candidate = parent / candidate.name
            try:
                candidate.mkdir(mode=0o700)
            except FileExistsError:
                pass
            except OSError as error:
                raise WorkspacePathError(
                    "workspace.root_create_failed",
                    f"Workspace root could not be created: {candidate}.",
                ) from error
            try:
                metadata = candidate.lstat()
            except OSError as error:
                raise WorkspacePathError(
                    "workspace.root_unavailable",
                    f"Workspace root cannot be inspected: {candidate}.",
                ) from error
        except OSError as error:
            raise WorkspacePathError(
                "workspace.root_unavailable",
                f"Workspace root cannot be inspected: {candidate}.",
            ) from error

        if _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise WorkspacePathError(
                "workspace.unsafe_root",
                f"Workspace root must be a real directory, not a link: {candidate}.",
            )
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise WorkspacePathError(
                "workspace.root_unavailable",
                f"Workspace root cannot be resolved: {candidate}.",
            ) from error
        self._root = resolved

    @property
    def root(self) -> Path:
        """The canonical absolute workspace root."""

        return self._root

    def for_read(self, relative: str | os.PathLike[str]) -> Path:
        """Return an existing contained path after rejecting every link."""

        return self._inspect(_relative_parts(relative), must_exist=True)

    def for_write(self, relative: str | os.PathLike[str]) -> Path:
        """Return a contained write target without creating it."""

        return self._inspect(_relative_parts(relative), must_exist=False)

    def ensure_directory(
        self,
        relative: str | os.PathLike[str],
        *,
        mode: int = 0o700,
    ) -> Path:
        """Create and verify one contained directory tree."""

        parts = _relative_parts(relative)
        current = self._root
        for part in parts:
            current = current / part
            try:
                current.mkdir(mode=mode)
            except FileExistsError:
                pass
            except OSError as error:
                raise WorkspacePathError(
                    "workspace.directory_create_failed",
                    f"Workspace directory could not be created: {current}.",
                ) from error
            try:
                metadata = current.lstat()
            except OSError as error:
                raise WorkspacePathError(
                    "workspace.path_unavailable",
                    f"Workspace directory cannot be inspected: {current}.",
                ) from error
            if _is_link_or_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
                raise WorkspacePathError(
                    "workspace.unsafe_path",
                    f"Workspace directory is a link or non-directory: {current}.",
                )
        return current

    def _inspect(self, parts: tuple[str, ...], *, must_exist: bool) -> Path:
        current = self._root
        missing = False
        for index, part in enumerate(parts):
            current = current / part
            if missing:
                continue
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                if must_exist:
                    raise WorkspacePathError(
                        "workspace.path_missing",
                        f"Workspace path does not exist: {current}.",
                    ) from None
                missing = True
                continue
            except OSError as error:
                raise WorkspacePathError(
                    "workspace.path_unavailable",
                    f"Workspace path cannot be inspected: {current}.",
                ) from error
            if _is_link_or_reparse(metadata):
                raise WorkspacePathError(
                    "workspace.symlink_escape",
                    f"Workspace path must not traverse a link or reparse point: {current}.",
                )
            if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
                raise WorkspacePathError(
                    "workspace.non_directory_parent",
                    f"Workspace path parent is not a directory: {current}.",
                )
        return current
