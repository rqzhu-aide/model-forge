# Method Hub Operational Completion Plan

Status: Active implementation plan

Prepared: 2026-08-03

## Current implementation checkpoint

As of commit `009a50a`:

- the sequential development harness and schema-example workflows remain
  available;
- WP0 command sealing, WP1 containment, and WP2 output validation have useful
  partial implementations, but none has passed its exit gate;
- rootless Podman can execute one hand-built Hermes diagnostic on the tested
  Linux host;
- diagnostic lifecycle, project profiles, runtime snapshots, memory policies,
  fencing, fixed-output validation, an OCI executor, and focused tests now
  provide substantial scaffolding;
- the public diagnostic command still does not compose the OCI executor, and
  the current service and executor lifecycle cannot complete a real invocation
  together;
- exact-profile mounting, durable container identity, current-lease fencing,
  awaited cancellation, memory promotion rules, complete resource bounds,
  provider-only egress, and secret-safe delivery remain open;
- the committed H0-B evidence is partial feasibility evidence rather than a
  complete integrated gate; and
- the Web interface still lacks the diagnostic status, logs, cancellation,
  memory, and evidence controls.

Production scientific execution remains disabled. The recommended next bounded
package is [End-to-End OCI Diagnostic Closure](next-block-end-to-end-oci-diagnostic-closure.md).
It must pass before the local diagnostic UI, WP0 reviewed-basis completion, or
real Phase 1 through Phase 5 pilots become the active block.

## 1. Operational version 1 outcome

Operational version 1 is a single-host, Linux-supported research harness in
which an authenticated researcher can:

1. create and inspect a native Method Hub project;
2. configure reproducible Hermes role profiles and recommended skills;
3. review the exact scientific and execution basis of a proposed run;
4. explicitly start, monitor, cancel, and inspect any eligible phase run;
5. execute real role work inside an isolated and recoverable boundary;
6. publish only complete, validated, unconflicted scientific records;
7. understand current method identity, alignment, attention, outcome, and
   uncertainty without reading internal storage files;
8. operate the same bounded commands locally or through an authorized remote
   client;
9. back up, restore, audit, and recover the system without changing the
   scientific meaning of formal records.

Version 1 is not an autonomous research director. It does not choose a method,
phase, scope, historical context, or rerun for the researcher. It does not
automatically retry scientific role work or start another phase after a run
finishes.

## 2. Research behavior that must not change

Every implementation package in this plan must preserve these rules:

- Every run and rerun is started by an explicit user command.
- Phase 2 presents and maintains possible methods. It does not select a branch
  for Phase 3 or Phase 4.
- Phase 3 and Phase 4 are sibling workflows after Phase 2. Either may run first.
- Phase 3 runs theorist, data analyst, then research lead.
- Phase 4 runs data analyst, theorist, then research lead.
- Each role sees the frozen current basis and only successful, accepted upstream
  outputs declared by its phase contract.
- Current formal records are the default context. Historical runs are opt-in.
- Phase 5 requires current, readable, exactly aligned Phase 1 through Phase 4
  inputs for one exact method identity.
- Operational state, publication position, dependency alignment, research
  attention, and scientific outcome remain distinct.
- A negative, contradictory, or inconclusive scientific result may publish when
  it is structurally complete and honestly represented.
- There is no generic approval step after a user starts a run.
- There is no hidden phase progression, method selection, repair loop, or
  automatic scientific retry.

## 3. Verified starting point

