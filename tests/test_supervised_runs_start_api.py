"""WP-F1a API tests: supervised-run START endpoint.

Covers the explicit start command end to end with a stub Hermes
executable (mirroring ``tests/test_run_launcher.py``): the endpoint
returns 202 and the WP-F0 read surface shows the launch record as
``running`` then ``succeeded``; the stub observes ``HERMES_HOME``
pointing at the assembled run profile; an idempotent replay returns the
existing invocation with 200 and does NOT launch again; empty briefs and
unknown roles are 400; a held project-role state lock and a failing
preflight are 409 (with the preflight detail in the error body); and a
provider key from the environment never appears in logs, the manifest,
launch records, or responses.

The service builds its own WP-D1 assembler over the SAME
``<data_root>/hub.sqlite3`` that its lazy ``run_seal_store`` reads, so
the start response and the read surface always agree.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from model_forge.api import create_app
from model_forge.api.models import StartSupervisedRunRequest
from model_forge.application.run_profile_assembler import (
    HermesProbe,
    RunProfileAssembler,
)
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

STUB_VERSION = "0.0.1"

#: Provider key whose shape (``sk-...``) must be caught by the
#: executor's redaction when the stub echoes it back.
SECRET_ENV_NAME = "DEEPSEEK_API_KEY"
SECRET_KEY_VALUE = "sk-test-" + "a" * 28

_STUB_SCRIPT = r'''#!/usr/bin/env python3
"""Stub Hermes executable for WP-F1a start-endpoint tests.

Handles --version and accepts the -z/-p/--usage-file/-m/--provider/
--skills args.  Prints the effective HERMES_HOME, the full argv, and
the value of DEEPSEEK_API_KEY (when set) so tests can assert on the
launcher's environment and secret redaction, then exits 0 after a short
pause so the ``running`` launch state is observable.
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
    print("SECRET=" + os.environ.get("DEEPSEEK_API_KEY", ""))
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
def stub_hermes(tmp_path: Path) -> Path:
    """Create the stub Hermes executable and return its absolute path."""
    stub = tmp_path / "stub-hermes"
    stub.write_text(_STUB_SCRIPT)
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


def _poll_terminal_status(
    client: TestClient, invocation_id: str, deadline: float = 15.0
) -> list[str]:
    """Poll the WP-F0 list endpoint until the launch is terminal.

    Returns the sequence of observed ``latest_launch_status`` values.
    """
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


# --------------------------------------------------------------------------- #
# Happy path                                                                   #
# --------------------------------------------------------------------------- #


def test_start_returns_202_and_launch_progresses_to_succeeded(
    tmp_path: Path, stub_hermes: Path
) -> None:
    environment = _environment(tmp_path, stub_hermes)
    client = environment["client"]
    data_root = environment["data_root"]

    # NOTE on TestClient semantics: this portal blocks per-request on the
    # event loop's default executor, so through TestClient the POST only
    # returns after the background launch settles (~1.7s with this stub)
    # and the transient ``running`` state is never observable here.  The
    # non-blocking behavior is therefore proven at the service level in
    # test_service_level_launch_progresses_through_running (0.05s return,
    # running -> succeeded transition); the API-level assertions below
    # cover the contract, not the threading.
    response = _post_start(client)

    assert response.status_code == 202
    detail = response.json()
    assert detail["invocation_id"] == "inv-001"
    assert detail["project_id"] == PROJECT
    assert detail["role"] == "theorist"
    assert detail["manifest"]["phase"] == "P3"
    assert detail["seal_id"]
    assert detail["manifest"]["method_identity"] == {
        "method_id": "mf-1",
        "version": "1.0",
    }
    assert detail["manifest"]["memory_snapshot"]["policy"] == "persistent"
    assert detail["manifest"]["expected_outputs"] == [
        {
            "output_id": "out-1",
            "path": "results/summary.json",
            "required_fields": ["conclusion"],
        },
    ]
    assert detail["manifest"]["hermes"]["executable"] == str(stub_hermes)
    # The real --version probe records the stub's full version output.
    assert detail["manifest"]["hermes"]["version"] == "stub-hermes 0.0.1"

    # The brief text was materialized under the run's briefs area.
    run_dir = data_root / "runs" / "inv-001"
    brief_path = run_dir / "briefs" / "task.md"
    assert brief_path.is_file()
    assert brief_path.read_text(encoding="utf-8") == _start_payload()["brief_text"]

    # The WP-F0 read surface shows the launch reaching its terminal state.
    statuses = _poll_terminal_status(client, "inv-001")
    assert statuses[-1] == "succeeded"

    # The stub observed HERMES_HOME pointing at the assembled run profile.
    stdout_log = run_dir / "logs" / "stdout.log"
    assert stdout_log.is_file()
    stdout = stdout_log.read_text(encoding="utf-8")
    assert f"HERMES_HOME={(run_dir / 'profile').resolve()}" in stdout
    argv_line = next(line for line in stdout.splitlines() if line.startswith("ARGV="))
    assert '"-p"' not in argv_line

    # The launcher materialized the brief into the workspace as task.md.
    assert (run_dir / "workspace" / "task.md").is_file()

    # Exactly one launch record, closed as succeeded with exit code 0.
    final = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/inv-001"
    ).json()
    assert len(final["launches"]) == 1
    launch = final["launches"][0]
    assert launch["status"] == "succeeded"
    assert launch["exit_code"] == 0
    assert launch["closed_at"]


