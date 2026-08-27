# Phase 0: Safe Hermes Execution

Status: Active implementation instruction, Revision 3. Exit gate open.

Prepared: 2026-08-03
Revised: 2026-08-04 (Revision 3, trusted local execution topology)

Revision 3 replaces rootless OCI as the Version 1 completion path with trusted
local Hermes execution under ADR-012. The OCI and Kanban material retained
below is historical design and optional future hardening. It is not the current
work order.

Current completion status: Partially implemented. The Phase 0 exit gate remains
open.

## Current implementation checkpoint

As of commit `a08604d`:

- Hermes host one-shot behavior, profile writes, memory, sessions, usage, and
  task delivery have useful observation records;
- profile, runtime-snapshot, lifecycle, lock, validation, and UI scaffolds exist;
- OCI feasibility work exists but is no longer a Version 1 prerequisite; and
- the local scientific run path is not yet composed end to end.

Still required:

- configuration-managed SOUL, skills, role configuration, and library guidance;
- exact per-run profiles built from the role definition and selected current
  project-role memory and session state;
- one supervised local Hermes executor with bounded logs, timeout,
  process-tree cancellation, and restart reconciliation;
- post-quiescence artifact validation and narrow atomic promotion;
- correct persistent, read-only, and fresh-reviewer state behavior; and
- complete researcher-facing configuration, run, log, validation, and state
  controls.

The controlling package is
[Trusted Local Hermes Execution Closure](../next-block-local-hermes-execution-closure.md).

The earlier revisions below remain useful for Hermes behavior and failure cases,
but their OCI topology and exit gates are superseded for Version 1.

## Revision 1 summary

This revision keeps the original plan's scope, checkpoints, and engineering
judgment intact. It incorporates the results of a grounded review that (a)
verified every claim in Section 2 against the current adapter source, and (b)
probed the live Hermes kanban interface for the behavior the original draft
flagged as unverified. The amendments are:

1. **A1 - Worker topology is now a named, gated deliverable.** The kanban
   dispatcher runs inside the Hermes gateway and spawns workers there. A
   container around the submitting CLI therefore isolates nothing. Section 5.4
   now names the reference topology (dedicated disposable profile plus a
   dedicated gateway inside the rootless container, with its own
   `HERMES_HOME`, subscribed only to the diagnostic board) and Checkpoint 0B
   gains an explicit worker-topology gate.
2. **A2 - Board-hygiene preflight.** Kanban boards are shared across every
   profile and gateway. Preflight must prove that no host gateway dispatches
   the diagnostic board; otherwise a host worker with ambient access executes
   the diagnostic task and all isolation evidence is void (Section 5.1,
   Section 7).
3. **A3 - Idempotent create confirmed, with an archived-task hole.** Live
   `--help` text confirms: if a *non-archived* task with the idempotency key
   exists, its ID is returned instead of creating a duplicate. Because
   `archive` is the current cancellation mechanism, a cancel-then-recover race
   can silently create a second task. Section 5.6 now defines the recovery
   rule for this hole.
4. **A4 - `--max-runtime` re-queues the task.** Documented dispatcher
   behavior: on timeout the dispatcher SIGTERMs (then SIGKILLs) the worker
   **and re-queues the task**. The current adapter sets `max-runtime` equal to
   the frozen invocation timeout, so a timed-out role can be killed and then
   run again after the harness has sealed a failure. Section 5.7 and the
   acceptance table now treat requeue prevention as a hard requirement.
5. **A5 - Real status vocabulary.** Live statuses are `{triage, todo, ready,
   running, blocked, done, review, scheduled, archived}`. There is no `failed`
   or `cancelled`; failure surfaces as `blocked` via the circuit breaker. The
   diagnostic state model (Section 5.8) must be built on the real enum.
6. **A6 - Two output domains separated.** Control-process streams (short-lived
   CLI calls) and agent output (the kanban event stream in SQLite) are
   different mechanisms with different bounding strategies (Section 5.3). The
   transport does expose structured agent events - `hermes kanban tail`,
   `log`, `runs`, `heartbeat` - so the diagnostic viewer must not invent
   streams (Section 5.8).
7. **A7 - New Checkpoint 0-pre: transport reconnaissance spike.** The five
   open behavioral questions that shape Checkpoints 0B/0D/0E are answered by a
   scripted, disposable-board spike before checkpoint code is written
   (Section 6). Note: Hermes refuses kanban mutations from delegated agent
   child contexts; the spike must run from a plain operator shell, and the
   backend's CLI invocation context must be verified for the same guard.
