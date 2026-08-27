# Next Work Block: Trusted Local Hermes Execution Closure

Status: Recommended Version 1 implementation block, Revision 1.

Baseline: commit `a08604d`, planned 2026-08-04.
Revision 1: 2026-08-04 - OCI removal executed; see the Revision 1 changelog
at the end of this document.

Architecture decision:

- [ADR-012: Trusted local Hermes execution for Version 1](../design/decisions/ADR-012-trusted-local-hermes-execution.md)

Related records:

- [ADR-011: Per-project Hermes memory and session model](../design/decisions/ADR-011-per-project-memory-model.md)
- [Operational completion plan](completed/operational-completion-plan.md)
- [WP0 reviewed-basis closure](completed/wp0-reviewed-basis-closure.md)

The former OCI closure plans are retained only as optional future hardening
references. They are not Version 1 prerequisites.

## 1. Target outcome

Make Model Forge a reliable local control plane for Hermes:

```text
Role configuration
  -> stable SOUL, config, skills, and library guidance

User starts a phase run
  -> seal run choices and selected context
  -> assemble a private run profile
  -> copy selected project-role memory and session state
  -> run local Hermes under bounded supervision
  -> wait for complete process quiescence
  -> validate expected artifacts
  -> atomically promote valid outputs and allowed role state
  -> present a compact result and validation summary
```

The researcher decides when to run or rerun every phase. Model Forge does not
select a method, advance a phase, retry scientific work, or promote partial
material automatically.

This block is complete when one real local Hermes role can run through this
whole path and the same control path is ready for all phase and role modes.

## 2. Operating boundary

Version 1 assumes:

- one researcher operates Model Forge on a trusted local machine;
- the installed Hermes executable, configured profiles, selected skills, and
  tools are trusted by that researcher;
- Linux is the supported platform;
- Model Forge controls workflow and state transitions, not host security; and
- OCI, provider-only networking, filesystem denial, and hostile-tool isolation
  are deferred.

Model Forge must state this boundary plainly. It supplies Hermes only the
intended run material, but it cannot guarantee that a local Hermes tool will
not access other files or use the host network.

## 3. State model

Keep four kinds of information separate:

| State | Purpose | Updated by |
|---|---|---|
| Role definition | SOUL, base configuration, skills, tool and library guidance | User through configuration |
| Current project-role state | Latest promoted memory and safe session snapshot | Validated successful runs or explicit user maintenance |
| Run profile and workspace | Private working copy for one invocation | Hermes during that invocation |
| Formal project records | Methods, proofs, empirical records, manuscript, summaries, and authority state | Model Forge validation and promotion only |

A run profile is disposable working state. It is assembled from the role
definition and selected project-role state. It is never copied wholesale back
into either source.

## 4. Fixed workflow rules

1. **Configuration controls role identity.** The configuration interface owns
   SOUL, base configuration, recommended skills, custom skills, and useful
   library guidance. A run cannot silently modify these files.

2. **Each run gets a private profile.** Model Forge creates a run-specific Hermes
   home, named profile, workspace, logs, outputs, and manifest. Hermes does not
   execute against the current project-role profile directly.

3. **State input is explicit.** Persistent author roles normally receive the
   latest promoted project-role memory and safe session snapshot. A first run
   starts clean. Read-only mode may inspect current state without promotion.
   The outside reviewer starts fresh.

4. **Every run records its basis.** Record phase, role, method identity, user
   choices, selected context, role-definition revision, skill digests, input
   state snapshot, Hermes version, model, provider, and expected outputs.

5. **Exit code is not the result.** A run succeeds only after Hermes and its
   descendants stop and Model Forge validates the required output inventory and
   phase-specific artifact contracts.

6. **Promotion is narrow and atomic.** Only declared formal outputs and
   allowlisted memory and session state may become current. SOUL, skills, base
   configuration, logs, caches, and unrelated profile files are never promoted.

7. **Failure preserves the last known good state.** Failed, cancelled,
   timed-out, invalid, conflicted, and unresolved runs retain bounded diagnostic
   evidence but cannot replace current formal records or role state.

8. **One writer owns role state.** A durable project-role lock covers run-state
   preparation, execution, memory maintenance, session maintenance, promotion,
   and cleanup. A stale owner cannot promote or release another owner's lock.

## 5. Implementation work blocks

Complete these blocks in order. Internal class names may change when the same
responsibility is clearer elsewhere.

