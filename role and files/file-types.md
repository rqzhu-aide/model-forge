# File Types and Storage Semantics

## Purpose

This page explains the files and structured records that researchers encounter
in Model Forge. The executable [phase contracts](../architecture/contracts/phases/)
and [schemas](../architecture/schemas/) remain normative. A logical record may
be stored as a file, database row, or object-store entry as long as its identity,
access rules, and update behavior remain unchanged.

## 1. Information depth

Information depth describes how much scientific detail an object exposes. It
does not determine whether the object is valid, formal, current, or aligned.

| Information type | Purpose | Typical contents |
|---|---|---|
| Primary artifact | Preserve detailed scientific work and source evidence | Source paper, proof manuscript, code, data reference, simulation output, figure, log, or manuscript source |
| Structured scientific record | Make claims, assumptions, evidence, dependencies, and changes addressable | Literature source, method, theory, protocol, evidence index, empirical synthesis, manuscript package, or review record |
| Compact decision view | Help the researcher understand the current conclusion and choose an action | Phase decision, method table row, change summary, unresolved-question summary, or status card |

The information type is metadata. It must not be inferred from a filename,
extension, directory, or file size. Formal authority is established only by
validation and atomic publication.

## 2. Scientific file and record types

| Type | Scientific purpose | Contract use |
|---|---|---|
| Primary artifact | Holds detailed work that should not be compressed into a summary | Proofs, sources, executable code, numerical outputs, figures, and manuscript files |
| `LiteratureSource` | Records bibliographic identity, source location, and provenance | Phase 1 cumulative literature basis |
| `MethodRecord` | Defines one method with stable identity, mathematical version, provenance, assumptions, scope, and limitations | Phase 2 catalog and the exact method basis for Phases 3 through 5 |
| `ScientificRecord` | Represents a general structured scientific account | Syntheses, coverage, audits, indexes, implementation records, and limitations records that do not have a more specific schema |
| `TheoryRecord` | Represents a complete theory account with a primary artifact and statement-level proof ledger | `p3.theory_candidate` and `p3.complete_theory`; `theory-record.schema.json` |
| `EmpiricalProtocol` | Prespecifies the claim-linked design and appends any later deviations without rewriting the plan | `p4.protocol`; `empirical-protocol.schema.json` |
| `ManuscriptPackage` | Represents the complete readable manuscript and its upstream claim-support index | `p5.manuscript_candidate`; `manuscript-package.schema.json` |
| `Statement` | Gives a stable identity to a definition, assumption, theorem, empirical claim, or manuscript statement | Proof dependencies and manuscript claim traceability |
| `Evidence` | Identifies one empirical result and its exact method, code, data, configuration, environment, and output basis | Phase 4 cumulative evidence |
| `Handoff` | Communicates accepted work, assumptions, changes, open questions, and requested checks | Within-run communication and selected reports |
| `AttentionItem` | Records a concrete scientific question that may require reassessment | Literature, theory, evidence, or manuscript attention history |
| `ReviewFinding` | Records one open, evidence-grounded specialist finding without a lead disposition | Items in `p5.theory_audit` and `p5.empirical_audit`, and findings carried by the outside report; `review-finding.schema.json` |
| `ReviewReport` | Packages the outside review, its reviewer boundary, assessment, prioritized open findings, and novelty-search limits | `p5.outside_review`; `review-report.schema.json` |
| `ReviewIssue` | Records the revision lead's disposition of an open review finding while preserving stable issue lineage | `p5.review_issues` and the formal review issue ledger |
| `DecisionRecord` | States the current conclusion, material changes, uncertainty, and meaningful user actions | Compact decision output for every phase |

Review findings and review issues have different owners. The theorist and data
analyst write open `ReviewFinding` items. The outside reviewer writes a
`ReviewReport` containing its open findings. The revision lead reads all three
review outputs and writes dispositioned `ReviewIssue` records. A reviewer does
not mark its own finding fixed, rejected, or accepted.

Structured records link to supporting primary artifacts. Compact decision views
link to the structured record and do not replace the proof, code, evidence, or
manuscript.

## 3. Run-control and execution records