| Area | Current state | Remaining boundary |
|---|---|---|
| Architecture package | 37 schemas, 58 valid examples, 16 rejected fixtures, 5 executable phase contracts, and cross-checked role/file guides | Several runtime representations and production attestations remain incomplete |
| Domain and storage | Typed identities, local durable storage, run state, publication, receipts, and deterministic reducers are implemented | Production concurrency, backup, restore, upgrade, and failure-injection evidence are incomplete |
| Harness | Preparation, sequential stage advancement, closures, submission, validation, publication, cancellation, and restart recovery work with development executors; an initial command basis is embedded | Method-bound role resources and the complete executable basis are not sealed or verified fail closed |
| Executors | Disabled, fake, development Kanban, and initial Bubblewrap, capability, and fencing scaffolds exist | No supported rootless OCI executor, verified termination, provider-only network boundary, or durable external-job fencing |
| Scientific phases | All five phase plans run end to end with schema examples; initial phase-validator modules exist | Validators are not yet schema-aligned or integrated with complete actual-Hermes output and artifact bindings |
| Web interface | Project navigation, phase tabs, methods, runs, profiles, lifecycle controls, and current-state views exist | Complete role-output inspection, Phase 4 checkpoint display, rich scientific artifacts, and operational administration are incomplete |
| Profiles and skills | Versioned role resources and recommended skill installation exist | Actual model/provider metadata, secret boundaries, resource drift handling, and reviewer no-memory attestation are incomplete |
| Security and remote operation | Typed delegation contracts and application command boundaries are specified | Authentication, authorization enforcement, sessions, CSRF protection, and a supported remote client are absent |
| Operations | Local development start and basic recovery exist | Supported deployment, observability, backup/restore, repair tools, and operating-system qualification are absent |
| Legacy adoption | Greenfield boundary is explicit | No one-way importer, reconciliation report, or cutover procedure |

## 4. Dependency order

For production scientific execution, WP0 remains the first hard gate in the
dependency chain below.

The current Phase 0 diagnostic block is a deliberate exception. It may
implement only the non-publishing containment, reconciliation, and cancellation
slices of WP1 before WP0. It must use separate diagnostic state and cannot
enable or create a scientific run.

Outside that diagnostic exception, the work must proceed in this order:

```text
WP0 specification and reviewed-basis closure
  -> WP1 production Hermes execution boundary
  -> WP2 actual scientific output adapters and validators
  -> WP3 complete researcher inspection and controls
  -> WP5 authentication and bounded remote operation
  -> WP6 durability, recovery, and administration
  -> WP7 supported deployment and operating systems
  -> WP9 scientific pilots and release decision

WP4 reproducible profiles and reviewer isolation begins after WP0
and must finish before WP2 and WP5 are accepted.

WP8 legacy import begins only after the native version 1 record model,
storage migrations, backup, and restore behavior are stable.
```

Work packages may overlap only where these dependency statements remain true.
A visible page or successful agent call is not evidence that an earlier
authority or isolation gate may be skipped.

## 5. WP0: close the executable specification

### Purpose

Make the user's accepted command correspond to one exact reviewed scientific
basis and finish the normative representations required to test real execution.

### Deliverables

1. Select and record one reviewed-basis boundary:
   - preferably accept and prepare as one compare-and-seal transaction; or
   - seal the complete basis in the accepted command and prohibit later
     substitution.
2. Bind the command to:
   - the current authority head;
   - exact formal input generation IDs and artifact digests;
   - exact method ID, version, and definition digest;
   - exact profile, soul, instruction, skill, tool, knowledge-resource, and
     memory-policy versions and digests;
   - the phase contract version, mode, and digest.
3. Reject any intervening basis change with one stable stale-basis error. Do not
   create a run that can later resolve a different basis.
4. Add the missing normative representations identified by the architecture
   audit:
   - orchestration binding;
   - role execution record;
   - progress event;
   - state-specific RunState requirements so pre-manifest states do not claim a
     manifest that does not exist;
   - dedicated Phase 4 evidence-index, empirical-synthesis, implementation, and
     phase-decision record obligations.
5. Define the executor attestation that proves the outside reviewer ran in an
   ephemeral or verified no-memory session.
6. Decide whether formal-generation withdrawal is in version 1. If retained in
   the accepted architecture, implement it as a complete no-run control
   transaction. Do not expose a placeholder action.
7. Update schemas, examples, invalid fixtures, digest contracts, traceability,
   and scenarios together.

### Primary code locations

- `architecture/schemas/`, `architecture/contracts/`, and
  `architecture/examples/`
- `src/method_hub/harness/commands.py`
- `src/method_hub/harness/preparation.py`
- `src/method_hub/harness/execution_records.py`
- `src/method_hub/domain/runs.py`
- `src/method_hub/application/run_lifecycle.py`

### Validation

- Concurrent basis-change tests for formal inputs, methods, profiles, and every
  required resource.
- Idempotent replay tests proving that the same accepted command never resolves
  newer objects.
- State-machine tests for created, preparing, prepared, running, submitted,
  failed, cancelled, conflicted, and published runs.
- Schema and semantic tests for all new representations.
- Reviewer-session tests that fail closed without a valid no-memory attestation.

### Exit gate