### Block 1: align architecture and contracts

Goal: remove OCI from the Version 1 definition before code depends on the new
runtime.

Required work:

- Apply ADR-012 to the system principles, run harness, implementation roadmap,
  traceability, and role-context documents.
- Preserve frozen prepared context, immutable invocation and closure records,
  explicit user control, reviewer packet construction, and formal publication
  rules.
- Replace claims of enforced host isolation with the honest trusted-local
  boundary. Model Forge can prove which inputs it supplied, not which ambient
  host resources Hermes could technically access.
- Add a versioned `trusted_local` executor binding to manifests and invocation
  records. It records the Hermes executable and version, role-definition and
  state-snapshot identities, working roots, command basis, and process-control
  policy.
- Keep executor type explicit so future local and OCI evidence cannot be
  confused.
- Update schemas, examples, rejected fixtures, digest contracts, and
  traceability together.

Checkpoint: the architecture package validates and no Version 1 contract
requires an OCI image or container identity.

### Block 2: make role setup a first-class configuration service

Goal: let the researcher see and manage exactly what defines each team member.

Required work:

- Store one configuration-managed role definition for the research lead,
  theorist, data analyst, and outside reviewer.
- Support one-click installation or update of recommended skills while showing
  installed version, source, digest, and customization status.
- Never overwrite a customized SOUL, configuration, or skill silently. Require
  an explicit user choice when an update conflicts with customization.
- Keep project-role memory and session state outside the role definition.
- Provision role definitions and new project-role state atomically, with
  rollback on partial failure.
- Provide clear status for missing Hermes, missing profiles, invalid role files,
  skill mismatch, and unsupported versions.

Checkpoint: the configuration page can create and inspect all four role
definitions and report their exact installed assets.

### Block 3: assemble one exact run profile

Goal: convert the user's run decision into a private and reconstructible Hermes
working profile.

Required work:

- Acquire the project-role state lock and seal one idempotent invocation before
  launching a process.
- Create a dedicated run directory containing profile, workspace, inputs,
  outputs, logs, and manifest subdirectories.
- Build a run-specific Hermes home and profile from the current role definition.
- Copy the selected current project-role memory and safe session snapshot
  according to the declared persistence policy.
- For a first run or fresh mode, create clean memory and session state. The
  outside reviewer defaults to this mode.
- Treat Hermes session storage as opaque. Use Hermes export and import if
  available; otherwise use a verified SQLite backup or checkpoint procedure
  while the source is locked and quiescent. Never copy a live `state.db`.
- Materialize only the user's selected context and the phase contract's required
  inputs into the run packet.
- Keep provider credentials outside copied profiles, manifests, logs, and
  retained evidence.
- Run preflight before launch: verify Hermes, role assets, selected state,
  paths, permissions, free space, lock ownership, task brief, and expected
  output contract.

Checkpoint: two preparations from the same sealed basis produce equivalent
manifests and run-profile content, apart from declared invocation identifiers
and timestamps.

### Block 4: implement one supervised local Hermes runner

Goal: run Hermes predictably without pretending that it is a security sandbox.

Required work:

- Add `LocalHermesExecutor` behind the existing executor interface and make it
  the only supported Version 1 real-Hermes backend.
- Launch the resolved executable directly, without a shell, using the exact run
  profile, run workspace, task brief, argument vector, and minimal environment.
- Record launch intent before process creation and persist a durable identity
  immediately after creation. Identity must distinguish PID reuse using process
  start identity, executable, invocation marker, and host boot or session
  identity where available.
- Stream stdout and stderr continuously into bounded logs and a capped live
  tail. A long line or output flood cannot block process completion or grow
  memory without bound.
- Maintain durable heartbeat and lifecycle state. One accepted idempotency key
  starts at most one Hermes process.
- On cancellation or timeout, request graceful termination, wait a fixed grace
  interval, terminate the complete process tree, drain final output, and verify
  quiescence before recording closure.
- On application restart, inspect the exact recorded identity. Reconcile or mark
  the invocation unresolved or failed; never start a replacement automatically.
- Detect a changed Hermes installation during preflight, show its version to the
  user, and record it in the next manifest. No container rebuild is involved.

Checkpoint: one fixed synthetic Hermes task succeeds, invalid output fails,
cancellation and timeout stop all descendants, and restart does not duplicate
work.

### Block 5: validate, record, and promote

Goal: turn completed Hermes work into current project state only when its
structure is trustworthy.

