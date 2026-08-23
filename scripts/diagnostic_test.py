#!/usr/bin/env python3
"""End-to-end diagnostic: run one real Hermes task through the hardened executor.

This script creates a real kanban task on the model-forge board, assigns it to
the theorist profile, and polls until terminal.  It exercises:

  - _create (with --max-retries 1)
  - _show (status polling with the real enum)
  - _capture_agent_log (Domain 2 log reading)
  - bounded output capture (Domain 1)
  - environment allowlist
  - profile existence verification

No formal state is touched.  The workspace is under /tmp.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

# Add model-forge to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from model_forge.executors.hermes import (
    HermesKanbanExecutor,
    HermesSettings,
    profile_exists,
    resolve_hermes_root,
)
from model_forge.executors.protocol import RoleExecutionStatus, RoleInvocation


class DiagnosticObserver:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def launch_intent(self, invocation: RoleInvocation) -> None:
        self.events.append(f"[intent] {invocation.invocation_id}")
        print(f"  [observer] launch_intent: {invocation.invocation_id}")

    async def launch_acknowledged(
        self, invocation: RoleInvocation, external_execution_id: str
    ) -> None:
        self.events.append(f"[ack] {external_execution_id}")
        print(f"  [observer] launch_acknowledged: {external_execution_id}")

    async def heartbeat(self, invocation: RoleInvocation, activity: str) -> None:
        self.events.append(f"[heartbeat] {activity}")
        print(f"  [observer] heartbeat: {activity}")


async def main() -> int:
    workspace = Path("/tmp/model-forge-diagnostic/workspace")
    task_brief = Path("/tmp/model-forge-diagnostic/task_brief.md")

    print("=== Model Forge Diagnostic: Real Hermes Execution ===")
    print()

    # 1. Verify profiles exist
    print("[1/5] Verifying Hermes profiles...")
    root = resolve_hermes_root()
    print(f"  Hermes root: {root}")
    profile = "theorist"
    if not profile_exists(profile, hermes_root=root):
        print(f"  FAIL: profile '{profile}' not found")
        return 1
    print(f"  OK: profile '{profile}' found")
    print()

    # 2. Configure executor
    print("[2/5] Configuring executor...")
    settings = HermesSettings(
        executable="hermes",
        board_slug="model-forge",
        hermes_home=root,
        poll_interval_seconds=5.0,
        command_timeout_seconds=30,
        output_limit_bytes=1_048_576,
        cancel_confirm_timeout_seconds=30.0,
    )
    executor = HermesKanbanExecutor(settings)
    print(f"  Board: {settings.board_slug}")
    print(f"  Poll interval: {settings.poll_interval_seconds}s")
    print()

    # 3. Build invocation
    print("[3/5] Building invocation...")
    invocation = RoleInvocation(
        execution_id="execution.diagnostic-001",
        invocation_id="invocation.diagnostic-001",
        run_id="run.diagnostic-001",
        project_id="project.diagnostic",
        phase="diagnostic",
        mode="connectivity",
        stage_id="diagnostic.word-count",
        role="theorist",
        profile=profile,
        workspace=workspace,
        task_brief=task_brief,
        expected_output_paths=(
            workspace / "output.json",
            workspace / "note.txt",
        ),
        timeout_seconds=180,
    )
    print(f"  Workspace: {workspace}")
    print(f"  Task brief: {task_brief}")
    print(f"  Timeout: {invocation.timeout_seconds}s")
    print()

    # 4. Execute
    print("[4/5] Executing real Hermes task...")
    print("  (This will take 30-120 seconds for the agent to complete)")
    print()
    observer = DiagnosticObserver()
    start = time.monotonic()
    result = await executor.execute(invocation, observer)
    elapsed = time.monotonic() - start
    print()
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Status:  {result.status.value}")
    print(f"  Task ID: {result.external_execution_id}")
    print(f"  Exit:    {result.exit_code}")
    print(f"  Summary: {result.summary}")
    if result.diagnostic_text:
        # Show first 500 chars of diagnostic
        diag = result.diagnostic_text[:500]
        if len(result.diagnostic_text) > 500:
            diag += "..."
        print(f"  Diagnostic:\n    {diag}")
    print()

    # 5. Verify output
    print("[5/5] Checking workspace output...")
    output_json = workspace / "output.json"
    note_txt = workspace / "note.txt"

    if output_json.exists():
        data = json.loads(output_json.read_text())
        print(f"  output.json: {data}")
    else:
        print(f"  output.json: NOT FOUND")

    if note_txt.exists():
        print(f"  note.txt: {note_txt.read_text().strip()}")
    else:
        print(f"  note.txt: NOT FOUND")

    print()
    print(f"=== Result: {result.status.value.upper()} ===")
    return 0 if result.status == RoleExecutionStatus.SUCCEEDED else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
