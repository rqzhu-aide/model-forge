# File Types and Storage Semantics

## Purpose

This page explains the files and structured records that researchers encounter in Method Hub. It is a researcher-facing guide derived from the [architecture specification](../architecture/README.md), especially the [storage and authority model](../architecture/03-storage-and-authority.md), [run harness](../architecture/02-run-harness.md), and executable [phase contracts](../architecture/contracts/phases/).

The architecture contracts and schemas remain normative. This page does not define a second storage contract. A logical record may be implemented as a filesystem object, database row, or object-store entry as long as its identity, access rules, and update behavior remain the same.

## 1. Information depth

Information depth describes how much scientific detail an object exposes. It does not determine whether the object is valid, formal, current, or aligned with the current method.

| Information type | Purpose | Typical contents |
|---|---|---|
| Primary artifact | Preserve detailed scientific work and source evidence | Source paper, proof manuscript, code, data reference, simulation output, figure, log, or manuscript source |
| Structured scientific record | Make scientific claims, assumptions, evidence, dependencies, and changes addressable | Literature source, method record, theory record, evidence index, empirical synthesis, statement registry, or review issue |
| Compact decision view | Help the researcher understand the current conclusion and choose the next action | Phase decision, method table row, change summary, unresolved-question summary, or status card |

A primary artifact can be incomplete run-local work. A compact decision view can summarize a formal current record. Neither is more authoritative because of its length or format. Formal authority is established only by validation and atomic publication.

The information type is recorded as metadata. It must not be inferred from a filename, extension, directory, or file size.

## 2. Scientific file and record types

| Type | Scientific purpose | Typical use |
|---|---|---|
| Primary artifact | Holds detailed work that should not be compressed into a structured summary | Proofs, source material, executable code, numerical outputs, figures, and manuscript files |
| `LiteratureSource` | Identifies a reference and records bibliographic, source, and provenance information | Phase 1 cumulative literature basis |
| `MethodRecord` | Defines one method with stable identity, mathematical version, provenance, assumptions, scope, and limitations | Phase 2 method catalog and the exact basis for Phases 3 through 5 |
| `ScientificRecord` | Represents a structured scientific account | Literature synthesis, coverage assessment, theory record, protocol, empirical synthesis, implementation record, or limitations record |
| `Statement` | Gives a stable identity to a definition, assumption, claim, theorem, or manuscript statement | Proof dependencies and manuscript claim traceability |
| `Evidence` | Identifies one empirical result and its exact method, code, data, configuration, environment, and output basis | Phase 4 cumulative empirical evidence |
| `Handoff` | Communicates accepted work, assumptions, changes, open issues, and requested checks to a later role | Within-run role communication and downstream phase guidance |
| `AttentionItem` | Records a concrete scientific question that may require reassessment | Literature, theory, evidence, or manuscript changes that deserve researcher attention |
| `ReviewIssue` | Records one stable specialist or outside-review concern and its disposition | Phase 5 review-revision workflow |
| `DecisionRecord` | States the current conclusion, material change, uncertainty, and meaningful user-controlled actions | Compact Web UI decision view for every phase |

Structured records link to their supporting primary artifacts. Compact decision views link to the structured record and do not replace the underlying proof, code, evidence, or manuscript.

## 3. Run-control and execution records

Every run is a controlled operation. These records describe what the user requested, what each role was permitted to see and produce, and what was submitted for validation.

| Record | Written by | Meaning |
|---|---|---|
| `RunCommand` | Command service from an authenticated user action | Exact phase, mode, method when applicable, instructions, selected context, and selected history |
| `RunManifest` | Run harness | Sealed run recipe containing frozen inputs, role order, profiles, output obligations, permissions, and publication bindings |
| `PreparedRoleContext` | Run harness | Exact context assembled for one role invocation |
| `RoleInvocationStart` | Run harness | Exact role profile, accepted inputs, capabilities, executor, write root, and expected outputs at role start |
| Role workspace artifacts | Active role | Scientific outputs written only inside that role's assigned run-local root |
| `RoleInvocationClosure` | Run harness | Terminal status, accepted outputs, handoffs, access record, and failure or cancellation information |
| `RunSubmission` | Run harness | Immutable package containing the complete successful role-closure chain and all candidate publication artifacts |
| Validation report | Validator | Structural, identity, provenance, phase, consistency, and publication-safety findings |
| Publication plan | Publisher | Exact atomic operations proposed for formal storage |

Roles do not write directly to the formal project store. A role writes only within:

```text
runs/{phase_id}/{run_id}/roles/{sequence}-{role_id}/
```

After a role closes, the harness verifies its declared outputs and makes accepted artifacts available to authorized later roles. A later stage reads only the exact accepted upstream outputs named by its invocation start. Parallel roles cannot read one another's in-group work.

The lead prepares candidate formal components under the lead's role root. The harness assembles the immutable submission. Validators inspect it, and only the publisher may create formal generations or change current projections.

## 4. Formal storage and authority records

