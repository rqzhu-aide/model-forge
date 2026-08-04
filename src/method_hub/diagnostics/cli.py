"""Diagnostic CLI: headless operation of the diagnostic lane (H0.8).

Commands:
    preflight    — verify Hermes, bwrap, profiles, and configuration.
    start        — launch a diagnostic invocation.
    status       — show one or all diagnostic invocations.
    logs         — show diagnostic output for an invocation.
    cancel       — cancel a running diagnostic.
    reconcile    — restart reconciliation for non-terminal invocations.
    memory       — show memory state for a profile.
    evidence     — list all evidence artifacts (snapshots, quarantine, outputs).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from ..application.settings import ApplicationSettings
from ..configuration.profiles import resolve_hermes_root
from ..diagnostics.contracts import DiagnosticState, TERMINAL_DIAGNOSTIC_STATES
from ..diagnostics.runtime_profiles import RuntimeProfileManager
from ..diagnostics.network_secrets import PROVIDER_EGRESS, provider_network_policy
from ..diagnostics.service import DiagnosticRequest, DiagnosticService
from ..diagnostics.store import DiagnosticStore
from ..profiles.project_profiles import (
    MemoryPolicy,
    ProjectProfileManager,
    RoleProfileSpec,
)
from ..storage.database import Database  # noqa: F401 (re-exported by some callers)


def _add_diagnostic_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``diag`` subcommand tree."""

    diag = subparsers.add_parser(
        "diag", help="Diagnostic lane operations (H0.8)."
    )
    diag_sub = diag.add_subparsers(dest="diag_command", required=True)

    # preflight
    preflight = diag_sub.add_parser(
        "preflight", help="Verify Hermes, bwrap, and profiles."
    )
    preflight.add_argument(
        "--hermes-root", type=Path, default=None, help="Hermes home directory."
    )

    # start
    start = diag_sub.add_parser("start", help="Launch a diagnostic invocation.")
    start.add_argument("--project-id", required=True)
    start.add_argument("--role", required=True)
    start.add_argument("--profile-name", required=True)
    start.add_argument(
        "--workspace", type=Path, required=True, help="Workspace directory."
    )
    start.add_argument(
        "--task-brief", type=Path, required=True, help="Task brief file."
    )
    start.add_argument("--memory-policy", default="persistent",
                       choices=["persistent", "read_only", "ephemeral"])
    start.add_argument("--model", default="")
    start.add_argument("--provider", default="")
    start.add_argument("--idempotency-key", default="")
    start.add_argument("--timeout", type=int, default=3600)

    # status
    status = diag_sub.add_parser("status", help="Show invocation status.")
    status.add_argument("invocation_id", nargs="?", default=None)
    status.add_argument("--project-id", default=None)
    status.add_argument("--status", default=None)
    status.add_argument("--limit", type=int, default=20)

    # logs
    logs = diag_sub.add_parser("logs", help="Show diagnostic output.")
    logs.add_argument("invocation_id")

    # cancel
    cancel = diag_sub.add_parser("cancel", help="Cancel a running diagnostic.")
    cancel.add_argument("invocation_id")

    # reconcile
    diag_sub.add_parser(
        "reconcile", help="Reconcile non-terminal invocations after restart."
    )

    # memory
    memory = diag_sub.add_parser("memory", help="Show memory state for a profile.")
    memory.add_argument("--profile-name", required=True)

    # evidence
    evidence = diag_sub.add_parser(
        "evidence", help="List evidence artifacts (snapshots, quarantine)."
    )
    evidence.add_argument(
        "--type", choices=["snapshots", "quarantine", "all"], default="all"
    )


def _run_diag_command(args: argparse.Namespace, settings: ApplicationSettings) -> int:
    """Dispatch a ``diag`` subcommand."""

    hermes_root = getattr(args, "hermes_root", None) or settings.hermes_root or resolve_hermes_root()

    if args.diag_command == "preflight":
        return _diag_preflight(hermes_root)
    elif args.diag_command == "start":
        return _diag_start(args, settings)
    elif args.diag_command == "status":
        from ..diagnostics.composition import open_diagnostic_store
        store = open_diagnostic_store(settings)
        return _diag_status(args, store)
    elif args.diag_command == "logs":
        from ..diagnostics.composition import open_diagnostic_store
        store = open_diagnostic_store(settings)
        return _diag_logs(args, store)
    elif args.diag_command == "cancel":
        from ..diagnostics.composition import open_diagnostic_store
        store = open_diagnostic_store(settings)
        return _diag_cancel(args, store)
    elif args.diag_command == "reconcile":
        from ..diagnostics.composition import open_diagnostic_store
        store = open_diagnostic_store(settings)
        return _diag_reconcile(store)
    elif args.diag_command == "memory":
        return _diag_memory(args, hermes_root)
    elif args.diag_command == "evidence":
        return _diag_evidence(args, hermes_root)
    else:
        print(f"Unknown diag command: {args.diag_command}", file=sys.stderr)
        return 2