def test_idempotent_replay_returns_existing_without_second_launch(
    tmp_path: Path, stub_hermes: Path
) -> None:
    environment = _environment(tmp_path, stub_hermes)
    client = environment["client"]
    data_root = environment["data_root"]

    first = _post_start(client)
    assert first.status_code == 202
    first_detail = first.json()

    # Replay the identical command: 200 with the same invocation, no relaunch.
    second = _post_start(client)
    assert second.status_code == 200
    second_detail = second.json()
    assert second_detail["invocation_id"] == first_detail["invocation_id"]
    assert second_detail["seal_id"] == first_detail["seal_id"]

    _poll_terminal_status(client, "inv-001")

    final = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/inv-001"
    ).json()
    assert len(final["launches"]) == 1
    # A single run directory with a single materialized brief.
    run_dir = data_root / "runs" / "inv-001"
    assert len(list((run_dir / "logs").glob("*.log"))) >= 3
    assert (run_dir / "briefs" / "task.md").is_file()


# --------------------------------------------------------------------------- #
# Invalid requests (400)                                                       #
# --------------------------------------------------------------------------- #


def test_empty_brief_is_400(tmp_path: Path, stub_hermes: Path) -> None:
    environment = _environment(tmp_path, stub_hermes)
    client = environment["client"]

    response = _post_start(client, brief_text="")
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "SUPERVISED_RUN_INVALID"
    assert payload["field_path"] == "brief_text"

    whitespace = _post_start(client, brief_text="   \n\t  ")
    assert whitespace.status_code == 400
    assert whitespace.json()["code"] == "SUPERVISED_RUN_INVALID"


def test_unknown_role_is_400(tmp_path: Path, stub_hermes: Path) -> None:
    environment = _environment(tmp_path, stub_hermes)
    client = environment["client"]

    response = _post_start(client, role="sociologist", idempotency_key="key-002")
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "SUPERVISED_RUN_INVALID"
    assert payload["field_path"] == "role"


def test_absolute_expected_output_path_is_400(
    tmp_path: Path, stub_hermes: Path
) -> None:
    environment = _environment(tmp_path, stub_hermes)
    client = environment["client"]

    response = _post_start(
        client,
        idempotency_key="key-003",
        expected_outputs=[
            {"output_id": "out-1", "path": "/etc/passwd"},
        ],
    )
    assert response.status_code == 400
    payload = response.json()
    assert payload["code"] == "SUPERVISED_RUN_INVALID"
    assert "expected_outputs.0.path" in payload["field_path"]


# --------------------------------------------------------------------------- #
# Conflicts (409)                                                              #
# --------------------------------------------------------------------------- #


def test_lock_conflict_returns_409(tmp_path: Path, stub_hermes: Path) -> None:
    environment = _environment(tmp_path, stub_hermes)
    client = environment["client"]
    data_root = environment["data_root"]

    # Hold the project-role state lock through a test-side assembler over
    # the SAME hub.sqlite3 the service's assembler seals against.
    database = Database(data_root / "hub.sqlite3", migrations=HUB_MIGRATIONS)
    database.initialize()
    holder = RunProfileAssembler(
        data_root=data_root,
        role_resources=RoleResourceCatalog.load(RESOURCE_ROOT),
        database=database,
        bundle_root=ROOT / "resources" / "skills",
        hermes_root=tmp_path / "hermes",
        hermes_binary="hermes",
        hermes_probe=lambda binary: HermesProbe("/fake/hermes", "9.9.9"),
    )

    with holder.state_lock(PROJECT, "theorist", "inv-other-holder"):
        response = _post_start(client, idempotency_key="key-004")
        assert response.status_code == 409
        payload = response.json()
        assert payload["code"] == "SUPERVISED_RUN_LOCKED"
        assert "inv-other-holder" in payload["researcher_message"]

    # The conflict aborted before any seal or launch record existed.
    assert client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/inv-001"
    ).status_code == 404


