# Next Work Block: Complete the Non-Publishing Hermes Diagnostic Lane

Status: Historical safety baseline. OCI containment is deferred for Version 1.

Current work order:

- [Trusted Local Hermes Execution Closure](next-block-local-hermes-execution-closure.md)

Prepared: 2026-08-03


The non-publishing, cancellation, reconciliation, bounded-log, and evidence
principles remain useful. Its OCI containment assumptions and implementation
order are superseded for Version 1 by ADR-012 and the trusted-local plan. Do not
implement this file as the current work order.
Related plans:

- [End-to-End OCI Diagnostic Closure](next-block-end-to-end-oci-diagnostic-closure.md)
- [Headless Hermes Runtime Closure](next-block-headless-hermes-runtime-closure.md)
- [Hermes-Specific Diagnostic Revision](revised-diagnostic-lane-plan.md)
- [Phase 0: Safe Hermes Execution](phase-0-safe-hermes-execution.md)
- [Operational Completion Plan](operational-completion-plan.md)
- [Completed Hermes Transport Findings](completed/phase-0-spike-findings.md)

## 1. Target goal

Deliver one trustworthy Linux diagnostic path in which a researcher can
explicitly start a fixed synthetic Hermes task, inspect bounded progress and
logs, cancel it, restart Method Hub, and reconcile the same external execution.

The actual Hermes agent and its tools must run inside the declared containment
boundary. The diagnostic must never create or replace a formal research record.

This block is complete only when the system proves all of the following:

1. One user action creates at most one external execution.
2. The external identity names the actual agent execution, not only a launcher.
3. Timeout and cancellation end the process tree and verify that output writes
   have stopped.
4. Application restart adopts or closes the same execution and never starts a
   replacement.
5. Inputs, outputs, logs, environment, network, processes, and storage remain
   within explicit limits.
6. A local user can understand the state and the smallest safe next action from
   the Web interface.
7. Formal generations, authority events, current indexes, method records, and
   publication receipts remain unchanged.

This is a non-publishing diagnostic gate. Passing it does not enable Phase 1
through Phase 5 with real Hermes output.

## 2. Why this block is next

The current code proves that Method Hub can reach Hermes and that one synthetic
task can finish through the development Kanban adapter. It does not yet prove a
reliable execution boundary.

The main unresolved facts are operational rather than scientific:

- the Bubblewrap prototype acknowledges a deterministic label rather than the
  operating-system process or container identity;
- cancellation and reconciliation therefore cannot identify the running work;
- Kanban `archived` status does not prove that a gateway worker stopped;
- output is still buffered without an in-process hard bound in some paths;
- the entire host Hermes home can be mounted instead of one selected profile;
- network allowlist mode currently shares the complete host network;
- capability-broker paths are not the paths rendered into the task brief;
- invocation fencing is process-local and does not survive two coordinators;
- there is no researcher-facing diagnostic log and control view;
- the new POSIX process tests fail on Windows instead of being qualified as
  Linux-only integration tests.

Until these behaviors are corrected, a successful role call is connectivity
evidence, not safe harness execution.

## 3. Decisions for this block

### 3.1 Keep the lane diagnostic and user-started

Use a separate diagnostic command and data namespace. The action must require
one explicit user click. Completion must not start another task, another role,
or a scientific phase.

The diagnostic service must not call submission, validation, promotion, or
publication services. It may reuse executor and observer interfaces.

### 3.2 Use one-shot Hermes execution inside rootless OCI

The recommended Linux reference implementation is one synchronous Hermes
one-shot process, such as `hermes -z`, inside one rootless OCI container.

This is preferable to submitting a Kanban item from inside a sandbox because
the Kanban gateway spawns the actual worker elsewhere. With one-shot execution,
the container is the agent boundary and its durable container ID can support
truthful cancellation and restart reconciliation.

Use rootless Podman or another OCI runtime that provides an inspectable durable
container ID. A different runtime is acceptable only if it satisfies the same
identity, isolation, termination, and restart tests. Record the choice in an
architecture decision before implementation if it changes the existing
execution semantics.

The existing `hermes_kanban` adapter remains a development connectivity tool.
It is not the completion path for this block.

### 3.3 Keep formal execution disabled

