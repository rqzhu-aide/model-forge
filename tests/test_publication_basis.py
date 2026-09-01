from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from model_forge.harness.publication_basis import (
    capture_publication_basis,
    recover_publication_head,
)
from model_forge.storage.repository import HubRepository, ZERO_SHA256


def _plan_stub() -> SimpleNamespace:
    return SimpleNamespace(
        identity=SimpleNamespace(phase_id="P1"),
        publication_bindings=(),
    )


def test_recover_publication_head_requires_sealed_inventory() -> None:
    basis = {
        "complete_current_slot_inventory": True,
        "authority_sequence": 0,
        "authority_root_sha256": ZERO_SHA256,
        "current_revision": 0,
    }
    with pytest.raises(ValueError):
        recover_publication_head(basis, plan=_plan_stub(), outputs={})


def test_capture_publication_basis_single_snapshot(tmp_path: Path) -> None:
    repository = HubRepository(tmp_path / "hub.sqlite3")
    repository.initialize()
    repository.create_project("project.basis", {"name": "Basis test"})

    basis = capture_publication_basis(
        repository=repository,
        project_id="project.basis",
        plan=_plan_stub(),
        method=None,
    )

    assert basis["authority_sequence"] == 0
    assert basis["authority_root_sha256"] == ZERO_SHA256
    assert basis["current_revision"] == 0
    assert basis["complete_current_slot_inventory"] is True
    assert basis["current_generations"] == {}
    assert basis["slot_scope_prefix"] is None