8. **A8 - Provisioning repeatability.** The current adapter assumes a board
   named `model-forge` and four role profiles with no in-repo provisioning.
   Phase 0 diagnostic resources (board, profile, container image) must be
   created by a recorded, repeatable procedure - not unrecorded host state
   (Section 4, Section 5.1). This preserves the future WP7 stop-ship
   condition on developer-machine state.

Items A3, A4, and A1 are blocking amendments: they change the recovery and
isolation design, not just its documentation.

---

## 1. Target goal

Phase 0 must demonstrate that Model Forge can execute one real Hermes role
through a bounded, observable, cancellable, and recoverable execution path.

The role works only in a disposable diagnostic workspace. Its output must not
enter the formal records, authority journal, current index, method catalog, or
publication path of any research project.

Phase 0 is complete only when:

1. Model Forge verifies the actual Hermes installation and selected profile
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

The following description records the pre-fb326de state of the
[Hermes executor](../../../src/model_forge/executors/hermes.py). It is retained as
historical rationale for Revision 1. The current implementation checkpoint at
the start of this plan supersedes it.

At that time, the adapter created a Hermes task with an idempotency key, polled
task status, reported heartbeats, applied elapsed-time limits, and requested
cancellation. It was not the supported execution boundary. The Revision 1
findings below were verified against that source state:

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
- the adapter assumes a board named `model-forge` and four role profiles that
  no in-repo procedure provisions (see A8).

Phase 0 now uses these findings to strengthen the shared executor boundary
through the one-shot OCI diagnostic path in Section 5.4. It must reuse the
execution, cancellation, and recovery semantics defined by the
[run harness](../../design/02-run-harness.md) and the isolation rules in the
[role and context contract](../../design/08-role-context-and-communication.md), while
remaining outside the scientific run, submission, and publication lifecycle.
Its tests must follow the [validation strategy](../../design/05-validation-strategy.md).

The active [Operational Completion Plan](operational-completion-plan.md)
continues to define the production sequence. Phase 0 is a non-publishing
diagnostic program and therefore does not weaken the requirement that the
reviewed scientific basis be sealed before any Hermes output can receive
formal authority. The completion plan records this diagnostic exception as its
first recommended implementation slice and links back to the same bounded work
package. WP0 remains a hard gate for any scientific Hermes run or formal
publication.

## 3. Scope

### 3.1 Included

Phase 0 includes:

- Hermes one-shot interface, version, rootless runtime, pinned image, and
  sanitized profile-bundle verification;
- a dedicated diagnostic invocation path;
- bounded process supervision;
- environment and credential minimization;
- workspace and capability isolation;
- console-log and artifact limits;
- durable external-execution identity;
- heartbeat, timeout, cancellation, and startup reconciliation;
- a minimal diagnostic status and log viewer;
- recorded, repeatable provisioning of the pinned image, sanitized disposable
  profile bundle, and provider-only network boundary;
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
   mount a real Model Forge project.
6. Record a digest or equivalent inventory of formal test-project state before
   any real invocation so unchanged state can be demonstrated afterward.
7. Confirm that credentials required to reach Hermes or its model provider can
   be injected narrowly. They must not be copied into task briefs, manifests,
   logs, artifacts, or diagnostic reports.
8. Provision the pinned rootless image and sanitized disposable profile bundle
   through a recorded procedure.
9. Retain the completed Kanban transport findings as Track A evidence, then run
   the new one-shot Hermes semantics spike required by the next work block.
   Completion-path code may not assume behavior that the one-shot spike has not
   confirmed.

If a safe disposable profile or isolated test host is unavailable,
implementation may proceed with mocks, but no real Hermes task should be
launched.

## 5. Required system behavior

### 5.1 Hermes preflight

Preflight must run before a task is created. It should report a typed,
researcher-readable result for each required check:

- rootless OCI runtime and Hermes one-shot interface found;
- Hermes version supported;
- pinned image digest and runtime security profile match configuration;
- selected sanitized profile bundle exists, is usable, and matches its digest;
- model and provider configuration is present without displaying secrets;
- runtime create, label lookup, start, inspect, logs, stop, kill, and cleanup
  capabilities are available;
- the one-shot task-brief, workspace, profile, output, signal, and exit
  semantics match the recorded spike;
