"""Tests for H0.8: headless diagnostic CLI."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from method_hub.cli import _parser, main


class TestCLIParser:
    def test_diag_preflight_parses(self) -> None:
        parser = _parser()
        args = parser.parse_args(["diag", "preflight"])
        assert args.command == "diag"
        assert args.diag_command == "preflight"

    def test_diag_start_parses(self, tmp_path: Path) -> None:
        parser = _parser()
        args = parser.parse_args([
            "diag", "start",
            "--project-id", "proj-001",
            "--role", "theorist",
            "--profile-name", "proj-001-theorist",
            "--workspace", str(tmp_path),
            "--task-brief", str(tmp_path / "brief.md"),
            "--memory-policy", "ephemeral",
            "--timeout", "600",
        ])
        assert args.diag_command == "start"
        assert args.project_id == "proj-001"
        assert args.role == "theorist"
        assert args.memory_policy == "ephemeral"
        assert args.timeout == 600

    def test_diag_status_single(self) -> None:
        parser = _parser()
        args = parser.parse_args(["diag", "status", "inv-001"])
        assert args.invocation_id == "inv-001"

    def test_diag_status_list(self) -> None:
        parser = _parser()
        args = parser.parse_args(["diag", "status", "--limit", "5"])
        assert args.invocation_id is None
        assert args.limit == 5

    def test_diag_cancel(self) -> None:
        parser = _parser()
        args = parser.parse_args(["diag", "cancel", "inv-001"])
        assert args.diag_command == "cancel"
        assert args.invocation_id == "inv-001"

    def test_diag_reconcile(self) -> None:
        parser = _parser()
        args = parser.parse_args(["diag", "reconcile"])
        assert args.diag_command == "reconcile"

    def test_diag_memory(self) -> None:
        parser = _parser()
        args = parser.parse_args([
            "diag", "memory", "--profile-name", "my-profile"
        ])
        assert args.diag_command == "memory"
        assert args.profile_name == "my-profile"

    def test_diag_evidence(self) -> None:
        parser = _parser()
        args = parser.parse_args(["diag", "evidence", "--type", "quarantine"])
        assert args.diag_command == "evidence"
        assert args.type == "quarantine"


class TestCLIReconcile:
    def test_reconcile_no_invocations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """diag reconcile with an empty DB should report no work."""
        from method_hub.storage.database import Database
        from method_hub.storage.migrations import HUB_MIGRATIONS
        from method_hub.diagnostics.store import DiagnosticStore
        from method_hub.diagnostics.cli import _diag_reconcile

        db_path = tmp_path / "test.sqlite3"
        db = Database(db_path, migrations=HUB_MIGRATIONS)
        db.initialize()

        result = _diag_reconcile(db_path)
        captured = capsys.readouterr()
        assert result == 0
        assert "No non-terminal" in captured.out

    def test_reconcile_with_running_invocation(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """diag reconcile finds a non-terminal invocation."""
        from method_hub.storage.database import Database
        from method_hub.storage.migrations import HUB_MIGRATIONS
        from method_hub.diagnostics.store import DiagnosticStore
        from method_hub.diagnostics.cli import _diag_reconcile

        db_path = tmp_path / "test.sqlite3"
        db = Database(db_path, migrations=HUB_MIGRATIONS)
        db.initialize()
        store = DiagnosticStore(db)

        store.create_invocation(
            invocation_id="inv-stuck",
            project_id="proj-001",
            role="theorist",
            profile_name="proj-001-theorist",
        )
        for s in ("preflight", "creating", "launch_acknowledged", "running"):
            store.update_status("inv-stuck", status=s)

        result = _diag_reconcile(db_path)
        captured = capsys.readouterr()
        assert result == 0
        assert "inv-stuck" in captured.out
        assert "running" in captured.out


class TestCLIPreflight:
    def test_preflight_reports_hermes_and_bwrap(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from method_hub.diagnostics.cli import _diag_preflight

        # Create a fake Hermes home.
        hermes_root = tmp_path / "hermes"
        profiles = hermes_root / "profiles" / "test-profile"
        profiles.mkdir(parents=True)
        (profiles / "SOUL.md").write_text("# Test")

        result = _diag_preflight(hermes_root)
        captured = capsys.readouterr()

        # Should find the Hermes home and profiles dir.
        assert "Hermes home" in captured.out
        assert "Profiles directory" in captured.out
        # Return code depends on bwrap/hermes being in PATH, which may
        # not be present in CI — just check the report is reasonable.

    def test_preflight_missing_hermes_home(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from method_hub.diagnostics.cli import _diag_preflight

        result = _diag_preflight(tmp_path / "nonexistent")
        assert result == 1  # Failure.