A developer can start from the user-reviewed screen and name every exact object
that will appear in the manifest before any role starts. Any drift rejects the
command without scientific side effects.

## 6. WP1: build the production Hermes execution boundary

### Purpose

Replace development-only process execution with a supported, isolated,
reconcilable executor. The orchestrator remains mechanical. Hermes roles supply
scientific judgment.

### Deliverables

1. Implement a production `ExecutorPort` adapter using rootless OCI containers on
   Linux.
2. Pin and record:
   - runtime image digest;
   - executor-profile digest;
   - Hermes version;
   - role profile and model configuration;
   - resource limits;
   - network policy;
   - process, mount, user, and security settings.
3. Run each invocation with:
   - a read-only root filesystem;
   - a private user namespace;
   - no Linux capabilities;
   - no-new-privileges;
   - a pinned seccomp policy;
   - one writable role root;
   - no formal-storage credentials;
   - no ambient access to project files.
4. Implement a capability broker that resolves only manifest-authorized logical
   references, verifies content digests, records every read, and materializes
   writes only inside the role root.
5. Make network access absent by default. When a phase authorizes external
   resources, proxy only the declared hosts or services and record the access.
6. Introduce durable invocation leases, fencing tokens, heartbeats, timeout,
   cooperative cancellation, and startup reconciliation.
7. Ensure restart recovery adopts or terminates the exact prior external job.
   It must never launch a duplicate scientific invocation.
8. Keep scientific retry disabled. Infrastructure reconciliation may reconnect
   to the same invocation, but a new agent call requires a new user-started run.
9. Keep secrets outside manifests, logs, role artifacts, and publication
   records. Inject the minimum secret at runtime and redact diagnostics.

### Suggested modules

- `src/method_hub/executors/oci.py`
- `src/method_hub/executors/runtime_profiles.py`
- `src/method_hub/capabilities/broker.py`
- `src/method_hub/capabilities/policy.py`
- `src/method_hub/harness/invocation_recovery.py`

These are suggested boundaries, not new authority layers.

### Validation

- Path traversal, symlink, hard-link, subprocess, mount, and direct-database
  escape tests.
- Network deny and allowlist tests.
- Container image and executor-profile mismatch tests.
- Crash before start, crash after start, lost heartbeat, cancellation race, and
  server-restart reconciliation tests.
- Duplicate-delivery tests proving one accepted invocation closure.
- Secret scanning over manifests, logs, run artifacts, and formal records.

### Exit gate

One dummy role and then one real Hermes role execute in the supported container
boundary. Restart, timeout, or cancellation cannot duplicate work, broaden
access, or change prior formal state.

## 7. WP2: validate actual scientific role outputs

### Purpose

Move from schema-example conformance to real phase execution without allowing
free-form agent output to become formal merely because files exist.

### Deliverables

1. Define one output adapter for each role-stage obligation in each executable
   phase mode.
2. Require structured output plus linked human-readable artifacts. Preserve
   mathematical notation, assumptions, uncertainty, negative findings, and
   unresolved disagreement.
3. Validate:
   - required files and structured fields;
   - exact method identity;
   - formal input and upstream-closure provenance;
   - role and stage ownership;
   - artifact digests;
   - phase-specific scientific-basis completeness;
   - publication binding and expected prior generation.
4. Reject missing, ambiguous, cross-method, stale-version, or untraceable output.
   Do not infer formal records from filenames or prose headings.
5. Preserve unfavorable but complete research conclusions as valid scientific
   outcomes. A validator must not convert “method failed under this condition”
   into an operational failure.
6. Build phase-specific conformance suites:
   - Phase 1 deduplication, correction, and cumulative synthesis;
   - Phase 2 full-catalog and focused-method identity and lineage;
   - Phase 3 complete replacement of the current proof record;
   - Phase 4 exact-version evidence applicability and four-slot atomic update;
   - Phase 5 exact aligned basis, closed review packet, issue disposition, and
     one complete replacement manuscript.
7. Store raw role output in the immutable run workspace even when validation
   fails. Failed output never becomes current.

### Validation

- Golden actual-Hermes output fixtures for every role and mode.
- Mutations that remove assumptions, alter method identity, cite an undeclared
  input, omit a required output, or mix sibling outputs.
- Negative, contradictory, and inconclusive outcome fixtures.
- End-to-end runs for all eight phase modes using the production executor.

### Exit gate

