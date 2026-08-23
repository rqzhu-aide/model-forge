"""WP-F1b API tests: supervised-run CANCEL endpoint.

Covers the explicit cancel command end to end with a stub Hermes
executable that sleeps 30 seconds (so a cancel can always be issued
mid-flight) and dies immediately on SIGTERM: at the service level a
running launch whose durable external id is present (``local:pid:...``
written by the launch-acknowledged observer) cancels with the record
closing as ``cancelled`` (never ``failed``) and the stub process gone;
re-cancelling a cancelled invocation is 409, cancelling an unknown
invocation is 404, and cancelling an already-succeeded launch is 409;
the HTTP endpoint returns the updated ``SupervisedRunDetail``; and a
running launch whose external id is somehow absent (the narrow
pre-acknowledge window, constructed deterministically at the store
level) is the 409 not-yet-cancellable guard.

The service builds its own WP-D1 assembler over the SAME
``<data_root>/hub.sqlite3`` that its lazy ``run_seal_store`` reads, so
the cancel response and the read surface always agree.

Threading notes (mirroring the WP-F1a start tests): the background
launch runs via ``asyncio.to_thread`` on the event loop's default
executor, so every test drives the launch through the SERVICE inside
one ``asyncio.run`` (a second ``asyncio.run`` would block until the
30s stub finishes, and TestClient's portal blocks per-request on the
same executor).  The CANCEL itself is fast — it only signals the
process and polls the record until the launch worker closes it — so it
is exercised through TestClient where the HTTP contract is under test.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from model_forge.api import create_app
from model_forge.api.errors import CommandRejected
from model_forge.api.models import StartSupervisedRunRequest, SupervisedRunDetail
from model_forge.application.service import ModelForgeService
from model_forge.application.settings import ApplicationSettings
from model_forge.configuration.resources import RoleResourceCatalog
from model_forge.executors.local_hermes import LocalHermesExecutorSettings
from model_forge.specification import SpecificationPackage
from model_forge.storage.artifacts import ArtifactStore
from model_forge.storage.database import Database
from model_forge.storage.migrations import HUB_MIGRATIONS
from model_forge.storage.paths import WorkspacePaths
from model_forge.storage.repository import HubRepository

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = ROOT / "resources" / "team"

PROJECT = "proj-001"

#: Slow stub for cancel tests: sleeps 30s so the ``running`` launch
#: state with its durable external id is always observable, and dies
#: immediately on SIGTERM (default signal disposition).  The executor
#: reads the signal death as exit code -15 / FAILED; the explicit-cancel
#: path classifies that death as ``cancelled`` at close time.  No
#: SIGTERM handler is installed: a clean exit-0 would read as SUCCEEDED
#: and would NOT be reclassified.
SLOW_STUB_SCRIPT = r'''#!/usr/bin/env python3
"""Stub Hermes executable for WP-F1b cancel tests.

