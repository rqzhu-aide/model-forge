# Hermes v0.19.0 Transport Reconnaissance and Initial Connectivity Findings

Status: Completed exploratory findings. The full Checkpoint 0-pre evidence
package and Phase 0 remain open.
Date: 2026-08-03
Hermes version: v0.19.0 (2026.7.20), upstream eb527605

Scope note: the repository does not yet contain the required reproducible spike
script or complete evidence for block and reclaim behavior, backend context
guards, and exact event formats. This record supports the verified findings
below, but does not satisfy the full Checkpoint 0-pre or Phase 0 exit gate.

## Method

All findings verified against Hermes v0.19.0 source code in
`/home/tez/.hermes/hermes-agent/` and live CLI behavior on a disposable
spike board. No real agent ran during the spike; all tasks used a
nonexistent assignee profile.

## Findings

### 1. Status enum (A5 -- confirmed)

Source: `hermes_cli/kanban_db.py:102`

```python
VALID_STATUSES = {"triage", "todo", "scheduled", "ready", "running",
                  "blocked", "review", "done", "archived"}
```

There is **no `failed` and no `cancelled`** status. The current Method Hub
adapter (`executors/hermes.py:165-184`) maps both, which are dead branches.

Real failure surfaces as **`blocked`** via the circuit breaker
(`_record_task_failure`, `kanban_db.py:7585`). The breaker increments
`consecutive_failures` and flips `ready → blocked` when the count reaches
the effective limit.

### 2. Idempotent create (A3 -- confirmed, hole is real)

Source: `hermes_cli/kanban_db.py:3028-3036`

```python
if idempotency_key:
    row = conn.execute(
        "SELECT id FROM tasks WHERE idempotency_key = ? "
        "AND status != 'archived' "
        "ORDER BY created_at DESC LIMIT 1",
        (idempotency_key,),
    ).fetchone()
```

**Live verification:**
- Create with key `spike-key-1` → task `t_a748b0b5`
- Recreate with same key → returns `t_a748b0b5` (dedup works)
- Archive `t_a748b0b5` → recreate with same key → **new task `t_8b4ab333`**

The archived-task hole is confirmed. Since `archive` is the cancellation
mechanism, a cancel-then-recover race can silently create a second task.

**Recovery rule:** a cancelled invocation is terminal. Reconciliation must
never re-create a task for an invocation that has a prior cancellation
record.

### 3. Requeue hazard (A4 -- confirmed in source, `--max-retries 0` is the fix)

Source: `hermes_cli/kanban_db.py:7585-7745` (`_record_task_failure`)

On timeout, the dispatcher kills the worker and calls
`_record_task_failure` with `outcome="timed_out"`. If
`consecutive_failures < effective_limit`, the task stays at `ready`
(ready for re-dispatch). If `>= effective_limit`, it flips to `blocked`.

The effective limit resolution (`kanban_db.py:7653-7663`):
1. Per-task `max_retries` if set (nothing overrides it)
2. Caller-supplied `failure_limit` (gateway config `kanban.failure_limit`)
3. `DEFAULT_FAILURE_LIMIT` (value: 2)

**`--max-retries 1` blocks on the first failure (zero retries).** This is
the correct setting for Method Hub: a timed-out task goes straight to
`blocked` and is never re-dispatched.

The current adapter sets `--max-retries 0`, which means "use the dispatcher
default (2)" -- allowing two retries. This is a bug.

### 4. Worker topology (A1 -- confirmed)

Source: `gateway/run.py:8576-8580`

```python
# Start background kanban dispatcher -- spawns workers for ready
# tasks. Gated by `kanban.dispatch_in_gateway` (default True).
self._spawn_supervised(self._kanban_dispatcher_watcher, "kanban_dispatcher_watcher")
```

The kanban dispatcher runs **inside the gateway process**. Workers are
spawned by the gateway, not by the submitting CLI. Containerizing only the
submitting `hermes kanban create` command isolates nothing about the actual
agent execution.

**Track A implication:** For local single-host use, the worker runs in the
host gateway with the host profile's full environment. This is acceptable
for a development diagnostic path where the operator owns the profiles. The
full OCI isolation boundary (Track B) is deferred.

### 5. Event streams (A6 -- confirmed)

Two distinct output domains:

**Domain 1 -- control processes:** stdout/stderr of short-lived CLI calls
(`create`, `show`, `archive`). These are captured via `subprocess.run` in
the current adapter.

**Domain 2 -- agent output:** Exposed through dedicated commands:
- `hermes kanban tail <task_id>` -- follow event stream (polling)
- `hermes kanban log <task_id> [--tail N]` -- worker log from SQLite
- `hermes kanban runs <task_id> --json` -- structured run history
- `hermes kanban heartbeat <task_id> [--note ...]` -- heartbeat events

The current adapter does not read Domain 2 at all. For Track A, the
heartbeat poll already reads `show` status; adding `log --tail N` after
terminal closure gives bounded agent-output capture.

### 6. Board and gateway model

- Boards are per-project SQLite DBs under `~/.hermes/kanban/boards/<slug>/`
- The host gateway dispatches all boards by default
- Board hygiene (dedicated gateway for diagnostic board) is a Track B concern
- For Track A, the existing `method-hub` board on the host gateway is sufficient

### 7. Cancellation semantics

`hermes kanban archive <task_id>` moves the task to `archived` status. It
does **not** directly stop a running worker -- the dispatcher's stale-claim
reclaim handles that. For Track A, after archiving we should poll until the
task reaches `archived` and report archive-state confirmation. This confirms
the task record only. It does not prove that the worker stopped or that output
writes became quiescent.

## Summary of required adapter fixes (Track A)

1. Fix status mapping: `done → SUCCEEDED`, `blocked → FAILED`, `archived →
   CANCELLED`, everything else continues polling.
2. Fix `--max-retries`: change `0` to `1` (block on first failure, no
   requeue).
3. Fix recovery: never re-create a task for a cancelled invocation.
4. Add bounded streaming output capture (Domain 1).
5. Add agent log capture after terminal state (Domain 2, via `log --tail`).
6. Add environment allowlist instead of `dict(os.environ)`.
7. Add Hermes profile existence verification before launch.
8. Add archive-state polling and distinguish it from confirmed worker termination.

## Initial Checkpoint 0G connectivity subtest passed; full 0G gate remains open

Date: 2026-08-03
Hermes version: v0.19.0
Task: t_bd8831c8 on board `method-hub`

A real Hermes agent (profile: `theorist`) completed a synthetic word-count
task through the hardened executor in 78.4 seconds. Evidence:

- **Status mapping:** `ready` (10 polls) -> `running` (5 polls) -> `done`.
  Correctly mapped to `SUCCEEDED`.
- **--max-retries 1:** confirmed in the persisted task record
  (`max_retries: 1`).
- **Agent log capture (Domain 2):** worker log captured via
  `hermes kanban log`, showing the agent's `kanban_show`, `read_file`, and
  `write_file` actions.
- **Initial capped output foundation (Domain 1):** the control-process output
  was captured without error in this finite test. The full bounded-supervisor
  and infinite-output gates remain open.
- **Environment allowlist:** task executed successfully with the minimal
  environment.
- **Profile verification:** `theorist` profile verified before launch.
- **Output:** `output.json` with `{"word_count": 31}`, `note.txt` with
  confirmation. Correct.

Formal scientific state was not touched. The diagnostic task was archived
after completion.
