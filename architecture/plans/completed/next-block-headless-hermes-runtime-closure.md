# Next Work Block: Headless Hermes Runtime Closure

Status: Deferred OCI hardening reference. Not a Version 1 gate.

Version 1 replacement:

- [Trusted Local Hermes Execution Closure](../next-block-local-hermes-execution-closure.md)

Baseline: commit `009a50a`, audited 2026-08-04.

Optional OCI corrective package:

- [End-to-End OCI Diagnostic Closure](next-block-end-to-end-oci-diagnostic-closure.md)

Related plans:

- [Phase 0: Safe Hermes Execution](phase-0-safe-hermes-execution.md)
- [Hermes-specific diagnostic design](revised-diagnostic-lane-plan.md)
- [Original diagnostic safety baseline](next-block-hermes-diagnostic-closure.md)
- [Completed host observations](spike-report-s5.0.md)

## Current implementation checkpoint

Commit `009a50a` adds a real OCI executor, runtime-profile and memory-policy
scaffolding, richer diagnostic state, output validation, resource-limit
primitives, and useful Linux observations. It also demonstrates that Hermes can
run in a rootless Podman container on the tested host.

Neither H0-A nor H0-B is accepted. The public diagnostic path still uses the
Bubblewrap executor, while the new OCI executor is not composed into that path.
The service and executor disagree about lifecycle ownership, the OCI path
mounts the complete host Hermes home read-write, and container identity,
fencing, cancellation, memory promotion, provider-only networking, secret
delivery, and resource bounds remain incomplete. The committed H0-B tests do
not exercise the complete public path or the required 27-case matrix.

The corrective package above closes these specific integration and evidence
gaps without reducing this parent plan's invariants.

## 1. Target outcome

Deliver one real, headless, non-publishing Hermes diagnostic path on Linux.
A rejected request or failed preflight launches no process. One accepted
start launches exactly one Hermes one-shot invocation through the selected
project-role profile. Every request launches at most one process. The
invocation must remain isolated and bounded, support verified cancellation
and restart reconciliation, and preserve evidence sufficient to explain the
result.

This block does not run a scientific phase. It must not create or publish
formal research artifacts, satisfy phase prerequisites, or trigger another
role. Formal scientific state must be identical before and after the diagnostic.

The block is complete only when real Linux evidence passes. Unit tests and
command-construction tests are necessary but not sufficient.

## 2. Why this gate remains next

The current repository contains more implementation than the original
`eecc6d1` baseline, but the central question is unchanged: can one user-started
Hermes invocation run inside the production OCI boundary and remain isolated,
bounded, cancellable, restart-reconcilable, and unable to alter scientific
state?

The answer is not yet demonstrated. Hand-built Podman commands establish
feasibility, while the actual diagnostic CLI, service, lifecycle store, profile
manager, and OCI executor do not yet operate as one conforming path. Advancing
to UI polish or scientific pilots would hide rather than close that execution
boundary.

The [end-to-end OCI corrective block](next-block-end-to-end-oci-diagnostic-closure.md)
is the implementation package if optional OCI hardening is resumed. This file
then remains the source of truth for that optional evidence standard.

## 3. Fixed architectural decisions

### 3.1 Non-publishing authority

The diagnostic lane has its own composition root:

```text
Diagnostic command or internal service
  DiagnosticService
    DiagnosticStore
    ProjectProfileManager
    OneShotDiagnosticExecutor
      RuntimeAdapter
      BoundedSupervisor
```

The scientific `RunCoordinator`, `HarnessExecutionServices`, and
`RoleLifecycleService` cannot select this executor. Configuration must reject
`oneshot` as a scientific executor kind. A diagnostic has no method-phase,
publication, prerequisite, branch, or role-chaining capability.

### 3.2 Controlled operation

One accepted request creates at most one external execution. Duplicate
submission is idempotent. Timeout, cancellation, coordinator restart, stale
lease, missing process, and ambiguous evidence never launch a replacement
automatically.

### 3.3 Scientific authority and Hermes memory

