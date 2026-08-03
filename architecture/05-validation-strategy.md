# Validation Strategy

## Purpose

This document defines how programmers prove that an implementation follows the
research architecture. Validation is divided into structural correctness,
workflow correctness, scientific-record discipline, and researcher-facing
behavior.

The system can validate identities, schemas, state transitions, provenance,
and declared relationships. It cannot mechanically prove that a theorem is
correct, an experiment is well designed, or a scientific interpretation is
true. Those judgments remain explicit outputs of the research roles.

## Validation layers

| Layer | Question | Primary method |
|---|---|---|
| Schema | Is the persisted object structurally valid? | JSON Schema and typed-model tests |
| Invariant | Does the operation preserve a system rule? | Unit and property tests |
| Transition | Is this publication or derived-state change allowed? | Event and state-machine tests |
| Phase contract | Did the phase receive and produce the required records? | Contract tests |
| Promotion | Was validated run work published atomically? | Integration and failure-injection tests |
| Research scenario | Does the complete workflow behave correctly for a researcher? | End-to-end acceptance tests |
| UI projection | Does the interface report canonical state without inventing it? | View-model and browser tests |

## Normative invariant test catalog

Each test ID names a required implementation test group. The machine-readable
[traceability registry](contracts/traceability.json) maps every invariant to its
research-workflow requirements, test ID, and end-to-end scenarios. Package
validation checks that the three identifier sets remain complete. It does not
claim that an implementation test has run.

| Test ID | Invariant | Required proof |
|---|---|---|
| IT-001 | INV-001 | Only an authenticated researcher or a currently valid, action-scoped delegation can start, rerun, or cancel a run. No result or recommendation starts another run. |
| IT-002 | INV-002 | The submitted command contains the resolved phase, mode, method when applicable, instructions, choices, and context policy. UI defaults never become undeclared scope. |
| IT-003 | INV-003 | Preparation freezes every formal input and `PreparedRoleContext`. Each role start copies the complete manifest recipe step and binds the exact profile, actual inputs, output contracts, capabilities, and write root. Closure seals the access ledger and final context snapshot. |
| IT-004 | INV-004 | A role process cannot read or write outside its broker-granted capabilities and role root, including through path traversal, symbolic links, subprocesses, or direct storage credentials. |
| IT-005 | INV-005 | Every downstream role starts only from successful upstream closures and exact accepted artifacts declared by the contract. Every material disagreement has an explicit disposition or remains visible. |
| IT-006 | INV-006 | Structural and cross-object validation proves a complete ordered successful role-closure chain, final lead closure, and every required submitted artifact before immutable submission or formal publication. |
| IT-007 | INV-007 | Failure injection at every commit boundary produces either one complete publication or no publication. Concurrent disjoint publications preserve both changes. |
| IT-008 | INV-008 | Capture every submitted run artifact and digest before publication, recovery, or replay, then prove that all bytes and run-local locations are unchanged afterward. |
| IT-009 | INV-009 | Normal preparation selects only current formal records unless the submitted command names exact historical generations. |
| IT-010 | INV-010 | Calculation-defining normalization is deterministic, a mathematical change advances method identity, and an exposition-only revision changes the record digest while preserving the definition digest and version. |
| IT-011 | INV-011 | A changed dependency produces the specified derived alignment and evidence-eligibility effects without mutating content or launching work. |
| IT-012 | INV-012 | Authority is determined only from formal generations, ordered authority events, receipts, and projections, never from paths, filenames, or file completeness. |
| IT-013 | INV-013 | Complete negative, contradictory, and inconclusive outcomes may publish, while operationally invalid work may not. |
| IT-014 | INV-014 | Publication state, record position, alignment, attention, scientific outcome, and evidence eligibility change and display independently. |
| IT-015 | INV-015 | Material claims retain assumptions, scope, uncertainty, provenance, disagreements, and recorded dispositions without silent deletion. |
| IT-016 | INV-016 | Every displayed state and action is a typed backend projection with complete provenance; the UI neither infers authority nor invents an available action. |
| IT-017 | INV-017 | Failure, rejection, conflict, interruption, and cancellation leave the last valid current state unchanged. Submission and cancellation resolve through one compare-and-swap boundary. |
| IT-018 | INV-018 | Every formal change is attributable to one authenticated source, sealed basis, ordered event range, projection set, and receipt, including concurrent commits. |
| IT-019 | INV-019 | Immutable generations remain byte-identical while event replay alone reconstructs every later position, alignment, attention, and eligibility state. |
| IT-020 | INV-020 | Omitted, duplicated, mode-inapplicable, multiply resolved, or stale publication bindings fail with stable diagnostics before commit. |
| IT-021 | INV-021 | Independent implementations reproduce every canonical JSON and journal-root vector, including Unicode and numeric edge cases, or reject values excluded by the digest contract. |
| IT-022 | INV-022 | Lifecycle and withdrawal commands require valid user authority or an exact live delegation, freeze target and control heads, remain idempotent, and cannot be authorized by an agent recommendation. |

