"""Regression tests for the R15 fencing deletion (audit 2026-08-31).

The invocation-fencing token/lease machinery was decorative (zero
effective production enforcement) and is removed. Single advancement of
a run is guaranteed by the per-run asyncio lock, the run-head
compare-and-swap, and closure-existence checks (02-run-harness.md
section 10).
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect

from model_forge.application import run_coordinator as rc


def test_invocation_fencing_module_removed() -> None:
    assert (
        importlib.util.find_spec("model_forge.harness.invocation_fencing")
        is None
    )
    assert not hasattr(rc, "InvocationFencer")
    assert not hasattr(rc, "FencingError")


def test_run_loop_has_no_lease_calls() -> None:
    run_source = inspect.getsource(rc.RunCoordinator.run)
    assert "_fencer" not in run_source
    assert "acquire_lease" not in run_source
    assert "release_lease" not in run_source
    init_source = inspect.getsource(rc.RunCoordinator.__init__)
    assert "_fencer" not in init_source


def test_per_run_asyncio_lock_serializes_advancement() -> None:
    coordinator = rc.RunCoordinator.__new__(rc.RunCoordinator)
    coordinator._locks = {}

    statuses = iter(["running", "published", "published"])
    in_flight = 0
    max_in_flight = 0

    class _Repo:
        def get_run(self, run_id: str) -> dict:
            return {"status": next(statuses, "published")}

    async def _execute(run_id: str) -> bool:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return True  # pending: end this advancement pass

    coordinator.repository = _Repo()
    coordinator._execute = _execute  # type: ignore[method-assign]

    async def drive() -> None:
        await asyncio.gather(
            coordinator.run("run-1"), coordinator.run("run-1")
        )

    asyncio.run(drive())
    assert max_in_flight == 1
