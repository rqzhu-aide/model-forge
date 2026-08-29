# Contract Traceability

## Purpose

This index connects each non-negotiable research-workflow rule to its normative
specification, persisted representation, and acceptance evidence. It gives
programmers a concrete starting point and prevents an implementation detail from
quietly changing the research process.

The word `must` identifies a conformance requirement. A feature is not complete
until every rule it touches has a passing automated test.

The machine-readable [traceability registry](../contracts/traceability.json) is the exact inverse index from every `INV` invariant to its `MF` requirements, `IT` test group, acceptance scenarios, phase contracts, and roadmap milestones. Package validation rejects an omitted or unknown identifier. This checks specification coverage, not whether implementation tests have passed.

## Global rules

| ID | Required behavior | Primary specification | Persisted or test evidence |
|---|---|---|---|
| MF-01 | Only the user may start or rerun a phase. | System principles, run harness, UI contract | Authenticated run command and command-authorization tests |
| MF-02 | An agent writes every artifact only inside its role-specific active run root; only the harness may materialize verified outputs into shared handoff, artifact, or submission locations. | Run harness, storage and authority, role and context contract | Role-root boundary, source-digest, and harness-materialization tests |
| MF-03 | Formal inputs, selected history, prepared contexts, phase contract, role profiles, output contracts, skills, tools, and knowledge resources are frozen before role work starts. | Run harness, role and context contract | Digested run basis and immutability tests |
| MF-04 | The system validates candidate output before it creates formal generations. | Run harness, validation strategy | Validation report and lifecycle tests |
| MF-05 | Publication commits the complete validated change or commits nothing. | Run harness, storage and authority | Receipt-bound generations, event range and root, projection digests, and current-index generation; S05 and S09 |
| MF-06 | Agents propose research records, but only the harness may create formal generations or authority events. | System principles, storage and authority | Role permissions and publication tests |
| MF-07 | Current formal records are the default context. Historical work is opt-in. | System principles, phase contracts | Context policy and selected-history manifest fields; S06 |
| MF-08 | No completion, status change, or agent recommendation starts another run. | System principles, UI contract | Command-authorization tests; all scenarios |
| MF-09 | Publication authority, record position, dependency alignment, research attention, and scientific outcome are separate dimensions. | Research domain model, storage and authority, UI contract | Authority-event, record-state, scientific-record, and projection tests |
| MF-10 | Machine validation may establish structure and provenance, but not scientific truth. | System principles, validation strategy | Validator boundaries in every phase contract |
| MF-11 | A structurally complete record may report a negative, contradictory, or inconclusive scientific result. | Research domain model, phase contracts | Scientific-outcome fixtures and S10 |
| MF-12 | An operationally incomplete or invalid run cannot replace valid current state. | Run harness, storage and authority | Run lifecycle and publication-guard tests; S05 |
| MF-39 | A formal content generation is immutable. Later replacement, alignment, attention, invalidation, or eligibility changes append events and update projections without rewriting it. | Research domain model, storage and authority | Forbidden-field schema tests, digest-preservation tests, and negative fixture |
| MF-40 | Derived record state and the current index are reproducible by ordered whole-field folding of the authority-event journal and agree with the publication receipt. Initial evidence state is allowed only for a subject absent from the authoritative checkpoint and earlier proposed events. | Storage and authority, validation strategy | Event-root, checkpoint-seeded subject-history, intermediate-state, multi-event replay, receipt-category, and state-digest tests |
| MF-44 | Authority-event content and journal-root digests use the specified RFC 8785 payload and prior-root plus content-digest algorithm, and each event type permits only its defined change family. | Research domain model, storage and authority | Cross-implementation hash vectors and illegal-change negative tests |
| MF-47 | Method retirement and reactivation use an authenticated lifecycle command, preserve exact mathematical identity, atomically replace the method and catalog generations, and create no research run. | Control commands, run harness, UI contract | Method-lifecycle schemas, semantic checks, and S11 |
| MF-48 | (Removed 2026-08-28) Formal-generation withdrawal was specified but never implemented; the command, schema, and `withdrawn` state were removed from the package. The id is retired. | - | - |
| MF-49 | Control commands freeze exact target and control-head state, use idempotent compare-and-swap, produce source-discriminated receipts, and behave identically through Web and remote clients. | Control commands, run harness, UI contract | Command digest, stale-basis, receipt-source, and parity tests; S11 |
| MF-51 | Publication, recovery, replay, and later formal changes preserve every submitted run artifact at its run-local logical location with identical bytes and digest. | System principles, run harness, storage and authority | IT-008 artifact-preservation test and S09 |
| MF-52 | Run cancellation uses an authenticated idempotent command, is legal only before immutable submission, and resolves against submission through one lifecycle compare-and-swap boundary. | Run harness, UI contract | Cancellation-command and run-state schemas, race tests, and S05 |
| MF-55 | Remote authority is an exact live delegation over project, action, and target, rechecked at execution. Accepted and rejected command attempts enter an append-only operational audit separate from scientific authority events. | System principles, control commands, run harness | Delegation-grant schema, expiry and revocation tests, audit tests, S05, and S11 |
| MF-56 | Concurrent publications may both commit only when their formal targets are disjoint. Authority events remain globally ordered, receipts bind their actual prior heads, and each current-index rebuild preserves earlier disjoint commits. | Run harness, storage and authority | Concurrency integration tests and S12 |
| MF-57 | Every persisted structured-object or derived-chain digest resolves to a machine-readable contract specifying its construction, included value, and exclusions, with cross-implementation vectors. Artifact pointers bind exact referenced bytes under a referenced-byte contract. Unsupported values or undeclared exclusions fail closed. | Research domain model, storage and authority | Digest-contract registry, Unicode and numeric vectors, referenced-byte checks, and IT-010, IT-019, and IT-021 |
| MF-59 | Every rejected start, cancellation, or lifecycle command returns a schema-valid stable error, changes no formal state, and creates a mandatory append-only operational audit entry. Web and remote clients receive the same code and correction. | Run harness, control commands, UI contract | Command-error schema, parity tests, S05, S11, and S12 |