Required work:

- Wait until Hermes, its descendants, log writers, and session writers are
  quiescent before reading final state.
- Preserve the raw run directory and bounded diagnostics before adaptation.
- Validate expected output names, safe paths, required schemas, nonempty
  scientific fields, declared companion files, run and method identity, and
  phase-specific consistency. Exit code zero alone is insufficient.
- Record memory-before and runtime-after snapshots and inventories for every
  readable closure.
- For a validated persistent run, stage only allowlisted memory files and the
  safe session snapshot. Never promote SOUL, skills, base configuration,
  credentials, logs, caches, or unrelated profile state.
- Stage formal artifacts and project-role state separately, verify current lock
  and command heads, then atomically advance current pointers. Preserve the last
  known good state until the complete promotion succeeds.
- Record a compact promotion receipt with input snapshot, output digests,
  validation results, promoted state, and previous current state.
- Failed, cancelled, timed-out, invalid, stale, or unresolved runs retain
  bounded evidence but do not change current pointers.
- Apply explicit retention rules to old run profiles, logs, sessions, and
  snapshots. Do not prune active or unresolved evidence.

Checkpoint: successful promotion is atomic and reproducible; injected failure
at any promotion step leaves the previous formal and project-role state usable.

### Block 6: expose the complete local operation in the Web interface

Goal: give the researcher enough information to decide, run, and diagnose
without reading internal files.

Required work:

- On configuration pages, show role-definition health, Hermes version, installed
  skills, customizations, and current project-role state.
- Before a run, show phase, role order, method identity, selected context,
  current or fresh state choice, and expected outputs.
- During a run, show state, elapsed time, bounded live logs, current role, and a
  cancellation control.
- After closure, show output validation, promoted and retained items, memory and
  session disposition, Hermes version, and the smallest safe next action.
- Keep every phase and rerun user-started. Completion never launches another
  phase or role sequence outside the run the user already requested.

Checkpoint: the user can configure, start, observe, cancel, and understand one
real local run entirely through Model Forge.

## 6. Reuse and simplification of the current implementation

Reuse where behavior is sound:

- the `RoleExecutor` interface;
- diagnostic lifecycle and idempotency records;
- project-role locks and fencing concepts;
- runtime-profile snapshot, quarantine, and retention concepts;
- fixed output and phase-specific validators;
- immutable run folders, artifact storage, and promotion receipts; and
- existing status, log, profile, and run-form UI components.

Replace or simplify:

- replace OCI and Bubblewrap selection with one `LocalHermesExecutor` for
  Version 1;
- replace container identity and image digest with local process identity and
  recorded Hermes executable and version;
- remove container mount, provider-only egress, image-build, and OCI secret
  delivery from Version 1 gates;
- route diagnostics and scientific role invocations through the same local
  preparation and supervision services, while keeping their publication
  authorities separate; and
- build `LocalHermesExecutor` from `executors/oneshot.py`, which already
  implements one-shot `hermes -z` launch (the process IS the agent),
  file-mounted task briefs, bounded streamed output with a live cap, secret
  redaction, PID-based external identity, heartbeat polling, and before/after
  memory digests. The Block 4 work is stripping the interim `bwrap` wrapper,
  adding durable process identity, restart reconciliation, and verified
  process-tree quiescence - not writing a runner from scratch.

OCI source and tests were removed from the working tree in Revision 1 (git
history preserves them). Block 4 has landed: the diagnostic lane is now wired
to `LocalHermesExecutor`, and the interim `OneShotExecutor` wiring is gone.

Do not rewrite functioning phase contracts or role order. Phase 3 remains
`theorist -> data analyst -> research lead`, Phase 4 remains
`data analyst -> theorist -> research lead`, and the user remains responsible
for starting each run.

## 7. Acceptance evidence

The block closes when the supported Linux host passes all of the following
through the real public path:

1. one-click role setup installs exactly the intended SOUL, configuration, and
   skills and does not silently overwrite customizations;
2. a first persistent run starts with clean project-role state;
3. a successful rerun sees exactly the latest promoted memory and safe session
   snapshot, with complete provenance;
4. a reviewer run receives no prior project-role memory or sessions;
5. double submission creates at most one Hermes process;
6. exit-zero with missing, malformed, wrong-basis, or undeclared outputs fails
   validation and changes no current state;
7. cancellation, timeout, process crash, and application restart do not leave
   unaccounted descendants or launch replacements;