## Required test groups

### 1. Schema tests

For every persisted schema:

- validate at least one complete example;
- reject missing required fields;
- reject unknown fields when the schema is closed;
- reject malformed IDs, paths, digests, and enum values;
- verify that schema upgrades are explicit and versioned;
- verify round-trip serialization through the typed implementation model;
- validate the digest and traceability registries against their schemas;
- require every schema-negative fixture to produce its registered validator and
  object paths, so added unrelated failures cannot hide fixture drift.

### 2. Invariant tests

At minimum, test these global invariants:

- only the user-facing launch service can reserve a run;
- agents cannot write outside their role-specific active run roots;
- only the harness can copy or reference verified closed-role outputs into harness-owned `handoffs/`, `artifacts/`, and `submission/` locations;
- frozen formal inputs, harness-prepared contexts, role-context snapshots,
  preference-memory bindings, and on-demand access ledgers cannot change after
  their respective seal points;
- the phase-contract version and digest, exact stage IDs, execution groups,
  role profiles, output contracts, input allowlists, and role write roots remain fixed for the run;
- an operationally failed or structurally incomplete run cannot replace a
  current record;
- a structurally complete negative, contradicted, or inconclusive result may
  become current;
- rejected validation leaves the previous current record unchanged;
- promotion publishes either the complete new record or nothing;
- method-bound work always carries the exact method identity;
- a definition change cannot retain the old method version;
- no status or agent output launches another run;
- historical context is excluded unless the user selected it;
- no immutable content generation contains mutable current-position,
  current-alignment, current-attention, or eligibility fields;
- an immutable generation remains byte-identical after replacement, method
  change, retirement, withdrawal, or invalidation;
- every submitted run artifact retains the same run-local logical location, byte
  length, and digest after publication, recovery, and replay.

### 3. Event and state-projection tests

Exercise every allowed run transition and every prohibited transition. Include
idempotent recovery after interruption, concurrent attempts to publish two
runs to the same current slot, and serialized publications to disjoint method
targets.

Publication and alignment tests must cover the dimensions separately:

- promotion constructs a new formal generation instead of mutating the
  run-local candidate;
- publication, replacement, withdrawal, invalidation, alignment, attention,
  and evidence-eligibility changes are represented by append-only authority
  events;
- record-state and current-index projections are derived from those events;
- every authority event advances a verifiable event-root digest;
- independent implementations reproduce the RFC 8785 event payload digest and the SHA-256 root formed from the 32-byte prior root followed by the 32-byte content digest;
- each authority-event type rejects changes outside its permitted publication, position, alignment, attention, or eligibility family;
- deleting and rebuilding a projection from the same ordered event journal
  reproduces the same state digest;
- replacement changes the derived record position from current to historical
  without changing the earlier generation;
- a dependency change moves derived alignment from exact to unassessed or
  outdated without changing the earlier generation;
- withdrawal and invalidation do not rewrite an earlier scientific outcome;
- an older method-definition digest is never treated as compatible;
- the latest P3 or P4 generation remains current in position while its derived
  alignment is outdated.

### 4. Phase contract tests

Each phase adapter must be tested against its contract, not against another
phase's behavior. A contract test verifies:

- exact command binding to one phase-contract version, digest, and mode;
- required and optional `choice_values` with their declared value kinds, including
  both Phase 1 search scopes and the method required by focused Phase 2;
- exact command-to-manifest choice equality and network-policy no-broadening;
- required and optional frozen inputs plus every mode-scoped prepared context and its declared sources;
- exact binding from materialized inputs and expected outputs to their executable-contract IDs;
- mode-scoped publication bindings from contract output IDs to exact append or
  current-slot operations, target types and slots, bundle components, and
  expected prior generations; mutation probes must separately omit a binding,
  duplicate it, use a binding outside its mode, and alter its frozen target;
- exact stage order and execution groups;
- exact role-specific read allowlists and write roots;
- required outputs;
- schema and identity checks;
- scientific outcome handling;
- promotion semantics;
- downstream alignment and attention effects;
- UI projection fields.