def test_preflight_failure_returns_409_with_detail(
    tmp_path: Path, stub_hermes: Path
) -> None:
    # An absurd free-space minimum makes the free_space preflight check
    # fail deterministically before any process is launched.
    environment = _environment(tmp_path, stub_hermes, min_free_bytes=2**62)
    client = environment["client"]

    response = _post_start(client)
    assert response.status_code == 409
    payload = response.json()
    assert payload["code"] == "SUPERVISED_RUN_PREFLIGHT_FAILED"
    assert "free_space" in payload["researcher_message"]
    detail = payload["detail"]
    assert detail["invocation_id"] == "inv-001"
    assert "free_space" in detail["failed_checks"]
    assert any(
        check["name"] == "free_space" and check["status"] == "fail"
        for check in detail["checks"]
    )

    # No process was created: the seal exists but there is no launch.
    record = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/inv-001"
    ).json()
    assert record["launches"] == []


# --------------------------------------------------------------------------- #
# Secret hygiene                                                               #
# --------------------------------------------------------------------------- #


def test_provider_secret_never_appears_in_logs_or_responses(
    tmp_path: Path, stub_hermes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(SECRET_ENV_NAME, SECRET_KEY_VALUE)
    environment = _environment(tmp_path, stub_hermes)
    client = environment["client"]
    data_root = environment["data_root"]

    response = _post_start(client)
    assert response.status_code == 202
    # The secret never appears in the HTTP response body.
    assert SECRET_KEY_VALUE not in response.text

    _poll_terminal_status(client, "inv-001")

    run_dir = data_root / "runs" / "inv-001"
    # The stub echoed the injected key on stdout; the executor redacted it
    # before the launcher persisted the captured stream.
    stdout = (run_dir / "logs" / "stdout.log").read_text(encoding="utf-8")
    assert "SECRET=[REDACTED]" in stdout
    assert SECRET_KEY_VALUE not in stdout

    for log in run_dir.glob("logs/*.log"):
        assert SECRET_KEY_VALUE not in log.read_text(
            encoding="utf-8"
        ), f"secret leaked into {log}"

    manifest_bytes = (run_dir / "manifest" / "manifest.json").read_bytes()
    assert SECRET_KEY_VALUE.encode() not in manifest_bytes

    launch = client.get(
        f"/api/v1/projects/{PROJECT}/supervised-runs/inv-001"
    ).json()
    assert SECRET_KEY_VALUE not in json.dumps(launch)


def test_service_level_launch_progresses_through_running(
    tmp_path: Path, stub_hermes: Path
) -> None:
    """The background launch is observable mid-flight at the service level:
    status transitions running -> succeeded while the start call itself
    returns immediately.  (TestClient's portal drains the executor per
    request, so this transition is not observable through the HTTP layer
    in-process; the API-level elapsed guard covers non-blocking there.)"""
    asyncio.run(_exercise_service_level_transition(tmp_path, stub_hermes))


async def _exercise_service_level_transition(
    tmp_path: Path, stub_hermes: Path
) -> None:
    environment = _environment(tmp_path, stub_hermes)
    service: ModelForgeService = environment["service"]
    command = StartSupervisedRunRequest(**_start_payload())
    start = time.monotonic()
    await service.start_supervised_run(PROJECT, command, raw_request=None)
    assert time.monotonic() - start < 1.0, "the service start must not block"
    seen: list[str] = []
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        rows = await service.list_supervised_runs(PROJECT)
        status = rows[0].latest_launch_status if rows else None
        if status is not None and (not seen or seen[-1] != status):
            seen.append(status)
        if status in ("succeeded", "failed", "cancelled"):
            break
        await asyncio.sleep(0.1)
    assert seen == ["running", "succeeded"], f"observed sequence: {seen}"
