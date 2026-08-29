# Storage and Authority

## 1. Purpose

Storage must preserve scientific provenance without forcing researchers to navigate implementation details. This document defines logical namespaces, information layers, formal authority, immutable generations, phase-specific update semantics, and downstream currency.

Physical storage may use a filesystem, database, or object store. The logical contracts remain the same.

> **Lane scope.** The formal-authority model here (immutable generations,
> authority events, current index) governs the formal lane; the supervised
> lane (ADR-012, see [02a](02a-supervised-run-walkthrough.md)) keeps its own
> durable state (run seals, launch records, validation and promotion records
> in `hub.sqlite3`, immutable `outputs/` snapshots) and does not write formal
> generations. The two stores are separate today.

## 2. Three information layers

Information layers describe format and retrieval depth only.

| Layer | Purpose | Typical contents |
|---|---|---|
| Primary artifact | Preserve the detailed scientific work and source evidence | Proof manuscript, source paper, code, data reference, simulation output, figure, frozen manuscript |
| Structured scientific record | Make claims, assumptions, evidence, changes, and dependencies machine-addressable | Method record, theory record, evidence index, empirical synthesis, review issues |
| Compact decision view | Help a researcher decide what to do next | Decision brief, method table row, phase summary card |

The layer is stored as artifact metadata. It must not be inferred from a directory name.

The layers do not form an authority hierarchy. A primary artifact may be run-local and invalid. A compact decision view may be the validated presentation of a current formal record. The structured record links the view to the supporting artifacts.

## 3. Formal authority model

One status field cannot express all relevant scientific states. Store these dimensions separately.

Every immutable content generation records a frozen `authority_at_creation`. That field describes the authority under which the bytes were created and never changes. Current publication state, record position, alignment, research attention, and evidence eligibility are derived from append-only authority events and exposed through record-state projections and the current index. They are not fields that mutate inside a content generation.

### 3.1 Derived publication state

| State | Meaning | Eligible as ordinary downstream input? |
|---|---|---|
| `run_local` | Work is mutable inside an active run | No |
| `submitted` | Run output is immutable and awaiting or undergoing validation | No |
| `validated` | Submission passed validation but publication has not committed | No |
| `formal` | Immutable generation was published with a receipt | Only when selected as current and suitably aligned |
| `invalid` | Object failed integrity or formal validation | No |

### 3.2 Derived record position

| Position | Meaning |
|---|---|
| `current` | Active formal generation for its logical record |
| `historical` | Preserved earlier formal generation |
| `none` | Object is not a formal record generation |

Supersession is an explicit relation between generations, not a deletion state. A historical generation may have been superseded by an ordinary update, corrected by a later generation, or displaced after a method change.

### 3.3 Alignment state

| State | Meaning |
|---|---|
| `exact` | Hard-dependency identities and digests match the current basis |
| `compatible` | A non-calculation dependency change was examined and judged not to affect the stated result, with justification |
| `unassessed` | A relevant change has not yet been scientifically assessed |
| `outdated` | The record depends on an earlier calculation-defining basis |
| `not_applicable` | No dependency of this type applies |

Compatibility is a scientific judgment made during a run. A mathematical-definition digest mismatch is always `outdated` and can never be assessed as `compatible`.

### 3.4 Research attention and scientific outcome

Research attention is represented by open `AttentionItem` objects with severity and disposition. Scientific outcome is represented by `ScientificOutcomeAssessment`. Neither changes publication state.

For example, a Phase 3 record may be:

```text
content_generation.authority_at_creation = formal_generation
content_generation.scientific_outcome = partially_supported
record_state.publication_state = formal
record_state.record_position = current
record_state.alignment.state = exact
record_state.research_attention.level = monitor
```

This is a coherent formal record, not a failed run.

## 4. Authority transitions

The arrows below describe derived state produced by append-only events. They do not describe mutation of an immutable content generation.

```text
run-local candidate: run_local -> submitted -> validated or invalid
promotion: create formal generation + publication event carrying current position
replacement: publication event for new current generation + supersession event carrying the prior generation's historical position
```