8. concurrent runs cannot mutate the same project-role state;
9. failed, invalid, stale, cancelled, timed-out, and unresolved runs cannot
   promote outputs, memory, or sessions;
10. successful promotion atomically advances formal outputs and allowed role
    state, while injected promotion failure preserves the last known good state;
11. changing the locally installed Hermes version requires preflight review and
    appears in the next manifest, but requires no Model Forge image rebuild; and
12. the Web interface exposes the selected basis, live and final logs,
    validation result, outputs, state disposition, and promotion receipt.

A complete real five-phase pilot follows this closure. It is not required to
prove the local runner itself, but every phase mode must use this same path
before Model Forge is called operational.

## 8. Deliverables

- accepted and aligned trusted-local architecture and contracts;
- configuration-managed definitions for all four roles;
- one atomic run-profile assembler;
- one supervised local Hermes executor;
- bounded logs, cancellation, timeout, and restart reconciliation;
- output and phase validation through the real run path;
- atomic formal-output and memory-session promotion;
- local run, log, validation, and state controls in the Web interface;
- focused portable tests plus real Linux evidence; and
- concise user documentation explaining setup, state continuity, cancellation,
  validation, retention, and the trusted-host limitation.

## 9. Explicitly deferred

- rootless OCI or another security sandbox;
- provider-only network enforcement;
- protection from malicious or compromised Hermes tools;
- multi-user hosting;
- unattended remote execution;
- Windows support;
- automatic scientific retries or phase progression; and
- autonomous project direction.

If any of the first five become requirements, revisit the optional OCI design
under a new bounded hardening plan. Do not silently claim that trusted local
execution already provides those protections.

## Revision 1 changelog (2026-08-04)

Amendments from validating this plan against the working tree at `17c1833`.
A1 and A2 are corrections to the original text; A3-A5 record decisions made
with the researcher.

- **A1 (correction).** The original §6 item "remove the unsafe scientific
  `executor_kind="oci"` mapping" was stale. That mapping was already
  neutralized: `application/settings.py` restricts `executor_kind` to
  `disabled`/`fake`/`hermes_kanban`, `api/models.py` mirrors the restriction,
  and `application/bootstrap.py` fail-closed on `oci`. The only remaining
  work was deleting the now-unreachable bootstrap branch, done in this
  revision.
- **A2 (correction).** Block 4 originally implied writing a runner from
  scratch and §6 omitted `executors/oneshot.py`. The one-shot executor
  already provides most supervised-runner primitives (synchronous
  `hermes -z`, mounted brief, bounded redacted output, PID identity,
  heartbeat, memory digests). §6 now names it as the Block 4 base.
- **A3 (decision).** OCI code and its tests are REMOVED from the working
  tree, not retained as experimental: `executors/oci.py`,
  `executors/bubblewrap.py`, `oci/Containerfile`,
  `diagnostics/network_secrets.py`, and tests `test_h0b_oci_evidence.py`,
  `test_slice1_composition.py`, `test_slice2_7_integration.py`,
  `test_real_linux_evidence.py`, `test_network_secrets.py`. Git history
  preserves them; the evidence index and OCI plan documents remain as
  historical records only. At removal time the H0-B evidence suite was
  already red (5 failures from the slice 2-7 runtime-profile requirement
  drift), confirming the code was not being kept viable.
- **A4 (decision).** The diagnostic lane composition root
  (`diagnostics/composition.py`) was interim-wired to `OneShotExecutor` with
  a `bwrap` preflight check; Block 4 replaced that interim wiring with
  `LocalHermesExecutor`, whose preflight checks the Hermes version instead.
  The lane stays dev-only.
  `diagnostics/contracts.py` `ProcessIdentity.runtime` keeps historical
  `"oci"` values readable.
- **A5 (conformance).** `OneShotExecutor.cancel` now conforms to the
  `RoleExecutor` protocol (`-> None`); the previous `-> bool` return was
  unused by `DiagnosticService` and only surfaced a protocol mismatch. The
  `test_wp1_wp2_integration.py` Bubblewrap command-construction cases were
  removed with the executor; its broker, fencing, adapter, network-policy,
  and fixture coverage is unchanged.

Post-revision state: 386 backend tests green (was 435 with 5 OCI failures
before removal). Remaining Block 1 contract work - schemas, examples,
rejected fixtures, and digest contracts that still carry OCI fields - is
unchanged and still required before code depends on the new runtime.