The current `oci` setting must not expose the incomplete Bubblewrap prototype
as a production executor. Until this block passes, configuration should either
reject that setting or label it diagnostic-only and make it unreachable from
scientific run commands.

### 3.4 Support Linux first

Run real containment and process tests on supported Linux. Cross-platform unit
tests should remain green. Windows should report that the diagnostic runtime is
unsupported or experimental, and POSIX-specific tests should skip with an
explicit reason instead of failing.

### 3.5 Use a separate diagnostic persistence model

Create dedicated diagnostic invocation, event, artifact, lease, and fence
records. Do not insert diagnostic work into scientific `runs` or depend on a
foreign key to a project run. Reuse stable execution value types and observer
interfaces where useful, but keep diagnostic authority and scientific authority
physically and semantically separate.

The diagnostic persistence model must define migrations, state transitions,
startup reconciliation, retention metadata, and idempotent cleanup. Its records
may prove execution behavior, but they can never satisfy a phase prerequisite
or become a publication input.

Gate: deleting all disposable diagnostic data leaves scientific runs, formal
records, authority journals, and current indexes unchanged.

## 4. Work already completed

Reuse rather than repeat these verified pieces:

- Hermes v0.19.0 status and retry reconnaissance;
- `done`, `blocked`, and `archived` transport mapping;
- one-attempt Kanban behavior through `--max-retries 1` for the development
  adapter;
- environment allowlisting and diagnostic redaction patterns;
- profile existence preflight for the development adapter;
- an initial capped control-command capture foundation;
- one successful synthetic theorist connectivity test;
- existing launch-intent, acknowledgement, heartbeat, closure, cancellation,
  and recovery records in the harness;
- the executor protocol and execution observer interfaces.

These are inputs to this block. They do not by themselves satisfy its exit
gate.

## 5. Required deliverables

### 5.0 Verify one-shot Hermes semantics before implementation

Run a recorded disposable-host spike for the exact supported Hermes one-shot
interface. Verify:

- the command or API and its versioned exit-status contract;
- exact profile selection and the minimum sanitized profile-bundle layout;
- task-brief delivery by mounted file or standard input;
- workspace and output-path behavior;
- declared skill and tool loading without ambient resources;
- model/provider configuration and minimum credential injection;
- signal handling, descendant-process behavior, and output quiescence;
- stdout, stderr, structured event, and artifact semantics.

Store the script and redacted findings in the repository. A one-shot behavior
that has not been observed must remain explicitly unverified and cannot be an
implementation assumption.

Gate: every runtime assumption used in Sections 5.2 through 5.7 cites the
one-shot spike, supported upstream documentation, or a test marked as still
blocking.

### 5.1 Align the specification and feature gates

1. Record the one-shot OCI decision and distinguish it from the Kanban
   development transport.
2. Define typed diagnostic request, preflight result, progress, terminal
   result, and stable failure categories.
3. Define the exact diagnostic task version, input digest, output contract, and
   execution-policy digest.
4. Add a dedicated diagnostic feature flag and data root.
5. Make production and scientific launch eligibility fail closed when the only
   configured executor is incomplete or diagnostic-only.
6. Update the Phase 0 plan and architecture traceability if the selected
   runtime changes an accepted execution invariant.

Gate: a fake diagnostic invocation completes without calling any publication
service or changing formal state.

### 5.2 Implement fail-closed preflight and reproducible provisioning

Preflight must verify before launch:

- supported Linux and rootless runtime;
- pinned runtime image digest and Hermes version;
- selected disposable profile and its non-secret model/provider metadata;
- the exact profile, soul, instruction, skill, tool, knowledge, and memory
  resources that will be materialized;
- a digest for the sanitized profile bundle that excludes ambient state;
- provider credential availability without displaying or persisting its value;
- container creation, inspection, stop, kill, and log capabilities;
- writable diagnostic root, free space, and configured quotas;
- effective network policy and provider-only egress mechanism;
- no access path to a real Method Hub project or formal storage.

Provide a recorded setup procedure for the image and disposable profile. A
resource that only exists because it was manually created on one developer
machine does not pass preflight.

Gate: every missing or unsafe prerequisite disables Start with one stable,
researcher-readable reason. No container is created by preflight.