Only the harness may advance run-local submission state. Only atomic promotion may create a formal content generation or append events that change the current projection.

Publication position, alignment, attention, and evidence eligibility may change after publication. Each change appends an authority event and rebuilds the derived projection. It never mutates the immutable generation, whose `authority_at_creation`, frozen basis, scientific content, and digest remain fixed.

### 4.1 Event-type and hash contract

The authority-event schema must enforce these legal change families:

| Event type | Permitted derived-state change |
|---|---|
| `published` | Establish formal publication and, for a record generation, current position; may carry its creation-time alignment and attention projection |
| `superseded` | Move one formal record generation from current to historical and identify its replacement |
| `invalidated` | Set publication to invalid and position to historical or none, with an integrity or validation reason |
| `alignment_recomputed` | Replace only the derived alignment assessment |
| `attention_changed` | Replace only the derived research-attention assessment |
| `evidence_eligibility_changed` | Change eligibility only for an evidence item; within the same publication transaction it may also establish the formal, alignment, and attention values required for a coherent first evidence projection |

An event with a change outside its event-type family is invalid. Position changes occur only through publication, supersession, or invalidation, not through an unconstrained generic event.

For hashing, form the event payload by omitting `content_sha256` and `event_root_sha256` and serializing the remaining complete object with RFC 8785 JSON Canonicalization Scheme. The content digest is SHA-256 of those payload bytes. Decode the prior-root and content-digest hexadecimal strings to 32 bytes, concatenate them in that order, and hash the 64 bytes with SHA-256 to obtain the new event root. The first event uses 32 zero bytes as its prior root.

Projection replay processes events strictly by sequence. For each record generation
or evidence item, a later event replaces each complete top-level state dimension
that it names; replay never deep-merges two alignment, attention, or eligibility
objects. Unnamed dimensions carry forward. Record generations begin with
`evidence_eligibility` set to `not_applicable`; evidence items begin with
`record_position` set to `none`. The final projection lists the complete
ordered event history for that subject through the checkpoint and uses the
checkpoint head time. An event that depends on a prior subject state records that
state's canonical digest. The complete initial evidence projection may omit this
digest only when the evidence subject is absent from the authoritative checkpoint
and all earlier events in the proposed transaction. Replay validation seeds its
subject set from that checkpoint and rejects any later no-prior event for the same
subject, even if the event repeats the complete initial field set.

### 4.2 Canonical JSON digest contract

Every persisted digest whose preimage is a parsed JSON value follows [the machine-readable digest registry](../contracts/digest-contracts.json). Each entry names the object schema, instance boundary, digest location, exact payload subtree or included-field projection, exclusions, and construction. An `ArtifactPointer.sha256` instead hashes the exact referenced artifact bytes and is verified by the storage service without parsing or reserializing them. Implementations must resolve the applicable structured-digest contract before hashing and fail if no supported entry exists.

RFC 8785 is normative for JSON preimages. Conforming production implementations must support its I-JSON number domain and produce ECMAScript-compatible binary64 number serialization. They must also reject duplicate property names, invalid Unicode scalar values, non-finite numbers, and values that cannot be represented under the contract. The serializer preserves strings as supplied and performs no Unicode normalization.

The bundled Python reference in `tools/jcs.py` intentionally supports only integers from $-(2^{53}-1)$ through $2^{53}-1$. It rejects floating-point values and integers outside that interval instead of silently producing non-interoperable bytes. A production service may use a complete RFC 8785 library, but it must pass the fixed Unicode and numeric vectors in `examples/digest-vectors.example.json` before it can write formal digests.

The method-definition contract is narrower than the whole method record. `definition_sha256` hashes only `mathematical_definition.canonical_definition`. The method artifact, locator, summary, and other exposition remain covered by the whole-record `content_sha256`. Therefore an exposition-only revision preserves exact method identity while changing artifact and whole-record integrity digests.

## 5. Logical namespaces

### 5.1 Run namespace

```text
project/runs/{phase_id}/{run_id}/...
```

Properties:

- Allocated before execution.
- Agents write only within their unique `roles/{sequence}-{role_id}/` roots.
- After a role step closes, the harness verifies its outputs and copies or content-addresses accepted artifacts into harness-owned `handoffs/`, `artifacts/`, and `submission/` locations.
- Submission and all referenced artifacts become immutable.
- Never used as a mutable formal current record.
- Preserved at their run-local logical locations for provenance and diagnosis. Physical archival cannot change their logical references, bytes, or digests.

### 5.2 Immutable formal generations

```text
project/generations/{record_type}/{record_id}/{generation_id}/
  record.json
  artifacts.json
  source-run.json
  authority-at-creation.json
```

Properties:

- Written only during promotion.
- Content-addressed and immutable after commit.
- Self-describing schema and digest metadata.
- Traceable to one source run and publication receipt.
- Carries frozen `authority_at_creation`.
- Never carries mutable current position, current alignment, current attention, or current evidence eligibility.

Generation identity is assigned at promotion: the publisher derives `generation_id` from digest-bound inputs (project, run, publication binding, current slot, record type, document digest, and artifact identity) over the final sealed bytes. Run-local candidates never carry generation identity. The closure schemas do not require `generation_id` of candidates, and the harness strips any candidate-supplied `generation_id` or `generation_number` before sealing, so an agent cannot fabricate provenance in a harness-owned field.

### 5.3 Current projections

```text
project/records/literature/current/
project/records/method-catalog/current/
project/records/methods/{method_id}/definition/current/
project/records/methods/{method_id}/theory/current/
project/records/methods/{method_id}/empirical/current/
project/records/methods/{method_id}/manuscript/current/
```

A `current/` location is a resolver projection of the current index. It may be implemented as a pointer, database view, manifest, or materialized read-only copy. It must never be the only copy of a formal generation.

A resolver joins the immutable content generation to its derived record-state projection. Rebuilding or replacing a projection never rewrites the referenced generation.

### 5.4 Control namespace

```text
project/control/current-index/current.json
project/control/current-index/generations/{index_generation_id}.json
project/control/record-state/{subject_kind}/{subject_id}.json
project/control/authority-events/{sequence}-{event_id}.json
project/control/publication-journal/{publication_id}.json
project/control/command-request-artifacts/{request_sha256}.bin
project/control/command-attempt-audit/{sequence}-{audit_event_id}.json
project/control/replay-checkpoints/{checkpoint_id}.json
```

Authority events and publication receipts are append-only. Each receipt carries
a self-digest computed over its complete RFC 8785 canonical object with only the
self-digest field omitted. One authority-event schema represents publication,
position, dependency impact, alignment, attention, invalidation,
and evidence-eligibility events. One record-state schema represents derived
state for both record generations and evidence items. Record-state,
current-index, and replay-checkpoint objects are projections that may be
discarded and rebuilt. This namespace is backend-owned. Researchers should not
need to edit it, and the UI obtains typed views through services rather than
reading control files directly.

The command-request artifact store and command-attempt audit are operational
control records, not scientific authority records. Each retained request keeps
the exact bytes received before parsing. Each audit event binds those bytes to
the action check, any validated command and exact target, requesting identities,
delegation results, stable error or committed effect, and its tamper-evident
audit root. No audit event may change a formal generation, derived record state,
or the current index.

## 6. Logical reference contract

Formal records should use stable logical references:

| Reference | Meaning |
|---|---|
| `record://literature/current` | Resolver query for the current literature record |
| `record://method/{method_id}/definition/current` | Resolver query for a current method definition |
| `generation://{record_type}/{record_id}/{generation_id}` | Immutable formal generation |
| `run://{run_id}/artifact/{artifact_id}` | Immutable artifact in a submitted run |
| `statement://{statement_id}` | Addressable scientific statement |
| `evidence://{evidence_id}` | Addressable evidence item |

Persistent frozen dependencies use generation, statement, evidence, or run-artifact references with digests. A `record://.../current` reference is permitted only as a query that is resolved and frozen during preparation.

Resolvers must reject:

- Path traversal.
- Cross-project references without explicit policy.
- Missing or mismatched digests.
- References to mutable role workspaces.
- References whose schema is unsupported.

## 7. Formal generation contents