Every phase can complete with actual Hermes output, and every formal field can
be traced to an accepted role artifact, exact frozen input, and publication
receipt.

## 8. WP3: complete researcher inspection and run controls

### Purpose

Give the researcher enough clear scientific information to decide what to run
next without exposing storage internals or asking for unnecessary approval.

### Deliverables

1. Before launch, show:
   - phase and mode;
   - exact method identity when applicable;
   - current formal input generations;
   - selected historical context;
   - role order and parallel groups;
   - profile and resource versions;
   - expected publication effects;
   - stable eligibility or stale-basis reasons.
2. During and after a run, expose a structured run packet:
   - frozen command and manifest summary;
   - prepared context for each role;
   - invocation start and closure;
   - accepted outputs;
   - handoffs;
   - immutable submission;
   - validation report;
   - publication receipt or exact failure.
3. Add a safe scientific artifact viewer with:
   - sanitized Markdown;
   - LaTeX mathematics;
   - tables and code;
   - exact source artifact and digest;
   - download of the original file.
4. Add the dedicated Phase 4 protocol and evidence view. It must distinguish:
   - planned computation;
   - method version;
   - code and environment;
   - completed evidence;
   - outdated or inapplicable evidence;
   - current empirical synthesis and decision.
5. Keep method-table columns separate for P3 and P4 alignment, attention,
   outcome, and operational state.
6. Show technical logs on demand, not as the primary scientific summary.
7. Provide cancel before submission and safe administrator recovery controls.
   Do not add approve, arbitrary prerequisite override, or automatic continuation
   controls.
8. Preserve unsaved user instructions and warn before abandoning edited input.

### Validation

- Browser tests for fresh, running, failed, cancelled, conflicted, published,
  outdated, and withdrawn states.
- Accessibility tests in light and dark modes.
- Malicious Markdown, HTML, link, and LaTeX payload tests.
- Projection tests proving the UI never derives authority from folder presence.
- User tests in which a researcher can answer: what changed, what is current,
  what remains uncertain, and what action is available.

### Exit gate

A researcher can inspect the complete basis and consequence of a run from the
Web interface and can make the next decision without opening the project
directory or interpreting raw JSON.

## 9. WP4: make profiles and resources reproducible

### Purpose

Make the role “soul” scientifically useful and operationally reproducible while
keeping memory and credentials appropriately bounded.

### Deliverables

1. Display actual read-only runtime metadata for each profile:
   - role;
   - Hermes profile ID;
   - model and provider;
   - endpoint class, without secrets;
   - fallback policy;
   - profile version and digest;
   - soul, instruction, skill, tool, and knowledge-resource versions.
2. Keep recommended skill installation explicit per role. Verify installed
   content by digest and distinguish absent, current, locally modified, and
   outdated states.
3. Freeze all selected resources in the reviewed run basis.
4. Fail preparation when a required resource is missing or has changed. Do not
   silently use a replacement.
5. Define memory policies per phase and role. Expose policy and attestation, not
   raw private memory by default.
6. Run the outside reviewer from a distinct profile and a closed scientific
   packet. Require ephemeral/no-memory proof before claiming independent review.
7. Add knowledge-resource registration for future libraries such as proof,
   optimization, and biological-domain resources without granting ambient file
   or network access.

### Validation

- Resource drift and missing-resource race tests.
- Skill install, verified replacement, and backup tests.
- Profile isolation and reviewer packet tests.
- Metadata redaction and secret-leak tests.
- Reconstruction test from manifest to exact profile-resource bundle.

### Exit gate

Every role invocation is reproducible by profile and resource identity, and the
reviewer isolation claim is supported by executor evidence rather than profile
naming alone.

## 10. WP5: authenticate users and bound remote operation

### Purpose

Allow local and remote clients to issue the same typed commands without giving a
remote agent general authority over projects or the host.

### Deliverables

1. Implement authenticated researcher sessions and an explicit administrator
   role for operational recovery.
2. Add secure session cookies, CSRF protection, origin checks, rate limits, and
   login event auditing.
3. Implement bounded delegation grants over:
   - project;
   - command family;
   - exact method or record target when applicable;
   - validity interval;
   - revocation state.
4. Recheck delegation at command execution, not only when an action is displayed.
5. Provide a documented remote client that calls the same application service
   used by the Web UI. Do not create a second execution or publication path.