- the realized network and execution policies match their reviewed digests;
- diagnostic workspace permissions and free space are adequate;
- isolation runtime and capability broker are available;
- configured limits are internally consistent.

Preflight must fail closed. A warning may describe an optional capability, but
a missing safety capability must disable the diagnostic launch action.

Use stable error categories such as unsupported version, missing profile,
unsupported runtime or one-shot interface, unsafe workspace, missing
isolation, policy-digest mismatch, unavailable provider boundary, or invalid
limits. Exact identifiers may follow the existing error-model conventions.

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

**Domain 1 - runtime control processes.** Short-lived OCI invocations for
container create, start, inspect, logs, stop, kill, and cleanup. Replace
unbounded command collection with a supervisor that
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

**Domain 2 - one-shot agent output.** The actual Hermes process runs inside the
container. Its stdout, stderr, artifacts, and any structured events established
by the one-shot spike are agent output. Do not assume that Kanban `tail`, `log`,
`runs`, or `heartbeat` exists in the one-shot path. Bounding and redacting this
domain is a runtime-stream and artifact concern:

- read the event stream incrementally with bounded retention;
- apply the same secret-pattern redaction and control-sequence
  neutralization before persistence or display;
- enforce a bounded retained event budget per invocation;
- never reconstruct agent activity from the process environment or undeclared files.

The implementation may choose an asynchronous subprocess library, a small
supervisor process, or another tested mechanism. The required result is
bounded memory use, bounded retained logs, reliable process-tree termination,
and structured diagnostics in both domains.

### 5.4 Isolation of the actual agent

Constraining only the short-lived Hermes command-line process is insufficient.
The kanban dispatcher runs inside the Hermes gateway and spawns workers there;
the actual agent is a gateway-spawned process holding the full profile
environment, persistent memory, tools, and network access of its host.

**Controlling completion topology.** The remaining Phase 0 implementation uses
one synchronous Hermes one-shot process inside one rootless OCI container. The
container process is the actual agent boundary. Model Forge persists the real
container ID and uses runtime create, start, inspect, logs, stop, and kill
operations for supervision. No Kanban gateway or host dispatcher participates
in the completion path.

Before implementation, verify the exact supported one-shot interface, profile
selection, task-brief delivery, workspace behavior, output and exit semantics,
tool loading, provider configuration, and signal handling through the recorded
spike required by the
[next work block](next-block-headless-hermes-runtime-closure.md). Record or update an
architecture decision for this topology.

The Kanban gateway and board findings remain valid for the development Track A
connectivity adapter only. They do not define Phase 0 completion and cannot be
used as evidence of worker termination or containment.

The one-shot container runs under:

- read-only root filesystem;
- private unprivileged user namespace;
- no unnecessary operating-system capabilities;
- no-new-privileges policy;
- one writable role root;
- read-only, digest-verified declared inputs;
- no direct Model Forge database, formal-storage, or current-project access;
- an allowlisted profile bundle containing only the declared profile, soul,
  instruction, skills, tools, knowledge resources, and memory policy;
- no host `HERMES_HOME`, profile memory, history, caches, logs, undeclared
  skills, credential files, or ambient host home-directory access;
- no cross-role or sibling-workspace access;
- no undeclared Unix socket, device, or service access;
- no network by default.

When the model provider requires network access, block direct egress and allow
only the declared provider endpoint through an enforced proxy or equivalent
boundary. Record the effective policy without recording credentials.

All role reads should pass through the capability boundary or through an exact
materialized input set produced by that boundary. Path traversal, symbolic
links, hard links, subprocesses, and alternate path spellings must not broaden
access.

An alternative rootless runtime is permitted only if it preserves an
inspectable durable external identity and the same containment, termination,
and restart semantics. A container around a Kanban submitting command does not
establish agent isolation. If the actual worker boundary cannot be verified,
Phase 0 remains incomplete.

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

The invocation lifecycle must preserve one durable identity across Model Forge
and the rootless OCI runtime:

1. Persist launch intent before contacting the runtime.
2. Create one container under a deterministic invocation label without
   automatic removal.
3. Persist the actual container ID immediately after creation and before start.
4. Verify the realized image, profile bundle, security, network, and execution
   policy digests immediately before start.
5. Record heartbeats and the last observed runtime state.
6. Seal one terminal closure only after a confirmed terminal outcome and
   quiescent output.