### 5.3 Replace the prototype with a truthful execution identity

For each diagnostic invocation:

1. Persist launch intent before contacting the runtime.
2. Create the container with a deterministic invocation label or name.
3. Persist the actual OCI container ID immediately after creation.
4. Immediately before start, inspect and verify the realized image, profile
   bundle, runtime security, network, and execution-policy digests.
5. Start the existing container only after acknowledgement is durable and the
   realized-policy check passes.
6. Stream its state and logs through the observer.
7. Seal exactly one terminal diagnostic closure.

`external_execution_id` must be the identifier accepted by runtime inspect,
stop, kill, logs, and removal commands. Do not derive cancellation from a
Method Hub execution ID that the operating system cannot resolve.

If the application crashes between create and acknowledgement, recovery must
locate the existing container by its deterministic invocation label. If its
identity is ambiguous, mark the invocation unresolved and require operator
inspection. Never create another container merely because acknowledgement is
missing.

Do not configure automatic container removal. Retain the container until its
closure and evidence are durable. Cleanup after closure must be idempotent and
must obey the diagnostic retention policy.

Gate: failure injection at every launch boundary produces at most one
container and either one terminal local closure or one explicitly unresolved,
fenced record.

### 5.4 Enforce the role capability boundary

Construct a minimal container-local runtime bundle:

- a read-only pinned image;
- an allowlisted profile bundle containing only the selected profile and
  declared resources, excluding memory, history, caches, undeclared skills,
  logs, credential files, and provider secrets;
- read-only, digest-verified synthetic inputs;
- one separate writable output directory;
- a read-only task brief file or standard input, not task text in the process
  command line;
- no host Hermes home, Kanban boards, project directory, database, artifact
  store, user home, Docker socket, or unrelated credentials.

Render the task brief with the capability broker's container-visible paths.
Do not materialize inputs and then tell Hermes to read the original host paths.
Make input materialization read-only to the role and keep the access inventory
outside the role-writable output tree.

Add a pre-seeded memory-canary test. The canary must remain unavailable unless
the exact memory resource was explicitly declared for the diagnostic task.

Gate: path traversal, symbolic-link, hard-link, alternate-path, subprocess,
and direct-storage probes cannot broaden access.

### 5.5 Enforce provider-only networking and secret handling

The real model call requires network access, so `network none` cannot be the
only successful configuration. Use an egress boundary in which:

- direct container egress is blocked;
- only the declared provider endpoint is reachable through an enforced proxy
  or equivalent policy;
- denied destinations are recorded without request secrets;
- the minimum credential is injected at runtime;
- credentials never appear in the command line, image, manifest, task brief,
  logs, diagnostic artifacts, API response, or evidence package.

Do not implement an allowlist by sharing the host network namespace. If the
chosen rootless runtime cannot prove provider-only egress, stop and record the
limitation rather than weakening the policy silently.

Gate: the provider call succeeds, an undeclared endpoint fails, and secret
canaries are absent from every persisted and displayed surface.

### 5.6 Bound processes, logs, and workspace growth during execution

Enforce limits while work is running:

- wall time and cancellation grace period;
- CPU, memory, process count, and open-file limits;
- stdout, stderr, and retained structured event bytes;
- maximum file count, per-file size, and total workspace growth;
- allowed output paths and file kinds;
- final accepted-output inventory with digest and byte length.

Also define aggregate limits across repeated diagnostics: total diagnostic-root
bytes, retained invocation count, log retention, artifact retention, stopped
container retention, and safe cleanup frequency. Cleanup may remove only
expired disposable diagnostic material after closure and evidence sealing. It
must never delete active or unresolved invocations and must never touch formal
research storage.

Read stdout and stderr incrementally. Do not call `communicate()` and truncate
only after unbounded bytes have entered memory. After the byte limit is reached,
retain a bounded tail and record a stable truncation reason.

On timeout, request graceful stop, wait for the fixed grace interval, issue a
hard kill if needed, inspect the runtime until the container is terminal, and
verify that output size and modification times remain quiescent. If quiescence
cannot be confirmed, report an unresolved termination and keep duplicate launch
fenced.

Gate: infinite output, a hung process, a process tree, and workspace-filling
fixtures remain within configured memory, time, process, and disk bounds.