| Record | Meaning | Mutation rule |
|---|---|---|
| Immutable formal generation | One validated published version of a scientific record and its frozen basis | Never edited after publication |
| `AuthorityEvent` | Append-only event recording publication, supersession, withdrawal, invalidation, alignment, attention, or evidence eligibility | Never rewritten; later changes append another event |
| `RecordState` | Rebuildable projection of publication state, current or historical position, alignment, attention, and evidence eligibility | Recomputed from authority events |
| `CurrentIndex` | Sole backend source for resolving current formal records | Replaced atomically from replayed authority state |
| `PublicationReceipt` | Proof of the exact source operation and the generations, events, projections, and index committed together. A research-run receipt binds its exact `RunSubmission`; a control-command receipt instead binds its exact authorized command transaction. | Immutable |
| `CommandAttemptAuditEvent` | Tamper-evident operational record of accepted or rejected user commands | Append-only and separate from scientific authority |

These authority dimensions remain separate:

- Publication state records whether an object is run-local, submitted, validated, formal, withdrawn, or invalid.
- Record position records whether a formal generation is current or historical.
- Alignment records whether hard dependencies match the current scientific basis.
- Research attention records questions that require scientific consideration.
- Scientific outcome records what the research supports, contradicts, or leaves unresolved.

A negative or incomplete scientific outcome can still be a formal current record. Conversely, a detailed and persuasive artifact is not formal until publication commits.

## 5. Update semantics by phase

| Phase | Cumulative content | Replaced current content | Important rule |
|---|---|---|---|
| Phase 1, literature basis | Unique literature sources, provenance, corrections, retractions, and attention items | Literature library projection, synthesis, coverage assessment, and phase decision | Existing sources are preserved. A rerun normally adds unique references and updates the current synthesis. |
| Phase 2, method catalog | Method lineage and attention items | Scoped method records, method catalog, and phase decision | Full-catalog mode may change multiple methods. Focused-method mode may change only the selected stable method. Retirement requires an explicit authorized action. |
| Phase 3, theory development | Attention items and immutable earlier generations | Complete theory record and phase decision for one exact method identity | A rerun publishes a complete replacement, not a patch. The earlier complete theory generation becomes historical. |
| Phase 4, empirical evaluation | New immutable evidence items and attention items | Evidence index, empirical synthesis, implementation record, and phase decision | Evidence accumulates. Evidence for an earlier mathematical definition remains traceable but is not applicable to the new version. Preliminary or comprehensive scope is selected by the user on every run. |
| Phase 5, manuscript assembly and revision | Attention items and, in review-revision mode, review issues | Complete manuscript package, review issue ledger when applicable, and phase decision | A rerun publishes one complete manuscript package tied to exact current Phase 1 through Phase 4 records. Earlier manuscript generations remain historical. |

No phase launches another phase or rerun automatically. Successful publication exposes updated information and available actions; the researcher decides what to run next.

## 6. Method identity and digest rules

An exact method identity contains:

```json
{
  "stable_id": "mth_01j...",
  "version": 2,
  "definition_sha256": "..."
}
```

The stable ID never changes. The positive integer version advances when a calculation-defining mathematical component changes. `definition_sha256` covers only the canonical mathematical definition. A prose or presentation edit may change the whole-record digest without changing the method version or definition digest.

Method-bound theory, evidence, implementation, and manuscript records carry the exact method identity. A definition-digest mismatch is `outdated` and cannot be treated as compatible.

Structured JSON digests use the exact registered RFC 8785 contract. A primary artifact pointer hashes the exact referenced bytes. Implementations must not substitute a hash of a filename, display text, or reserialized artifact.

## 7. Naming, references, and logical paths

Stable identifiers are opaque and permanent. They must not encode mutable names, scientific status, phase completion, or filesystem paths. Common prefixes include:

| Object | Example prefix |
|---|---|
| Project | `prj_` |
| Method | `mth_` |
| Run | `run_` |
| Record | `rec_` |
| Generation | `gen_` |
| Artifact | `art_` |
| Statement | `stm_` |
| Evidence | `evd_` |
| Attention item | `att_` |
| Review issue | `iss_` |
| Publication receipt | `pub_` |

Persistent dependencies use typed logical references with immutable identities and digests. Examples include:

```text
generation://{record_type}/{record_id}/{generation_id}
run://{run_id}/artifact/{artifact_id}
statement://{statement_id}
evidence://{evidence_id}
```

A reference such as `record://method/{method_id}/theory/current` is a resolver query. The harness resolves it during preparation and freezes the resulting generation identity and digest. A persisted scientific dependency must not point to a mutable `current` location.

The recommended logical namespaces are:

```text
project/
  records/       # Read-only current projections
  generations/   # Immutable formal generations
  runs/          # Controlled run workspaces and submissions
  control/       # Authority events, projections, receipts, and command audit
```

Filenames are labels, not trusted paths or scientific identities. Storage services must reject path traversal, cross-project access without policy, digest mismatches, and references to mutable role workspaces. No code may infer authority, current status, alignment, or scientific outcome from a directory name or file presence.
