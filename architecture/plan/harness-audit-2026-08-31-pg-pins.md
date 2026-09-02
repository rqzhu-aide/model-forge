# Implementation Pins: Pkg G (R14 - cancellation enforcement)

Status: PINNED 2026-09-01 (coordinator). Finding re-probed against the live
tree before pinning; the probe shows the audit's core premise is FALSE and
the requested enforcement already exists. Source of truth for the finding
and the ENFORCE decision:
[../harness-audit-2026-08-31.md](../archive/completed/harness-audit-2026-08-31.md) (R14;
Decisions: "wire cancellation polling into the execution path so
`executor.cancel` reaches the in-flight role").

## Probe facts (verified 2026-09-01 against the live tree, HEAD cad6c3c)

1. The audit's premise is contradicted by the tree at audit time. R14
   states: "The only `executor.cancel` call is in `settle_cancellation`"
   and "`executor.cancel`'s prompt-kill path (with its PID-identity
   guards) is unreachable for the role that matters." In fact
   `RepositoryExecutionObserver.heartbeat`
   (`src/model_forge/harness/execution_observer.py:96-114`) polls
   `repository.cancellation_requested(invocation.run_id)` on EVERY
   heartbeat and, once launch is acknowledged, invokes
   `await self.executor.cancel(self.external_execution_id)`. This code is
   present verbatim in the groundwork commit 429c198 that carries the
   audit doc (verified with `git show 429c198:.../execution_observer.py`),
   i.e. it predates the audit. The audit's own suggested fix - "have the
   execute loop (or observer heartbeat) poll
   `repository.cancellation_requested` and call `cancel`" - describes the
   shipped mechanism (the observer-heartbeat option).
2. The wiring is live: the `local_hermes` execute loop awaits
   `observer.heartbeat(...)` once per `poll_interval_seconds`
   (`executors/local_hermes.py:466-470`), and `role_execution.py:1563-1567`
   constructs the observer with the SAME executor instance that runs the
   role. `LocalHermesExecutor.cancel` (`local_hermes.py:568-611`) parses
   the durable external id, verifies PID identity (start time + host boot
   id, C2), and terminates the process group (SIGTERM, then SIGKILL after
   the grace window). The subprocess is spawned with
   `start_new_session=True` (`local_hermes.py:339`), so the group kill is
   scoped to the role's tree.
3. The closure layer converts the killed role to `cancelled`: both the
   base path (`role_execution.py:2715`) and the correction path
   (`role_execution.py:1973`) override the result status to
   `RoleExecutionStatus.CANCELLED` when
   `repository.cancellation_requested(run_id)` holds at close; the stage
   service maps that to `StageStatus.CANCELLED`
   (`stage_execution.py:153-163`). Pre-launch fences at
   `role_execution.py:1542` and `:1659` short-circuit to CANCELLED
   results before any executor call.
4. LIVE PROBE (/tmp/pg_probe.py, 2026-09-01, HEAD cad6c3c): drove the
   real `HarnessExecutionServices.execute_or_reconcile_stage` with a slow
   executor subclass that heartbeats in a 30 s loop (mirroring the
   local_hermes poll loop), requested cancellation 0.3 s after launch via
   the real `repository.request_cancellation`. Result: total elapsed
   0.33 s; both parallel-stage roles received `executor.cancel` with
   their durable external ids; stage outcome `StageStatus.CANCELLED`;
   both rows in `role_execution_closures` sealed with status
   "cancelled" (exit_code -15 recorded from the kill). Prompt
   termination + CANCELLED closure: CONFIRMED on the pre-package tree.
5. Existing coverage pins only the pre-launch fence
   (`tests/test_stage_execution_service.py:323`
   `test_cancellation_fence_prevents_new_role_launch`: cancellation
   BEFORE the stage starts; asserts no invocations). NOTHING pins the
   mid-flight path the probe exercised - a future refactor could break
   the observer-heartbeat cancel silently.
6. Suite baseline before this package: 1368 passed (P-F DONE note,
   HEAD cad6c3c).

## Resolution (per the program's contradiction rule)

R14's requested behavior already exists; per the fix-program execution
rules ("record the contradiction in the audit doc and skip that item")
NO production code changes. The package ships:

1. The planned regression test (mid-flight cancel -> prompt termination +
   CANCELLED closure), which PASSES on the pre-package tree and pins the
   existing behavior against silent regression (probe fact 5).
2. The `02-run-harness.md` section 11.1 wording update stating prompt
   enforcement (the current text says only "asks active work to stop").