Phase 5 tests must also prove that an older review target belongs to the same
stable method lineage as the selected method. The harness must construct
`p5.review_packet` only from its declared manuscript, reviewer-visible
literature, and instruction sources. The outside reviewer's scientific context
contains only this packet. It receives no project formal record, attention item,
selected history, non-reviewer command detail, project memory, or
project-specific knowledge resource outside the packet. System invariants and a
non-project reviewer profile may accompany it as execution metadata. Specialist
roles receive exactly their declared internal sets.

### 5. Promotion and recovery tests

Inject failures before validation, during validation, while formal generations
are prepared, while authority events are appended, before projections change,
and immediately after the current index changes. After recovery, the project
must have one unambiguous current record, a complete audit trail, and projections
that agree with replayed authority events.

Test at least:

- process termination;
- partial filesystem write;
- stale frozen input;
- method identity changing during launch;
- duplicate run submission;
- duplicate evidence ID;
- permission or disk failure;
- two simultaneous promotions;
- an unbound, multiply bound, mode-inapplicable, or stale publication target;
- a role output that appears directly under a harness-owned destination without a verified source under the producing role root;
- corrupted current record;
- missing run artifact;
- an authority event committed without a matching projection refresh;
- a projection write attempted without its complete ordered source event IDs;
- two events for one subject where an earlier state dimension must carry forward
  and a later named dimension must replace it;
- an event whose prior-state digest does not match deterministic replay;
- a full initial-shaped evidence event that omits its prior-state digest for an
  evidence subject already present at the authoritative checkpoint;
- a receipt that omits, duplicates, or misclassifies a state-only event;
- a publication receipt with a sequence gap, wrong event-root digest, missing
  projection digest, or wrong current-index generation;
- a publication receipt whose `content_sha256` does not equal SHA-256 of the
  RFC 8785 canonical complete receipt with only `content_sha256` omitted;
- a withdrawal receipt that incorrectly invents a new scientific generation;
- a publication or recovery path that moves, deletes, normalizes, truncates, or
  rewrites any submitted run artifact;
- two disjoint publications whose second index rebuild drops the first commit.

### 6. Scientific-record tests

These tests validate declared research structure without pretending to validate
scientific truth. They should verify that:

- every material statement has assumptions, scope, assessment, and provenance;
- every P4 scientific result points to reproducible evidence;
- every successful P4 publication appends its evidence and replaces exactly one evidence-index, empirical-synthesis, implementation-record, and phase-decision slot in one atomic transaction;
- lead decisions cite existing statements or evidence;
- unresolved reviewer concerns remain unresolved until explicitly disposed;
- P3 and P4 records declare the exact sibling basis considered;
- P5 records identify all current upstream records used;
- a later dependency change produces an outdated derived state for affected
  records while preserving their published content.

### 7. Run cancellation and formal control-command tests

Test run cancellation, method lifecycle, and formal withdrawal independently:

- canonical command digests, authenticated actor or exact live delegation, and
  idempotency-key binding;
- cancellation only from `created`, `preparing`, `prepared`, or `running`, with
  `cancellation_requested` as a durable fence and exactly one winner against
  immutable submission;
- legal lifecycle transitions and rejection of a no-op transition;
- exact target generation, catalog, derived-state, current-index, event-sequence, and event-root compare-and-swap;
- lifecycle-only method and catalog replacements that preserve method version, definition digest, and scientific content and create no run;
- withdrawal of only a formal exact generation, with no replacement generation or automatic historical fallback;
- source-discriminated receipts that exclude run-only fields for control commands and preserve complete event and projection proofs;
- identical Web and authorized-remote behavior;
- no formal change after stale, unauthorized, malformed, interrupted, or
  duplicate commands;
- acceptance and pre-commit checks for project, action, exact target, issue time,
  expiry, and append-only revocation of a delegation grant;
- exact raw request byte capture, byte length, artifact digest, and an optional
  validated-command binding that is mandatory at pre-commit and for acceptance;
- an explicitly unresolved target and unauthenticated requester form for
  rejected acceptance-stage requests, without fabricating a trusted command,
  target, or user identity;
- separate acceptance and pre-commit audit events, exact action targets, and a
  committed effect reference for every accepted pre-commit event;
- a complete schema-valid stable CommandError embedded in every rejected audit
  event, identical through Web and remote clients;
- contiguous audit sequences, RFC 8785 content digests, binary prior-root
  chaining, raw-artifact verification, replay, and interruption recovery;
- cancellation-run events that bind the exact RunCancellationCommand,
  requesting user and optional operator and delegation, and accepted audit
  event and root.
