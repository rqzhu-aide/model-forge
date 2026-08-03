# Phase 0: Safe Hermes Execution

Status: Implementation instruction — Revision 1

Prepared: 2026-08-03 (original draft)
Revised: 2026-08-03 (Revision 1, grounded review amendments)

## Revision 1 summary

This revision keeps the original plan's scope, checkpoints, and engineering
judgment intact. It incorporates the results of a grounded review that (a)
verified every claim in Section 2 against the current adapter source, and (b)
probed the live Hermes kanban interface for the behavior the original draft
flagged as unverified. The amendments are:

1. **A1 — Worker topology is now a named, gated deliverable.** The kanban
   dispatcher runs inside the Hermes gateway and spawns workers there. A
   container around the submitting CLI therefore isolates nothing. Section 5.4
   now names the reference topology (dedicated disposable profile plus a
   dedicated gateway inside the rootless container, with its own
   `HERMES_HOME`, subscribed only to the diagnostic board) and Checkpoint 0B
   gains an explicit worker-topology gate.
2. **A2 — Board-hygiene preflight.** Kanban boards are shared across every
   profile and gateway. Preflight must prove that no host gateway dispatches
   the diagnostic board; otherwise a host worker with ambient access executes
   the diagnostic task and all isolation evidence is void (Section 5.1,
   Section 7).
3. **A3 — Idempotent create confirmed, with an archived-task hole.** Live
   `--help` text confirms: if a *non-archived* task with the idempotency key
   exists, its ID is returned instead of creating a duplicate. Because
   `archive` is the current cancellation mechanism, a cancel-then-recover race
   can silently create a second task. Section 5.6 now defines the recovery
   rule for this hole.
4. **A4 — `--max-runtime` re-queues the task.** Documented dispatcher
   behavior: on timeout the dispatcher SIGTERMs (then SIGKILLs) the worker
   **and re-queues the task**. The current adapter sets `max-runtime` equal to
   the frozen invocation timeout, so a timed-out role can be killed and then
   run again after the harness has sealed a failure. Section 5.7 and the
   acceptance table now treat requeue prevention as a hard requirement.
5. **A5 — Real status vocabulary.** Live statuses are `{triage, todo, ready,
   running, blocked, done, review, scheduled, archived}`. There is no `failed`
   or `cancelled`; failure surfaces as `blocked` via the circuit breaker. The
   diagnostic state model (Section 5.8) must be built on the real enum.
6. **A6 — Two output domains separated.** Control-process streams (short-lived
   CLI calls) and agent output (the kanban event stream in SQLite) are
   different mechanisms with different bounding strategies (Section 5.3). The
   transport does expose structured agent events — `hermes kanban tail`,
   `log`, `runs`, `heartbeat` — so the diagnostic viewer must not invent
   streams (Section 5.8).
7. **A7 — New Checkpoint 0-pre: transport reconnaissance spike.** The five
   open behavioral questions that shape Checkpoints 0B/0D/0E are answered by a
   scripted, disposable-board spike before checkpoint code is written
   (Section 6). Note: Hermes refuses kanban mutations from delegated agent
   child contexts; the spike must run from a plain operator shell, and the
   backend's CLI invocation context must be verified for the same guard.
8. **A8 — Provisioning repeatability.** The current adapter assumes a board
   named `method-hub` and four role profiles with no in-repo provisioning.
   Phase 0 diagnostic resources (board, profile, container image) must be
   created by a recorded, repeatable procedure — not unrecorded host state
   (Section 4, Section 5.1). This preserves the future WP7 stop-ship
   condition on developer-machine state.

Items A3, A4, and A1 are blocking amendments: they change the recovery and
isolation design, not just its documentation.

---

## 1. Target goal

Phase 0 must demonstrate that Method Hub can execute one real Hermes role
through a bounded, observable, cancellable, and recoverable execution path.

The role works only in a disposable diagnostic workspace. Its output must not
enter the formal records, authority journal, current index, method catalog, or
publication path of any research project.

Phase 0 is complete only when:

1. Method Hub verifies the actual Hermes installation and selected profile
   before launch.
2. One real single-role invocation succeeds through the bounded execution path.
3. Failure, timeout, cancellation, and application restart are observable and
   do not create a duplicate Hermes invocation.
