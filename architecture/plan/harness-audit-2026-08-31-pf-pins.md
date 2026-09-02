# Implementation Pins: Pkg F (R15 - fencing deletion)

Status: PINNED 2026-09-01 (coordinator). Every finding below was re-probed
against the live tree before pinning. Source of truth for the finding and
the DELETE decision:
[../harness-audit-2026-08-31.md](../archive/completed/harness-audit-2026-08-31.md) (R15;
Decisions: "DELETE the dead token/lease path; keep the per-process
asyncio lock and the DB compare-and-swap as the documented
single-advancement mechanism; update 02-run-harness.md accordingly").

## Probe facts (verified 2026-09-01 against the live tree, HEAD 6eb6584)

1. R15 confirmed. Production usage of `harness/invocation_fencing.py` is
   exactly four lines in `src/model_forge/application/run_coordinator.py`:
   import at :43 (`FencingError, InvocationFencer`), construction at :97
   (`self._fencer = InvocationFencer(repository)`), `acquire_lease` at
   :115-116 (holder `f"coordinator:{run_id}"`, deterministic per run, so
   the lease excludes no one - same holder string in every process),
   `release_lease` at :175-176 (the sole occupant of the outer
   try/finally in `run()`). The token machinery (`advance`, `check_fence`,
   `current_token`, `_seed_from_heartbeats`, `is_terminal`) has ZERO
   production callers. `FencingError` is imported but never caught or
   raised anywhere else in run_coordinator.py.
2. Same-named classes elsewhere are SEPARATE machinery, out of scope:
   `diagnostics/store.py` defines its own `FencingToken`/`FencingError`
   (imported by `diagnostics/service.py:58-64` from `.store`), and
   `application/run_profile_assembler.py` defines its own
   `FencingToken`/`StateFencingError`. Neither imports
   `harness.invocation_fencing`. `architecture/design/scenarios/
   S21-stale-lock-ownership.md` describes the diagnostics store's own
   token/lease pair; untouched.
3. Test references: `tests/test_wp1_wp2_modules.py` is the only fencing
   test file - import block :14-18, fakes `_FakeConn`/`_FakeDB`/
   `_FakeRepo` :121-146, `TestInvocationFencer` :148-189 (3 tests), and
   the module docstring :1-2 names "D1.4 InvocationFencing".
   `tests/test_wp1_wp2_integration.py:27` imports `InvocationFencer` but
   never uses it; its module docstring item 4 (:7) claims "InvocationFencer
   is active during run coordination"; its `import asyncio` at :15 is
   likewise unused (grep: only occurrence).
4. No other wiring: `harness/__init__.py` does not re-export fencing;
   `validate_package.py` and `architecture/tools/` carry no reference;
   the only architecture/design mention is S21 (probe fact 2). The
   archive doc `architecture/archive/completed/
   wp1-wp2-execution-and-validation.md` is historical and stays.
5. The documented post-deletion guarantee is real in the live tree:
   per-run `asyncio.Lock` wraps the whole advancement loop
   (run_coordinator.py:113-114); every lifecycle transition goes through
   `RunLifecycle._mutate` -> `compare_and_swap_run` (run_lifecycle.py:90,
   repository.py:454); closed role invocations reconcile through
   closure-existence reads rather than re-executing (P-A recovery lane).
6. Suite baseline before this package: 1368 passed (dot count 19x72, no
   failures), HEAD 6eb6584.

## Allowed files (exactly these)

- DELETE `src/model_forge/harness/invocation_fencing.py` (git rm).
- `src/model_forge/application/run_coordinator.py`
- `tests/test_wp1_wp2_modules.py`
- `tests/test_wp1_wp2_integration.py`
- `tests/test_run_advancement_guarantee.py` (NEW)
- `architecture/design/02-run-harness.md` (one inserted paragraph, below)

No other files. This package is the exception to the "no architecture/
edits in the fix commit" boundary: the plan assigns the 02-run-harness.md
update to P-F itself.

## run_coordinator.py pin

1. Delete line 43 (`from ..harness.invocation_fencing import FencingError,
   InvocationFencer`).
2. Delete line 97 (`self._fencer = InvocationFencer(repository)`).
3. In `run()`, delete the `holder = f"coordinator:{run_id}"` and
   `self._fencer.acquire_lease(run_id, holder)` lines (:115-116).
4. The outer try/finally in `run()` (:117 try, :175-176 finally
   release_lease) exists ONLY to release the lease. With the lease gone,
   unwrap it: remove the `try:` and the `finally:` block and de-indent
   the `for` loop one level. The `async with lock:` stays and keeps its
   current body. The INNER try (:123, `except asyncio.CancelledError` /
   `except Exception` -> `_handle_error`) is unchanged.

## test_wp1_wp2_modules.py pin

- Remove the `from model_forge.harness.invocation_fencing import (...)`
  block (:14-18).
- Remove `_FakeConn`, `_FakeDB`, `_FakeRepo` (:121-146) and the whole
  `TestInvocationFencer` class (:148-189), including the
  "InvocationFencer" section banner comment (:117-119).
- Update the module docstring (:1-2) to drop "D1.4 InvocationFencing":
  `"""Tests for WP1 D1.2 CapabilityBroker, WP2 D2.1 OutputAdapter, and
  D2.2 scientific validators."""`

## test_wp1_wp2_integration.py pin

- Remove `import asyncio` (:15; verified unused) and
  `from model_forge.harness.invocation_fencing import InvocationFencer`
  (:27; verified unused).
- Update the module docstring: replace item 4 ("InvocationFencer is
  active during run coordination", :7) with
  "4. Golden fixtures are schema-valid" and renumber the following items
  (5 NetworkPolicy..., 6 Golden..., 7 Mutation... becomes
  4 NetworkPolicy modes work correctly, 5 Golden fixtures are
  schema-valid, 6 Mutation fixtures are properly labelled). Exact new
  docstring list:

```
These tests verify that:
1. CapabilityBroker is invoked during role execution (inputs materialized)
2. OutputAdapter is invoked after validation (linked artifacts captured)
3. Raw output is preserved on failure
4. NetworkPolicy modes work correctly
5. Golden fixtures are schema-valid
6. Mutation fixtures are properly labelled
```

## 02-run-harness.md pin

Insert ONE new paragraph at the end of section 10 "Concurrency and
conflicts", immediately after the paragraph ending "...requires a later
architecture decision and phase-specific tests." (currently :395) and
before the paragraph starting "The global authority journal". Exact text
(plain ASCII, no em/en dashes, no trailing whitespace):

```
Advancement of a single run is single-threaded by construction. Within one
server process, a per-run asyncio lock in the run coordinator serializes the
whole advancement loop. Across processes and restarts, every lifecycle
transition commits through an exact run-head compare-and-swap
(`compare_and_swap_run`), so a stale advancer conflicts instead of
double-advancing, and role re-execution is excluded by closure-existence
checks during reconcile. There is no separate fencing-token or
coordinator-lease layer.
```

## Regression tests: tests/test_run_advancement_guarantee.py (NEW)

```python
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
```

Expected pre-fix failures (all three FAIL on the pre-fix tree):

1. `test_invocation_fencing_module_removed`: find_spec returns a spec;
   both hasattr checks are True.
2. `test_run_loop_has_no_lease_calls`: `_fencer`, `acquire_lease`,
   `release_lease` all present in the source.
3. `test_per_run_asyncio_lock_serializes_advancement`: raises
   AttributeError - the `__new__`-constructed coordinator has no
   `_fencer`, and pre-fix `run()` calls `self._fencer.acquire_lease`.
   Post-fix the same test proves the asyncio lock alone serializes the
   two concurrent passes (`max_in_flight == 1`).

## Boundaries

- Write ONLY inside /home/tez/product/model-forge; never create or edit
  files outside it - not skill files, notes, memory, or scratch outside
  /tmp.
- Exactly one commit for the package. Do NOT touch the fix-program plan
  file or the audit doc; the coordinator marks DONE separately.
- Do not touch the diagnostics or run_profile_assembler fencing classes
  (probe fact 2) or the S21 scenario doc.
- Test-count math: baseline 1368; remove 3 (TestInvocationFencer), add 3
  (new file); expected final count 1368. Report the exact final count.
- Gates before commit: `.venv/bin/python -m pytest tests -q` exit 0 and
  `.venv/bin/python architecture/tools/validate_package.py` exit 0.
- Every new regression test MUST be observed failing on pre-fix code
  (stash the src changes, run the three new tests, confirm the predicted
  failures, restore). Report the pre-fix failure output.
- No em/en dashes and no trailing whitespace in any architecture/ file
  (validator-enforced). Commit message:
  `Audit-2026-08-31 Pkg F: delete decorative invocation fencing machinery (R15)`

## Report back

- Commit SHA and `git show --stat`.
- Pre-fix failure output for each of the three new tests.
- Final suite count and validator exit code.
- Any deviation from these pins, with evidence.
