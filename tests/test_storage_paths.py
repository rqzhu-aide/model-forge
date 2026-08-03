from __future__ import annotations

from pathlib import Path

import pytest

from method_hub.storage import WorkspacePathError, WorkspacePaths


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspacePaths:
    return WorkspacePaths(tmp_path / "workspace", create=True)


@pytest.mark.parametrize(
    "relative",
    [
        "../outside.txt",
        "safe/../../outside.txt",
        "safe\\..\\outside.txt",
        "/absolute.txt",
        "\\absolute.txt",
        "C:\\absolute.txt",
        "safe//file.txt",
        "safe/./file.txt",
        "bad\x00name.txt",
    ],
)
def test_workspace_rejects_unsafe_write_paths(
    workspace: WorkspacePaths,
    relative: str,
) -> None:
    with pytest.raises(WorkspacePathError) as raised:
        workspace.for_write(relative)

    assert raised.value.code == "workspace.unsafe_path"


def test_workspace_creates_and_resolves_contained_directories(
    workspace: WorkspacePaths,
) -> None:
    directory = workspace.ensure_directory("runs/run_001/artifacts")
    target = workspace.for_write("runs/run_001/artifacts/result.json")

    assert directory.is_dir()
    assert target == directory / "result.json"
    assert target.is_relative_to(workspace.root)


def test_workspace_rejects_symlink_escape_for_writes(
    workspace: WorkspacePaths,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace.root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Directory symlinks are unavailable: {error}")

    with pytest.raises(WorkspacePathError) as raised:
        workspace.for_write("escape/result.json")

    assert raised.value.code == "workspace.symlink_escape"