4. Console output and role artifacts remain within explicit memory, storage,
   path, and time limits.
5. The actual agent and its tools cannot access undeclared project state,
   credentials, memory, files, or network resources.
6. Formal scientific state remains unchanged.

This phase proves the execution boundary. It does not authorize real Phase 1
through Phase 5 research runs or formal publication. Exact reviewed-basis
sealing remains a later prerequisite for publishable Hermes work.

## 2. Relationship to the existing architecture

The current [Hermes executor](../../src/method_hub/executors/hermes.py) is a
useful development adapter. It already creates a Hermes task with an
idempotency key, polls task status, reports heartbeats, applies elapsed-time
limits, and requests cancellation.

It is not yet the supported execution boundary. Each original finding is now
verified against source:

- it inherits the host process environment (`dict(os.environ)`,
  `hermes.py:47`);
- it buffers complete command output before checking the configured byte limit
  (`subprocess.run` with `PIPE`, size checked after the fact,
  `hermes.py:52-71`);
- it gives Hermes a host directory without proving a capability boundary
  around the actual agent and its tools (`--workspace dir:{...}`,
  `hermes.py:101`);
- its cancellation action does not confirm that the external Hermes task
  stopped (`cancel()` calls `archive` and never verifies a terminal state,
  `hermes.py:203-216`);
- recovery depends on Hermes idempotency behavior that has not been verified
  by dedicated integration tests (`reconcile()` requires an already-persisted
  external task ID, `hermes.py:218-243`);
- it has no dedicated Hermes executor test suite (no test file references
  `HermesKanbanExecutor`).

The grounded review additionally established:

- the adapter maps statuses `failed` and `cancelled` that do not exist in the
  live status enum; real failure surfaces as `blocked` (see A5);
- the adapter sets `--max-runtime` to the frozen invocation timeout, which
  under documented dispatcher behavior can re-queue the task after a kill
  (see A4);
- the adapter assumes a board named `method-hub` and four role profiles that
  no in-repo procedure provisions (see A8).

Phase 0 should strengthen this adapter and the shared executor boundary. It
must reuse the execution, cancellation, and recovery semantics defined by the
[run harness](../02-run-harness.md) and the isolation rules in the
[role and context contract](../08-role-context-and-communication.md), while
remaining outside the scientific run, submission, and publication lifecycle.
Its tests must follow the [validation strategy](../05-validation-strategy.md).

The active [Operational Completion Plan](operational-completion-plan.md)
continues to define the production sequence. Phase 0 is a non-publishing
diagnostic program and therefore does not weaken the requirement that the
reviewed scientific basis be sealed before any Hermes output can receive
formal authority. Phase 0 delivers the first tranche of WP1 (completion-plan
slices 5 and 6) ahead of WP0; the completion plan should record this
reordering with a cross-link so the two documents do not drift. WP0 remains a
hard gate for any publishable run.

## 3. Scope

### 3.1 Included

Phase 0 includes:

- Hermes installation, version, transport, board, and profile verification;
- a dedicated diagnostic invocation path;
- bounded process supervision;
- environment and credential minimization;
- workspace and capability isolation;
- console-log and artifact limits;
- durable external-execution identity;
- heartbeat, timeout, cancellation, and startup reconciliation;
- a minimal diagnostic status and log viewer;
- recorded, repeatable provisioning of all diagnostic resources (board,
  disposable profile, container image);
- one successful real single-role test;
- failure-injection and containment tests.

### 3.2 Excluded

Phase 0 must not:

- run a scientific Phase 1 through Phase 5 contract as production work;
- create a run submission or publication receipt;
- validate or publish a scientific record;
- update a method, evidence registry, theory record, manuscript, or current
  project view;
- introduce automatic scientific retry or phase progression;
- claim outside-reviewer independence;
- enable remote or non-loopback operation;
- claim Windows support;
- replace the later reviewed-basis, authentication, backup, restore, or
  release qualification work.

Reusable infrastructure is encouraged, but Phase 0 must remain small enough to
diagnose Hermes execution independently from the scientific workflow.

## 4. Entry conditions

Before Phase 0 implementation begins:

1. Run the architecture package validator, backend test suite, and frontend
   test suite. Record the baseline results.
2. Keep the default executor disabled and preserve the fake-executor
   development path.