Each immutable formal generation contains or resolves:

- Canonical structured record.
- Source run and submission digest.
- Frozen `authority_at_creation`.
- Frozen hard and contextual input references.
- Exact method identity when applicable.
- Primary artifact inventory.
- Compact decision view.
- Scientific statements, evidence, outcome, and the alignment and attention assessments made on the generation's frozen basis.
- Change summary from the prior generation.
- Schema versions.
- Publication receipt reference.

A content generation must not store mutable record position, current alignment, current attention, or current evidence eligibility as if those values were part of its immutable scientific content. Those values are resolved from the control projections and their supporting events.

Large primary artifacts may remain in content-addressed run or object storage. The formal generation then stores a verified immutable reference. The published record must remain usable even if temporary caches are removed.

## 8. Phase-specific storage semantics

### 8.1 Phase 1: cumulative literature

Phase 1 maintains:

- One deduplicated literature corpus index.
- Immutable source cards or source records.
- Search and screening provenance.
- One replaceable current literature synthesis.
- Explicit duplicate, correction, retraction, and withdrawal relations.

A new run normally adds unique references and updates the synthesis. It does not copy the complete corpus into every run output or replace unchanged source records. A corrected bibliographic record creates a new generation linked to the earlier one.

### 8.2 Phase 2: method catalog and definitions

Phase 2 supports two scopes:

- Full catalog update.
- Focused update of one selected method.

It maintains:

- One current method catalog.
- One stable lineage per method.
- One current method definition generation for each active or retired stable method ID.
- Literature provenance for each method and claim.
- Retirement state without deletion.

Focused publication must not silently rewrite unrelated methods. Catalog-wide summaries may be recomputed as part of the same atomic transaction.

Method retirement is a Phase 2 portfolio action on the method lifecycle state.

### 8.3 Phase 3: replaceable complete theory

Phase 3 maintains one complete current theory record for each stable method. The record names the exact method version and definition digest. Every promoted rerun publishes a full new generation rather than a patch that requires previous runs to interpret.

A method-definition change does not itself replace the current theory generation. It appends an authority event that changes the generation's derived alignment to `outdated` until a user-started P3 rerun publishes a complete record for the new exact method identity. Only that successful replacement moves the previous theory generation to history. The current theory record must link every material statement to the appropriate proof location, counterexample, or unresolved obligation.

### 8.4 Phase 4: cumulative evidence, four-slot current package

Phase 4 maintains:

- Immutable empirical evidence items.
- One current evidence index that classifies their applicability.
- One current empirical synthesis for the selected method identity.
- One current implementation record that identifies the code, environment, configuration, and reproducibility basis.
- One current phase decision that summarizes the exact current evidence and user-relevant change.

A rerun appends new evidence items and atomically publishes replacement generations for the evidence index, empirical synthesis, implementation record, and phase decision. Earlier evidence is never silently overwritten. Evidence computed for an earlier mathematical definition is always `outdated` for the current method and cannot be reclassified as compatible. A new P4 run may reuse data, baselines, or code components when justified, but selected-method results must be computed under the exact current definition and receive new evidence identities.

Preliminary and comprehensive are user-selected scopes. They are not inferred from run number.

### 8.5 Phase 5: replaceable complete manuscript

Phase 5 maintains one complete current manuscript per selected method or manuscript target. Each generation freezes the exact P1, P2, P3, and P4 formal records it uses.

An upstream hard dependency change appends an authority event that alters the manuscript's derived alignment state while leaving its record position `current`. The manuscript remains readable, but it cannot satisfy exact-current use until a user-selected P5 rerun publishes an aligned replacement. Only that replacement moves the prior manuscript generation to history.

## 9. Publication and current-index update

The current index is the sole backend source for current-record resolution. A promotion transaction must:

1. Resolve the sealed, mode-scoped publication bindings and reject any missing, ambiguous, or stale source-to-target operation.
2. Verify expected prior current generations and the preceding committed event sequence.
3. Install all new immutable content generations from only the outputs and bundle components named by those bindings, with frozen `authority_at_creation`.
4. Append authority events for publication, supersession, alignment, attention, eligibility, and dependency impact. Position changes are carried only by the applicable typed event.
5. Replay the complete proposed event sequence to compute derived record-state projections for record generations and evidence items.
6. Write a complete replacement current index from those projections.
7. Commit generations, events, projections, the index, and publication receipt atomically.

