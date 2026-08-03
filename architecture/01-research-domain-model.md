# Research Domain Model

## 1. Purpose

This document defines the scientific objects that the run harness stores, validates, relates, and projects. It describes meaning and relationships. Machine representations belong in `schemas/`.

The model separates four kinds of state:

- Formal authority: whether the record has been validated and published.
- Scientific identity: which exact project, method, run, and input generations the record concerns.
- Scientific assessment: what the work supports, contradicts, or leaves unresolved.
- Presentation layer: how much detail a particular file exposes.

No field in one category should be overloaded to represent another.

## 2. Identity conventions

### 2.1 Stable identifiers

Stable identifiers are opaque, permanent, and never reused. A display name may change without changing identity.

Recommended formats:

| Object | Example |
|---|---|
| Project | `prj_01j...` |
| Method | `mth_01j...` |
| Run | `run_01j...` |
| Record | `rec_01j...` |
| Generation | `gen_01j...` |
| Artifact | `art_01j...` |
| Statement | `stm_01j...` |
| Evidence item | `evd_01j...` |
| Attention item | `att_01j...` |
| Review issue | `iss_01j...` |
| Publication receipt | `pub_01j...` |

The exact identifier algorithm may be UUIDv7, ULID, or an equivalent collision-resistant scheme. IDs must not encode mutable names, phase status, or filesystem paths.

### 2.2 Immutable generations

A formal record has a permanent `record_id` and one or more immutable generations. Publishing a change creates a new `generation_id`. The `current` relation points to one generation; it does not modify an existing generation.

Every immutable object has a canonical representation and `content_sha256`. All hashed JSON uses RFC 8785 JSON Canonicalization Scheme. The machine-readable registry in `contracts/digest-contracts.json` identifies the exact payload, digest location, excluded fields, and hash construction for each object. Implementations must not substitute ordinary key-sorted JSON serialization.

### 2.3 Logical references

Relations use typed references containing at least:

```json
{
  "kind": "record_generation",
  "record_id": "rec_01j...",
  "generation_id": "gen_01j...",
  "content_sha256": "..."
}
```

A frozen run input must reference a generation, not `current`. User-facing links may resolve `current`, but persisted scientific dependencies may not.

## 3. Core objects

### 3.1 Project

A `Project` is the research workspace and namespace for all other objects.

Required meaning:

- Research question or program.
- Scientific domains and intended use.
- User ownership and delegated operators.
- Active phase definitions and schema versions.
- Formal record index.

The project does not store a single global phase status because different methods may be at different stages.

### 3.2 Phase definition

A `PhaseDefinition` is a versioned contract specifying:

- Scientific purpose.
- User-selectable modes and context.
- Required and optional input types.
- Role order and visibility rules.
- Required run-local outputs.
- Validation policy.
- Publication policy.
- Downstream impact rules.
- UI projection fields.

The phase-definition version is frozen into every run manifest. Updating the specification does not reinterpret completed runs.

### 3.3 Method record

A `MethodRecord` represents one research method with permanent identity and revision lineage.

Required components:

- `stable_id`.
- Display name and aliases.
- Lifecycle state: proposed, active, or retired.
- Monotonically increasing positive-integer method version.
- Authoritative mathematical definition.
- `definition_sha256` computed from the canonical mathematical definition only.
- Whole-record `content_sha256` for integrity.
- Parent method version or derivation relation, when applicable.
- Reason for revision.
- Literature provenance.
- Current scientific summary and known limitations.

Retirement is a method-portfolio lifecycle decision. Withdrawal applies only to the authority state of a specific formal content generation and is not a `MethodRecord` lifecycle state.

The authoritative mathematical definition must include every object that changes the calculation or mathematical claim. Its exact identity payload is `mathematical_definition.canonical_definition` and has these required components:

- Definition schema version.
- Target or estimand.
- Objective or estimating equation.
- Ordered algorithm or update rule.
- Constraints and normalization.
- Tuning definitions and selection rules.
- Calculation-defining assumptions and their mathematical roles.

The definition digest is SHA-256 of the RFC 8785 bytes for that object only. Artifact pointers, locators, summaries, rationale, literature discussion, limitations, and presentation-only notation outside this object are excluded. Arrays in the payload are ordered scientific content. Changing their order changes identity unless the producing contract first defines and applies a deterministic set ordering. RFC 8785 preserves string code points without Unicode normalization, so producers must validate the intended exact strings before sealing the payload.

An exposition-only edit may create a new method-record generation, artifact digest, and whole-record digest, but it preserves the method version and definition digest. Each calculation-changing edit advances the method version by one revision and produces a new definition digest. Version changes cannot skip backward or reuse an earlier number. A developer must not infer this distinction from a whole Markdown file hash.