Introduce the minimum lease or fencing mechanism needed to ensure that only
one Model Forge worker may advance an invocation at a time.

Startup reconciliation must distinguish at least:

- intent persisted, external creation not attempted;
- external creation may have occurred, acknowledgement not persisted;
- container acknowledged but not started;
- container acknowledged and still running;
- container terminal, local closure missing;
- termination requested but terminal state or quiescence remains unresolved;
- local closure already sealed.

**Completion-path reconciliation decision.** The runtime container ID and its
deterministic invocation label are the only accepted external identities.

- If creation may have occurred before acknowledgement, query by the
  deterministic label and adopt exactly one matching container.
- If the container was durably acknowledged but not started, restart may start
  that same container after the realized-policy check passes.
- If an acknowledged container is absent, seal failure or retain an unresolved
  fenced state. Never create a replacement.
- Do not configure automatic container removal before the local closure is
  durable and its evidence has been collected.
- Cleanup after closure must be idempotent and must not erase retained
  diagnostic evidence before its configured retention boundary.
- If runtime inspection, worker termination, or output quiescence cannot be
  confirmed, keep the invocation in an unresolved, fenced, nonterminal state.

The archived-task idempotency hole remains relevant only to the development
Kanban adapter. It is one reason that adapter cannot establish the Phase 0
completion boundary.

Infrastructure recovery may reconnect to the same invocation. It must never
retry the scientific task as a new invocation. A new role call always requires
a new explicit user action in the later research workflow.

### 5.7 Timeout and cancellation

Cancellation is a durable controlled operation, not merely a user-interface
signal.

The cancellation path must:

1. record the cancellation request;
2. fence new work for the invocation;
3. request graceful stop of the recorded container;
4. wait for the fixed grace interval and hard-kill the same container if it
   remains active;
5. inspect until the container and its process set are terminal;
6. verify that output size and modification times are quiescent;
7. record whether termination and quiescence were confirmed;
8. seal the final diagnostic closure only after confirmation.

If runtime inspection, process termination, or output quiescence cannot be
confirmed, the invocation remains unresolved, fenced, and nonterminal. The UI
must not describe it as successfully cancelled, and recovery must not create a
replacement container.

**Track A transport note.** Kanban archive status does not prove worker
termination. Dispatcher timeout can also requeue a Kanban task. The development
adapter must retain its no-requeue and archived-task protections, but neither
behavior is part of the one-shot completion path. The one-shot timeout protocol
must instead prove that:

- the recorded container cannot restart automatically;
- no second container exists for the invocation label;
- termination and output quiescence satisfy the same cancellation gate.

Timeout uses the same termination protocol. If termination cannot be
confirmed, the interface must report an unresolved operational condition and
block any action that could duplicate or conflict with that invocation.

### 5.8 Minimal diagnostic interface

Phase 0 needs a small control surface before the first real invocation. It is
not the complete researcher interface planned later.

The interface must show:

- a prominent diagnostic and non-publishing label;
- Hermes, rootless-runtime, profile-bundle, network, and quota preflight checks
  with disabled reasons;
- selected disposable profile and non-secret model/provider metadata;
- configured execution limits;
- one explicit start action;
- invocation ID and actual container ID when available;
- typed diagnostic lifecycle state, including preflight blocked, creating,
  acknowledged, running, cancellation requested, terminating, succeeded,
  failed, cancelled, and unresolved;
- current activity, heartbeat, and elapsed time;
- bounded and redacted runtime and Hermes stdout and stderr;
- only the structured runtime or Hermes events verified by the one-shot spike,
  without inventing an event stream;
- bounded Model Forge system events;
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

### Historical Track A transport reconnaissance (A7)

These questions shaped the development Kanban adapter. The completed findings
record is intentionally scoped as exploratory because the required script and
some evidence remain absent. The exploration used a disposable board with
tasks parked in a non-dispatching status, or assigned to a nonexistent
profile, so no real agent ran. It asked:

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
`architecture/plans/completed/` and cite them in the affected checkpoints.

This material is Track A evidence only and does not control Sections 5.4-5.8.

### Checkpoint 0-pre-B: One-shot Hermes semantics spike

Before completion-path code is written, verify the supported one-shot command
or API, exact profile selection, sanitized profile layout, task-brief delivery,
workspace behavior, declared skill and tool loading, provider configuration,
output and exit semantics, signal handling, descendant processes, and output
quiescence.