3. Prepare a supported Linux test host with a known Hermes installation.
4. Create or designate a disposable Hermes profile with no project-specific
   persistent memory, through a recorded, repeatable provisioning procedure.
   It must not be confused with a production research profile.
5. Use a dedicated diagnostic data root and workspace. It must not contain or
   mount a real Method Hub project.
6. Record a digest or equivalent inventory of formal test-project state before
   any real invocation so unchanged state can be demonstrated afterward.
7. Confirm that credentials required to reach Hermes or its model provider can
   be injected narrowly. They must not be copied into task briefs, manifests,
   logs, artifacts, or diagnostic reports.
8. Provision the diagnostic kanban board through a recorded procedure, and
   record which gateways are expected to dispatch it (exactly one: the
   containerized diagnostic gateway defined in Section 5.4).
9. Run the Checkpoint 0-pre transport reconnaissance spike (Section 6) and
   record its findings. Checkpoint design may not assume behavior the spike
   has not confirmed.

If a safe disposable profile or isolated test host is unavailable,
implementation may proceed with mocks, but no real Hermes task should be
launched.

## 5. Required system behavior

### 5.1 Hermes preflight

Preflight must run before a task is created. It should report a typed,
researcher-readable result for each required check:

- executable or service endpoint found;
- Hermes version supported;
- configured transport responds;
- configured board or task namespace is accessible;
- **board hygiene: no gateway or dispatcher other than the designated
  diagnostic gateway can claim tasks from the diagnostic board** (see A2);
- selected profile exists and is usable;
- model and provider configuration is present without displaying secrets;
- required create, inspect, cancel, and idempotency capabilities are available
  — including the specific behaviors confirmed by the 0-pre spike
  (idempotent create, requeue policy, cancellation semantics);
- the backend's CLI invocation context is accepted by Hermes context guards
  (kanban mutation is refused from delegated agent child contexts; the
  diagnostic backend must invoke the CLI from an accepted context);
- diagnostic workspace permissions and free space are adequate;
- isolation runtime and capability broker are available;
- configured limits are internally consistent.

Preflight must fail closed. A warning may describe an optional capability, but
a missing safety capability must disable the diagnostic launch action.

Use stable error categories such as unsupported version, missing profile,
unavailable transport, unsafe workspace, missing isolation, board contested,
or invalid limits. Exact identifiers may follow the existing error-model
conventions.

Profile verification must inspect Hermes itself or its supported configuration
interface. Checking that a profile name is a nonempty string is not
sufficient. A health check must not silently create a research task.

All preflight-verified resources must trace to the recorded provisioning
procedure (Section 4). A resource that exists only because someone once
created it by hand fails this check.

### 5.2 Diagnostic invocation contract

The diagnostic action must be separate from the five scientific phase
commands. It may reuse the RoleExecutor and execution-observer interfaces, but
it must not enter submission, validation, promotion, or publication services.

The accepted diagnostic request must identify:

- the selected disposable profile;
- the exact diagnostic task version;
- the fixed synthetic input digest;
- the expected output names and formats;
- the execution-policy version and digest;
- time, log, file, workspace, process, and network limits;
- an idempotency key;
- the requesting local user or operator identity available in development
  mode.

The diagnostic task should be scientifically harmless. A suitable task reads
one small synthetic Markdown file and produces:

- one small structured result;
- one short readable note;
- no external research claim;
- no request to start another task.

The role must be told that this is a diagnostic invocation and that only the
declared outputs are permitted. The task must not force-load any skill; the
diagnostic profile's skill set is pinned by the provisioning procedure.

### 5.3 Bounded supervision of two output domains

Phase 0 supervises two distinct output domains. They must not be conflated.

**Domain 1 — control processes.** Short-lived CLI invocations (task create,
inspect, cancel). Replace unbounded command collection with a supervisor that
enforces limits while output is being produced. The supervisor must:

- start the control process without an interactive shell;
- place the process in a controllable process group or equivalent operating
  system job;
- pass an explicit environment allowlist rather than copying the complete
  host environment;
- keep credentials out of command-line arguments and persisted process
  metadata;
- stream stdout and stderr incrementally;
- redact configured secret patterns before persistence or display;
- treat stream content as untrusted text and neutralize terminal or markup
  control sequences before display;