An exact method identity is:

```json
{
  "stable_id": "mth_01j...",
  "version": 2,
  "definition_sha256": "..."
}
```

All method-bound records must embed this identity.

### 3.4 Run command

A `RunCommand` records the user's requested operation before input resolution.

It contains:

- Authenticated user and optional delegated operator.
- Phase, exact phase-contract version and digest, and run mode.
- Exact `choice_values` keyed by the selected contract's choice IDs. These values contain the method, instructions, Phase 1 search scope, and selected history when applicable.
- Global context and optional resource policies.
- Request time and idempotency key.

The command is an authorization boundary. The harness may resolve defaults but may not expand the scientific scope beyond it.

### 3.5 Run manifest

A `RunManifest` is the immutable prepared basis of one run.

It contains:

- Run ID and source command.
- Exact phase-contract version and digest copied from the source command.
- Selected mode and an exact copy of the command `choice_values`.
- Exact method identity inside the contract-defined method choice, when applicable.
- Required and user-selected frozen input references.
- Initial expected generation of the publication target.
- Exact stage plan, execution groups, role profiles, prepared contexts, skills, memory policy, knowledge resources, and tools.
- Role-specific read allowlists, write roots, output-contract artifacts, and resource policy.
- Mode-scoped publication bindings from exact contract output IDs to append or current-slot operations, including target types, logical slots, bundle components, and expected prior generations.
- Creation time and manifest digest.

The manifest answers: "What exact scientific information and instructions produced this run?"

### 3.6 Artifact

An `Artifact` is an immutable file or object produced or consumed by a run. Examples include a proof manuscript, source paper, simulation program, tabular result, figure, role report, or manuscript snapshot.

Required metadata:

- Artifact ID, media type, and information layer.
- Source run or formal generation.
- Content digest and size.
- Producing actor and time.
- Scientific object references.
- Logical location.

Artifact presence does not establish formal authority or scientific validity.

### 3.7 Scientific record

A `ScientificRecord` is an immutable structured generation of a phase result. It connects claims, evidence, limitations, changes, and decisions to exact source artifacts.

Required metadata:

- Record and generation identity.
- Record type and phase.
- Source run and authority at creation.
- Frozen input basis.
- Method identity when applicable.
- Statements and evidence relations.
- Alignment and research-attention assessments at creation.
- Scientific outcome assessment.
- Change summary relative to the prior current generation.
- Presentation artifacts for each supported information layer.

The generation never stores mutable current position, current alignment, later attention, withdrawal, invalidation, or evidence eligibility. Those values belong to the derived state projection built from append-only authority events. A generation may be the current formal record and scientifically inconclusive without any contradiction.

### 3.8 Scientific statement

A `ScientificStatement` is an addressable claim, definition, limitation, or open question.

It should contain:

- Stable statement ID within its lineage.
- Exact wording.
- Statement type, such as definition, assumption, theorem, empirical finding, interpretation, limitation, or open question.
- Scope and population or parameter domain.
- Assumptions.
- Scientific outcome: `supported`, `partially_supported`, `contradicted`, `inconclusive`, `not_assessed`, or `not_applicable`.
- Evidence and counterevidence references.
- Source locations in primary artifacts.
- Parent or superseded statement relations.

The assessment records the team's conclusion for that immutable record generation. A later reassessment belongs to a new generation. It does not replace the underlying proof or evidence.

### 3.9 Evidence item

An `EvidenceItem` is an immutable unit of literature, mathematical, or empirical support or counterevidence.

Common required fields:

- Evidence ID and type.
- Source artifact and exact location.
- Statements addressed.
- Method identity if method-bound.
- Producing run and input basis.
- Assessment and limitations.
- Reproducibility metadata appropriate to the evidence type.

Empirical evidence also records code identity, data identity, configuration, tuning values, random seeds, software environment, outputs, and applicability against the frozen method identity at creation. Later current-index eligibility is derived without rewriting the evidence item.

Evidence is never silently overwritten. A correction or reanalysis creates a new item and an explicit relation to the prior item.

### 3.10 Role handoff

A `RoleHandoff` is the formal communication from one role to the next within a run.

It contains:

- Producer and intended consumer.
- Run and frozen basis.
- Work completed and artifacts produced.
- Material changes from the incoming current record.
- Statements supported, narrowed, contradicted, or unresolved.
- Assumptions and limitations.
- Issues the next role must examine.
- Relevant artifact references.

The handoff is concise, but each material item must link to the detailed work. It is a research communication object, not a chat transcript.

### 3.11 Attention item

An `AttentionItem` records research work that may be needed without declaring the current result invalid.

Required fields:

- Stable attention ID and immutable attention-version ID.
- Scientific question or defect.
- Severity and likely consequence.
- Source role or validator.
- Affected statements and records.
- Disposition: open, resolved, deferred, accepted limitation, or rejected with justification.
- Exact rerun question when further work is recommended.

Attention is separate from alignment and outcome. A supported and exactly aligned record may still contain valuable future research questions. A later disposition creates a new attention version linked to the prior version.

### 3.12 Authority event and derived state

An `AuthorityEvent` is an append-only record of a state change after a scientific object was created. It may publish or supersede a generation, recompute alignment, add or resolve research attention, withdraw or invalidate an object, or change evidence eligibility. Publication, supersession, withdrawal, and invalidation carry their permitted record-position effects, so there is no unconstrained generic position-change event. Every event names its subject, trigger, reason, prior-state digest when available, and exact changes.

The canonical event payload is the RFC 8785 serialization of the complete event object with `content_sha256` and `event_root_sha256` omitted. Let $H$ be SHA-256. The stored content digest is

\[
\texttt{content\_sha256} = H(\text{canonical payload bytes}).
\]

The journal root is

\[
\texttt{event\_root\_sha256}
= H(\operatorname{bytes}(\texttt{prior\_event\_root\_sha256})
\mathbin{\|\|}
\operatorname{bytes}(\texttt{content\_sha256})),
\]

where each digest is decoded from hexadecimal to 32 bytes before concatenation. The genesis prior root is 32 zero bytes. Event-type-specific schema conditions define the only legal `changes` fields for publication, supersession, withdrawal, invalidation, alignment recomputation, attention change, and evidence eligibility change.

A `DerivedRecordState` is a rebuildable projection from those events. It contains current publication state, record position, alignment, research attention, and evidence eligibility. The current index uses this projection. Deleting and rebuilding a projection from the event journal must reproduce the same state digest.

### 3.13 Alignment assessment

An `AlignmentAssessment` compares a record's frozen hard dependencies with the project's current formal dependencies.

Recommended states:

- `exact`: all hard identities and digests match.
- `compatible`: a non-calculation dependency change does not affect the record's calculation or claim, with justification.
- `unassessed`: a relevant dependency changed and compatibility has not been judged.
- `outdated`: the record uses a superseded calculation-defining basis.
- `not_applicable`: the record has no dependency of this type.

Compatibility is a scientific judgment made during a run, not an automatic digest comparison. The system can establish exact mismatch; it cannot infer harmlessness without an explicit assessment. A changed mathematical-definition digest is always `outdated` and can never be classified as `compatible`.

### 3.14 Scientific outcome assessment

A `ScientificOutcomeAssessment` summarizes what the phase established:

- `supported`.
- `partially_supported`.
- `contradicted`.
- `inconclusive`.
- `not_assessed`.
- `not_applicable`.

It includes scope, assumptions, strongest evidence, strongest counterevidence, uncertainty, and role disagreement. Phase specifications may define more precise subfields but must preserve this common meaning.

### 3.15 Decision brief

A `DecisionBrief` is the compact user-facing projection prepared by the lead and validated against the structured record.

It contains:

- Exact method and scientific basis.
- Decision currently available to the user.
- Most defensible conclusion.
- Fundamental contribution or change.
- Strongest evidence.
- Principal uncertainty or risk.
- Material disagreement.
- Available user actions and their consequences.
- Exact question a rerun would answer.

A decision brief may recommend an action but cannot authorize or launch it.

### 3.16 Review issue

A `ReviewIssue` is a stable, traceable criticism of a frozen manuscript or scientific record.

It contains:

- Stable issue ID, immutable issue-version ID, and reviewer identity.
- Frozen review basis.
- Location and affected statement.
- Severity and scientific consequence.
- Requested resolution or question.
- Disposition: fixed, partially fixed, deferred, rejected with justification, or open.

Later revisions refer to the stable issue ID. Any changed disposition creates a new issue version linked to the earlier version rather than overwriting it.

### 3.17 Publication receipt

A `PublicationReceipt` proves how a run changed formal project state.

It records:

- Source command and run.
- Prior and new current generation for each affected record.
- Validation report digests.
- Promotion policy and schema version.
- Lock or transaction identity.
- Publication time.
- Committed authority-event sequence range and event-root digest.
- Derived projection digests and current-index generation and digest.
- Resulting downstream alignment changes.
- A self-digest over the complete receipt.

The receipt is append-only and is the basis of audit and recovery. Its
`content_sha256` is SHA-256 of the RFC 8785 canonical complete receipt object
with only `content_sha256` omitted.

### 3.18 Publication binding

A `PublicationBinding` is the executable connection between validated run output and formal project state. It contains:

- Applicable phase mode.
- Exact source contract output IDs.
- Operation: append an immutable item, create a current slot, or replace a current slot.
- Target record type and logical slot identity.
- Named bundle components when several run outputs form one formal generation.
- Expected prior generation or explicit no-prior expectation.

The phase contract declares the binding and the run manifest resolves it to exact run output IDs and target generations. Publication never infers this relation from paths or output names.

## 4. Relationship model

The primary relations are:

```text
Project
  contains MethodRecord lineages
  contains RunManifest objects
  contains ScientificRecord lineages

RunCommand
  authorizes RunManifest

RunManifest
  freezes MethodIdentity and RecordGeneration references
  defines RoleHandoff sequence
  produces Artifacts and a submitted ScientificRecord

ScientificRecord generation
  cites Artifacts
  contains ScientificStatements
  relates immutable EvidenceItems
  contains creation-time AlignmentAssessment, ScientificOutcomeAssessment,
    AttentionItems, and DecisionBrief

PublicationReceipt
  proves one atomic publication

AuthorityEvent
  records publication, position, alignment, attention, and eligibility changes
  never rewrites a ScientificRecord or EvidenceItem

DerivedRecordState and CurrentIndex
  project current state from AuthorityEvents
  can be rebuilt from the append-only event journal
```

No relation to a mutable `current` pointer is valid as a frozen scientific dependency.

## 5. Hard and contextual dependencies

A hard dependency is information whose change can alter the calculation, proof, evidence interpretation, or manuscript claim. A contextual dependency informs reasoning but does not define the result.

Examples:

| Record | Typical hard dependencies | Typical contextual dependencies |
|---|---|---|
| Method definition | Literature sources and selected prior method definition used to formulate it | Broader literature corpus |
| P3 theory | Exact method identity and declared assumptions | Current P4 synthesis and selected prior P3 history |
| P4 evidence | Exact method identity, code, data, configuration, and protocol | Current P3 theory and selected prior P4 history |
| P5 manuscript | Exact selected P1, P2, P3, and P4 formal generations | Older review history and optional background material |

Phase 3 and Phase 4 are parallel. A current sibling record can inform a run, but its role as a hard or contextual dependency must be declared in the run manifest. The system must not automatically invalidate P3 because any P4 file changed, or invalidate P4 because any P3 prose changed.

## 6. Change and downstream impact

Publication computes impact from typed dependencies:

1. A changed method definition digest leaves the latest method-bound P3, P4, and P5 generations in their current record positions but changes their alignment to `outdated`. They cannot satisfy exact-current use until user-started replacement runs publish records for the new identity.
2. A replaced P3 theory generation makes any P5 manuscript bound to the earlier P3 generation non-current in alignment.
3. A P4 publication atomically replaces the evidence index, empirical synthesis, implementation record, and phase decision. A P5 manuscript becomes non-current in alignment when any P4 generation in its frozen hard-dependency basis is replaced; a phase decision is contextual unless the manuscript explicitly binds it as hard.
4. New P1 literature does not automatically invalidate every downstream record. The publication records literature-basis drift, and phase contracts determine whether reassessment is required.
5. Retiring a method prevents new ordinary runs for it but does not delete its records or history.
6. Withdrawing evidence or a scientific statement propagates an explicit affected-dependency notice to records that cite it.

Impact changes alignment and attention metadata. It does not erase scientific outcomes or launch reruns.

## 7. Phase-specific formal records

| Phase | Formal current record | History semantics |
|---|---|---|
| P1 | Literature corpus index plus current synthesis | New unique sources accumulate; corrections, duplicates, retractions, and withdrawals remain traceable |
| P2 | Method catalog plus one current definition generation for each active or retired stable method ID | Catalog-wide and focused updates preserve stable method lineage |
| P3 | One complete current theory record per method identity | Each promoted rerun supersedes the prior complete theory generation; older generations remain immutable |
| P4 | Current evidence index, empirical synthesis, implementation record, and phase decision per method identity | Evidence items accumulate immutably; all four current slots are replaced atomically |
| P5 | One complete current manuscript per selected method | Each promoted assembly or revision supersedes the prior manuscript generation and freezes its upstream basis |

## 8. Schema and migration rules

- Every persisted object declares its schema name and version.
- Validators reject unknown required semantics but may preserve unknown optional extension fields according to schema policy.
- Schema migration creates a new canonical representation and migration receipt. It must not falsify the original creation basis.
- Scientific revision and schema migration are different operations. A representation-only migration must not create a new method definition digest or scientific generation unless the canonical scientific content changes.
- Display text may be regenerated from structured records. Structured scientific meaning must not be reconstructed from display text.

See `schemas/` for machine contracts and `scenarios/` for required relationship and propagation tests.