6. Require idempotency keys and exact action-descriptor basis for remote
   mutations.
7. Record accepted, rejected, malformed, expired, and unauthorized attempts in
   the operational audit without creating scientific authority events.
8. Never expose host file paths, database credentials, model keys, or arbitrary
   shell execution to a remote controller.

### Validation

- Authentication, session fixation, CSRF, expired grant, revoked grant, target
  mismatch, replay, rate-limit, and privilege-boundary tests.
- Web and remote command-parity tests.
- Audit-root reconstruction with rejected requests.
- Security review before any non-loopback binding is enabled.

### Exit gate

The Web UI and remote client produce identical authorized command effects, and a
compromised delegated client cannot act outside its exact grant.

## 11. WP6: durability, recovery, and administration

### Purpose

Make failure visible and recoverable without editing formal files by hand.

### Deliverables

1. Complete startup reconciliation for runs, invocations, submissions,
   publication journals, and control transactions.
2. Add fencing and concurrent-run protection at every mutable operational
   boundary.
3. Implement bounded structured logs, metrics, and health checks.
4. Provide safe administrator commands and matching UI actions for:
   - inspect a stuck run;
   - retry operational cleanup;
   - reconcile one external invocation;
   - release a verified stale lock;
   - rebuild projections from authority events;
   - verify receipts and audit roots.
5. Every repair action must have preconditions, a dry-run description, an actor,
   a reason, and an operational audit event.
6. Implement consistent backup and restore of:
   - database;
   - immutable generations;
   - authority and command-audit journals;
   - run artifacts;
   - resource registry and configuration.
7. Verify restore into an empty data root and compare generation counts, digests,
   event roots, projections, and current-index state.
8. Add schema migration tooling with forward migration, preflight, backup
   requirement, and documented rollback boundary.
9. Bound log and temporary-file retention without deleting formal or submitted
   research artifacts.
10. Benchmark large Phase 4 evidence registries and long authority journals.

### Validation

- Failure injection at each write and commit boundary.
- Process kill during each run state and publication step.
- Same-target and disjoint-target concurrency tests.
- Backup during idle and controlled active states.
- Full restore and deterministic replay tests.
- Corruption detection for artifacts, journals, indexes, and receipts.

### Exit gate

A documented operator can recover every tested interruption without scientific
data loss, duplicate role work, silent authority change, or manual editing of
formal records.

## 12. WP7: supported deployment and operating systems

### Purpose

Turn the development server into a repeatable supported installation.

### Deliverables

1. Support Linux first with pinned Python, Node build, rootless container runtime,
   Hermes, filesystem, and database requirements.
2. Build the frontend once and serve its static assets through the application
   or a documented reverse proxy.
3. Provide:
   - one production configuration template;
   - data-root and backup-root policy;
   - service definition;
   - TLS reverse-proxy guidance;
   - health and readiness endpoints;
   - startup preflight;
   - upgrade and rollback procedure.
4. Bind to loopback by default. Non-loopback operation requires authentication
   and an explicit deployment setting.
5. Document minimum and recommended resources, container prerequisites, file
   permissions, ports, storage growth, and backup capacity.
6. Treat Windows as experimental until a separate qualification suite passes.
   Document whether execution uses WSL2 or another supported isolation boundary.
   Do not imply native Windows parity before it is tested.
7. Produce a clean-machine installation test and a repeatable release artifact.
8. Generate a software bill of materials and run production-dependency audits.
   A high or critical runtime advisory requires a patched version or a reviewed
   non-applicability analysis with compensating controls and an expiry date.
   An unresolved advisory blocks production release.

### Validation

- Supported Linux matrix in CI.
- Clean install, upgrade, rollback, backup, and restore tests.
- Permission-denied, full-disk, unavailable-container-runtime, and port-conflict
  tests.
- Experimental Windows smoke tests labeled separately from supported tests.
- Production dependency and secret-scanning gates over the release artifact.

### Exit gate

A new Linux host can install, start, stop, upgrade, back up, restore, and verify
Method Hub using documented commands and no source-tree assumptions.

## 13. WP8: import legacy Research Hub projects

### Purpose

Offer a controlled adoption path only after native Method Hub operation is
stable.

### Deliverables

1. Accept legacy Research Hub input read-only.
2. Inventory source records, methods, branches, runs, artifacts, and unresolved
   states without assigning Method Hub authority.