### 5.7 Make reconciliation and fencing durable

Use the dedicated durable diagnostic execution records as the source of truth.
Add a monotone fencing token and time-bounded coordinator lease in durable storage,
not only in process-local dictionaries.

Every launch, heartbeat, cancel, terminal observation, and closure must reject
a stale token. Startup reconciliation must inspect the exact recorded container
and choose one of these outcomes:

- still running: adopt and continue observing it;
- terminal with valid outputs: seal the recorded result;
- terminal with invalid or missing outputs: seal failure;
- absent after acknowledged creation: seal failure, do not recreate;
- identity uncertain: mark unresolved, do not recreate.

`unresolved` is a fenced, nonterminal operational state. It is not equivalent
to failed or cancelled. Only a later reconciliation that proves the same
container terminal and its writes quiescent, or a reasoned administrator action
with audit evidence, may close it.

Gate: two coordinators and a lease takeover cannot launch, cancel, heartbeat,
or close the same invocation from a stale owner.

### 5.8 Add the local diagnostic interface

Add a small loopback-only diagnostic view. It should show:

- a prominent non-publishing label;
- preflight checks and disabled reasons;
- disposable profile and non-secret provider metadata;
- configured limits and effective network policy;
- one Start action;
- Method Hub invocation ID and actual container ID;
- lifecycle state, heartbeat, elapsed time, and stale-activity warning;
- bounded redacted stdout, stderr, and structured events;
- Cancel only while cancellation is legal;
- terminal result, termination confidence, and smallest safe next action;
- output inventory and downloads;
- confirmation that formal scientific state was unchanged.

The backend determines available actions. Refresh, double click, or a stale
browser action must not create another execution.

Gate: a researcher can start, monitor, cancel, refresh, and diagnose the
synthetic task without opening the database or diagnostic directory.

## 6. Suggested implementation sequence

Keep the work reviewable through six checkpoints:

1. **One-shot spike:** verify and record the exact Hermes runtime semantics.
2. **Contract, persistence, and gating:** align the topology decision,
   diagnostic types and tables, preflight, settings, and production-disable
   behavior.
3. **Runtime identity:** implement rootless OCI create, acknowledge, start,
   inspect, bounded log streaming, stop, kill, and terminal collection.
4. **Containment:** wire exact capability paths, sanitized profile resources,
   provider-only egress, secrets, quotas, and escape tests.
5. **Durability:** add database-backed lease and fencing, restart adoption,
   unresolved termination, retention, and launch-boundary failure injection.
6. **Researcher inspection:** add the loopback diagnostic view, run the real
   synthetic task, and assemble the completion evidence.

Do not combine scientific output adapters, reviewed-basis repair, or real phase
pilots into these changes. They have separate acceptance gates.

## 7. Required test matrix

| Area | Required case | Required result |
|---|---|---|
| One-shot spike | Any required behavior remains unverified | Implementation gate remains blocked and the assumption is labeled explicitly |
| Preflight | Realized image, profile, security, network, or execution digest differs | Container is not started |
| Gating | Diagnostic executor configured while a scientific phase is viewed | No Phase 1 through Phase 5 action is enabled and no scientific run can be created |
| Preflight | Runtime, image, profile, credential, proxy, or quota support missing | Start disabled before container creation |
| Launch | Crash before create | Restart creates one container |
| Launch | Crash after create but before acknowledgement | Existing container adopted by deterministic label |
| Launch | Crash after durable acknowledgement but before start | Same created container is inspected, policy-checked, and started at most once |
| Launch | Repeated request or double click | Original invocation returned, no duplicate container |
| Output | Infinite stdout or stderr | Memory and retained bytes stay bounded |
| Time | Hung process ignores graceful stop | Hard kill occurs and termination is verified |
| Process | Agent launches descendants | Entire container process set terminates |
| Cancellation | Cancel while starting or running | One terminal result, no surviving work or writes |
| Cancellation | Runtime inspection or output-quiescence check fails | Invocation remains unresolved, fenced, and nonterminal |
| Recovery | Application restarts while container runs | Same container is reconciled |
| Recovery | Acknowledged container is absent | Failure or unresolved state, never replacement work |
| Recovery | Container exists in created but not started state | Same container is reconciled; no replacement is created |
| Fencing | Two coordinators and lease takeover | Stale coordinator can no longer mutate execution |
| Filesystem | Host path, database, home, link, device, or socket probe | Access denied and recorded safely |
| Profile | Pre-seeded memory, cache, history, undeclared skill, or credential canary | Canary is unavailable inside the container |
| Workspace | Oversized file, too many files, or excessive growth | Limit enforced before disk exhaustion |
| Retention | Repeated diagnostics exceed aggregate limits | Only expired closed diagnostic material is cleaned; active, unresolved, and formal data remain |
| Cleanup | Cleanup repeats after durable closure | Operation is idempotent and retained evidence remains until expiry |
| Network | Provider endpoint | Model request succeeds through declared boundary |
| Network | Undeclared endpoint | Connection denied and denial recorded |
| Secrets | Canary in provider credential and host environment | Canary absent from every persisted or displayed surface |
| UI | Refresh, stale action, and cancellation race | Authoritative state remains consistent and no duplicate starts |
| Authority | Formal-state inventory before and after each case | No formal scientific change |
| Platform | Windows test run | Portable tests pass; Linux-only tests skip explicitly |

