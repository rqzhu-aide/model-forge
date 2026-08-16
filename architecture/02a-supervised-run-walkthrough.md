# Supervised Run Walkthrough (Programmer's Guide)

This is the concrete, code-anchored walkthrough of **one supervised run**: the
execution lane that actually runs Hermes today (WP-E0/F0/F1, plus the
2026-08-15 restart-watcher closure). Read it as the companion to
[02-run-harness.md](02-run-harness.md), which specifies the older *formal lane*
state machine (`created → … → published`, formal generations, publication
receipts) driven by `run_coordinator.py`.

**Why two lanes exist.** The formal lane (`run_coordinator.py`,
`runs` + `run_manifests` + `formal_generations` tables, `roles/`-shaped run
directories) is the full publication pipeline specified in docs 02/03. The
supervised lane (this doc, `run_profile_seals` + `run_launch_records` tables,
`briefs/workspace/logs/outputs/profile`-shaped run directories) is the trusted-
local execution program (ADR-012): one sealed Hermes process per project-role,
validated outputs, promoted memory. The Web UI's **Runs** page and all real
Hermes execution to date use the supervised lane. Formal publication from
supervised outputs is **not yet wired**: see §8.

---

## 1. The user action

Runs page → start form: `role` (e.g. `research_lead`), `phase` (e.g. `p1`),
`brief_text`, `expected_outputs` (relative paths + optional JSON schema /
required fields), `memory_policy`, optional `method_identity`, optional
`timeout_seconds` (UI default 14400). The form's client-side builder lives in
`web/src/pages/SupervisedRunsPage.tsx` (`buildSupervisedRunRequest`).

```
POST /api/v1/projects/{project_id}/supervised-runs/start
```

## 2. Seal: the durable contract (synchronous, before any process)

`MethodHubService.start_supervised_run` (`application/service.py`) does, in
order, all before returning:

1. **Idempotency**: an existing `idempotency_key` returns the surviving run
   (`replayed: true`) instead of a second launch.
2. **Project-role state lock**: one run per (project, role); a second start
   while one is live gets `SUPERVISED_RUN_LOCKED` 409.
3. **Seal** (`run_profile_assembler.seal_run`): creates
   `~/.method-hub/runs/<invocation_id>/`, writes the manifest (brief hash,
   expected outputs, timeout, resolved Hermes binary, memory policy), hashes
   it, registers it in `hub.sqlite3` (`run_profile_seals`,
   `run_launch_records`). Survives any restart.
4. **Brief**: `run_dir/briefs/task.md` (exactly the submitted text).
5. **Preflight** (`run_preflight.py`): Hermes binary exists and is the
   recorded one, disk headroom, profile sanity. The report is persisted
   (`run_preflight_reports`) on **both** pass and fail paths. Fail → 409
   `SUPERVISED_RUN_PREFLIGHT_FAILED`, **no process was ever created**.
6. **202 Accepted.** Everything below is background.

## 3. Launch: one Hermes process (worker thread)

`_launch_supervised_in_background` → `launch_sealed_run`
(`application/run_launcher.py`), via `asyncio.to_thread` so the event loop is
never blocked:

- Copies the brief to `run_dir/workspace/task.md` (hash recorded).
- Provisioned profile home at `run_dir/profile/`: a copy of the role's
  profile (persona, skills, tool permissions) that becomes `HERMES_HOME`.
- Environment: allowlisted vars + `HERMES_HOME` + provider keys injected at
  runtime only (`secret_env` is never persisted; logs are redacted).
- The **only external program** the harness runs:

```
hermes -p <role-profile> -z "Read and execute the task brief at <abs path>. Write only the declared output files." --usage-file <workspace>/usage.json
```

`executors/local_hermes.py` builds this (`_build_command`), executes it, and
while it runs:

- appends bounded heartbeat lines → `run_dir/logs/heartbeat.log`
- captures stdout/stderr (bounded, redacted) → written to
  `run_dir/logs/stdout.log` / `stderr.log` at exit