These tests implement [S05](scenarios/S05-failed-run.md),
[S11](scenarios/S11-control-commands.md), and the
[control-command contract](09-control-commands.md).

### 8. Role-profile and execution-plan tests

Verify that:

- every role profile names the exact applicable stage IDs;
- instructions, output contracts, memory policy, skills, tools, and knowledge
  resources resolve to immutable versioned artifacts with digests;
- a missing required resource blocks preparation;
- each run-manifest role step matches one contract stage and records its
  execution group, exact input IDs, expected outputs, and role write root;
- the manifest role plan contains only the frozen recipe and no future context,
  artifact, access-ledger, start-time, or closure digest;
- each role invocation has one immutable prepared context, start, and terminal
  closure, with exact digest continuity across the three records;
- a later role start rejects an unsuccessful, missing, or digest-mismatched
  upstream closure or accepted output;
- `RunSubmission` exactly covers the selected role plan with successful closures,
  the final lead closure, and every required accepted output;
- a role cannot read an undeclared formal input, prepared context, or another role's private output;
- accepted handoffs and submission components retain the digest and producing-role identity of their verified source artifact;
- parallel roles in one execution group see the same frozen group-start basis;
- deterministic packing honors exact tokenizer, token, and byte budgets, with
  whole-item omission, frozen compaction, or explicit preparation failure and no
  silent truncation;
- the final role-context snapshot reconstructs every supplied input and permitted
  on-demand read from its ordered hash-chained ledger;
- broker and supported-platform tests deny credential discovery, path traversal,
  symbolic-link, subprocess, network, direct-storage, and cross-role escape;
- the outside reviewer accepts only the closed review packet and metadata
  allowlist, with empty project-memory and on-demand-read sets.

### 9. UI projection tests

The UI must read structured current records, derived record states, and decision
records. Test that it does not infer authority from folder existence, select a
method automatically, or launch a phase because a status changed.

For each phase, test:

- empty state;
- active run state;
- rejected or failed run state;
- current aligned record;
- current record that needs research attention;
- outdated record;
- unavailable phase with a precise reason;
- every user-selectable run mode and context option;
- all typed start, cancel, lifecycle, and withdrawal action branches, including
  cross-branch field rejection and stable disabled reasons;
- canonical labels for publication authority, record position, alignment,
  attention, scientific outcome, evidence eligibility, and execution state;
- monotone view revisions, explicit stale active-run progress, out-of-order
  update rejection, and current-index provenance for empty states.

## Package conformance command

Before implementation work or review, run:

```text
python architecture/tools/validate_package.py
```

This command validates every schema, positive example, targeted negative
example and expected diagnostic, split and aggregate phase contract, digest
contract and vector, exact-method exposition revision, traceability registry,
scenario registration, local documentation link, canonical run state,
cancellation and delegation object, typed command-attempt audit journal, typed action branch, role-context snapshot,
reviewer isolation, command-to-contract materialization, publication-binding
mutation probe, event replay, receipt accounting, and no-automatic-run rule. It
is a fast contract check, not a scientific review.

## Acceptance scenarios

The files under `scenarios/` are normative end-to-end tests. Each scenario must
be implemented as an automated test before the corresponding milestone is
complete.

`contracts/traceability.json` registers each scenario by exact executable ID, document, phase suite, invariant, requirement, test group, and roadmap milestone. Package validation checks exact equality with every phase contract and every `S*.md` file. A non-phase suite such as S11 is registered with an empty phase list rather than attached to an unrelated phase.

Scenario tests should assert:

1. initial formal records and derived state;
2. user action;
3. frozen basis and execution plan;
4. role execution order and visibility;
5. run-local artifacts;
6. validation result;
7. new formal generations and authority events;
8. rebuilt record-state and current-index projections;
9. UI projection;
10. prohibited side effects.

## Recommended test organization

```text
tests/
|-- schema/
|-- domain/
|-- harness/
|-- storage/
|-- contracts/
|-- phases/
|-- scenarios/
|-- recovery/
`-- ui/
```

## Definition of done

A feature is complete only when it has:

- a normative specification section;
- a persisted schema when data crosses a process or run boundary;
- a typed implementation model;
- a validator;
- positive and negative tests;
- an event-replay test when it changes derived project state;
- a recovery test when it changes formal project state;
- an end-to-end scenario;
- a researcher-facing UI projection when applicable;
- an entry in the machine-readable invariant, requirement, test, scenario, and milestone traceability map;
- stable schema-valid failure diagnostics when the feature rejects a command or object;
- documentation generated from, or checked against, the same contract.