Handles --version and accepts the -z/-p/--usage-file/-m/--provider/
--skills args, then sleeps 30 seconds so the running launch state is
observable long enough to cancel.  Dies promptly on SIGTERM via the
default signal disposition.
"""
import argparse
import json
import os
import sys
import time


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
    time.sleep(30)

    if args.usage_file:
        with open(args.usage_file, "w") as f:
            f.write('{"tokens": 1}')
    sys.exit(0)


if __name__ == "__main__":
    main()
'''

#: Fast stub (mirrors the WP-F1a start tests): succeeds after ~1.5s so a
#: launch can be let to reach ``succeeded`` before a cancel attempt.
FAST_STUB_SCRIPT = r'''#!/usr/bin/env python3
"""Stub Hermes executable that succeeds quickly (WP-F1b terminal test)."""
import argparse
import json
import os
import sys
import time


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
    time.sleep(1.5)

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
def stub_hermes_slow(tmp_path: Path) -> Path:
    """Create the slow (30s) stub Hermes executable."""
    stub = tmp_path / "stub-hermes-slow"
    stub.write_text(SLOW_STUB_SCRIPT)
    stub.chmod(0o755)
    return stub


@pytest.fixture
def stub_hermes_fast(tmp_path: Path) -> Path:
    """Create the fast (1.5s) stub Hermes executable."""
    stub = tmp_path / "stub-hermes-fast"
    stub.write_text(FAST_STUB_SCRIPT)
    stub.chmod(0o755)
    return stub


def _environment(
    tmp_path: Path,
    stub_hermes: Path,
    *,
    min_free_bytes: int = 1_048_576,
) -> dict[str, Any]:
    """Service + TestClient over one tmp data root (WP-F1a layout)."""
    workspace = WorkspacePaths(tmp_path / "data", create=True)
    repository = HubRepository(workspace.root / "model-forge.sqlite3")
    repository.initialize()
    service = ModelForgeService(
        settings=ApplicationSettings(
            data_root=workspace.root,
            hermes_executable=str(stub_hermes),
        ),
        specification=SpecificationPackage.load(ROOT / "architecture"),
        repository=repository,
        artifacts=ArtifactStore(workspace),
        role_resources=RoleResourceCatalog.load(RESOURCE_ROOT),
        supervised_executor_settings=LocalHermesExecutorSettings(
            hermes_binary=str(stub_hermes),
            poll_interval_seconds=0.05,
            output_limit_bytes=65536,
            terminate_grace_seconds=1,
            kill_grace_seconds=1,
        ),
        supervised_min_free_bytes=min_free_bytes,
    )
    return {
        "service": service,
        "client": TestClient(create_app(service)),
        "data_root": workspace.root,
    }


def _start_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "invocation_id": "inv-001",
        "idempotency_key": "key-001",
        "role": "theorist",
        "phase": "P3",
        "method_identity": {"method_id": "mf-1", "version": "1.0"},
        "brief_text": "# Brief\nProduce the declared output.\n",
        "expected_outputs": [
            {
                "output_id": "out-1",
                "path": "results/summary.json",
                "required_fields": ["conclusion"],
            },
        ],
        "memory_policy": "persistent",
        "model": "some-model",
        "provider": "deepseek",
        "timeout_seconds": 600,
    }
    payload.update(overrides)
    return payload


def _post_start(client: TestClient, **overrides: Any):
    return client.post(
        f"/api/v1/projects/{PROJECT}/supervised-runs",
        json=_start_payload(**overrides),
    )


def _post_cancel(client: TestClient, invocation_id: str):
    return client.post(
        f"/api/v1/projects/{PROJECT}/supervised-runs/{invocation_id}/cancel"
    )


def _poll_terminal_status(
    client: TestClient, invocation_id: str, deadline: float = 15.0
) -> list[str]:
    """Poll the WP-F0 list endpoint until the launch is terminal."""
    start = time.monotonic()
    statuses: list[str] = []
    while time.monotonic() - start < deadline:
        rows = client.get(f"/api/v1/projects/{PROJECT}/supervised-runs").json()
        row = next(
            (item for item in rows if item["invocation_id"] == invocation_id),
            None,
        )
        status = row.get("latest_launch_status") if row is not None else None
        if status is not None:
            statuses.append(status)
            if status in ("succeeded", "failed", "cancelled"):
                return statuses
        time.sleep(0.05)
    raise AssertionError(
        f"launch for {invocation_id} did not reach a terminal state; "
        f"observed statuses: {statuses}"
    )


async def _wait_running_with_external_id(
    service: ModelForgeService, invocation_id: str, deadline: float = 15.0
) -> dict[str, Any]:
    """Poll the seal store until the launch record is ``running`` AND its
    durable external id is present (written by the launch-acknowledged
    observer the moment the process exists)."""
    store = service.run_seal_store
    start = time.monotonic()
    while time.monotonic() - start < deadline:
        record = store.find_launch_record_by_invocation(invocation_id)
        if (
            record is not None
            and record["status"] == "running"
            and record["external_execution_id"]
        ):
            return record
        await asyncio.sleep(0.05)
    raise AssertionError(
        f"launch for {invocation_id} never reached running with a durable "
        "external execution id"
    )


def _parse_durable_external_id(external_id: str) -> int:
    """Assert the durable format ``local:pid:<N>:st:...:mk:...:bi:...`` and
    return the embedded PID."""
    parts = external_id.split(":")
    assert parts[0] == "local", external_id
    assert parts[1] == "pid", external_id
    assert parts[2].isdigit(), external_id
    assert parts[3] == "st", external_id
    assert parts[5] == "mk", external_id
    assert parts[7] == "bi", external_id
    return int(parts[2])


async def _wait_process_gone(pid: int, deadline: float = 5.0) -> None:
    """Assert the process behind *pid* no longer exists (ESRCH)."""
    start = time.monotonic()
    while time.monotonic() - start < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"stub process {pid} is still alive after the cancel")


# --------------------------------------------------------------------------- #
# Service level: happy cancel path                                            #
# --------------------------------------------------------------------------- #


def test_service_level_cancel_closes_record_cancelled_and_process_gone(
    tmp_path: Path, stub_hermes_slow: Path
) -> None:
    asyncio.run(_exercise_service_level_cancel(tmp_path, stub_hermes_slow))


async def _exercise_service_level_cancel(
    tmp_path: Path, stub_hermes: Path
) -> None:
    environment = _environment(tmp_path, stub_hermes)
    service: ModelForgeService = environment["service"]
    command = StartSupervisedRunRequest(**_start_payload())
    start = time.monotonic()
    await service.start_supervised_run(PROJECT, command, raw_request=None)
    assert time.monotonic() - start < 1.0, "the service start must not block"

    record = await _wait_running_with_external_id(service, "inv-001")
    external_id = str(record["external_execution_id"])
    pid = _parse_durable_external_id(external_id)

    detail = await service.cancel_supervised_run(PROJECT, "inv-001")
    assert isinstance(detail, SupervisedRunDetail)
    launch = detail.launches[-1]
    assert launch.status == "cancelled"
    assert launch.closed_at is not None
    # The stub died by SIGTERM (not a clean exit), so the executor's
    # exit code is -15; the record closes as cancelled, not failed.
    assert launch.exit_code == -15
    assert launch.external_execution_id == external_id

    # The durable launch record itself is closed as cancelled (never
    # failed) and the external id survived closure.
    closed = service.run_seal_store.find_launch_record_by_invocation("inv-001")
    assert closed["status"] == "cancelled"
    assert closed["external_execution_id"] == external_id
    assert closed["closed_at"] is not None

    # The cancel path reaped the stub process.
    await _wait_process_gone(pid)


# --------------------------------------------------------------------------- #
# Conflicts and guards                                                        #
# --------------------------------------------------------------------------- #


def test_recancel_after_cancel_returns_409(
    tmp_path: Path, stub_hermes_slow: Path
) -> None:
    asyncio.run(_exercise_recancel(tmp_path, stub_hermes_slow))


async def _exercise_recancel(tmp_path: Path, stub_hermes: Path) -> None:
    environment = _environment(tmp_path, stub_hermes)
    service: ModelForgeService = environment["service"]
    client: TestClient = environment["client"]
    command = StartSupervisedRunRequest(**_start_payload())
    await service.start_supervised_run(PROJECT, command, raw_request=None)
    await _wait_running_with_external_id(service, "inv-001")

    first = _post_cancel(client, "inv-001")
    assert first.status_code == 200
    assert first.json()["launches"][-1]["status"] == "cancelled"

    # The invocation is terminal now — there is nothing left to cancel.
    second = _post_cancel(client, "inv-001")
    assert second.status_code == 409
    payload = second.json()
    assert payload["code"] == "INVALID_TRANSITION"
    assert payload["http_status"] == 409
    assert "cancelled" in payload["researcher_message"]


def test_cancel_unknown_invocation_is_404(
    tmp_path: Path, stub_hermes_slow: Path
) -> None:
    environment = _environment(tmp_path, stub_hermes_slow)
    client = environment["client"]

    response = _post_cancel(client, "inv-unknown")
    assert response.status_code == 404
    payload = response.json()
    assert payload["code"] == "TARGET_NOT_FOUND"
    assert payload["http_status"] == 404


def test_cancel_succeeded_launch_is_409(
    tmp_path: Path, stub_hermes_fast: Path
) -> None:
    environment = _environment(tmp_path, stub_hermes_fast)
    client = environment["client"]

    response = _post_start(client)
    assert response.status_code == 202
    statuses = _poll_terminal_status(client, "inv-001")
    assert statuses[-1] == "succeeded"

    cancel = _post_cancel(client, "inv-001")
    assert cancel.status_code == 409
    payload = cancel.json()
    assert payload["code"] == "INVALID_TRANSITION"
    assert payload["http_status"] == 409
    assert "succeeded" in payload["researcher_message"]


def test_cancel_guard_when_external_id_absent_is_409(
    tmp_path: Path, stub_hermes_slow: Path
) -> None:
    asyncio.run(_exercise_cancel_guard(tmp_path, stub_hermes_slow))


async def _exercise_cancel_guard(tmp_path: Path, stub_hermes: Path) -> None:
    environment = _environment(tmp_path, stub_hermes)
    service: ModelForgeService = environment["service"]
    data_root = environment["data_root"]
    command = StartSupervisedRunRequest(**_start_payload())
    await service.start_supervised_run(PROJECT, command, raw_request=None)
    record = await _wait_running_with_external_id(service, "inv-001")
    launch_id = str(record["launch_id"])
    external_id = str(record["external_execution_id"])

    # Deterministic construction of the narrow pre-acknowledge window: the
    # launch is running but its durable external id has not been recorded.
    # The acknowledge observer fires once, so clearing the field via the
    # store database directly is stable for the whole 30s stub lifetime.
    database = Database(data_root / "hub.sqlite3", migrations=HUB_MIGRATIONS)
    database.initialize()
    with database.transaction() as conn:
        conn.execute(
            "UPDATE run_launch_records SET external_execution_id = NULL "
            "WHERE launch_id = ?",
            (launch_id,),
        )

    with pytest.raises(CommandRejected) as excinfo:
        await service.cancel_supervised_run(PROJECT, "inv-001")
    error = excinfo.value.error
    assert error.code == "TARGET_STATE_MISMATCH"
    assert error.http_status == 409
    assert "not yet cancellable" in error.researcher_message

    # Restore the durable id and cancel for real so no process is leaked.
    with database.transaction() as conn:
        conn.execute(
            "UPDATE run_launch_records SET external_execution_id = ? "
            "WHERE launch_id = ?",
            (external_id, launch_id),
        )
    detail = await service.cancel_supervised_run(PROJECT, "inv-001")
    assert detail.launches[-1].status == "cancelled"
    await _wait_process_gone(_parse_durable_external_id(external_id))


# --------------------------------------------------------------------------- #
# API level                                                                    #
# --------------------------------------------------------------------------- #


def test_api_level_cancel_returns_updated_detail(
    tmp_path: Path, stub_hermes_slow: Path
) -> None:
    asyncio.run(_exercise_api_level_cancel(tmp_path, stub_hermes_slow))


async def _exercise_api_level_cancel(tmp_path: Path, stub_hermes: Path) -> None:
    environment = _environment(tmp_path, stub_hermes)
    service: ModelForgeService = environment["service"]
    client: TestClient = environment["client"]
    command = StartSupervisedRunRequest(**_start_payload())
    await service.start_supervised_run(PROJECT, command, raw_request=None)
    record = await _wait_running_with_external_id(service, "inv-001")
    external_id = str(record["external_execution_id"])

    response = _post_cancel(client, "inv-001")
    assert response.status_code == 200
    payload = response.json()
    assert payload["invocation_id"] == "inv-001"
    assert payload["project_id"] == PROJECT
    assert payload["seal_id"]
    assert len(payload["launches"]) == 1
    launch = payload["launches"][-1]
    assert launch["status"] == "cancelled"
    assert launch["exit_code"] == -15
    assert launch["closed_at"]
    assert launch["external_execution_id"] == external_id

    # The read surface agrees with the cancel response.
    readback = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/inv-001"
    ).json()
    assert readback["launches"][-1]["status"] == "cancelled"
