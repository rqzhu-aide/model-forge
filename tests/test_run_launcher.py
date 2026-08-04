"""WP-E0 tests: supervised launch of sealed runs (Block 5).

Covers the supervised launch path end to end with a stub Hermes
executable: the happy path (HERMES_HOME pointing at the assembled run
profile, no ``-p`` argument, brief digest recorded, bounded logs and
heartbeats persisted, launch record closed as succeeded); a preflight
failure aborting before any process is created; the project-role state
lock conflict; provider-key secret hygiene through the executor's
redaction; and the executor regression guard that the diagnostic lane
keeps its ``-p`` behavior by default.  Uses tmp_path fixtures and a stub
executable — no real Hermes required.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from method_hub.application.run_launcher import (
    LaunchPreflightError,
    LaunchResult,
    launch_sealed_run,
)
from method_hub.application.run_profile_assembler import (
    HermesProbe,
    RunProfileAssembler,
    StateLockHeld,
)
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.executors.local_hermes import (
    LocalHermesExecutor,
    LocalHermesExecutorSettings,
)
from method_hub.executors.protocol import RoleExecutionStatus, RoleInvocation
from method_hub.profiles.project_profiles import (
    MemoryPolicy,
    project_role_profile_name,
)
from method_hub.storage.database import Database
from method_hub.storage.migrations import HUB_MIGRATIONS

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources" / "team"
SKILL_BUNDLE = ROOT / "resources" / "skills"

STUB_VERSION = "0.0.1"

#: Provider key whose shape (``sk-proj-...`` with dashes/underscores)
#: must be caught by the executor's widened redaction regex.
SECRET_ENV_NAME = "TEST_PROVIDER_KEY"
TEST_PROVIDER_KEY_VALUE = "sk-proj-testkey_1234567890abcd"

_STUB_SCRIPT = r'''#!/usr/bin/env python3
"""Stub Hermes executable for WP-E0 supervised-launch tests.