| Record | Written by | Meaning |
|---|---|---|
| `RunCommand` | Command service from an authenticated user action | Exact phase, mode, method when applicable, instructions, context, and selected history |
| `RunManifest` | Run harness | Sealed recipe containing frozen inputs, role order, profiles, output obligations, permissions, and publication bindings |
| `PreparedRoleContext` | Run harness | Exact context assembled for one role invocation |
| `RoleInvocationStart` | Run harness | Exact role profile, accepted inputs, capabilities, executor, write root, and expected outputs at role start |
| Role workspace artifacts | Active role | Scientific outputs written only inside that role's assigned run-local root |
| `RoleInvocationClosure` | Run harness | Terminal status, accepted outputs, handoffs, access record, and failure or cancellation information |
| `RunSubmission` | Run harness | Immutable package containing the complete successful closure chain and all candidate publication artifacts |
| Validation report | Validator | Structural, identity, provenance, scientific, and publication-safety findings |
| Publication plan | Publisher | Exact atomic operations proposed for formal storage |

Roles write only within:

```text
runs/{phase_id}/{run_id}/roles/{sequence}-{role_id}/
```

After a role closes, the harness verifies its declared outputs and exposes only
accepted artifacts to authorized later roles. Parallel roles cannot read one
another's in-group work. The lead prepares candidate formal components, but
only the publisher may create formal generations or change current projections.

## 4. Formal storage and authority records

| Record | Meaning | Mutation rule |
|---|---|---|
| Immutable formal generation | One validated published version of a scientific record and its frozen basis | Never edited after publication |
| `AuthorityEvent` | Publication, supersession, withdrawal, invalidation, alignment, attention, or evidence-eligibility event | Append-only |
| `RecordState` | Rebuildable projection of publication state, position, alignment, attention, and evidence eligibility | Recomputed from authority events |
| `CurrentIndex` | Backend source for resolving current formal records | Replaced atomically from replayed authority state |
| `PublicationReceipt` | Proof of the source operation and all generations, events, projections, and index changes committed together | Immutable |
| `CommandAttemptAuditEvent` | Tamper-evident operational record of accepted or rejected user commands | Append-only and separate from scientific authority |

Publication state, current position, method alignment, research attention, and
scientific outcome remain separate. A negative or incomplete result may be a
formal current record. A persuasive artifact is not formal until publication.

## 5. Update semantics by phase

| Phase | Cumulative content | Replaced current content | Important rule |
|---|---|---|---|
| Phase 1, literature basis | Unique sources, provenance, corrections, retractions, and attention items | Literature library projection, synthesis, coverage, and decision | Existing sources are preserved; reruns add unique references and update the current assessment. |
| Phase 2, method catalog | Method lineage and attention items | In-scope method records, catalog, and decision | Full-catalog may change several methods; focused-method may change only the selected stable method; researcher-proposal evaluates a supplied specification and may register it. |
| Phase 3, theory development | Attention items and immutable earlier generations | Complete `TheoryRecord` and decision for one exact method identity | Establishment builds the scoped account. Revision publishes a complete replacement and may strengthen, weaken, condition, contradict, or retract claims. |
| Phase 4, empirical evaluation | New immutable evidence and attention items | Evidence index, empirical synthesis, implementation record, and decision | Preliminary and comprehensive are user-selected scientific scopes, not chronological steps. Comprehensive does not require a prior preliminary run. Prior code may be reused only after exact-method verification. |
| Phase 5, manuscript assembly and revision | Attention items and, in review-revision, review issues | Complete `ManuscriptPackage`, review issue ledger when applicable, and decision | Reviewers produce open findings or a report. The revision lead owns issue disposition and publishes one complete revised package. |

No phase launches another phase or rerun automatically. Publication exposes
updated information and actions; the researcher decides what to run next.

## 6. Method identity and digest rules

An exact method identity contains:

```json
{
  "stable_id": "mth_01j...",
  "version": 2,
  "definition_sha256": "..."
}
```

The stable ID never changes. The positive integer version advances when a
calculation-defining mathematical component changes. `definition_sha256`
covers only the canonical mathematical definition. A prose edit may change the
whole-record digest without changing the method version or definition digest.

Method-bound theory, protocol, evidence, implementation, and manuscript records
carry the exact method identity. A definition-digest mismatch is `outdated` and
cannot be treated as compatible.

Structured JSON digests use the registered RFC 8785 contract. A primary artifact
pointer hashes the exact referenced bytes, not a filename or display text.

## 7. Naming and logical references

Stable identifiers are permanent and must not encode mutable status, phase
completion, or filesystem paths. Persistent dependencies use typed logical
references and immutable identities, for example:

```text
generation://{record_type}/{record_id}/{generation_id}
run://{run_id}/artifact/{artifact_id}
statement://{statement_id}
evidence://{evidence_id}
```

A `current` reference is a resolver query. The harness resolves it during
preparation and freezes the resulting generation identity and digest. Persisted
scientific dependencies do not point to mutable role workspaces or `current`
locations.
