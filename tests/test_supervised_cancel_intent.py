"""NA-2 regression tests: persisted cancel intent for supervised runs.

Before NA-2 the explicit-cancel intent lived only in an in-memory
``threading.Event`` that dies with the server process, so a supervised
launch cancelled (SIGTERM/SIGKILL) shortly before a server restart was
closed as ``failed`` by BOTH reconcile close paths.  Migration 13 adds
``run_launch_records.cancel_requested_at``; the cancel command writes
it BEFORE signalling, and both close paths (startup
``_reconcile_supervised_launches`` and the ``_watch_reconciled_run``
completion watcher) consult it when the process is gone.

Every "restart" below is simulated by constructing a FRESH
Database/RunSealStore/MethodHubService over the same ``hub.sqlite3``
file — no in-memory cancel event carries over.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from method_hub.application.run_profile_assembler import RunSealStore
from method_hub.application.service import MethodHubService
from method_hub.domain.runs import isoformat_utc, utc_now
from method_hub.executors.protocol import (
    RoleExecutionResult,
    RoleExecutionStatus,
)
from method_hub.storage.database import Database
from method_hub.storage.migrations import HUB_MIGRATIONS

PROJECT = "proj-001"
INVOCATION = "inv-001"
SEAL = "seal.inv-001"
LAUNCH = "launch.inv-001"
EXTERNAL_ID = "local:pid:4242:st:1:mk:x:bi:y"


# --------------------------------------------------------------------------- #
# Harness                                                                      #
# --------------------------------------------------------------------------- #


def _fresh_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "hub.sqlite3", migrations=HUB_MIGRATIONS)
    assert database.initialize() == 13
    return database


def _restarted_store(tmp_path: Path) -> RunSealStore:
    """A brand-new store over the EXISTING database file (a restart)."""
    database = Database(tmp_path / "hub.sqlite3", migrations=HUB_MIGRATIONS)
    database.initialize()  # already migrated — applies nothing
    return RunSealStore(database)


def _seed_running_launch(store: RunSealStore) -> None:
    store.create_seal(
        seal_id=SEAL,
        invocation_id=INVOCATION,
        project_id=PROJECT,
        role="theorist",
        idempotency_key="key.inv-001",
        run_dir="/nonexistent/run/dir",
        manifest_sha256="a" * 64,
        sealed_at=isoformat_utc(utc_now()),
    )
    store.create_launch_record(
        launch_id=LAUNCH,
        seal_id=SEAL,
        invocation_id=INVOCATION,
        launched_at=isoformat_utc(utc_now()),
    )
    store.record_launch_external_id(LAUNCH, EXTERNAL_ID)


def _restarted_service(store: RunSealStore) -> MethodHubService:
    """A 'restarted' service: real store, EMPTY in-memory cancel state."""
    service = MethodHubService.__new__(MethodHubService)
    service.settings = SimpleNamespace(  # type: ignore[assignment]
        hermes_executable="/nonexistent/hermes"
    )
    service._run_seal_store = store
    service._cancel_requests = {}
    service._reconcile_watchers = {}
    return service


def _gone_result(external_id: str) -> RoleExecutionResult:
    """What LocalHermesExecutor.reconcile returns for a gone process."""
    return RoleExecutionResult(
        status=RoleExecutionStatus.FAILED,
        external_execution_id=external_id,
        exit_code=None,
        summary="process exited while the server was offline",
    )


class _GoneExecutor:
    async def reconcile(self, external_id: str) -> RoleExecutionResult:
        return _gone_result(external_id)


@pytest.fixture
def fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    real_sleep = asyncio.sleep

    async def _fast_sleep(seconds: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(
        "method_hub.application.service.asyncio.sleep", _fast_sleep
    )


# --------------------------------------------------------------------------- #
# Startup reconcile close path (_reconcile_supervised_launches)               #
# --------------------------------------------------------------------------- #


def test_reconcile_after_restart_closes_cancelled_when_intent_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _fresh_database(tmp_path)
    store = RunSealStore(database)
    _seed_running_launch(store)
    store.mark_launch_cancel_requested(LAUNCH, isoformat_utc(utc_now()))

    # Restart: fresh store + service over the same file, no cancel event.
    restarted = _restarted_service(_restarted_store(tmp_path))
    monkeypatch.setattr(
        "method_hub.application.service.LocalHermesExecutor",
        lambda settings: _GoneExecutor(),
    )

    asyncio.run(restarted._reconcile_supervised_launches())

    closed = restarted.run_seal_store.get_launch_record(LAUNCH)
    assert closed is not None
    assert closed["status"] == "cancelled"
    assert closed["external_execution_id"] == EXTERNAL_ID
    assert closed["closed_at"] is not None


def test_reconcile_after_restart_closes_failed_without_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = _fresh_database(tmp_path)
    store = RunSealStore(database)
    _seed_running_launch(store)

    restarted = _restarted_service(_restarted_store(tmp_path))
    monkeypatch.setattr(
        "method_hub.application.service.LocalHermesExecutor",
        lambda settings: _GoneExecutor(),
    )

    asyncio.run(restarted._reconcile_supervised_launches())

    closed = restarted.run_seal_store.get_launch_record(LAUNCH)
    assert closed is not None
    assert closed["status"] == "failed"
    assert closed["cancel_requested_at"] is None


# --------------------------------------------------------------------------- #
# Completion-watcher close path (_watch_reconciled_run)                       #
# --------------------------------------------------------------------------- #


def test_watcher_closes_cancelled_when_intent_persisted(
    tmp_path: Path, fast_sleep: None
) -> None:
    database = _fresh_database(tmp_path)
    store = RunSealStore(database)
    _seed_running_launch(store)
    store.mark_launch_cancel_requested(LAUNCH, isoformat_utc(utc_now()))

    restarted_store = _restarted_store(tmp_path)
    service = _restarted_service(restarted_store)
    post_exit_calls: list[str] = []
    service._run_post_exit_validation = post_exit_calls.append  # type: ignore[method-assign]

    asyncio.run(
        service._watch_reconciled_run(
            _GoneExecutor(),  # type: ignore[arg-type]
            restarted_store,
            LAUNCH,
            INVOCATION,
            EXTERNAL_ID,
        )
    )

    closed = restarted_store.get_launch_record(LAUNCH)
    assert closed is not None
    assert closed["status"] == "cancelled"
    # Post-exit validation runs only for a succeeded close.
    assert post_exit_calls == []


def test_watcher_closes_failed_without_intent(
    tmp_path: Path, fast_sleep: None
) -> None:
    database = _fresh_database(tmp_path)
    store = RunSealStore(database)
    _seed_running_launch(store)

    restarted_store = _restarted_store(tmp_path)
    service = _restarted_service(restarted_store)
    post_exit_calls: list[str] = []
    service._run_post_exit_validation = post_exit_calls.append  # type: ignore[method-assign]

    asyncio.run(
        service._watch_reconciled_run(
            _GoneExecutor(),  # type: ignore[arg-type]
            restarted_store,
            LAUNCH,
            INVOCATION,
            EXTERNAL_ID,
        )
    )

    closed = restarted_store.get_launch_record(LAUNCH)
    assert closed is not None
    assert closed["status"] == "failed"
    assert post_exit_calls == []


# --------------------------------------------------------------------------- #
# Cancel command: intent persisted BEFORE the signal                          #
# --------------------------------------------------------------------------- #


def test_cancel_command_persists_intent_before_signalling(
    tmp_path: Path,
) -> None:
    database = _fresh_database(tmp_path)
    store = RunSealStore(database)
    _seed_running_launch(store)

    service = _restarted_service(store)

    observed: dict[str, Any] = {}

    class _StubCancelExecutor:
        """Stands in for the identity-safe cancel executor.

        Asserts the persisted intent is visible at SIGNAL time (i.e. the
        column was written before ``cancel`` ran), then plays the launch
        worker: the signalled process dies and the record closes as
        ``cancelled``.
        """

        async def cancel(self, external_id: str) -> None:
            row = store.get_launch_record(LAUNCH)
            assert row is not None
            observed["cancel_requested_at_at_signal_time"] = row[
                "cancel_requested_at"
            ]
            store.close_launch_record(
                LAUNCH,
                status="cancelled",
                external_execution_id=external_id,
                exit_code=-15,
                closed_at=isoformat_utc(utc_now()),
            )

    service._supervised_cancel_executor = lambda: _StubCancelExecutor()  # type: ignore[method-assign]

    detail = asyncio.run(service.cancel_supervised_run(PROJECT, INVOCATION))

    assert detail.launches[-1].status == "cancelled"
    # The intent was durable BEFORE the signal path ran.
    assert observed["cancel_requested_at_at_signal_time"] is not None
    closed = store.get_launch_record(LAUNCH)
    assert closed is not None
    assert closed["cancel_requested_at"] is not None
    # The in-memory event mirrors the persisted intent.
    assert service._cancel_requests[INVOCATION].is_set()