Mocks may cover deterministic failure injection, but they do not replace real
Linux runtime, cancellation, restart, containment, and provider-egress tests.

## 8. Required completion evidence

Store a small, redacted evidence package containing:

1. supported Linux, OCI runtime, image digest, and Hermes versions;
2. the recorded one-shot spike script and redacted findings;
3. reproducible image and sanitized disposable-profile provisioning instructions;
4. diagnostic persistence schema, migration, and state-transition evidence;
5. preflight report with no secret values;
6. diagnostic request, profile-bundle, network, and execution-policy digests;
7. one realized-policy mismatch trace proving the container did not start;
8. launch intent, actual container acknowledgement, heartbeats, and terminal
   closure for one successful real invocation;
9. one confirmed cancellation trace, including hard-kill fallback testing;
10. one unresolved-termination trace that remains fenced and nonterminal;
11. one application-restart trace that adopts the same container;
12. launch-boundary crash traces proving no duplicate container;
13. bounded log, process, input, access, output, and quota inventories;
14. aggregate-retention and idempotent-cleanup evidence;
15. network allow and deny results plus the secret-scan result;
16. formal-state and scientific-action inventories proving no scientific
    authority or eligibility change;
17. architecture, backend, frontend, and Linux integration test results.

Do not store model credentials, raw environment dumps, private profile memory,
or unrelated host paths in the evidence package.

## 9. Exit gate

This block is complete only when one real synthetic Hermes role succeeds
through the rootless one-shot boundary and all required failure cases pass.

In particular:

- one-shot Hermes semantics are established by a recorded spike;
- diagnostic persistence, migrations, reconciliation, and cleanup are separate
  from scientific runs;
- the actual container ID supports launch, inspection, cancellation, and
  recovery;
- realized image, profile, security, network, and execution policies match
  their reviewed digests before start;
- cancellation and timeout verify process termination and output quiescence;
- restart never creates replacement work;
- output and workspace growth are bounded while produced;
- only declared input, profile resources, provider network, and output paths
  are available;
- the diagnostic Web view is sufficient to understand and control the task;
- aggregate retention cannot remove active or unresolved diagnostic evidence;
- formal research state is demonstrably unchanged;
- the diagnostic capability cannot enable or create any Phase 1 through Phase
  5 run;
- scientific executors remain disabled.

A successful connectivity run, passing command-construction tests, an archived
Kanban record, or a clean UI screenshot does not satisfy this gate.

## 10. Work explicitly deferred

The following belong to later blocks:

- complete reviewed-basis sealing and visible pre-launch scientific context;
- actual phase-specific Hermes output adapters and validators;
- formal Phase 1 through Phase 5 execution and publication;
- reproducible production role profiles and reviewer no-memory attestation;
- authentication and remote operation;
- backup, restore, migration, and release packaging;
- native Windows execution qualification.

After this diagnostic gate passes, the next recommended block is exact
reviewed-run basis closure. Production scientific execution must wait until
both gates pass.