- enforce separate and combined console byte limits while reading;
- stop the process when a hard limit is exceeded;
- preserve a bounded diagnostic tail and a stable truncation or limit reason;
- apply a short timeout to control commands and a separate limit to the
  actual role invocation;
- return a structured result rather than interpreting arbitrary prose.

**Domain 2 — agent output.** The actual agent's events and logs live in the
kanban event stream (SQLite), exposed through `hermes kanban tail`, `log`,
`runs`, and `heartbeat` — not in the control processes. Bounding and
redacting this domain is a worker-side and read-side concern:

- read the event stream incrementally with bounded retention;
- apply the same secret-pattern redaction and control-sequence
  neutralization before persistence or display;
- enforce a bounded retained event budget per invocation;
- never reconstruct agent activity from the worker's process environment.

The implementation may choose an asynchronous subprocess library, a small
supervisor process, or another tested mechanism. The required result is
bounded memory use, bounded retained logs, reliable process-tree termination,
and structured diagnostics in both domains.

### 5.4 Isolation of the actual agent

Constraining only the short-lived Hermes command-line process is insufficient.
The kanban dispatcher runs inside the Hermes gateway and spawns workers there;
the actual agent is a gateway-spawned process holding the full profile
environment, persistent memory, tools, and network access of its host.

**Reference topology (A1).** The Phase 0 execution path runs:

1. one dedicated disposable Hermes profile with its own `HERMES_HOME`;
2. one dedicated Hermes gateway instance running **inside the rootless
   container**, subscribed only to the diagnostic board;
3. the diagnostic board, claimed by no other gateway;
4. Method Hub's diagnostic backend outside the container, submitting tasks and
   reading status through the CLI against the shared board.

This makes the isolation enforcement point explicit and testable: the actual
agent and its tool processes execute inside the container, under:

- read-only root filesystem;
- private unprivileged user namespace;
- no unnecessary operating-system capabilities;
- no-new-privileges policy;
- one writable role root;
- read-only, digest-verified declared inputs;
- no direct Method Hub database, formal-storage, or current-project access;
- no ambient host home-directory access (the container carries only the
  disposable `HERMES_HOME`);
- no cross-role or sibling-workspace access;
- no undeclared Unix socket, device, or service access;
- no network by default.

When model or Hermes transport requires network access, allow only the minimum
declared endpoint class (the model provider endpoint). Record the effective
policy without recording credentials.

All role reads should pass through the capability boundary or through an exact
materialized input set produced by that boundary. Path traversal, symbolic
links, hard links, subprocesses, and alternate path spellings must not broaden
access.

An alternative topology is permitted only if it identifies where the actual
agent executes and constrains that execution to the same standard, with tests.
A local container around only the submitting command does not establish agent
isolation. If the worker boundary cannot be verified, the connectivity
checkpoint may pass, but Phase 0 as a whole must remain incomplete.

### 5.5 Workspace and artifact limits

The diagnostic workspace must enforce:

- safe normalized relative output paths;
- an allowlist of expected output locations;
- maximum output-file count;
- maximum size per file;
- maximum total workspace growth;
- configurable allowed file types where applicable;
- rejection of device files, links, sockets, and other unexpected file kinds;
- a final inventory with byte size and digest for every accepted artifact.

Limits must be enforced during or immediately around execution, not only after
unbounded files have filled the disk. The mechanism may use filesystem quotas,
container limits, a monitoring supervisor, or a combination justified by
tests.

Unexpected or oversized output should end the invocation with an exact
operational failure. Retain only the bounded diagnostic material needed to
understand the failure.

Successful outputs remain diagnostic artifacts. They do not become formal
scientific records.

### 5.6 Durable identity and no-duplicate recovery

The invocation lifecycle must preserve one durable identity across Method Hub
and Hermes:

1. Persist launch intent before contacting Hermes.
2. Use a deterministic Hermes idempotency key derived from the invocation
   identity.
3. Persist the external Hermes task ID immediately after creation.
4. Record heartbeats and the last observed external state.
5. Seal one terminal closure after a confirmed terminal outcome.

Introduce the minimum lease or fencing mechanism needed to ensure that only
one Method Hub worker may advance an invocation at a time.

Startup reconciliation must distinguish at least:

- intent persisted, external creation not attempted;
- external creation may have occurred, acknowledgement not persisted;
- external task acknowledged and still running;
- external task terminal, local closure missing;
- local closure already sealed.