Handles --version and accepts the -z/-p/--usage-file/-m/--provider/
--skills args.  Prints the effective HERMES_HOME, the full argv, and
the value of TEST_PROVIDER_KEY (when set) so tests can assert on the
launcher's environment and command construction, then exits 0.
"""
import argparse
import json
import os
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", action="store_true")
    parser.add_argument("-z", dest="prompt")
    parser.add_argument("-p", dest="profile")
    parser.add_argument("--usage-file", dest="usage_file")
    parser.add_argument("-m", dest="model")
    parser.add_argument("--provider", dest="provider")
    parser.add_argument("--skills", dest="skills")
    args, _ = parser.parse_known_args()

    if args.version:
        print("stub-hermes 0.0.1")
        sys.exit(0)

    print("HERMES_HOME=" + os.environ.get("HERMES_HOME", ""))
    print("ARGV=" + json.dumps(sys.argv))
    print("SECRET=" + os.environ.get("TEST_PROVIDER_KEY", ""))

    if args.usage_file:
        with open(args.usage_file, "w") as f:
            f.write('{"tokens": 1}')
    sys.exit(0)


if __name__ == "__main__":
    main()
'''


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "hub.sqlite3", migrations=HUB_MIGRATIONS)
    db.initialize()
    return db


@pytest.fixture
def catalog() -> RoleResourceCatalog:
    return RoleResourceCatalog.load(RESOURCE_ROOT)


@pytest.fixture
def hermes_root(tmp_path: Path) -> Path:
    root = tmp_path / "hermes"
    root.mkdir()
    return root


@pytest.fixture
def stub_hermes(tmp_path: Path) -> Path:
    """Create the stub Hermes executable and return its absolute path."""
    stub = tmp_path / "stub-hermes"
    stub.write_text(_STUB_SCRIPT)
    stub.chmod(0o755)
    return stub


def _stub_probe(stub_hermes: Path):
    """Probe lambda matching the stub executable and its recorded version."""
    return lambda binary: HermesProbe(str(stub_hermes), STUB_VERSION)


@pytest.fixture
def assembler(
    tmp_path: Path,
    database: Database,
    catalog: RoleResourceCatalog,
    hermes_root: Path,
    stub_hermes: Path,
) -> RunProfileAssembler:
    """Assembler whose seal records the stub executable and its version."""
    return RunProfileAssembler(
        data_root=tmp_path / "data",
        role_resources=catalog,
        database=database,
        bundle_root=SKILL_BUNDLE,
        hermes_root=hermes_root,
        hermes_binary=str(stub_hermes),
        hermes_probe=_stub_probe(stub_hermes),
    )


def _seal_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = dict(
        invocation_id="inv-001",
        idempotency_key="key-001",
        project_id="proj-001",
        role="theorist",
        phase="P3",
        method_identity={"method_id": "mh-1", "version": "1.0"},
        user_choices={"mode": "headless", "context_policy": "strict"},
        selected_context_references=[
            {"context_id": "ctx-1", "record_id": "rec-1"},
        ],
        expected_outputs=[
            {"output_id": "out-1", "kind": "scientific_record", "required": True},
        ],
        memory_policy=MemoryPolicy.PERSISTENT,
    )
    kwargs.update(overrides)
    return kwargs


def _launch_settings(stub_hermes: Path) -> LocalHermesExecutorSettings:
    """Fast-polling executor settings pointing at the stub binary."""
    return LocalHermesExecutorSettings(
        hermes_binary=str(stub_hermes),
        poll_interval_seconds=0.05,
        output_limit_bytes=65536,  # 64 KiB — small for fast tests.
        terminate_grace_seconds=1,
        kill_grace_seconds=1,
    )


def _make_invocation(workspace: Path) -> RoleInvocation:
    """Minimal invocation with a named profile (executor guard tests)."""
    return RoleInvocation(
        execution_id="exec-1",
        invocation_id="inv-1",
        run_id="run-1",
        project_id="p",
        phase="diagnostic",
        mode="headless",
        stage_id="diag-1",
        role="theorist",
        profile="test-profile",
        workspace=workspace,
        task_brief=workspace / "task.md",
        expected_output_paths=(),
        timeout_seconds=60,
    )


def _write_brief(tmp_path: Path, name: str = "brief.md") -> Path:
    brief = tmp_path / name
    brief.write_text("# Brief\nProduce the declared output.\n", encoding="utf-8")
    return brief


# --------------------------------------------------------------------------- #
# (a) Happy path                                                               #
# --------------------------------------------------------------------------- #


class TestLaunchHappyPath:
    def test_sealed_run_launches_to_success(
        self,
        assembler: RunProfileAssembler,
        stub_hermes: Path,
        tmp_path: Path,
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        brief = _write_brief(tmp_path)

        result = launch_sealed_run(
            assembler,
            sealed,
            brief,
            executor_settings=_launch_settings(stub_hermes),
            hermes_probe=_stub_probe(stub_hermes),
            min_free_bytes=1_048_576,
        )

        assert isinstance(result, LaunchResult)
        assert result.status == RoleExecutionStatus.SUCCEEDED
        assert result.exit_code == 0
        assert result.run_dir == sealed.run_dir

        # The launch record is closed as succeeded with the exit code.
        record = assembler.store.get_launch_record(result.launch_id)
        assert record is not None
        assert record["status"] == "succeeded"
        assert record["exit_code"] == 0
        assert record["invocation_id"] == "inv-001"
        assert record["seal_id"] == sealed.seal_id
        assert record["closed_at"] is not None

        # The materialized brief digest is recorded on the launch record.
        assert record["task_brief_sha256"] == hashlib.sha256(
            brief.read_bytes()
        ).hexdigest()
        assert (
            sealed.run_dir / "workspace" / "task.md"
        ).read_bytes() == brief.read_bytes()

        # Bounded logs: stdout and heartbeats were persisted.
        run_dir = sealed.run_dir
        stdout_log = run_dir / "logs" / "stdout.log"
        heartbeat_log = run_dir / "logs" / "heartbeat.log"
        assert stdout_log.is_file()
        assert (run_dir / "logs" / "stderr.log").is_file()
        assert heartbeat_log.is_file()
        assert "launch_intent" in heartbeat_log.read_text(encoding="utf-8")

        # HERMES_HOME points at the assembled run profile...
        stdout = stdout_log.read_text(encoding="utf-8")
        assert f"HERMES_HOME={(run_dir / 'profile').resolve()}" in stdout
        # ...and the command carries no -p profile argument.
        argv_line = next(
            line for line in stdout.splitlines() if line.startswith("ARGV=")
        )
        assert '"-p"' not in argv_line
        assert "--usage-file" in argv_line


# --------------------------------------------------------------------------- #
# (b) Preflight failure aborts before any process is created                   #
# --------------------------------------------------------------------------- #


class TestLaunchPreflightAbort:
    def test_tampered_profile_aborts_before_launch(
        self,
        assembler: RunProfileAssembler,
        stub_hermes: Path,
        tmp_path: Path,
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        soul = sealed.run_dir / "profile" / "SOUL.md"
        soul.write_text(
            soul.read_text(encoding="utf-8") + "\n# Tampered\n",
            encoding="utf-8",
        )
        brief = _write_brief(tmp_path)

        with pytest.raises(LaunchPreflightError) as excinfo:
            launch_sealed_run(
                assembler,
                sealed,
                brief,
                executor_settings=_launch_settings(stub_hermes),
                hermes_probe=_stub_probe(stub_hermes),
                min_free_bytes=1_048_576,
            )
        assert "role_assets" in excinfo.value.report.to_dict()["failed_checks"]

        # The launch record is closed as failed; no process ever ran.
        record = assembler.store.find_launch_record_by_invocation("inv-001")
        assert record is not None
        assert record["status"] == "failed"
        assert record["exit_code"] is None
        assert record["external_execution_id"] is None
        assert not (sealed.run_dir / "logs" / "stdout.log").exists()
        assert not (sealed.run_dir / "logs" / "heartbeat.log").exists()
        # The state lock was released on the abort path.
        assert assembler.store.state_lock_holder(
            project_role_profile_name("proj-001", "theorist")
        ) is None


# --------------------------------------------------------------------------- #
# (c) Project-role state lock conflict                                        #
# --------------------------------------------------------------------------- #


class TestLaunchLockConflict:
    def test_lock_held_by_another_invocation_raises(
        self,
        assembler: RunProfileAssembler,
        stub_hermes: Path,
        tmp_path: Path,
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        brief = _write_brief(tmp_path)

        with assembler.state_lock("proj-001", "theorist", "inv-other-holder"):
            with pytest.raises(StateLockHeld):
                launch_sealed_run(
                    assembler,
                    sealed,
                    brief,
                    executor_settings=_launch_settings(stub_hermes),
                    hermes_probe=_stub_probe(stub_hermes),
                    min_free_bytes=1_048_576,
                )
        # The lock conflict aborts before any launch record is created.
        assert assembler.store.find_launch_record_by_invocation("inv-001") is None
        assert not (sealed.run_dir / "logs" / "stdout.log").exists()


# --------------------------------------------------------------------------- #
# (d) Secret hygiene through the executor's redaction                          #
# --------------------------------------------------------------------------- #


class TestLaunchSecretHygiene:
    def test_provider_key_never_persisted(
        self,
        assembler: RunProfileAssembler,
        stub_hermes: Path,
        tmp_path: Path,
    ) -> None:
        sealed = assembler.seal_invocation(**_seal_kwargs())
        brief = _write_brief(tmp_path)

        result = launch_sealed_run(
            assembler,
            sealed,
            brief,
            executor_settings=_launch_settings(stub_hermes),
            hermes_probe=_stub_probe(stub_hermes),
            secret_env={SECRET_ENV_NAME: TEST_PROVIDER_KEY_VALUE},
            min_free_bytes=1_048_576,
        )
        assert result.status == RoleExecutionStatus.SUCCEEDED

        run_dir = sealed.run_dir
        # The stub echoed the injected key on stdout; the executor
        # redacted it from the captured stream before the launcher
        # persisted it.
        stdout = (run_dir / "logs" / "stdout.log").read_text(encoding="utf-8")
        assert "SECRET=[REDACTED]" in stdout
        assert TEST_PROVIDER_KEY_VALUE not in stdout

        # No log under the run directory carries the literal key.
        for log in run_dir.glob("logs/*.log"):
            assert TEST_PROVIDER_KEY_VALUE not in log.read_text(
                encoding="utf-8"
            ), f"secret leaked into {log}"

        # The manifest never saw the key either.
        manifest_bytes = (run_dir / "manifest" / "manifest.json").read_bytes()
        assert TEST_PROVIDER_KEY_VALUE.encode() not in manifest_bytes

        # Nor the launch record.
        record = assembler.store.get_launch_record(result.launch_id)
        assert record is not None
        assert TEST_PROVIDER_KEY_VALUE not in json.dumps(record)


# --------------------------------------------------------------------------- #
# (e) Executor regression guard: -p behavior preserved by default              #
# --------------------------------------------------------------------------- #


class TestExecutorProfileArgRegression:
    def test_default_settings_emit_profile_arg(self, tmp_path: Path) -> None:
        """The diagnostic lane keeps its -p behavior by default (WP-E0)."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "task.md").write_text("# Test")

        settings = LocalHermesExecutorSettings()
        assert settings.use_profile_arg is True
        executor = LocalHermesExecutor(settings)
        cmd = executor._build_command(_make_invocation(workspace), "/usr/bin/hermes")
        assert "-p" in cmd
        profile_idx = cmd.index("-p") + 1
        assert cmd[profile_idx] == "test-profile"

    def test_use_profile_arg_false_suppresses_profile_arg(
        self, tmp_path: Path
    ) -> None:
        """The sealed-run lane never emits -p (the profile IS the home)."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "task.md").write_text("# Test")

        settings = replace(LocalHermesExecutorSettings(), use_profile_arg=False)
        executor = LocalHermesExecutor(settings)
        cmd = executor._build_command(_make_invocation(workspace), "/usr/bin/hermes")
        assert "-p" not in cmd