The prior index remains recoverable. Record-state and materialized `records/.../current/` views are projections of immutable generations plus the ordered event log. Starting from an empty state or a verified checkpoint, replay must reproduce the same projection digests and current index recorded by the latest publication receipt. A sequence gap, duplicate event, digest mismatch, or replay disagreement fails closed and blocks new publication.

## 10. Retention and cleanup

The system distinguishes scientific records from reproducible caches:

- Immutable submissions, formal generations, publication receipts, exact input manifests, and evidence needed for scientific traceability must be retained.
- Operational audit events and their exact raw request artifacts follow an explicit security-audit retention and archival policy. Any retained range must preserve its sequence boundaries and verifiable chain roots.
- Download caches, rendered previews, dependency installations, and reconstructible temporary files may be cleaned by policy.
- Large data may be retained externally when its immutable identity, access conditions, and provenance are recorded.
- Deletion or archival must never leave a formal generation with unresolved required artifacts.

Retention policy is explicit and project-configurable. Cleanup is never inferred from age alone for authoritative scientific objects.

## 11. Integrity and security requirements

- Canonical structured objects use the exact payload and exclusions in `contracts/digest-contracts.json`, RFC 8785 serialization, and SHA-256. Implementations fail closed when an object or numeric value is outside their supported contract.
- Each authority event records the prior event-journal root, the RFC 8785 payload digest excluding its two computed digest fields, and the new root computed as SHA-256 of the 32-byte prior root followed by the 32-byte content digest. The first event uses 32 zero bytes as its prior root.
- Each operational audit event applies its registered RFC 8785 content contract and independently advances the command-audit root as SHA-256 of the 32-byte prior audit root followed by the 32-byte content digest. The raw request digest covers the exact referenced bytes before parsing or normalization.
- Each publication receipt records a contiguous event range, its prior and new roots, every derived projection digest, and the committed current-index generation and digest. It categorizes each event exactly once as a record change, cumulative-object change, or derived-state-only change.
- All external artifacts are verified on ingestion and again before publication.
- User-provided filenames are labels, not trusted paths.
- The storage service enforces project boundaries and role write scopes.
- Secrets and private credentials are referenced through a secrets service and never stored in run artifacts.
- Personal or restricted data carry access metadata that survives publication and UI projection.
- Formal correction operations are append-only and auditable.

## 12. Required storage tests

Implementation must prove:

1. Information layer changes do not change authority.
2. A current projection can be rebuilt entirely from immutable generations, append-only authority events, and the publication journal.
3. A P3 rerun replaces the complete current theory record without deleting history.
4. A P4 rerun appends evidence and atomically replaces the evidence index, empirical synthesis, implementation record, and phase decision.
5. A focused P2 run does not modify unrelated method definitions.
6. A method definition change marks dependent records as mismatched without deleting them.
7. Digest mismatch prevents resolution and publication.
8. Cleanup removes only reconstructible or policy-approved material.
9. Concurrent publication cannot produce a mixed current index.
10. Supersession, method changes, attention changes, and evidence reclassification leave committed generation bytes and digests unchanged.
11. Event replay from an empty state and from a verified checkpoint yields identical record-state and current-index digests.
12. Independent implementations produce the fixed canonical bytes and SHA-256 values for all accepted Unicode and numeric digest vectors and reject every fail-closed vector.
13. An exposition-only method revision preserves `definition_sha256` and the method version while changing its artifact digest and whole-record `content_sha256`.
14. Publication, recovery, replay, archival, and later formal changes preserve every submitted artifact at the same run-local logical location with identical bytes and digest.
15. Accepted, rejected, schema-invalid, and unauthenticated command attempts preserve their exact raw request bytes and replay to the same operational audit root.
16. A sequence gap, altered request artifact, content-digest mismatch, or broken operational audit root blocks later commands while leaving scientific authority state unchanged.