**Tested transport decision (A3).** Live Hermes documentation confirms that
repeating task creation with the same idempotency key returns the original
task ID instead of creating a duplicate — **for non-archived tasks**. The
reconciliation rule is therefore:

- For the create-before-acknowledgement window, re-issue creation with the
  deterministic idempotency key and adopt the returned task ID. The 0-pre
  spike must verify this behavior on the supported Hermes version.
- **Archived-task hole:** if the original task was archived (the current
  cancellation mechanism archives), re-creation with the same key may create
  a new task. Recovery must therefore first resolve any task — including
  archived ones — bound to the invocation identity, and must treat a prior
  cancellation record as terminal. A cancelled invocation is never revived by
  reconciliation.
- If the spike shows lookup-by-key and idempotent re-creation are both
  unreliable, the invocation remains unresolved and fenced for operator
  inspection. Recovery must not create another task merely because the
  external ID is missing locally.

The RoleExecutor protocol may be extended if reconciliation by external task
ID alone cannot represent the verified recovery behavior.

Infrastructure recovery may reconnect to the same invocation. It must never
retry the scientific task as a new invocation. A new role call always requires
a new explicit user action in the later research workflow.

### 5.7 Timeout and cancellation

Cancellation is a durable controlled operation, not merely a user-interface
signal.

The cancellation path must:

1. record the cancellation request;
2. fence new work for the invocation;
3. stop the local control process and its descendants when present;
4. request cancellation of the external Hermes task through a mechanism whose
   semantics the 0-pre spike has verified;
5. poll or otherwise verify the external terminal state;
6. record whether termination was confirmed;
7. seal the final diagnostic closure.

Killing the local Hermes command does not prove that an external or daemon-run
agent stopped. Sending an archive or cancel request, or observing an archived
task label, also does not prove termination unless the supported Hermes
contract guarantees that meaning and an integration test verifies it.
Confirmed cancellation requires evidence that the actual worker stopped and
that output writes became quiescent. The final state must distinguish
confirmed cancellation from an unresolved external task.

**Requeue hazard (A4).** Documented dispatcher behavior: when a task exceeds
its runtime cap, the dispatcher SIGTERMs (then SIGKILLs) the worker and
**re-queues the task**. A re-queued task can start a second worker after the
local invocation has already recorded timeout or failure — a duplicate
scientific invocation. The timeout protocol must therefore:

- verify on the supported Hermes version how `--max-runtime`, the dispatcher's
  failure limit, and `--max-retries 0` interact (0-pre spike);
- prevent re-dispatch of a timed-out diagnostic task, or detect and fence the
  re-queued instance before it starts work;
- never treat dispatcher kill-and-requeue as a terminal outcome without
  evidence that no further worker will start.

Timeout uses the same termination protocol. If termination cannot be
confirmed, the interface must report an unresolved operational condition and
block any action that could duplicate or conflict with that task.

### 5.8 Minimal diagnostic interface

Phase 0 needs a small control surface before the first real invocation. It is
not the complete researcher interface planned later.

The interface must show:

- a prominent diagnostic and non-publishing label;
- Hermes preflight checks and disabled reasons (including board hygiene);
- selected disposable profile and non-secret model/provider metadata;
- configured execution limits;
- one explicit start action;
- invocation ID and external task ID when available;
- lifecycle state mapped from the **real kanban status enum** (A5): `triage`,
  `todo`, `ready`, `running`, `blocked`, `done`, `review`, `scheduled`,
  `archived` — with documented Method Hub semantics for each, and no reliance
  on nonexistent `failed`/`cancelled` statuses;
- current activity, heartbeat, and elapsed time;
- bounded and redacted control-process stdout and stderr (Domain 1);
- bounded structured agent events from the kanban event stream — `tail`,
  `log`, `runs`, `heartbeat` (Domain 2) — without inventing streams that
  Hermes does not provide;
- bounded Method Hub system events;
- one cancellation action when cancellation is legal;
- terminal outcome and smallest safe next step;
- diagnostic output inventory and downloads;
- an explicit statement that formal research state did not change.

The backend remains authoritative for eligibility and actions. The frontend
must not infer that a task may start or may be cancelled.

The diagnostic interface must bind to loopback and remain disabled unless an
explicit development setting enables it. Remote use is outside Phase 0.