Formal Method Hub records remain authoritative. Hermes memory is
supplementary working context and must be researcher-visible and
reconstructible. No assumption, method definition, result, conclusion, or
user decision may exist only in memory.

[ADR-011](../../decisions/ADR-011-per-project-memory-model.md) accepts the
`persistent`, `read_only`, and `ephemeral` runtime policy for this diagnostic
lane only. Before implementation relies on it, align the diagnostic schemas,
examples, digest contracts, and traceability; retain reconstructible before and
runtime-after snapshots; and prove the policy, retention, user-operation, and
reviewer-ephemerality scenarios.

The existing formal role-memory contract remains authoritative. Until this
non-publishing gate passes and a later ADR expands scope, diagnostic runtime
memory cannot become load-bearing for scientific execution.

### 3.4 Runtime boundary and named gates

Linux is the supported environment for this block. ADR-004 requires rootless
OCI for production CLI roles. Rootless Podman is therefore the reference
production boundary.

This block has two named gates. Both remain open at the `009a50a` checkpoint:

1. **H0-A, Bubblewrap diagnostic subgate.** Current Bubblewrap observations are
   partial containment evidence on the verified host. They do not close Phase
   0, WP1, or this work block.
2. **H0-B, rootless OCI runtime gate.** Current Podman observations establish
   feasibility, but the complete evidence must be repeated through the public
   diagnostic path and ADR-004 production boundary. Only an accepted H0-B gate
   completes this headless runtime block.

Bubblewrap may be used first when it shortens feedback. A different
production boundary requires a new or superseding architecture decision.

### 3.5 Kanban relationship

Kanban remains a development connectivity path. It does not count as
one-shot containment evidence and cannot publish scientific artifacts during
this block. If Kanban and one-shot can touch the same project profile, they
must share the same durable profile mutex. Otherwise project profiles must be
unavailable to Kanban until that mutex is enforced.

## 4. Work packages

Complete these in order. A later package may begin early for exploration, but
its exit cannot be accepted before its dependencies pass.

### H0.1 Decision and contract alignment

Goal: make the authority, memory, profile, and diagnostic contracts explicit
before implementation depends on them.

Work:

1. Add or accept the memory/session ADR described in Section 3.3.
2. Update architecture 08 and the role-profile schema only as authorized by
   that ADR.
3. Define a versioned `ProfileManifest` containing:
   - exact project ID and Method Hub role;
   - mapped Hermes profile name;
   - SOUL, configuration, and skill digests;
   - exact skill names and versions;
   - memory policy and policy version;
   - profile revision and provisioning provenance; and
   - runtime compatibility requirements.
4. Define a versioned diagnostic request, result, process-identity, memory
   snapshot, usage, and state-transition contract.
5. Define the fixed synthetic task and its output contract. It must produce a
   small deterministic file that can be validated independently of prose.

Acceptance:

- contracts have examples and rejecting validators;
- the reviewer mapping and default memory policy are unambiguous;
- no project research question or mutable method state is stored in SOUL.md;
- session browsing is either disabled or exactly reconstructible; and
- architecture validation passes.

### H0.2 Safety gating and application composition

Goal: make accidental scientific use impossible.

Work:

1. Remove `oneshot` from scientific executor settings or reject it during
   scientific application bootstrap.
2. Construct `DiagnosticService` in a separate application composition root.
3. Add a diagnostic feature flag that defaults off outside development and
   explicit local diagnostic operation.
4. Align settings across domain, application, API, and tests. Unknown or
   incompatible executor values fail closed.
5. Make repeated requests with the same idempotency key return the existing
   invocation rather than launch another process.
6. Inventory formal project records before and after each evidence run.

Acceptance:

- no diagnostic call reaches the scientific coordinator;
- no scientific setting can select the one-shot executor;
- diagnostics cannot mutate formal phase, method, branch, decision, or
  publication records; and
- duplicate submission produces one invocation and one external execution.

### H0.3 Exact project-profile provisioning

Goal: create only the identity and state that the selected role is allowed to
receive.

Work:

1. Provision into a temporary directory, validate the complete result, write
   its ownership manifest, then rename atomically.
