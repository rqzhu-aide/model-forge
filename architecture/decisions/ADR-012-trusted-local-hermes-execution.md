# ADR-012: Trusted local Hermes execution for Version 1

## Status

Accepted, 2026-08-04.

This decision supersedes only the rootless OCI and operating-system containment
requirements of ADR-004 for Version 1. It also expands the runtime-memory model
of ADR-011 from diagnostics to local scientific execution. All formal context,
record, user-control, and publication invariants remain in force.

## Context

Method Hub is currently a local application operated by one researcher on a
trusted machine. Research work is performed by locally installed Hermes
profiles. Method Hub prepares each run, starts Hermes, records progress,
validates expected outputs, and promotes valid results and role state.

The previous architecture required every role to run inside rootless OCI. That
boundary is useful for multi-user operation, untrusted tools, or unattended
remote execution, but it adds image management, mount policy, network policy,
and container reconciliation that are not necessary for the current trusted
local use case.

Version 1 needs workflow and state integrity. It does not need to claim that
Hermes is isolated from the researcher's host account.

## Invariants that remain true

- Every run and rerun requires an explicit user action.
- Method Hub records the exact phase, role, selected context, role assets,
  Hermes version, and project-state snapshot used by a run.
- Hermes works in an invocation-specific profile and workspace. It does not
  write the canonical role definition or current project-role state directly.
- Formal project records change only through validated promotion.
- Failed, cancelled, timed-out, invalid, or unresolved work cannot become
  current and cannot replace current memory or session state.
- The outside reviewer starts from a fresh runtime state unless a later user
  decision and architecture change explicitly allow otherwise.
- Cancellation and timeout cover the complete Hermes process tree and reach
  verified quiescence before closure.
- Application restart never launches a replacement invocation automatically.
- Method Hub validates operational and artifact contracts. It does not claim to
  decide whether a scientific argument is correct or important.

## Options considered

### Option A: keep OCI as the Version 1 execution boundary

This provides stronger host isolation, but makes the first local release depend
on container images, network mediation, secret delivery, mount enforcement, and
container lifecycle recovery.

### Option B: trusted local execution with per-run profiles

Run the locally installed Hermes executable under Method Hub supervision. Build
an invocation-specific profile from configuration-managed role assets and the
selected project-role memory and session snapshot. This matches the current
single-user operating model and is selected for Version 1.

### Option C: support local and OCI execution equally in Version 1

This preserves both modes immediately, but doubles the execution, recovery,
testing, and support surface before the research workflow itself is complete.

## Decision

1. **Version 1 uses a local host executor.** Method Hub invokes the installed
   Hermes executable directly, without a shell, using an explicit argument
   vector, environment, working directory, invocation profile, and workspace.

2. **The host is trusted.** Method Hub does not claim that Hermes or its tools
   are prevented from reading other files, using the host network, inspecting
   processes, or exercising the user's operating-system permissions. Method Hub
   supplies only declared inputs and paths, but this is workflow discipline,
   not an operating-system security guarantee.

3. **Role assets and project state are separate.** SOUL, base configuration,
   skills, and library guidance are managed from the configuration interface.
   Project-role memory and session state evolve through validated runs. A run
   profile is assembled from both sources and is never the canonical source of
   the role assets.

4. **Every invocation gets a private runtime profile.** Method Hub creates a
   run-specific Hermes home, profile, workspace, logs, and output directory.
   The run profile receives exact copies of the configured role assets and the
   selected current project-role state. The global Hermes profile is not used
   as mutable run state.

5. **Memory and sessions use snapshot semantics.** Memory files and any safe
   session snapshot are copied into the run profile before launch. Session
   state is copied only while quiescent, through Hermes export and import when
   available or a verified SQLite backup procedure. Method Hub never copies a
   live database file.

6. **Only allowed mutable state is promoted.** After Hermes and its descendants
   stop, Method Hub validates expected artifacts and seals before and after
   memory and session evidence. Only a successful, valid run under the current
   ownership token may atomically replace the current project-role state. SOUL,
   skills, and base configuration are never copied back from a run.

7. **The local process is durably supervised.** Runtime identity binds the PID,
   process start identity, executable, invocation marker, and host boot or
   session identity. Logs are streamed under fixed bounds. Timeout and
   cancellation terminate the complete process tree and verify quiescence.
   Restart reconciliation inspects the same identity and never relaunches.

8. **Hermes updates do not require a Method Hub runtime image.** Preflight
   verifies the installed executable and records its path, version, and other
   available immutable identity. A changed Hermes version is shown to the user
   and becomes part of the next run manifest.

9. **OCI is deferred optional hardening.** Existing OCI code and evidence may be
   retained as experimental work. OCI is not a Version 1 prerequisite, default
   executor, Phase 0 gate, or scientific execution gate. A later ADR may enable
   it for multi-user, remote, unattended, or untrusted-tool operation.

10. **Linux remains the supported Version 1 platform.** Windows may be added
    after process-tree termination, path, file-locking, and session-snapshot
    behavior pass equivalent tests.

## Consequences

### Benefits

- The execution model matches how the local research system is actually used.
- Hermes upgrades no longer require rebuilding a container image.
- Profile setup, run preparation, output validation, and memory continuity can
  be completed before optional infrastructure hardening.
- The existing executor interface still permits an isolated backend later.

### Costs and risks

- Hermes and its tools inherit the local user's host access.
- Filesystem and network isolation cannot be claimed or tested as enforced.
- Correctness depends on exact run-profile construction, bounded supervision,
  locks, quiescence checks, validation, and atomic promotion.
- Multi-user or untrusted execution remains unsupported.

## Contract changes

- Executor identity becomes a versioned local-host binding rather than an OCI
  image and container binding.
- Role invocation start records include Hermes executable identity and version,
  role-asset digests, project-state snapshot identity, working roots, and the
  local process-control policy.
- Role closure records include exact process identity, exit and cancellation
  evidence, output inventory, validation result, and memory-session disposition.
- Strict host-denial statements are deferred to an optional hardened executor.

## Schema changes

- Add a `trusted_local` executor binding to the invocation and manifest schemas.
- Do not require OCI image or container fields for a trusted local invocation.
- Record the run profile, role-definition revision, project-state snapshot,
  Hermes version, executable identity, and process identity.
- Preserve explicit executor type and version so future OCI records remain
  distinguishable.

## Scenario changes

Add scenarios for exact role setup, first-run state, successful continuation,
fresh reviewer state, invalid output, cancellation, timeout, restart
reconciliation, stale locks, failed promotion, Hermes version changes, bounded
logs, and safe session snapshots. OCI escape and network-isolation scenarios
move to an optional post-Version 1 hardening package.