## Research-object rules

| ID | Required behavior | Primary specification | Persisted or test evidence |
|---|---|---|---|
| MF-13 | Every method has a permanent stable ID and an exact calculation-defining identity. | Research domain model, Phase 2 | Method schema; S02 and S04 |
| MF-14 | Any calculation-defining method change advances the method version; a prose-only revision does not. | Research domain model, Phase 2 | Definition-digest validator and lineage tests; S02 and S04 |
| MF-15 | Method-bound theory, computation, evidence, and manuscript records name the exact method identity used. | Research domain model, Phases 3 to 5 | Frozen-basis fields and cross-record validation |
| MF-16 | A method-version change leaves the latest method-bound generations current in position but gives them outdated derived alignment until replacement runs complete. | Storage and authority, Phases 2 to 5 | Authority-event and record-state transition tests; S04 and S07 |
| MF-17 | A newly published sibling record is available to the next P3 or P4 run but never rewrites or automatically reruns the other phase. | Phases 3 and 4 | Handoff and frozen-basis records; S03 |
| MF-18 | Material claims and decisions retain assumptions, scope, provenance, and unresolved disagreement. | Research domain model | Statement, evidence, decision, and handoff schemas |

## Phase rules

| ID | Required behavior | Primary specification | Persisted or test evidence |
|---|---|---|---|
| MF-19 | P1 appends unique literature records and replaces the current synthesis. | Phase 1 | Literature generation tests; S01 |
| MF-20 | P2 supports a full catalog update or one user-selected focused method update. | Phase 2 | Scope validator; S01 and S02 |
| MF-21 | P2 presents methods but does not select a P3 or P4 branch. | Phase 2, UI contract | Catalog projection and command tests; S01 |
| MF-22 | P3 replaces the complete current theory record for one exact method identity. | Phase 3 | P3 contract tests |
| MF-23 | Each P3 run executes theorist, data analyst, then research lead. | Phase 3 | Stage and role-plan order test; S03 |
| MF-24 | P4 appends immutable evidence and atomically replaces the evidence index, empirical synthesis, implementation record, and phase decision for one exact method identity. | Phase 4, storage and authority | Four-slot publication and evidence-lineage tests; S03 and S07 |
| MF-25 | Each P4 run executes data analyst, theorist, then research lead. | Phase 4 | Stage and role-plan order test; S03 |
| MF-26 | P3 and P4 are independently user-launchable after P2. | Phases 3 and 4, UI contract | Eligibility projection tests; S03 |
| MF-27 | P5 requires current P1 and selected-method records, current P3 and P4 records for the exact method identity, readable artifacts, and no blocking integrity state. | Phase 5 | Readiness validator; S08 |
| MF-28 | P5 maintains one current complete manuscript and replaces it atomically. | Phase 5 | Manuscript slot and replacement tests; S08 |
| MF-29 | P5 review roles work from one frozen manuscript snapshot through distinct allowlists. The outside reviewer receives only the harness-prepared `p5.review_packet` as scientific context, with no project records, attention, selected history, project memory, or project-specific knowledge outside it. | Phase 5, role and context contract | Prepared-context, profile-resource, and role-specific read tests; S08 |
| MF-41 | A P5 review target may use an older version only within the selected stable method lineage. It must never come from another method. | Phase 5 | `same_stable_method` contract and negative lineage test |

## User-interface rules