## 6. Implementation checkpoints

Phase 0 should be delivered in small, reviewable checkpoints.

### Checkpoint 0-pre: Transport reconnaissance spike (A7)

Before any checkpoint code is written, answer the behavioral questions that
shape the design, on a disposable board with tasks parked in a non-dispatching
status (or assigned to a nonexistent profile) so no real agent runs:

1. Idempotent create: does repeating `create` with the same idempotency key
   return the original task ID? Does it still do so after the original task
   is archived? (A3)
2. Requeue: with `--max-runtime` exceeded, does the dispatcher re-queue the
   task, and does `--max-retries 0` prevent a second worker? (A4)
3. Cancellation semantics: what do `archive`, `block`, and `reclaim` each do
   to a task in `ready` and in `running` state? Does any of them stop the
   actual worker process?
4. Event streams: what do `tail`, `log`, `runs`, and `heartbeat` expose, in
   what formats, suitable for bounded incremental reading?
5. Dispatch model: which gateways dispatch which boards, and how is a gateway
   verifiably restricted to (or excluded from) the diagnostic board?
6. Context guards: from which invocation contexts does Hermes accept kanban
   mutations? (Agent child contexts are refused; confirm the backend's
   server-side invocation context is accepted.)

Run the spike as a recorded script from a plain operator shell (not from an
agent session). Publish the findings as a short note under
`architecture/plans/` and cite them in the affected checkpoints.

Gate: every behavioral assumption in Sections 5.6–5.8 cites either spike
evidence or a mock marked "unverified — integration test required."

### Checkpoint 0A: Define the diagnostic boundary

- Define the diagnostic request, result, and stable failure categories.
- Keep it outside scientific submission and publication services.
- Add a feature flag and dedicated diagnostic data root.
- Add tests proving that diagnostic actions cannot call publication code.

Gate: a fake diagnostic invocation completes without changing formal state.

### Checkpoint 0B: Verify Hermes and profiles

- Implement executable or endpoint discovery.
- Establish the supported-version policy.
- Verify board, transport, profile, and required capabilities.
- **Verify and document the worker topology (A1):** where the dispatcher runs,
  where workers are spawned, and at which boundary isolation is enforced.
- **Verify board hygiene (A2):** no gateway other than the designated
  diagnostic gateway can claim the diagnostic board.
- Implement the recorded provisioning procedure for the diagnostic board and
  disposable profile (A8).
- Return structured redacted preflight results.

Gate: valid and invalid configurations are distinguished before task creation,
and the worker-topology note names the isolation enforcement point with test
evidence.

### Checkpoint 0C: Build the bounded supervisor

- Replace inherited environment handling.
- Stream and cap control-process output (Domain 1).
- Add incremental, bounded, redacted reading of the kanban event stream
  (Domain 2).
- Add timeout and process-group termination.
- Add secret redaction and structured failure results.

Gate: infinite output, a hung process, and a secret-canary test remain within
fixed memory, time, and disclosure bounds — in both output domains.

### Checkpoint 0D: Enforce the execution workspace

- Constrain the actual agent and tools under the Section 5.4 topology:
  dedicated disposable profile, containerized diagnostic gateway, single
  diagnostic board.
- Materialize only declared synthetic inputs.
- Enforce write-root, path, network, and artifact quotas.
- Produce the final access and artifact inventories.

Gate: escape and quota tests fail closed, and accepted outputs are complete
and digest-verified.

### Checkpoint 0E: Complete durable supervision

- Persist launch intent and acknowledgement.
- Verify idempotent external creation, including the archived-task rule (A3).
- Prevent or fence dispatcher requeue after runtime-cap expiry (A4).
- Add lease, fencing, heartbeat, and terminal closure.
- Implement confirmed cancellation and startup reconciliation.

Gate: interruption at every launch boundary produces at most one external task
and one terminal local closure; a timed-out task never starts a second worker.

### Checkpoint 0F: Add the diagnostic viewer

- Display preflight, state (real status enum), heartbeat, bounded logs from
  both output domains, outputs, and cancellation.
- Preserve backend-projected actions and stable failure explanations.
- Add browser tests for every terminal and unresolved state.

Gate: a local operator can understand and control the invocation without
opening the database or diagnostic directory.