2. Read allowed identity resources from a base role template if useful, but
   do not clone base `.env`, `auth.json`, memories, `state.db`, sessions,
   request dumps, logs, checkpoints, cache, or undeclared skills.
3. Install only the skills declared by the profile manifest.
4. Keep SOUL.md, config.yaml, and skills stable, versioned, and free of
   project scientific context and secrets.
5. Validate project IDs, role names, profile names, path containment, file
   types, permissions, and symlink targets.
6. Resolve existing profiles by exact manifest identity. Reject collisions or
   mismatched ownership.
7. Retire profiles by exact manifest ownership, never by string-prefix match.
8. Replace MD5 in public evidence fields with SHA-256.

Memory-policy realization:

The canonical project profile is never mounted directly as writable. While
holding the profile mutex, Method Hub creates a per-invocation writable
runtime profile or overlay from a consistent canonical snapshot. Hermes
writes only to that isolated runtime state.

- `persistent`: seed the runtime profile from the canonical author profile;
  capture immutable before and after memory snapshots and the exact accessible
  session state; after validated success and verified quiescence, atomically
  promote allowed changes only while the original token and lease remain
  current;
- `read_only`: seed a disposable writable runtime profile from the selected
  immutable memory snapshot and discard all runtime changes; and
- `ephemeral`: create a fresh writable runtime profile with no prior
  memories, `state.db`, sessions, request dumps, logs, checkpoints, or cache,
  then discard it completely.

If prior-session browsing is enabled, create the start snapshot with a
verified SQLite backup or checkpoint procedure while the profile mutex is
held. Copying a live `state.db`, or recording only its digest, is not a
consistent reconstruction. If this procedure is unavailable, disable
prior-session browsing.

Failed, cancelled, timed-out, lease-lost, or unresolved runtime changes are
never promoted. They are discarded after evidence is sealed or retained in a
bounded quarantine that cannot become future role context.

Acceptance:

- a cross-project canary cannot be read;
- reviewer runs start and end without retained mutable state;
- declared skills are present and undeclared skills are absent;
- a stale or lease-lost process cannot change canonical profile state;
- interrupted provisioning leaves no discoverable partial profile; and
- retirement cannot affect a similarly prefixed project.

### H0.4 Isolated runtime view and exact Hermes invocation

Goal: expose only the selected capability set.

Work:

1. Build a synthetic `HERMES_HOME` containing only the selected profile.
2. Pass `-p <selected-profile>` explicitly.
3. Mount the sealed task brief and frozen inputs read-only.
4. Mount only the declared diagnostic workspace read-write.
5. Mount SOUL.md, non-secret config, and the exact skill set read-only.
6. Realize the complete memory policy from H0.3.
7. Pin and record the Hermes binary, runtime dependencies, runtime image or
   host-bind manifest, model reference, and provider reference.
8. Verify realized mounts and permissions before Hermes starts.

Acceptance:

- sibling profiles, boards, global memories, host project files, and Method
  Hub databases are inaccessible;
- writes to identity resources fail;
- writes outside the declared workspace and policy-allowed state fail; and
- the realized invocation and profile manifests identify the selected profile;
  `usage.json` independently confirms the expected model, provider, completion
  fields, usage, and new session.

### H0.5 Bounded supervisor and truthful outcome

Goal: control one process tree without unbounded memory, disk, or time.

Work:

1. Introduce a launch handshake. Create the process in a held state, persist
   its real identity, then release it to start Hermes. If persistence fails,
   terminate it before release.
2. For OCI, persist the exact container ID and image digest. For Bubblewrap,
   persist boot ID, PID, `/proc` start ticks, executable identity, process
   group, and an invocation marker.
3. Drain stdout and stderr incrementally into bounded redacted ring buffers.
4. Enforce wall time, CPU, memory, process count, open files, per-file size,
   file count, workspace growth, retained logs, and aggregate diagnostic
   storage.
5. Parse `usage.json` and validate the declared output contract.
6. Do not infer success from exit code 0. Hermes completion flags, required
   outputs, schemas, size limits, and semantic checks must all agree.