| ID | Required behavior | Primary specification | Persisted or test evidence |
|---|---|---|---|
| MF-30 | The Web UI projects canonical structured records and never infers success from folder presence. | UI contract | View-model and adversarial-folder tests |
| MF-31 | Every phase explains availability, current basis, material changes, uncertainty, and available user actions. | UI contract, phase contracts | Projection fixtures and browser tests |
| MF-32 | Method tables report publication position, alignment, attention, and outcome separately for P3 and P4. | UI contract, Phase 2 | Method-overview projection tests |
| MF-33 | The Web UI and remote-control client invoke the same application commands and authorization rules. | UI contract, run harness | Command parity and authorization tests |
| MF-58 | Every displayed start, rerun, cancel, or lifecycle action is a typed discriminated descriptor with stable availability and reason fields. Publication state, record position, alignment, attention, outcome, and evidence eligibility use canonical display mappings. | UI contract, system principles | Action-descriptor schema and projection tests |

## Reproducibility and executable-contract rules

| ID | Required behavior | Primary specification | Persisted or test evidence |
|---|---|---|---|
| MF-34 | Every role step freezes an applicable stage ID, execution group, exact read allowlist, role-specific write root, versioned role profile, instructions, output contract, memory policy, skills, tools, knowledge resources, visibility, and output obligations. | Role and context contract, run harness | Role-profile and run-manifest schemas; execution-plan tests |
| MF-35 | A missing required output contract, skill, tool, knowledge resource, artifact digest, or role-profile digest blocks preparation rather than silently weakening the role. | Role and context contract | Resource-resolution and preparation-failure tests |
| MF-36 | Roles communicate material claims, assumptions, uncertainty, disagreement, and next checks through explicit run-local handoffs rather than hidden shared memory. | Role and context contract, phase contracts | Handoff schema, access-manifest tests, role-order tests |
| MF-37 | Prose phase contracts and the executable registry change together and remain machine-valid. | Phase contracts, executable contracts | Phase-contract schema, split-registry equality check, package validator |
| MF-38 | User authorization, immutable run basis, prepared contexts, lifecycle history, formal generations, authority events, derived state, and publication receipt remain distinct objects. | Research domain model, run harness, storage and authority | Run-command, run-manifest, run-state, scientific-record, authority-event, record-state, and publication-receipt schemas |
| MF-42 | Every harness-prepared context declares its source formal inputs, source user choices, applicable modes, immutable content requirements, and permitted role reads. | Run harness, executable contracts, role and context contract | Phase-contract prepared-context and undeclared-read tests |
| MF-43 | Every contract-selected manifest input and expected output names the exact executable-contract obligation that it materializes. Prepared contexts also retain their exact source input and user-choice IDs. | Run harness, executable contracts | Manifest-binding and contract-materialization tests |
| MF-45 | Every phase contract declares mode-scoped publication bindings from exact output IDs to append or current-slot operations, target types and slots, bundle components, and expected prior generations; the manifest seals the resolved bindings. | Run harness, executable contracts, research domain model | Publication-binding completeness, ambiguity, and stale-target tests |
| MF-46 | Shared handoff and submission artifacts are harness-owned materializations of verified immutable outputs from a producing role root, never direct role writes. | Run harness, role and context contract | Role-root escape tests and source-to-materialization digest tests |
| MF-50 | Every run command binds one exact phase-contract version, digest, and mode, and supplies only that mode's required or optional choice IDs with values of the declared kind. The manifest copies those choices exactly. | Research domain model, run harness, executable contracts | Eight-mode command resolution, P1 scope coverage, choice-type, missing-choice, stale-contract, and command-to-manifest tests |
| MF-53 | Every role invocation freezes an exact context snapshot, deterministic packing order, token and byte budgets, preference-memory basis, compaction artifact when used, and access ledger for permitted on-demand reads. Silent truncation is prohibited. | Role and context contract, run harness | Role-context-snapshot schema, overflow tests, reconstruction tests, and S08 |
| MF-54 | Role isolation is enforced by a capability-based storage broker and the supported-platform process sandbox. Roles receive no formal-storage credentials, and path, link, subprocess, and direct-storage escape attempts fail. | Role and context contract, run harness, storage and authority | Capability and platform escape tests |
| MF-60 | The sealed manifest role plan is a recipe only. Each executed stage has an immutable prepared context, invocation start, and terminal closure. A downstream stage uses only successful upstream closures and exact accepted outputs, and immutable submission requires the complete ordered successful closure chain, final lead closure, and every required output. | Run harness, role and context contract, validation strategy | Prepared-context, invocation-start, invocation-closure, downstream mismatch, and RunSubmission tests |

## Trusted-local execution rules