### Checkpoint 0G: Run real Hermes tests

First run the fixed synthetic task as a disposable connectivity test. Then run
it through the complete isolated, durable execution path.

Gate: the evidence package in Section 8 is complete and formal state is
unchanged.

The first connectivity test may precede completion of rootless containment
only when it uses a disposable host, disposable profile, synthetic inputs, a
quarantined workspace, bounded supervision, and no reachable formal project
state. It is a transport observation, not the Phase 0 exit gate.

## 7. Required acceptance tests

| Test area | Required case | Required result |
|---|---|---|
| Preflight | Hermes absent or unsupported | Launch disabled with a stable reason |
| Preflight | Host gateway can claim the diagnostic board | Launch disabled with a board-contested reason (A2) |
| Profile | Profile missing, inaccessible, or incompatible | No external task created |
| Environment | Secret canaries in unrelated host variables | Canaries absent from child environment, logs, and artifacts |
| Memory | Pre-seeded profile-memory canary | Canary absent unless the exact memory resource was declared |
| Console | Infinite or oversized available log stream | Process stopped within configured memory and byte bounds |
| Agent events | Oversized kanban event stream | Bounded retained budget enforced with stable truncation reason |
| Time | Hung control command or role | Bounded termination protocol begins and outcome is recorded |
| Time | Runtime-cap expiry with dispatcher requeue (A4) | No second worker starts; re-queued task fenced or prevented; invocation recorded once |
| Workspace | Absolute path, traversal, link, socket, or undeclared output | Access or collection rejected without formal effects |
| Storage | Oversized file, too many files, or excess total growth | Execution stopped or output rejected within disk bounds |
| Network | Undeclared destination | Connection denied and attempt recorded without secret data |
| Launch | Crash before external creation | Safe restart without duplicate work |
| Launch | Crash after creation but before local acknowledgement | Original task adopted via idempotency key or marked unresolved, never duplicated (A3) |
| Launch | Reconciliation of an invocation with a prior cancellation record | Cancelled invocation stays terminal; archived-task idempotency hole cannot spawn a new task (A3) |
| Recovery | Restart while external task runs | Same task reconciled using its durable identity |
| Cancellation | Cancel before and after acknowledgement | Exactly one terminal outcome and no surviving task |
| Cancellation | External stop cannot be confirmed | Unresolved state shown and duplicate launch blocked |
| Closure | Malformed or missing declared output | Operational failure with bounded retained diagnostics |
| UI | Refresh, double click, and stale action | No duplicate task and stable current projection |
| Fencing | Two coordinators, lease takeover, then stale-worker resume | Stale token cannot launch, heartbeat, cancel, or close |
| Authority | Formal scientific state before and after every case | Generations, authority journal, current indexes, method records, and receipts are unchanged |

Hermes-specific integration tests must exercise the actual supported Hermes
version. Mocks remain useful for deterministic failure injection but cannot
replace the real success, cancellation, and recovery evidence.

## 8. Required completion evidence

The Phase 0 pull requests must leave a reviewable evidence package containing:

1. Baseline and final architecture, backend, and frontend test results.
2. Supported Hermes and isolation-runtime versions.
3. The 0-pre transport reconnaissance spike note and script.
4. Redacted preflight report, including board hygiene and worker topology.
5. The recorded provisioning procedure for board, disposable profile, and
   container image.
6. Diagnostic request and execution-policy digest.
7. Durable launch intent, external acknowledgement, heartbeat sequence, and
   terminal closure for one successful invocation.
8. Bounded log metadata showing retained bytes and any truncation, for both
   output domains.
9. Input, access, and output inventories with digests.
10. One confirmed cancellation trace.
11. One restart-reconciliation trace from a launch-boundary interruption.
12. One runtime-cap expiry trace proving no second worker started.
13. Test evidence that escape, quota, secret, and duplicate-launch probes fail
    safely.
14. Inventories proving that formal generations, authority events, current
    indexes, method records, and publication receipts did not change.
    Expected diagnostic execution records must be listed separately.
15. A short operator note explaining how to provision, enable, run, inspect,
    cancel, and disable diagnostic execution.

The evidence package must not contain access tokens, model credentials,
unredacted environment values, private profile memory, or unrelated host
paths.

## 9. Exit gate

Phase 0 is complete only when all of the following are true:

- one real Hermes role succeeds through the complete isolated path;
- success, failure, timeout, confirmed cancellation, and unresolved
  termination are represented correctly;
- a runtime-cap expiry never produces a second worker;
- console and artifact growth are bounded while they are produced, in both
  output domains;
- the actual agent execution, not only the submitting command, is confined,
  at the topology boundary documented in Checkpoint 0B;
- the diagnostic board is claimed only by the designated diagnostic gateway;
- restart recovery never creates a second task for the same invocation,
  including across the archived-task idempotency hole;
- no secret appears in logs, task material, artifacts, or evidence;
- the local diagnostic UI exposes enough information to control and diagnose
  the run;
- all required automated tests pass;
- all formal scientific records and authority data remain unchanged, while
  expected diagnostic execution records are complete and accounted for;
- the executor remains disabled for publishable research runs.

Passing the connectivity checkpoint alone is not Phase 0 completion.

## 10. Engineering judgment

### 10.1 Non-negotiable

Programmers must preserve these requirements even if Hermes behaves
differently from current assumptions:

- explicit user action starts the diagnostic;
- Phase 0 cannot publish or update formal scientific state;
- the actual agent and tools are constrained at a documented topology
  boundary;
- ambient host environment, project storage, memory, credentials, and network
  access are prohibited;
- console output and files are bounded while they are produced;
- cancellation is confirmed rather than inferred;
- ambiguous recovery never launches a replacement task;
- a runtime-cap expiry never silently re-runs the task;
- scientific retry and phase progression remain user decisions;
- logs and diagnostic artifacts never establish scientific authority.

### 10.2 Adaptable

Programmers may choose, based on verified Hermes behavior:

- Hermes CLI or a supported API transport;
- the rootless OCI runtime;
- polling, server-sent events, or another bounded progress transport;
- internal diagnostic-log representation;
- exact initial time, byte, file, and retention limits;
- lease duration and heartbeat interval;
- whether a disposable connectivity test and isolated execution test use the
  same profile;
- an alternative worker topology, provided it names and tests the isolation
  enforcement point for the actual agent;
- internal module boundaries.

Any alternative must produce the same observable safety and recovery evidence.
Configuration values should be explicit and testable, not hidden constants.

### 10.3 Requires an architecture decision

Stop and create or update an architecture decision before implementation if
the actual situation would require:

- allowing Hermes direct access to formal storage;
- weakening the rootless or capability boundary;
- treating unconfirmed cancellation as terminal;
- accepting dispatcher requeue of a timed-out task as equivalent to one
  invocation;
- retrying a scientific invocation automatically;
- accepting duplicate external tasks;
- exposing the diagnostic endpoint remotely;
- changing the RoleExecutor authority boundary;
- allowing diagnostic output into scientific publication;
- changing persisted production run states or their meaning.

## 11. Recommended code areas

The exact decomposition is adaptable, but likely work areas include:

- [executor protocol](../../src/method_hub/executors/protocol.py);
- [Hermes adapter](../../src/method_hub/executors/hermes.py);
- [execution observer](../../src/method_hub/harness/execution_observer.py);
- [role execution service](../../src/method_hub/harness/role_execution.py);
- executor configuration and application startup;
- diagnostic application service and API transport;
- diagnostic status and log components in the Web interface;
- new Hermes supervisor, containment, provisioning, and integration-test
  modules.

Do not add publication access to an executor. Reuse the existing narrow
executor protocol where possible, and change it only when the required durable
or bounded behavior cannot be represented.

## 12. Phase handoff

After Phase 0, the system will know how to execute one real role safely, but
it will still lack authority to treat that output as formal research.

The next phase must bind the user's reviewed command to the exact formal
inputs, method identity, phase contract, profile, soul, instructions, skills,
tools, knowledge resources, memory policy, and execution policy before any
scientific role starts.

Two handoff notes for the completion-plan sequence:

1. The Operational Completion Plan should record that Phase 0 delivered WP1
   slices 5 and 6 ahead of WP0, with a link to this document and its evidence
   package.
2. Independent of Phase 0, the `disabled`-executor configuration currently
   accepts run commands that can never execute (a run row is created and
   stalls in `created`). WP0/WP3 should make launch eligibility fail visibly
   instead; Phase 0's preflight-and-disabled-reason pattern is the model.
