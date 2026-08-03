"""Verified, non-overwriting installation of bundled recommended skills."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path


class SkillInstallationError(RuntimeError):
    pass


class SkillConflictError(SkillInstallationError):
    pass


@dataclass(frozen=True, slots=True)
class SkillInstallation:
    skill_id: str
    destination: Path
    content_sha256: str
    created: bool


def directory_sha256(path: Path) -> str:
    """Hash relative names and exact bytes after rejecting linked entries."""

    root = _safe_directory(path, "skill directory")
    digest = hashlib.sha256()
    files: list[Path] = []
    for candidate in root.rglob("*"):
        metadata = candidate.lstat()
        if _linked(metadata):
            raise SkillInstallationError(f"Skill contains a linked path: {candidate}.")
        if stat.S_ISREG(metadata.st_mode):
            files.append(candidate)
        elif not stat.S_ISDIR(metadata.st_mode):
            raise SkillInstallationError(f"Skill contains a non-file entry: {candidate}.")
    for candidate in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = candidate.relative_to(root).as_posix().encode("utf-8")
        payload = candidate.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def install_bundled_skill(
    *,
    bundle_root: Path,
    profile_home: Path,
    skill_id: str,
) -> SkillInstallation:
    """Install one exact bundle without replacing a different local directory."""

    if not skill_id or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in skill_id):
        raise SkillInstallationError("Skill ID contains unsupported characters.")
    source = _safe_directory(bundle_root / skill_id, "bundled skill")
    profile = _safe_directory(profile_home, "Hermes profile")
    source_digest = directory_sha256(source)
    skills = profile / "skills"
    try:
        skills.mkdir(mode=0o700)
    except FileExistsError:
        pass
    skills = _safe_directory(skills, "Hermes skills directory")
    destination = skills / skill_id
    try:
        destination.lstat()
    except FileNotFoundError:
        pass
    else:
        destination = _safe_directory(destination, "installed skill")
        installed_digest = directory_sha256(destination)
        if installed_digest != source_digest:
            raise SkillConflictError(
                "A different local skill uses this name. It was not overwritten."
            )
        return SkillInstallation(skill_id, destination, source_digest, False)

    staging = skills / f".{skill_id}.install-{uuid.uuid4().hex}"
    try:
        staging.mkdir(mode=0o700)
        for source_path in sorted(source.rglob("*")):
            relative = source_path.relative_to(source)
            target = staging / relative
            metadata = source_path.lstat()
            if _linked(metadata):
                raise SkillInstallationError(
                    f"Bundled skill contains a linked path: {source_path}."
                )
            if stat.S_ISDIR(metadata.st_mode):
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise SkillInstallationError(
                    f"Bundled skill contains a non-file entry: {source_path}."
                )
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = os.open(target, flags, 0o644)
            try:
                payload = source_path.read_bytes()
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise SkillInstallationError("Skill copy stopped before completion.")
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if directory_sha256(staging) != source_digest:
            raise SkillInstallationError("Staged skill digest differs from its bundle.")
        os.rename(staging, destination)
        if directory_sha256(destination) != source_digest:
            raise SkillInstallationError("Installed skill failed post-install verification.")
        return SkillInstallation(skill_id, destination, source_digest, True)
    except FileExistsError as error:
        raise SkillConflictError(
            "The skill destination changed during installation. Nothing was overwritten."
        ) from error
    finally:
        try:
            shutil.rmtree(staging)
        except FileNotFoundError:
            pass


def _safe_directory(path: Path, label: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise SkillInstallationError(f"{label.capitalize()} is unavailable: {path}.") from error
    if _linked(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise SkillInstallationError(f"{label.capitalize()} must be a real directory: {path}.")
    return path.resolve(strict=True)


def _linked(metadata: os.stat_result) -> bool:
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400 if os.name == "nt" else 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(
        reparse and getattr(metadata, "st_file_attributes", 0) & reparse
    )


__all__ = [
    "SkillConflictError",
    "SkillInstallation",
    "SkillInstallationError",
    "directory_sha256",
    "install_bundled_skill",
]
