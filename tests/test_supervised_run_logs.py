"""Supervised run logs endpoint + restart completion watcher (trust package).

Covers:
- GET /projects/{id}/supervised-runs/{inv}/logs — heartbeat/stdout/stderr
  tails, outputs listing, missing run_dir, unknown invocation, byte cap.
- Reconcile watcher — closes an orphaned still-running record when the
  process exits; never spawns twice for the same launch.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from method_hub.api.models import SupervisedRunLogs
from method_hub.application.run_profile_assembler import (
    HermesProbe,
    RunProfileAssembler,
    SealedRun,
)
from method_hub.application.service import MethodHubService
from method_hub.configuration.resources import RoleResourceCatalog
from method_hub.domain.runs import isoformat_utc, utc_now
from method_hub.profiles.project_profiles import MemoryPolicy
from method_hub.storage.database import Database
from method_hub.storage.migrations import HUB_MIGRATIONS

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources" / "team"
SKILL_BUNDLE = ROOT / "resources" / "skills"


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@dataclass
class _FakeSealRecord:
    seal_id: str = "seal.logs.001"
    invocation_id: str = "inv.logs.001"
    project_id: str = "project.logs"
    role: str = "theorist"
    run_dir: str = ""
    idempotency_key: str = "key-1"
    manifest_sha256: str = "a" * 64
    sealed_at: str = "2026-08-15T00:00:00Z"


class _FakeSealStore:
    def __init__(self, record: _FakeSealRecord | None) -> None:
        self._record = record

    def find_by_invocation_id(self, invocation_id: str):
        if self._record and self._record.invocation_id == invocation_id:
            return self._record.__dict__
        return None

    def list_running_launch_records(self):
        return []


def _make_logs_service(run_dir: Path) -> MethodHubService:
    """Build a service whose run_seal_store property serves a fake record.

    The property lazily initializes from ``self._run_seal_store``; setting
    that instance attribute to the fake store is enough and never touches
    the class, so no cross-test pollution is possible.
    """
    record = _FakeSealRecord(run_dir=str(run_dir))
    service = MethodHubService.__new__(MethodHubService)
    service._reconcile_watchers = {}
    service._run_seal_store = _FakeSealStore(record)  # type: ignore[assignment]
    return service


def _get_logs(service: MethodHubService, invocation: str, tail: int = 65536):
    return asyncio.run(
        service.get_supervised_run_logs("project.logs", invocation, tail)
    )


class TestLogsEndpoint:
    @pytest.fixture()
    def logs_service(self, tmp_path: Path):
        run_dir = tmp_path / "runs" / "inv.logs.001"
        (run_dir / "logs").mkdir(parents=True)
        (run_dir / "outputs").mkdir()
        return _make_logs_service(run_dir), run_dir

    def test_serves_all_three_tails(self, logs_service):
        service, run_dir = logs_service
        (run_dir / "logs" / "heartbeat.log").write_text("hb-1\nhb-2\n")
        (run_dir / "logs" / "stdout.log").write_text("out-line")
        (run_dir / "logs" / "stderr.log").write_text("err-line")

        result = _get_logs(service, "inv.logs.001")

        assert isinstance(result, SupervisedRunLogs)
        assert result.heartbeat_tail == "hb-1\nhb-2\n"
        assert result.stdout_tail == "out-line"
        assert result.stderr_tail == "err-line"
        assert result.run_dir_available is True
        assert result.outputs == []

    def test_lists_outputs_with_sizes(self, logs_service):
        service, run_dir = logs_service
        (run_dir / "outputs" / "model.py").write_bytes(b"x" * 128)
        (run_dir / "outputs" / "notes.md").write_bytes(b"y" * 32)

        result = _get_logs(service, "inv.logs.001")

        names = [o.relative_path for o in result.outputs]
        assert names == ["model.py", "notes.md"]
        sizes = {o.relative_path: o.size_bytes for o in result.outputs}
        assert sizes["model.py"] == 128
        assert sizes["notes.md"] == 32

    def test_missing_run_dir_reports_unavailable(self, logs_service):
        service, run_dir = logs_service
        record = service._run_seal_store._record  # type: ignore[attr-defined]
        record.run_dir = str(run_dir.parent / "deleted")

        result = _get_logs(service, "inv.logs.001")

        assert result.run_dir_available is False
        assert result.heartbeat_tail == ""
        assert result.outputs == []

    def test_missing_log_files_yield_empty_tails(self, logs_service):
        service, _ = logs_service

        result = _get_logs(service, "inv.logs.001")

        assert result.run_dir_available is True
        assert result.heartbeat_tail == ""
        assert result.stdout_tail == ""
        assert result.stderr_tail == ""

    def test_tail_byte_cap_respected(self, logs_service):
        service, run_dir = logs_service
        payload = "A" * 10_000
        (run_dir / "logs" / "heartbeat.log").write_text(payload)

        result = _get_logs(service, "inv.logs.001", tail=1024)

        assert len(result.heartbeat_tail) == 1024
        assert result.heartbeat_tail == "A" * 1024

    def test_unknown_invocation_raises(self, logs_service):
        from method_hub.api.errors import CommandRejected

        service, _ = logs_service
        with pytest.raises(CommandRejected):
            _get_logs(service, "inv.does-not-exist")


class TestReconcileWatcher:
    def _make_service(self) -> MethodHubService:
        service = MethodHubService.__new__(MethodHubService)
        service._reconcile_watchers = {}
        service._run_seal_store = _FakeSealStore(None)
        service.__dict__["run_profile_assembler"] = None
        return service

    def test_watcher_closes_record_on_exit(self, tmp_path, monkeypatch):
        from method_hub.executors.protocol import (
            RoleExecutionResult,
            RoleExecutionStatus,
        )

        service = self._make_service()
        closed: list[dict] = []

        class _Store:
            def close_launch_record(self, launch_id, **kwargs):
                closed.append({"launch_id": launch_id, **kwargs})

            def find_by_invocation_id(self, invocation_id: str):
                return None

        class _Executor:
            def __init__(self):
                self.polls = 0

            async def reconcile(self, external_id):
                self.polls += 1
                if self.polls >= 2:
                    return RoleExecutionResult(
                        status=RoleExecutionStatus.SUCCEEDED,
                        external_execution_id=external_id,
                        exit_code=0,
                        summary="exited",
                    )
                return None  # still alive

        executor = _Executor()
        real_sleep = asyncio.sleep

        async def _fast_sleep(seconds: float):
            await real_sleep(0)

        monkeypatch.setattr(
            "method_hub.application.service.asyncio.sleep", _fast_sleep
        )

        async def _run():
            await service._watch_reconciled_run(
                executor, _Store(), "launch-1", "inv-1", "local:pid:1"
            )

        asyncio.run(_run())
        assert closed, "watcher must close the record"
        assert closed[0]["status"] == "succeeded"
        assert closed[0]["exit_code"] == 0

    def test_spawn_watcher_deduplicates(self):
        service = self._make_service()

        class _Task:
            def add_done_callback(self, fn):
                pass

        service._reconcile_watchers["launch-1"] = _Task()  # type: ignore[assignment]
        before = dict(service._reconcile_watchers)
        service._spawn_reconcile_watcher(
            None, None, "launch-1", "inv-1", "ext"  # type: ignore[arg-type]
        )
        assert service._reconcile_watchers == before


# --------------------------------------------------------------------------- #
# NA-1: post-exit validation must use the digest-verified reconstruction path #
# --------------------------------------------------------------------------- #

_GOOD_THEORY = {
    "basis": {"assumptions": ["a1"]},
    "representations": {"statements": []},
    "invocation_id": "inv-001",
    "run_id": "inv-001",
    "method_id": "mh-1",
}


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
            {
                "output_id": "p3.complete_theory",
                "kind": "scientific_record",
                "required": True,
                "relative_path": "p3/complete_theory.json",
                "required_fields": ["basis", "representations"],
                "companions": ["fig1.pdf"],
            },
            {
                "output_id": "p3.notes",
                "kind": "scientific_record",
                "required": False,
                "relative_path": "p3/notes.json",
            },
        ],
        memory_policy=MemoryPolicy.PERSISTENT,
    )
    kwargs.update(overrides)
    return kwargs


def _write_valid_outputs(sealed: SealedRun) -> None:
    outputs = sealed.run_dir / "outputs"
    (outputs / "p3").mkdir(parents=True, exist_ok=True)
    (outputs / "p3" / "complete_theory.json").write_text(
        json.dumps(_GOOD_THEORY), encoding="utf-8"
    )
    (outputs / "p3" / "notes.json").write_text(
        json.dumps({"note": "ok"}), encoding="utf-8"
    )
    (outputs / "p3" / "fig1.pdf").write_bytes(b"%PDF-1.4\n% fake figure\n")


def _close_launch(
    assembler: RunProfileAssembler,
    sealed: SealedRun,
    status: str = "succeeded",
    launch_id: str = "launch-001",
) -> str:
    now = isoformat_utc(utc_now())
    assembler.store.create_launch_record(
        launch_id=launch_id,
        seal_id=sealed.seal_id,
        invocation_id=sealed.invocation_id,
        launched_at=now,
    )
    assembler.store.close_launch_record(
        launch_id,
        status=status,
        external_execution_id="ext-001",
        exit_code=0,
        closed_at=isoformat_utc(utc_now()),
    )
    return launch_id


class TestPostExitValidation:
    @pytest.fixture()
    def watcher_service(self, tmp_path: Path):
        database = Database(tmp_path / "hub.sqlite3", migrations=HUB_MIGRATIONS)
        database.initialize()
        assembler = RunProfileAssembler(
            data_root=tmp_path / "data",
            role_resources=RoleResourceCatalog.load(RESOURCE_ROOT),
            database=database,
            bundle_root=SKILL_BUNDLE,
            hermes_root=tmp_path / "hermes",
            hermes_binary="stub-hermes",
            hermes_probe=lambda binary: HermesProbe(binary, "0.0.1"),
        )
        service = MethodHubService.__new__(MethodHubService)
        service._reconcile_watchers = {}
        service._run_seal_store = assembler.store  # type: ignore[assignment]
        service._run_assembler = assembler
        return service, assembler

    def test_reconciled_success_validates_via_verified_manifest(
        self, watcher_service
    ):
        """Sealed run + closed SUCCEEDED launch + valid declared outputs must
        record a "pass" verdict.  Before NA-1 the watcher validated against
        an empty hand-built manifest, so every output was "undeclared" and
        this exact scenario recorded "fail"."""
        service, assembler = watcher_service
        sealed = assembler.seal_invocation(**_seal_kwargs())
        _write_valid_outputs(sealed)
        launch_id = _close_launch(assembler, sealed)

        service._run_post_exit_validation(sealed.invocation_id)

        stored = assembler.store.get_validation_report(launch_id)
        assert stored is not None
        assert stored["verdict"] == "pass"

    def test_missing_manifest_is_logged_and_never_passes(self, watcher_service):
        """A deleted/corrupt manifest must fail digest-verified reconstruction
        inside the best-effort handler: no "pass" row is recorded and the
        watcher does not crash."""
        service, assembler = watcher_service
        sealed = assembler.seal_invocation(**_seal_kwargs())
        _write_valid_outputs(sealed)
        launch_id = _close_launch(assembler, sealed)
        (sealed.run_dir / "manifest" / "manifest.json").unlink()

        service._run_post_exit_validation(sealed.invocation_id)  # must not raise

        stored = assembler.store.get_validation_report(launch_id)
        assert stored is None or stored["verdict"] != "pass"