These rules implement the trusted local Hermes boundary of
[ADR-012](decisions/ADR-012-trusted-local-hermes-execution.md). They are
machine-validated together with the global rules above, and each is exercised
by at least one scenario in the trusted-local suite (S13-S24).

| ID | Required behavior | Primary specification | Persisted or test evidence |
|---|---|---|---|
| MF-61 | Role definitions are configuration-managed. SOUL, base configuration, recommended and custom skills, and library guidance come from the configuration interface; an update that conflicts with a customization requires an explicit user choice and never overwrites it silently; provisioning is atomic with rollback. | ADR-012 items 3 and 4, role and context contract | Role-configuration service tests; S13 |
| MF-62 | A first persistent run, and any explicit fresh mode, starts with clean project-role state: no memory and no session snapshot copied from another project, role, or the global profile. | ADR-012 item 5, run harness | Run-profile assembler state-policy tests; S14 |
| MF-63 | A persistent rerun receives exactly the latest promoted memory and safe session snapshot, byte-identical, with complete provenance recorded in the manifest. | ADR-012 items 5 and 6, run harness | Snapshot-identity and promotion-digest tests; S15 |
| MF-64 | The outside reviewer always starts from fresh, ephemeral runtime state with no project-role memory or session, unless a later user decision and architecture change explicitly allow otherwise. | ADR-012 invariant, role and context contract | Reviewer-state-policy tests; S16 |
| MF-65 | Exit code zero alone is never sufficient. Missing, malformed, wrong-basis, or undeclared outputs fail validation and change no current state. | ADR-012 invariant, run harness, validation strategy | Output-inventory and verdict tests; S17 (pilot attempt 1) |
| MF-66 | A changed Hermes installation surfaces at preflight. The executable path, version, and immutable identity are recorded; a real version change is shown to the user and recorded in the next manifest, and update-check noise never causes false drift. | ADR-012 item 8, run harness | Preflight drift tests; S18 (pilot attempt 2, commit 7986f12) |
| MF-67 | Cancellation and timeout terminate the complete Hermes process tree and reach verified quiescence before closure; no descendant is left unaccounted. | ADR-012 invariant, run harness | Process-tree termination and quiescence tests; S19 |
| MF-68 | Application restart reconciliation inspects the recorded durable process identity and never launches a replacement invocation automatically. | ADR-012 invariant and item 7, run harness | Durable-identity and reconciliation tests; S20 |
| MF-69 | A stale lock owner cannot promote state or release another owner's project-role lock; fencing tokens and leases protect ownership. | Closure plan fixed rule 8, run harness | Lock-fencing and stale-owner tests; S21 |
| MF-70 | Failed promotion preserves the last known good formal and project-role state byte-identically; current pointers advance only after the complete promotion succeeds. | ADR-012 invariant, run harness, storage and authority | Promotion-failure injection tests; S22 |
| MF-71 | Logs are streamed under fixed bounds. Output floods and over-long lines cannot block process completion or grow memory without bound. | ADR-012 item 7, run harness | Bounded-log and flood tests; S23 |
| MF-72 | Session snapshots use a verified procedure: read-only source, SQLite online backup with integrity check, quiescence flag, and fail-fast refusal of a busy source. A live database file is never copied. | ADR-012 item 5, run harness | Session-snapshot and busy-abort tests; S24 |
| MF-73 | A correction command is accepted only for a run in a correctable terminal state (failed or rejected with correctable findings); all other states refuse with a stable error. | K-1 correction command path design | Correction command foundation and acceptance-gate tests |
| MF-74 | A correction command may name only outputs the corrected role closure actually declared; any other scope refuses with a stable error. | K-1 correction command path design | Correction command foundation and scope-gate tests |
| MF-75 | Correction attempts are bounded per run: when the packaging and scientific bounds are spent, further correction commands refuse with a stable error and the run displays as completed with correction still required. | K-1 correction command path design | Correction command foundation and bounds tests |

## Machine-readable coverage

`contracts/traceability.json` is the canonical coverage registry. Its scenario entries use the exact identifiers accepted by executable phase contracts. A scenario with no phase contract, such as S11, names an empty `phase_contracts` list and remains part of the control-command suite. The trusted-local scenarios S13-S24 name the same empty list and form the trusted-local execution suite. The validator checks both directions: every declared identifier exists, every invariant and requirement is covered, every scenario document is registered exactly once, and every phase-contract reference agrees with the registry.

## Change procedure

When a proposed change alters one of these rules:

1. update the governing normative document;
2. record an architecture decision when two reasonable behaviors would differ;
3. update every affected schema and example;
4. update the linked scenarios and negative tests;
5. update this table in the same change;
6. implement only after the revised contract is accepted.

If code behavior and this package disagree, the discrepancy is a contract
failure. Programmers must not resolve it by silently weakening a test.
