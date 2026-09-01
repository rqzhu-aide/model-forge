# P-A Implementation Pins (Recovery core: R1, R5, R6)

Companion to `harness-audit-2026-08-31-fix-program.md`. These pins are the
binding design for package P-A. All line numbers verified against the live
tree at groundwork commit 429c198.

## Probe summary (coordinator verified 2026-08-31, all audit claims hold)

- `src/model_forge/application/run_coordinator.py:300-336` (`_execute`)
  never returns True; the `if pending: return` branch at :135-137 is dead.
- `src/model_forge/harness/role_execution.py:1529` and :1654 raise
  `RoleExecutionPending` on a non-terminal acknowledged execution and
  re-raise it untouched; `orchestration/sequential.py` and
  `harness/stage_execution.py` do not catch it, so it reaches `_execute`.
- `role_execution.py:196`: `identity.get("version", 1) < 1` raises
  TypeError for `"version": null` or `"0"`. The enclosing repair function
  is `_apply_disclosed_mechanical_repairs` (:66); `_fix_item` (:186-208)
  runs per output document (dict) or per list item.
- `role_execution.py:1534-1541` (base path) and :1659-1666 (correction
  path) catch ALL exceptions from `executor.execute`/`reconcile` and seal
  a durable FAILED `RoleExecutionResult`.
- The observer is `RepositoryExecutionObserver` in
  `src/model_forge/harness/execution_observer.py` (imported as
  `_RepositoryObserver` at role_execution.py:48). Its repository calls:
  `launch_intent` -> `repository.get_or_create_execution` (:30),
  `launch_acknowledged` -> `repository.acknowledge_execution` (:42),
  `heartbeat` -> `repository.append_execution_heartbeat` (:60) and
  `repository.cancellation_requested` (:72). Subclass `_CorrectionObserver`
  (role_execution.py:1412) overrides `launch_acknowledged` and calls
  `repository.acknowledge_execution` directly (:1437-1449).
- One executor instance is built in `application/bootstrap.py:61-70` and
  held as `RunCoordinator.executor`; `_execution_components`
  (run_coordinator.py:494, :607) reads `self.executor` fresh on every
  pass, so tests may replace `coordinator.executor` after construction.

## Fix R1 (pinned)

In `run_coordinator._execute`, wrap the `orchestrator.execute(...)` call
(currently :306-312):

```python
        try:
            result = await orchestrator.execute(
                run_id=context.run_id,
                manifest_sha256=context.manifest_sha256,
                binding=binding,
                plan=plan,
                services=ProgressReportingServices(services, self.lifecycle),
            )
        except (RoleExecutionPending, RoleExecutionInfrastructureError):
            # Restart-safe recovery: an acknowledged execution is still in
            # flight, or harness bookkeeping hit a transient failure. Leave
            # the run `running`; the next resume/notify pass reconciles.
            return True
```

Import both exceptions from `..harness.execution_records` in
run_coordinator.py. This makes the pending branch at :135-137 live.

## Fix R5 (pinned, exact replacement)

Replace role_execution.py:196-198:

```python
            identity = item.get("identity")
            if isinstance(identity, dict) and identity.get("version", 1) < 1:
                identity["version"] = 1
                changed = True
```

with:

```python
            identity = item.get("identity")
            if isinstance(identity, dict):
                version = identity.get("version")
                if (
                    isinstance(version, bool)
                    or not isinstance(version, (int, float))
                    or version < 1
                ):
                    identity["version"] = 1
                    changed = True
```