Run the spike through a recorded script on a disposable Linux host and store a
redacted findings note. Do not infer one-shot behavior from the Kanban adapter.

Gate: every one-shot assumption in Sections 5.4-5.8 cites the spike, supported
upstream documentation, or a blocking integration test.

### Checkpoint 0A: Define the diagnostic boundary

- Define the diagnostic request, result, and stable failure categories.
- Keep it outside scientific submission and publication services.
- Add a feature flag and dedicated diagnostic data root.
- Add tests proving that diagnostic actions cannot call publication code.

Gate: a fake diagnostic invocation completes without changing formal state.

### Checkpoint 0B: Verify Hermes and profiles

- Implement rootless runtime, image, and Hermes one-shot discovery.
- Establish the supported-version policy.
- Verify the sanitized profile bundle and required runtime capabilities.
- Verify and document that the one-shot container is the actual agent and tool
  boundary, with no gateway or host dispatcher involved.
- Verify the realized image, profile, execution, security, and network policy
  digests before start.
- Implement recorded provisioning for the pinned image and disposable profile
  bundle.
- Return structured redacted preflight results.

Gate: valid and invalid configurations are distinguished before container creation,
and the topology note names the isolation enforcement point with test
evidence.

### Checkpoint 0C: Build the bounded supervisor

- Replace inherited environment handling.
- Stream and cap runtime and Hermes stdout and stderr while produced.
- Retain only structured events established by the one-shot spike.
- Add timeout, whole-container termination, and output-quiescence checks.
- Add secret redaction and structured failure results.

Gate: infinite output, a hung process, and a secret-canary test remain within
fixed memory, time, and disclosure bounds.

### Checkpoint 0D: Enforce the execution workspace

- Constrain the actual agent and tools under the Section 5.4 one-shot topology
  using a sanitized allowlisted profile bundle.
- Materialize only declared synthetic inputs.
- Exclude profile memory, history, caches, logs, undeclared resources, and credentials.
- Enforce write-root, path, network, and artifact quotas.
- Produce the final access and artifact inventories.

Gate: escape and quota tests fail closed, and accepted outputs are complete
and digest-verified.

### Checkpoint 0E: Complete durable supervision

- Persist launch intent, deterministic invocation label, container
  acknowledgement, and the actual container ID.
- Reconcile creation-before-acknowledgement by label and
  acknowledgement-before-start by reusing the same policy-checked container.
- Add leases, fencing, heartbeats, and terminal closure.
- Implement confirmed cancellation, startup reconciliation, and output
  quiescence checks.
- Keep ambiguous termination or identity in a fenced unresolved state. Never
  create a replacement container automatically.

Gate: interruption at every launch boundary produces at most one container
and one durable closure or unresolved record. Timeout never restarts or
duplicates the container.

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
| Preflight | Completion path invokes a host gateway or Kanban board | Launch disabled because the actual worker boundary would be outside the recorded container |
| Profile | Profile missing, inaccessible, incompatible, or digest-mismatched | No container created or started |
| Environment | Secret canaries in unrelated host variables | Canaries absent from child environment, logs, and artifacts |
| Memory | Pre-seeded profile-memory canary | Canary absent unless the exact memory resource was declared |
| Console | Infinite or oversized available log stream | Process stopped within configured memory and byte bounds |
| Agent events | Oversized one-shot log or verified event stream | Bounded retained budget enforced with stable truncation reason |
| Time | Hung control command or role | Bounded termination protocol begins and outcome is recorded |
| Time | Runtime-cap expiry | Recorded container is terminated, cannot restart automatically, and no second container exists |
| Workspace | Absolute path, traversal, link, socket, or undeclared output | Access or collection rejected without formal effects |
| Storage | Oversized file, too many files, or excess total growth | Execution stopped or output rejected within disk bounds |
| Network | Undeclared destination | Connection denied and attempt recorded without secret data |
| Launch | Crash before external creation | Safe restart without duplicate work |
| Launch | Crash after creation but before local acknowledgement | Original container adopted by deterministic label or marked unresolved, never duplicated |
| Launch | Crash after acknowledgement but before start | Same created container is policy-checked and started at most once |
| Launch | Reconciliation after a cancellation request | Same container remains fenced; no replacement is created |
| Recovery | Restart while external container runs | Same container reconciled using its durable identity |
| Cancellation | Cancel before and after acknowledgement | One closure or unresolved state, with no unaccounted container, process, or write activity |
| Cancellation | External stop cannot be confirmed | Unresolved state shown and duplicate launch blocked |
| Closure | Malformed or missing declared output | Operational failure with bounded retained diagnostics |
| Retention | Repeated diagnostics exceed aggregate limits | Only expired closed diagnostic material is removed |
| Gating | Diagnostic executor is configured | No scientific phase action or run becomes enabled |
| UI | Refresh, double click, and stale action | No duplicate container and stable current projection |
| Fencing | Two coordinators, lease takeover, then stale-worker resume | Stale token cannot launch, heartbeat, cancel, or close |
| Authority | Formal scientific state before and after every case | Generations, authority journal, current indexes, method records, and receipts are unchanged |