7. On cancellation or timeout, record the request, send TERM to the process
   tree, wait a bounded grace period, send KILL if required, reap descendants,
   and verify output quiescence before terminal closure.

Acceptance:

- stdout or stderr flooding cannot exceed configured memory or retained-log
  budgets;
- a descendant writer cannot survive cancellation or mutate files after
  terminal closure;
- process and disk exhaustion close with a specific bounded failure; and
- an internal Hermes failure with exit code 0 closes as failed.

### H0.6 Durable lifecycle, fencing, reconciliation, and cleanup

Goal: make cancellation, timeout, lease loss, coordinator restart, and
retention safe.

Required lifecycle:

```text
pending -> preflight -> creating -> launch_acknowledged -> running
pending | preflight -> cancel_requested -> cancelled
creating | launch_acknowledged | running -> cancel_requested -> terminating
running -> timeout_requested -> terminating
running -> closing -> succeeded | failed
terminating -> cancelled | timed_out | failed | unresolved
any nonterminal state -> unresolved, only when exact reconciliation is impossible
```

`terminating` carries a reason such as user cancellation, timeout, lease loss,
or supervisor failure. A terminal state is recorded only after the process
tree is quiescent or the inability to prove quiescence is recorded as
`unresolved`.

Work:

1. Define allowed transitions and a monotone terminal-state rule.
2. Guard acknowledgement, heartbeat, cancellation, timeout, memory records,
   result records, promotion, terminal closure, cleanup, and lock release with
   the current fencing token and unexpired lease.
3. Renew invocation and profile leases while work is active.
4. On lease-renewal failure, prohibit canonical profile promotion and begin
   verified termination. Quarantine the runtime state if closure is uncertain.
5. Do not grant a successor the profile lock merely because a lease expired.
   Reclaim requires proof that the prior runtime is quiescent or controlled
   adoption of that exact runtime identity.
6. Release a profile lock only when invocation owner and token both match.
7. Enclose lock acquisition, memory snapshotting, profile preparation, launch,
   promotion, and cleanup in guaranteed ownership-aware cleanup.
8. On startup, reconcile every nonterminal invocation against its exact
   durable runtime identity.
9. If identity is absent, reused, inconsistent, or otherwise ambiguous, close
   as `unresolved`. Never signal an unverified PID and never relaunch.
10. Make terminal cleanup idempotent and conditional on exact invocation
    ownership. Active and `unresolved` runtime state or evidence is never
    pruned automatically. Closed evidence is pruned only after sealing and
    the declared retention boundary.
11. Record every rejected stale mutation and cleanup attempt in operational
    evidence.

Acceptance:

- a stale coordinator cannot update state, promote profile changes, clean up
  another invocation, or release a newer lock;
- two coordinators racing on one idempotency key create one execution;
- two invocations racing for one profile never run concurrently;
- restart at each launch boundary yields one explainable terminal or active
  state and never a second process;
- PID reuse and host reboot simulations do not signal an unrelated process;
- cancellation works before spawn, during creation, after acknowledgement,
  and while running;
- timeout and lease loss pass through verified termination; and
- exceptions before and after spawn do not leak a profile lock.

### H0.7 Provider-only network and secret handling

Goal: permit the declared model call without general network access or secret
leakage.

Work:

1. Deny network access by default.
2. Implement and document a provider-only egress topology that works inside
   the selected runtime namespace.
3. Do not treat `--share-net` as allowlist enforcement.
4. Deliver the minimum scoped credential through a mechanism that does not
   expose it in command arguments, profile files, workspace files, logs,
   database fields, diagnostic responses, or retained evidence.
5. Redact provider errors before persistence while retaining useful failure
   classification.
6. Scan the complete evidence package and retained runtime state for canary
   secrets.

Acceptance:

- the declared provider endpoint is reachable;
- an unrelated Internet destination and host-local service are unreachable;
- canary credentials are absent from `/proc/<pid>/cmdline`,
  `/proc/<pid>/environ`, OCI inspection output, runtime configuration, crash
  diagnostics, retained files, database records, and evidence; and