3. A Coordinator note in the audit doc recording the contradiction.

## Execution mode

Planner-direct (no subagent dispatch). After the probe, the remaining work
is one ~55-line test mirroring `test_cancellation_fence_prevents_new_role_
launch`'s fixture vocabulary plus two small doc edits - smaller than the
brief needed to describe it (playbook: "the coder does only truly tiny
surgical fixes"; K-1 P2/K-1 P6 precedent for planner-built tests against a
known fixture stack).

## Allowed files (exactly these)

- `tests/test_stage_execution_service.py` (one new test + imports)
- `architecture/design/02-run-harness.md` (one inserted paragraph, below)
- `architecture/archive/completed/harness-audit-2026-08-31.md` (one Coordinator note)
- `architecture/plan/harness-audit-2026-08-31-pg-pins.md` (this file)

No other files. As with P-F, this package is an exception to the "no
architecture/ edits in the fix commit" boundary: the plan assigns the
02-run-harness.md update to P-G itself, and the contradiction rule
requires the audit-doc note.

## Test pin

Add `test_mid_flight_cancellation_terminates_role_and_closes_cancelled` to
`tests/test_stage_execution_service.py` immediately after
`test_cancellation_fence_prevents_new_role_launch` (:323-350). Recipe:
test-local `SlowExecutor(DeterministicFakeExecutor)` whose `execute` does
launch_intent/launch_acknowledged, then loops up to 30 s: if its
external id is in `self.cancelled` return a FAILED result (exit_code -15,
"killed" semantics, matching what local_hermes produces after
`executor.cancel`); else `await observer.heartbeat(...)` and sleep 10 ms;
falling out of the loop raises AssertionError (cancel never arrived).
Drive stage 0 (parallel, two roles) as an asyncio task; after 0.3 s
record the cancel command rows and call
`repository.request_cancellation(...)` exactly as the fence test does;
`asyncio.wait_for(task, timeout=10)` so a regression to unreachable
cancel FAILS the test instead of hanging. Assert: outcome is
`StageStatus.CANCELLED`; `len(executor.cancelled) == 2`; both
`role_execution_closures.payload_json` documents have status
"cancelled". New imports: `json`, `time`, `RoleExecutionResult`,
`RoleExecutionStatus` (the latter two re-exported from
`model_forge.executors`).

## 02-run-harness.md pin

Insert ONE new paragraph at the end of section 11.1, immediately after
the paragraph ending "...Cancellation preserves available diagnostics and
never changes formal records." (:453-456) and before "### 11.2". Text:

```
Prompt enforcement is durable, not advisory. The local_hermes executor's
poll loop heartbeats through the repository-backed execution observer, which
reads the run's `cancellation_requested` flag at every heartbeat. On the
first heartbeat after acceptance the observer calls `executor.cancel` with
the durable external execution identity; the executor verifies PID identity
(process start time and host boot id) and terminates the process group
(SIGTERM, then SIGKILL after the grace window). The in-flight role then
closes as `cancelled` instead of running to natural exit. End-to-end
cancellation latency is bounded by the executor poll interval plus the
termination grace window.
```

## Audit-doc pin

Append ONE bullet to "## Coordinator notes (added during the fix
program)":

```
- 2026-09-01, Pkg G pinning, R14 contradiction: the finding's premise
  that `settle_cancellation` is the only `executor.cancel` call site and
  that the prompt-kill path is "unreachable for the role that matters"
  was already false at audit time. `RepositoryExecutionObserver.heartbeat`
  polls `cancellation_requested` on every heartbeat and invokes
  `executor.cancel` (execution_observer.py:96-114); this code is present
  in the groundwork commit 429c198 carrying this audit. The local_hermes
  poll loop heartbeats once per poll interval (local_hermes.py:466-470)
  with the same executor instance, so the finding's own suggested fix
  ("execute loop (or observer heartbeat) poll ... and call cancel")
  describes the shipped mechanism. Live probe (recipe and output in this
  pins doc, probe fact 4; the audit-doc rendering links
  plan/harness-audit-2026-08-31-pg-pins.md): a 30 s in-flight role
  terminated 0.33 s after cancellation acceptance; both parallel roles
  received `executor.cancel`; stage outcome CANCELLED; both closures
  sealed "cancelled". Resolution: no production change; P-G ships the
  planned mid-flight regression test (passes on the pre-package tree,
  pinning existing behavior) and the 11.1 wording update.
```