Note: this also stamps `version = 1` when the key is absent (the audit
pin's explicit semantics). That is intended normalization, not a bug.

## Fix R6 (pinned)

1. New exception in `src/model_forge/harness/execution_records.py`,
   immediately after `RoleExecutionPending` (:24):

```python
class RoleExecutionInfrastructureError(RoleLifecycleError):
    """Harness-side bookkeeping failed; the execution outcome is unknown.

    Raised when an observer/persistence call (not the executor's domain
    logic) fails, so the failure must NOT be sealed into a durable FAILED
    closure. The run stays `running` and a later pass reconciles.
    """
```

   Add `"RoleExecutionInfrastructureError"` to that module's `__all__`
   (:217-230), import it in role_execution.py (next to the
   `RoleExecutionPending` import at :54), and add it to role_execution.py's
   `__all__` (:3076 area) mirroring RoleExecutionPending.

2. Wrap every repository call in
   `harness/execution_observer.py` (`launch_intent`, `launch_acknowledged`,
   both repository calls in `heartbeat`) and the
   `_CorrectionObserver.launch_acknowledged` repository call
   (role_execution.py:1437-1449) with:

```python
        try:
            <existing repository call>
        except Exception as error:
            raise RoleExecutionInfrastructureError(
                f"Harness bookkeeping for execution "
                f"{invocation.execution_id} failed: "
                f"{type(error).__name__}: {error}"
            ) from error
```

   Do NOT wrap `await self.executor.cancel(...)` in `heartbeat`
   (executor-domain). `asyncio.CancelledError` is BaseException and is
   unaffected. Never wrap a `RoleExecutionInfrastructureError` again if it
   is already that type (guard with `except RoleExecutionInfrastructureError:
   raise` first, or structure so wrapping happens once).

3. In role_execution.py, add to BOTH try blocks (:1521-1541 and
   :1646-1666), immediately after the existing
   `except RoleExecutionPending: raise`:

```python
        except RoleExecutionInfrastructureError:
            raise
```

   The broad `except Exception` that seals FAILED stays for genuine
   executor-domain failures (audit: "executor-domain failures still seal
   FAILED").

4. run_coordinator._execute catches it (see R1 pin; one except clause
   covers both). In the correction command path
   (`application/correction_execution.py:1189`) the exception now
   propagates to the command caller instead of sealing a durable FAILED
   closure; that is the sanctioned "re-raise" outcome (a transient
   infrastructure error surfaces as a failed command attempt and the
   correction can be retried). No new error codes; do NOT touch the
   error-code registry.

## Regression tests (pinned)

All new tests go in `tests/test_run_coordinator_recovery.py`, reusing its
fixture vocabulary: `_service(tmp_path)`, `_create_project`,
`_start_phase_one`, `_wait_for_terminal`, `TERMINAL_STATES`,
`service.run_launcher.__self__` is the coordinator, set
`service.run_launcher = None` to drive passes manually,
`coordinator.run(run_id)` drives one pass, `coordinator.executor` is
replaceable.

### Test 1 (R1 + R6): restart with an in-flight role recovers

Shape: `test_restart_with_in_flight_role_recovers`.

- Custom executor subclassing `SchemaExampleFakeExecutor`
  (`src/model_forge/executors/development.py:55`):

```python
class _RestartFakeExecutor(SchemaExampleFakeExecutor):
    """External process finishes its work but the harness pass is
    interrupted before close; reconcile stays non-terminal once, then
    returns the completed result."""

    def __init__(self, architecture_root: Path) -> None:
        super().__init__(architecture_root)
        self.completed: dict[str, RoleExecutionResult] = {}
        self.reconcile_suspended = True

    async def execute(self, invocation, observer):
        await observer.launch_intent(invocation)
        external_id = f"fake:{invocation.execution_id}"
        await observer.launch_acknowledged(invocation, external_id)
        for offset, output_path in enumerate(invocation.expected_output_paths, start=1):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(self._example_output(invocation, offset), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        result = RoleExecutionResult(
            RoleExecutionStatus.SUCCEEDED, external_id, 0,
            "Process completed; the harness pass was interrupted before close.",
        )
        self.completed[invocation.execution_id] = result
        await observer.heartbeat(invocation, "interrupted pass")
        return result

    async def reconcile(self, external_execution_id: str):
        if self.reconcile_suspended:
            return None
        return self.completed.get(external_execution_id.removeprefix("fake:"))

    async def cancel(self, external_execution_id: str) -> None:
        return None
```

- One-shot harness-side failure: wrap
  `service.repository.append_execution_heartbeat` so the FIRST call raises
  `sqlite3.OperationalError("database is locked")` and later calls
  delegate to the original (verify the observer's repository is the same
  object as `service.repository`; bootstrap wires a single instance).
- Sequence:
  1. `service = _service(tmp_path)`;
     `coordinator = service.run_launcher.__self__`;
     `service.run_launcher = None`;
     `coordinator.executor = _RestartFakeExecutor(ARCHITECTURE)`.
  2. Create project + start P1 run (helpers above).
  3. Pass 1: `await coordinator.run(run_id)`. Heartbeat raises inside the
     observer -> R6: run must stay `running` (pre-fix: sealed FAILED
     closure, run `failed`). Assert state == "running".
  4. Pass 2: `await coordinator.run(run_id)`. Acknowledgement exists,
     reconcile returns None -> R1: run must stay `running`. Assert
     state == "running" and `len(coordinator.executor.invocations)` is
     unchanged from after pass 1 (reconcile path, not re-execution).
     Note: `_RestartFakeExecutor` inherits `self.invocations` but the
     pinned `execute` above does not append; either append in `execute`
     or assert on `completed`. Pick one and keep it consistent.
  5. `coordinator.executor.reconcile_suspended = False`;
     drive `await coordinator.run(run_id)` (loop a few times if needed)
     until terminal via `_wait_for_terminal`.
  6. Assert final state == "published".

### Test 2 (R5): null identity version is coerced

Shape: `test_null_identity_version_is_coerced_during_repair`.

- Executor: subclass `SchemaExampleFakeExecutor`, override
  `_example_output` to call super() and then set
  `target["identity"] = {"version": None}` on the produced document
  (top-level dict, or each item of the list for `each_item`
  applications).
- Drive a normal P1 run to completion (the existing helpers).
- Post-fix assertion: run reaches `published` (repair coerces the version
  to 1; P1 schemas `handoff.schema.json` / `literature-source.schema.json`
  declare `created_at` so `_fix_item` always runs, and both allow
  additional properties so the coerced identity block does not fail
  validation).
- Pre-fix behavior (must be confirmed): the run ends `failed` because
  `identity.get("version", 1) < 1` raises TypeError through
  `_validate_and_close` into `_handle_error`.

## TDD gate (mandatory)

Write the tests FIRST and run them against the UNFIXED code: both must
fail (test 1 at the state assertion after pass 1, test 2 with a failed
run). Then apply the fixes and confirm both pass. Record the observed
pre-fix failure output in the report-back.

## Boundaries

- Write ONLY inside /home/tez/product/model-forge; never create or edit
  files outside it - not skill files, notes, memory, or scratch outside
  /tmp.
- Files expected in the diff: `src/model_forge/harness/execution_records.py`,
  `src/model_forge/harness/execution_observer.py`,
  `src/model_forge/harness/role_execution.py`,
  `src/model_forge/application/run_coordinator.py`,
  `tests/test_run_coordinator_recovery.py`. Nothing else.
- Do NOT add error codes; do NOT touch `architecture/`; do NOT modify the
  pending branch, `_handle_error`, or the cancellation paths.
- No em/en dashes anywhere.