3. Produce a dry-run report that identifies:
   - exact convertible objects;
   - ambiguous or unsupported objects;
   - proposed stable identities and versions;
   - missing provenance;
   - count and digest reconciliation;
   - user decisions required.
4. Import into a new Method Hub project. Never dual write or update the source.
5. Create a conversion receipt that binds source inventory, mapping rules,
   created generations, and reconciliation results.
6. Define rollback before cutover and recovery after cutover.
7. Keep the source project archived and readable until the researcher accepts
   the converted project.

### Validation

- Representative legacy projects, including stale branches, failed runs,
  retired methods, old method versions, and incomplete evidence.
- Repeatable dry runs and idempotent conversion.
- Exact count, digest, method-lineage, and current-record reconciliation.
- Failure at every conversion stage without partial Method Hub authority.

### Exit gate

A researcher can review the complete conversion report and either accept one
coherent Method Hub project or retain the untouched legacy project. No project
is governed by both systems.

## 14. WP9: real scientific pilots and release gates

### Purpose

Demonstrate that operational correctness supports, rather than obscures, real
research reasoning.

### Pilot set

Use at least three native projects:

1. a statistical or machine-learning method with nontrivial theory and
   simulation;
2. a mathematical method with proof repair and an inconclusive branch;
3. a biological or biostatistical method with domain-specific evidence and
   reproducibility requirements.

Each pilot must exercise reruns, a method-definition change, P3/P4 either-first
order, outdated evidence, negative or inconclusive findings, Phase 5 assembly,
and outside review.

### Evaluation

For every pilot, verify:

- the user understood every launch choice;
- the team received the intended phase-specific roles, souls, resources, and
  exact context;
- material claims retained assumptions and provenance;
- method version changes made prior proofs and computations visibly outdated;
- reruns produced lean current records while preserving immutable provenance;
- summaries identified both scientific innovation and decision-relevant change;
- failures did not alter current formal state;
- another operator could reproduce the manifest, artifacts, and receipt.

### Release gates

| Release | Required evidence |
|---|---|
| Development alpha | Architecture, backend, frontend, and fake-executor suites pass; no production execution claim |
| Isolated beta | WP0 through WP4 pass on Linux with actual Hermes outputs; access and recovery tests pass; use is limited to controlled pilot projects |
| Release candidate | WP5 through WP7 pass; authentication, remote parity, backup/restore, failure injection, and deployment qualification pass |
| Version 1 | Scientific pilots pass; all stop-ship issues close; operator and researcher documentation match the running system |
| Legacy adoption release | WP8 passes independently after version 1 storage and migration interfaces are stable |

### Stop-ship conditions

Do not enable production execution when any of these remain:

- an accepted command can prepare a different scientific or profile basis;
- a role can reach undeclared storage, network, memory, or credentials;
- an invocation can duplicate after restart;
- actual output can publish without exact identity and provenance validation;
- reviewer isolation lacks an execution attestation;
- authentication or authorization can be bypassed;
- backup and restore cannot reproduce formal state;
- a high or critical runtime dependency advisory lacks a patched version or a
  time-bounded reviewed non-applicability decision;
- the UI hides stale alignment, failed validation, or the exact publication
  consequence;
- a supported installation depends on unrecorded developer-machine state.

## 15. Recommended implementation slices

Use small pull requests with one observable gate each:

1. Complete the [headless Hermes runtime closure](next-block-headless-hermes-runtime-closure.md),
   including the H0-B rootless OCI, durable reconciliation, and cancellation
   gate.
2. Add the local diagnostic status, bounded-log, cancellation, preflight, and
   memory-control UI; close the remaining Phase 0 usability evidence.
3. Close the exact reviewed-basis gate and add its missing runtime schemas and
   state-specific validation.
4. Complete profile metadata, reviewer-session attestation, resource-drift
   checks, and the dedicated Phase 4 representations.
5. Validate one complete Phase 4 actual-Hermes run, then generalize the adapter
   pattern to the other phases.
6. Add the complete run packet and scientific artifact viewer.
7. Add authentication, bounded remote delegation, and parity tests.
8. Add operational repair, backup/restore, and failure injection.
9. Package the supported Linux deployment and run the pilot release gates.
Every pull request must state the affected invariant, contract, schema,
researcher-visible consequence, tests, and rollback behavior. Contract changes
require a decision record and updated scenarios before code depends on them.