- a missing or invalid network policy fails before Hermes starts.

### H0.8 Headless operation and real evidence

Goal: make the backend inspectable and controllable without depending on the
unfinished Web UI.

Provide a narrow local service or CLI with these operations:

- `preflight` with a structured pass, blocked, or unsupported result;
- `start` with project, role, fixed task, and idempotency key;
- `status` with lifecycle and bounded evidence summary;
- `logs` with bounded redacted output;
- `cancel` that waits for verified closure;
- `reconcile` for startup and explicit testing;
- `memory inspect` and `memory export` for the exact canonical snapshot;
- `memory clear` with explicit confirmation and an audit record; and
- `memory configure` for policy changes that create a new policy and profile
  revision.

Memory clear, configure, promotion, and maintenance require no active profile
lock. They are explicit, versioned operations and never occur as a side
effect of starting or closing a diagnostic.

Preflight is read-only and fail-closed. Its structured result verifies:

- supported Linux, kernel, namespace, cgroup, and rootless runtime features;
- pinned Hermes binary, dependencies, runtime image, and digests;
- exact profile manifest, revision, identity-resource digests, and skills;
- absence of credential files and readiness of secret-safe provider delivery;
- realized network policy and provider endpoint configuration;
- path containment, symlink safety, workspace permissions, and free space;
- configured process, stream, file, workspace, and aggregate quota headroom;
- memory-policy and session-snapshot capability; and
- invocation and profile-lock conflicts.

A blocked or unsupported preflight launches no process and reports the
smallest safe operator action.

The command is local and diagnostic-only. It must display that no scientific
material will be published.

Replace or extend `scripts/diagnostic_test.py` so it invokes this new lane,
not Kanban. Produce a machine-readable evidence index that links every exit
criterion to its test, result, logs, runtime manifest, memory snapshots,
cleanup record, and formal-state inventory.

## 5. Required test matrix

### 5.1 Portable unit and integration tests

- settings reject one-shot scientific execution;
- diagnostic and scientific persistence are separated;
- unsupported or blocked preflight launches no process;
- two coordinators racing on one idempotency key create one execution;
- two invocations racing for one profile cannot run concurrently;
- profile creation is atomic and manifest-owned;
- path and symlink escapes are rejected;
- exact skill selection is enforced;
- every memory policy and canonical-promotion rule is enforced;
- memory inspect, export, clear, and reconfiguration are explicit and audited;
- every lifecycle transition is validated, including pre-running cancellation,
  timeout, lease loss, and unresolved closure;
- every mutation, promotion, cleanup, and lock release requires the active
  fencing token;
- stale lock release and stale profile promotion are rejected;
- active and unresolved evidence cannot be pruned;
- terminal cleanup is idempotent and ownership-checked;
- output buffers and retained logs stay bounded;
- exit-zero internal failure is rejected; and
- no formal scientific record changes.

### 5.2 Real Linux Hermes tests

The complete matrix must pass through rootless OCI for H0-B. If H0-A is
claimed first, run the same applicable cases through Bubblewrap and label that
evidence as interim.

Use the real pinned Hermes runtime:

1. blocked preflight with zero spawned processes;
2. successful fixed synthetic task;
3. exact profile, SOUL, and skill selection;
4. two persistent author invocations showing intended memory continuity and
   atomic canonical promotion;
5. failed and lease-lost author invocations whose runtime state is not
   promoted;
6. consistent SQLite session snapshot, or verified disabled session browsing;
7. read-only seeded memory with all changes discarded;
8. fresh outside-reviewer invocation with no prior mutable state;
9. memory inspect, export, explicit clear, and policy reconfiguration;
10. project A and project B cross-leakage canaries;
11. undeclared host-file and database access attempts;
12. identity-file and out-of-workspace write attempts;
13. two coordinators racing on one idempotency key;
14. two invocations contending for one project-role profile;
15. stdout and stderr flooding;
16. child and grandchild writer cancellation;
17. cancellation before spawn, during creation, after acknowledgement, and
    while running;