# --------------------------------------------------------------------------- #
# Commands                                                                     #
# --------------------------------------------------------------------------- #


def _diag_preflight(hermes_root: Path) -> int:
    """Verify Hermes binary, Podman, bwrap, and profile directory exist."""
    problems: list[str] = []

    hermes_bin = shutil.which("hermes")
    if hermes_bin:
        print(f"  ✓ hermes found: {hermes_bin}")
    else:
        problems.append("hermes binary not found in PATH")

    podman_bin = shutil.which("podman")
    if podman_bin:
        print(f"  ✓ podman found: {podman_bin}")
    else:
        problems.append("podman binary not found in PATH (required for OCI execution)")

    bwrap_bin = shutil.which("bwrap")
    if bwrap_bin:
        print(f"  ✓ bwrap found: {bwrap_bin} (interim boundary only)")
    else:
        print("  - bwrap not found (optional — OCI is the production boundary)")

    if hermes_root.is_dir():
        print(f"  ✓ Hermes home: {hermes_root}")
        profiles_dir = hermes_root / "profiles"
        if profiles_dir.is_dir():
            profile_count = sum(
                1 for p in profiles_dir.iterdir() if p.is_dir()
            )
            print(f"  ✓ Profiles directory: {profile_count} profiles")
        else:
            problems.append(f"Profiles directory missing: {profiles_dir}")
    else:
        problems.append(f"Hermes home directory missing: {hermes_root}")

    print(f"\nProvider egress endpoints:")
    for name, endpoint in PROVIDER_EGRESS.items():
        print(f"  {name}: {endpoint.host}:{endpoint.port}")

    if problems:
        print(f"\n✗ {len(problems)} problem(s) found:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print("\n✓ All preflight checks passed.")
    return 0


def _diag_start(
    args: argparse.Namespace, settings: ApplicationSettings
) -> int:
    """Launch a diagnostic invocation."""
    from ..diagnostics.composition import build_diagnostic_service, DiagnosticNotEnabled

    try:
        service = build_diagnostic_service(settings)
    except DiagnosticNotEnabled as e:
        print(str(e), file=sys.stderr)
        return 1

    request = DiagnosticRequest(
        project_id=args.project_id,
        role=args.role,
        profile_name=args.profile_name,
        workspace=args.workspace,
        task_brief=args.task_brief,
        memory_policy=MemoryPolicy(args.memory_policy),
        model=args.model,
        provider=args.provider,
        idempotency_key=args.idempotency_key,
        timeout_seconds=args.timeout,
    )

    result = asyncio.run(service.run_diagnostic(request))
    print(f"Invocation: {result.invocation_id}")
    print(f"Status:     {result.status}")
    print(f"Exit code:  {result.exit_code}")
    if result.summary:
        print(f"Summary:    {result.summary}")
    if result.external_execution_id:
        print(f"Exec ID:    {result.external_execution_id}")

    if result.status == DiagnosticState.SUCCEEDED.value:
        return 0
    return 1


def _diag_status(args: argparse.Namespace, store: DiagnosticStore) -> int:
    """Show invocation status."""
    if args.invocation_id:
        inv = store.get_invocation(args.invocation_id)
        if inv is None:
            print(f"Invocation {args.invocation_id} not found.", file=sys.stderr)
            return 1
        _print_invocation(inv)
        return 0

    invocations = store.list_invocations(
        project_id=args.project_id,
        status=args.status,
        limit=args.limit,
    )
    if not invocations:
        print("No diagnostic invocations found.")
        return 0

    print(f"{'ID':<30} {'Status':<20} {'Profile':<25} {'Created'}")
    print("-" * 95)
    for inv in invocations:
        print(
            f"{inv['invocation_id']:<30} {inv['status']:<20} "
            f"{inv.get('profile_name', ''):<25} {inv.get('created_at', '')}"
        )
    return 0


def _diag_logs(args: argparse.Namespace, store: DiagnosticStore) -> int:
    """Show diagnostic output for an invocation."""
    inv = store.get_invocation(args.invocation_id)
    if inv is None:
        print(f"Invocation {args.invocation_id} not found.", file=sys.stderr)
        return 1
    _print_invocation(inv, verbose=True)
    return 0


def _diag_cancel(args: argparse.Namespace, store: DiagnosticStore) -> int:
    """Cancel a running diagnostic invocation."""

    # For cancellation we need the service, which needs the executor.
    # But we can do it at the store level for simplicity.
    inv = store.get_invocation(args.invocation_id)
    if inv is None:
        print(f"Invocation {args.invocation_id} not found.", file=sys.stderr)
        return 1

    status = inv["status"]
    if status in TERMINAL_DIAGNOSTIC_STATES:
        print(
            f"Invocation {args.invocation_id} is already in terminal "
            f"state: {status}",
            file=sys.stderr,
        )
        return 1

    # Transition through cancel states.
    try:
        store.update_status(
            args.invocation_id,
            status=DiagnosticState.CANCEL_REQUESTED.value,
        )
        store.update_status(
            args.invocation_id,
            status=DiagnosticState.CANCELLED.value,
        )
        print(f"Cancelled {args.invocation_id}")
        return 0
    except Exception as e:
        print(f"Failed to cancel: {e}", file=sys.stderr)
        return 1


def _diag_reconcile(store: DiagnosticStore) -> int:
    """Reconcile non-terminal invocations."""

    nonterminal = store.list_nonterminal_invocations()
    if not nonterminal:
        print("No non-terminal invocations to reconcile.")
        return 0

    print(f"Found {len(nonterminal)} non-terminal invocation(s):")
    for inv in nonterminal:
        print(
            f"  {inv['invocation_id']}: {inv['status']} "
            f"(created {inv.get('created_at', '')})"
        )

    # Also clean up stale locks.
    freed = store.reconcile_locks()
    if freed:
        print(f"\nFreed {len(freed)} expired profile lock(s): {freed}")

    return 0


def _diag_memory(args: argparse.Namespace, hermes_root: Path) -> int:
    """Show memory state for a profile."""
    pm = ProjectProfileManager(hermes_root=hermes_root)
    profile_dir = pm.profiles_root / args.profile_name
    if not profile_dir.is_dir():
        print(f"Profile {args.profile_name} not found.", file=sys.stderr)
        return 1

    from ..executors.oneshot import OneShotExecutor

    state = OneShotExecutor.record_memory_state(profile_dir)
    print(f"Profile: {args.profile_name}")
    print(f"  Directory: {profile_dir}")
    for key, value in state.items():
        print(f"  {key}: {value}")

    # Show policy.
    policy_sidecar = profile_dir / ".method-hub-policy.json"
    if policy_sidecar.exists():
        policy = json.loads(policy_sidecar.read_text())
        print(f"  Memory policy: {policy.get('memory_policy', 'unknown')}")

    return 0


def _diag_evidence(args: argparse.Namespace, hermes_root: Path) -> int:
    """List evidence artifacts."""
    rpm = RuntimeProfileManager(hermes_root)

    if args.type in ("snapshots", "all"):
        snapshots_dir = rpm.snapshots_root
        if snapshots_dir.is_dir():
            entries = [e for e in snapshots_dir.iterdir() if e.is_dir()]
            print(f"Active snapshots ({len(entries)}):")
            for entry in entries:
                print(f"  {entry.name}")
        else:
            print("No snapshots directory.")

    if args.type in ("quarantine", "all"):
        quarantine_dir = rpm.quarantine_root
        if quarantine_dir.is_dir():
            entries = [e for e in quarantine_dir.iterdir() if e.is_dir()]
            print(f"\nQuarantined snapshots ({len(entries)}):")
            for entry in entries:
                meta_file = entry / "_quarantine_metadata.json"
                reason = "?"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text())
                        reason = meta.get("reason", "?")
                    except json.JSONDecodeError:
                        pass
                print(f"  {entry.name}: {reason}")
        else:
            print("\nNo quarantine directory.")

    return 0


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _print_invocation(inv: dict[str, Any], *, verbose: bool = False) -> None:
    """Print a single invocation record."""
    print(f"Invocation ID:    {inv['invocation_id']}")
    print(f"Status:           {inv['status']}")
    print(f"Project:          {inv.get('project_id', '')}")
    print(f"Role:             {inv.get('role', '')}")
    print(f"Profile:          {inv.get('profile_name', '')}")
    print(f"Exit code:        {inv.get('exit_code', '')}")
    print(f"Created:          {inv.get('created_at', '')}")
    print(f"Updated:          {inv.get('updated_at', '')}")
    if inv.get("external_execution_id"):
        print(f"External ID:      {inv['external_execution_id']}")
    if inv.get("summary"):
        print(f"Summary:          {inv['summary']}")
    if verbose and inv.get("diagnostic_text"):
        print(f"\nDiagnostic output:")
        print("-" * 60)
        print(inv["diagnostic_text"])
        print("-" * 60)
    if verbose and inv.get("memory_state_before"):
        print(f"\nMemory before: {inv['memory_state_before']}")
    if verbose and inv.get("memory_state_after"):
        print(f"Memory after:  {inv['memory_state_after']}")


__all__ = [
    "_add_diagnostic_parser",
    "_run_diag_command",
]