Hermes-specific integration tests must exercise the actual supported Hermes
version. Mocks remain useful for deterministic failure injection but cannot
replace the real success, cancellation, and recovery evidence.

## 8. Required completion evidence

The Phase 0 pull requests must leave a reviewable evidence package containing:

1. Baseline and final architecture, backend, and frontend test results.
2. Supported Hermes and isolation-runtime versions.
3. The archived Track A findings plus the one-shot spike note and script.
4. Redacted preflight report, including runtime, image, profile-bundle, network, and worker-boundary checks.
5. The recorded provisioning procedure for the container image and sanitized
   disposable profile bundle.
6. Diagnostic request, profile-bundle, network, and execution-policy digests.
7. Durable launch intent, actual container acknowledgement, heartbeat sequence,
   and terminal closure for one successful invocation.
8. Bounded log metadata showing retained bytes and any truncation, for both
   output domains.
9. Input, access, and output inventories with digests.
10. One confirmed cancellation trace.
11. One unresolved-termination trace proving that the invocation remains
    fenced and nonterminal.
12. Restart-reconciliation traces for interruption after container creation
    but before acknowledgement, and after acknowledgement but before start.
13. One runtime-cap expiry trace proving that the container did not restart
    and no replacement container was created.
14. Realized-policy mismatch and aggregate-retention traces.
15. Test evidence that escape, quota, secret, and duplicate-launch probes fail
    safely.
16. Inventories proving that formal generations, authority events, current
    indexes, method records, and publication receipts did not change.
    Expected diagnostic execution records must be listed separately.
17. A short operator note explaining how to provision, enable, run, inspect,
    cancel, and disable diagnostic execution.

The evidence package must not contain access tokens, model credentials,
unredacted environment values, private profile memory, or unrelated host
paths.

## 9. Exit gate

Phase 0 is complete only when all of the following are true:

- one real Hermes role succeeds through the complete isolated path;
- success, failure, timeout, confirmed cancellation, and unresolved
  termination are represented correctly;
- a runtime-cap expiry cannot restart the recorded container or create a
  replacement;
- console and artifact growth are bounded while they are produced, in both
  output domains;
- the actual agent execution, not only the submitting command, is confined,
  at the topology boundary documented in Checkpoint 0B;
- the one-shot container is the actual agent and tool boundary, with no host
  gateway or Kanban dispatcher involved;
- the realized image, profile, execution, security, and network policy
  digests are verified before the container starts;
- restart recovery adopts or reuses only the same uniquely identified
  container and never creates a replacement;
- ambiguous identity, termination, or output quiescence remains unresolved,
  fenced, and nonterminal;
- aggregate retention bounds repeated diagnostic use without deleting active
  or unresolved evidence;
- no secret appears in logs, task material, artifacts, or evidence;
- the local diagnostic UI exposes enough information to control and diagnose
  the run;
- all required automated tests pass;
- diagnostic persistence remains separate from scientific run records;
- all formal scientific records and authority data remain unchanged, while
  expected diagnostic execution records are complete and accounted for;
- no scientific phase action is enabled by the diagnostic executor.

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
- internal module boundaries.

Any alternative must produce the same observable safety and recovery evidence.
Configuration values should be explicit and testable, not hidden constants.

### 10.3 Requires an architecture decision

Stop and create or update an architecture decision before implementation if
the actual situation would require:

- changing the one-shot container as the actual agent boundary or adopting an
  alternative worker topology;

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

- [executor protocol](../../../src/model_forge/executors/protocol.py);
- [Hermes adapter](../../../src/model_forge/executors/hermes.py);
- [execution observer](../../../src/model_forge/harness/execution_observer.py);
- [role execution service](../../../src/model_forge/harness/role_execution.py);
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