18. timeout, lease loss, TERM/KILL escalation, and output quiescence;
19. CPU, memory, process, file, and disk quota exhaustion;
20. restart before spawn, after spawn but before acknowledgement, while
    running, during termination, and after process exit before closure;
21. stale-coordinator and expired-lease mutation, promotion, cleanup, and lock
    release attempts;
22. PID reuse, host reboot, or identity-mismatch simulation;
23. allowed provider call and denied arbitrary Internet and host-local calls;
24. canary-secret scan across process metadata, runtime inspection, crash
    diagnostics, retained state, and evidence;
25. Hermes internal failure with process exit code 0;
26. cleanup and retention with active, unresolved, and closed invocations; and
27. before and after inventories of formal scientific Method Hub state.

Linux-only tests must be marked clearly on unsupported hosts. They are not
replaced by mocks.

## 6. Deliverables

- accepted memory/session and authority decision record;
- aligned schemas, examples, and validators;
- separate diagnostic application composition;
- atomic exact-profile manager and per-invocation runtime-profile builder;
- token-guarded canonical profile promotion;
- Bubblewrap adapter and H0-A evidence if the interim subgate is used;
- rootless OCI adapter and complete H0-B evidence;
- bounded supervisor;
- durable diagnostic lifecycle, fencing, mutex, reconciliation, cleanup, and
  retention;
- local headless diagnostic and memory-control interface;
- updated diagnostic script;
- portable automated tests;
- real Linux evidence suite and evidence index; and
- concise operator notes for preflight, run, cancel, recovery, memory
  operations, and cleanup.

## 7. Exit gate

This block closes only when all statements below are true:

- [ ] a rejected or blocked request launches zero processes, an accepted start
      launches exactly one, and every request launches at most one;
- [ ] scientific execution cannot select or reach the diagnostic executor;
- [ ] the exact selected profile and declared skills are used;
- [ ] only declared workspace and policy-allowed runtime profile state are
      writable;
- [ ] canonical profile state is never directly writable by Hermes and
      promotion is atomic, quiescent, successful, and token-guarded;
- [ ] author memory is reconstructible, researcher-operable, and subordinate
      to formal records;
- [ ] outside-reviewer state is fully ephemeral;
- [ ] formal scientific state is unchanged;
- [ ] output, process tree, resources, files, logs, and storage are bounded;
- [ ] cancellation, timeout, and lease loss are awaited, escalated, reaped,
      and quiescent;
- [ ] restart reconciliation uses exact identity and never auto-relaunches;
- [ ] all mutations, promotions, cleanup, and lock releases are fenced;
- [ ] active and unresolved evidence cannot be pruned, and closed cleanup is
      ownership-checked and idempotent;
- [ ] provider access works while arbitrary egress and host-local access fail;
- [ ] no credential appears in process metadata, runtime inspection, retained
      state, or evidence;
- [ ] task outcome is validated independently of process exit code;
- [ ] the portable suite passes; and
- [ ] H0-B passes the complete real Linux matrix through rootless OCI.

H0-A may be reported separately when its Bubblewrap evidence passes. It never
marks this file complete.

A partial result remains an open block. Record the unmet criterion and
evidence; do not weaken or silently waive it.

## 8. Explicitly deferred

- the user-facing diagnostic UI;
- scientific WP1 integration and publication authority;
- reviewed-basis closure;
- phase-specific scientific output adapters and validators;
- real Phase 1 through Phase 5 pilots;
- automatic multi-role orchestration;
- remote authentication and authorization;
- backup, restore, migration, and release packaging; and
- Windows execution support.

If optional H0-B is resumed and passes, its results may strengthen the local
execution boundary. It does not change the Version 1 work order defined by
ADR-012 and the trusted-local closure plan.

## 9. Implementation judgment

The programmer may change internal classes, module boundaries, or command
syntax when real Hermes behavior requires it. Preserve the authority,
isolation, boundedness, identity, fencing, no-relaunch, and evidence
invariants. If Hermes cannot satisfy one of them, stop at that gate, record
the observed limitation, and propose an architecture decision rather than
working around it silently.