- records the **process identity** (pid, start time, boot id, marker) onto the
  RUNNING launch record the moment the process exists (`ExternalIdRecordingObserver`);
  this is what makes restart reconciliation possible.

## 4. Exit and output validation

On process exit the launch record closes (`succeeded` / `failed` by exit code,
`cancelled` when an explicit cancel flag explains a signal death). Then
`output_validation.validate_run_outputs`:

1. Snapshots `workspace/` → `run_dir/outputs/` (immutable from then on; the
   raw inventory is recorded before any judgment).
2. Every **declared** output must exist under `outputs/`.
3. **Nothing undeclared** may exist there: no stray files, no symlinks or
   normalization tricks escaping the directory.
4. JSON outputs are checked against their declared schema and required
   scientific fields.

Verdict `pass`/`fail` is persisted (`run_validation_reports`).

## 5. Memory promotion (what "promotion" actually means here)

On pass, `state_promotion.promote_run_state` promotes the run profile's
**allowlisted memory/session state** (`run_dir/profile/memories/` and the
profile state DB) into the canonical project-role profile directory
(`~/.method-hub/<project-role profile>/`). It holds the project-role state
lock, captures before/after inventories and digests, swaps atomically via a
staging directory, and rolls back entirely on any error.

> **Note for readers of older prose:** promotion does **not** publish outputs
> as formal phase records. Outputs remain immutable evidence under `outputs/`.
> The validated artifacts become the phase's official records only through the
> formal lane's publication pipeline, which is not yet fed by the supervised
> lane (§8).

## 6. Restart reconciliation + completion watcher (2026-08-15)

On boot, reconcile finds launches still marked `running`. The recorded process
identity decides: alive → leave running (the hub did not own its death);
dead → close the record. Since 2026-08-15 a background watcher
(`_watch_reconciled_run`, deduplicated per launch id) polls reconciled
still-alive processes and, when the process finally exits, closes the record,
runs output validation, and promotes: so a hub restart mid-run no longer
orphans a `running` record forever.

## 7. Run directory layout (supervised lane)

```
~/.method-hub/runs/<invocation_id>/
├── manifest/
│   └── manifest.json     # sealed contract (hashed, registered in hub.sqlite3)
├── briefs/task.md         # exactly the submitted brief text
├── workspace/task.md      # copy given to Hermes; agent writes outputs here
│   └── usage.json         # --usage-file (token/cost accounting)
├── logs/
│   ├── heartbeat.log      # bounded progress lines, appended while running
│   ├── stdout.log         # captured, redacted, written at exit
│   └── stderr.log
├── outputs/               # post-validation immutable snapshot of workspace
└── profile/               # the private Hermes home for this run (HERMES_HOME)
    └── memories/          # promotable memory state
```

> Older `~/.method-hub/runs/run.p*.*/` directories with `roles/` + `tasks/`
> subtrees are **formal-lane** layouts from the pre-ADR-012 coordinator -
> not this lane. Don't use them as a reference.

## 8. Reading the flow in code

| Concern | Module |
|---|---|
| Start command, sealing order, 202/409 paths | `application/service.py` (`start_supervised_run`) |
| Seal + registry + state locks | `application/run_profile_assembler.py` |
| Preflight | `application/run_preflight.py` |
| Launch, brief copy, heartbeat, close | `application/run_launcher.py` |
| Process execution, identity, cancel, reconcile | `executors/local_hermes.py` |
| Output validation | `application/output_validation.py` |
| Memory promotion | `application/state_promotion.py` |
| Logs endpoint for the UI | `service.get_supervised_run_logs` → `GET …/supervised-runs/{inv}/logs` |
| UI: start form / run detail / logs panel | `web/src/pages/SupervisedRunsPage.tsx`, `SupervisedRunDetailPage.tsx` |

**Open gap.** Supervised outputs are validated evidence and promotable
memory, but nothing yet ingests them into formal phase records / generations.
When that lands, this doc's §5 and `02-run-harness.md` §9 must be updated
together.
