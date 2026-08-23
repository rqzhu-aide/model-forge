# HV-4: Harness-Owned Envelope Construction

Status: Revised plan, 2026-08-12
Parent: [harness-validation-index.md](harness-validation-index.md)

## Goal

Reduce avoidable agent formatting errors without weakening validation. The
harness populates system envelope fields deterministically; agents focus on
the scientific payload.

## What the audit found

Currently, agents are responsible for:
- Copying method-definition digests into their output
- Populating identity fields (project, run, phase, producer)
- Filling harness-known identifiers, timestamps, pointers, and hashes
- Producing the full canonical envelope structure

This means agents can accidentally invent authoritative run or method
identity, mistype digests, or omit required envelope fields -- all of which
become validation failures that look like execution failures.

The existing repair layer (`_apply_disclosed_mechanical_repairs`,
`role_execution.py:51-275`) partially compensates by injecting timestamps and
fixing self-referential hashes, but it is reactive (fixes after the fact) rather
than proactive (provides the correct fields before the agent runs).

## Design: two-layer output model

**Scoping decision (Revision 2):** the canonical document shape does NOT
change. The envelope sketch below is a logical view of field ownership, not a
new document structure. The harness populates harness-owned fields of the
EXISTING phase schemas in place; the agent authors the scientific fields of
the same schema. A new envelope document structure would be a contract change
requiring an ADR, new schemas, and rework of all finding codes and tests; that
blast radius is not justified by the goal. If a future review concludes the
schema shapes themselves are the problem, that is an HV-6 contract amendment,
not an HV-4 side effect.

### Layer 1: Agent-authored scientific payload

A smaller, scientifically-focused payload per output type: the subset of the
existing schema's fields that carry scientific content. The agent writes only
scientific content:

- Theorems, proofs, assumptions (theory-record)
- Protocol, results, thresholds (empirical-protocol)
- Manuscript sections, claims (manuscript-package)
- Review findings (review-finding, review-report)

The agent does **not** write:
- `content_sha256` or any digest
- Identity fields (project_id, run_id, phase, producer)
- Generation/lineage identifiers
- Timestamps (created_at, updated_at)
- Artifact pointers or storage paths
- Role identity or run basis

### Layer 2: Harness-populated fields (same document, existing schema)

The harness fills the harness-owned fields of the same document before
validation. Logical view of ownership:

```
{
  "identity": {          <- harness-owned
    "project_id": ...,
    "run_id": ...,
    "phase": ...,
    "producer": ...,
    "method_identity": ...
  },
  "basis": {             <- harness-owned (frozen run basis)
    "sealed_basis_digest": ...,
    "generation": ...
  },
  "content": {           <- agent-authored
    ...scientific payload...
  },
  "content_sha256": ..., <- harness-computed from canonical content
  "provenance": {        <- harness-owned
    "created_at": ...,
    "producer": ...
  }
}
```

The actual field paths come from each existing phase schema, not from this
sketch. `content_sha256` and artifact digests are computed over the bytes that
will actually be sealed and stored; artifact digests always bind the stored
artifact bytes, never recomputed-from-memory content.

## Work items

### HV-4.1: Define per-output-type scientific payload schema

**Target:** `architecture/schemas/`, `src/model_forge/harness/task_briefs.py`

For each output type (theory-record, empirical-protocol, manuscript-package,
review-finding, review-report, and earlier P1/P2 types), define a
"scientific payload" subset: the fields the agent is responsible for.

The full schema remains the source of truth; the payload schema is the agent's
contract surface. Derive the payload subset PROGRAMMATICALLY from the full
schema (for example by an ownership annotation or a harness-owned field list
per schema) rather than maintaining parallel schema documents, so the two can
never drift.

### HV-4.2: Populate harness-owned fields from sealed run facts

**Target:** `src/model_forge/harness/role_execution.py`, new module
`src/model_forge/harness/envelope.py`

A function that takes:
- The agent's scientific payload (raw output, preserved per HV-1)
- The sealed run facts (identity, basis, method, role)
- The output type

And produces the complete candidate document in the EXISTING schema shape:
- All harness-owned fields populated in place
- The correct `content_sha256` computed from canonical content
- Method-definition and artifact digests computed from the stored canonical
  bytes

```
populate_harness_fields(
    payload: dict, run_facts: SealedRunFacts, output_type: str
) -> dict  # complete document in the existing schema shape
```

All harness-owned fields are reproducible from sealed inputs. No model call is
needed.

### HV-4.3: Populate harness-owned fields deterministically

Fields the harness must own:

| Field | Source |
| --- | --- |
| `identity.project_id` | Sealed run basis |
| `identity.run_id` | Sealed run basis |
| `identity.phase` | Sealed run basis |
| `identity.producer` | Role identity |
| `identity.method_identity` | Selected method descriptor (full identity dict) |
| `basis.sealed_basis_digest` | Frozen run basis digest |
| `basis.generation` | Formal generation ordinal |
| `provenance.created_at` | Harness event timestamp |
| `provenance.updated_at` | Harness event timestamp |
| `content_sha256` | RFC8785 canonical digest of content |
| Artifact digests | Content-addressed store |
| `artifact_pointer.storage_relative_path` | Artifact store layout |

### HV-4.4: Pre-validation workspace tool

**Target:** `src/model_forge/harness/envelope.py`

Provide a function the role can call (or the harness applies automatically
after agent exit) to build and validate a candidate output before closure:

```
prepare_candidate_output(
    raw_payload_path: Path, run_facts: SealedRunFacts, output_type: str
) -> CandidateOutput
```

This:
1. Reads the agent's raw payload
2. Builds the canonical envelope
3. Validates against the schema
4. Reports any remaining scientific-payload errors
5. Returns the candidate (or findings if the payload is incomplete)

### HV-4.5: Update task briefs with concise examples

**Target:** `src/model_forge/harness/task_briefs.py`

Include concise, complete, mode-correct examples of the **scientific payload**
in the task brief -- not the full canonical envelope. The agent sees what it
needs to write; the harness handles the rest.

Keep the schema and validator as the source of truth. The examples are
illustrative, not normative.

The task brief should explicitly state which fields the harness will provide,
so the agent does not attempt to write them.

### HV-4.6: Update default instruction templates

**Target:** `resources/instructions/`, `src/model_forge/application/default_instructions.py`

Instruction templates should instruct agents to focus on scientific content
and not attempt to populate system envelope fields. The instruction should say
something like:

> You are responsible for the scientific content of your output. The harness
> will populate identity, provenance, timestamps, and digest fields
> automatically. Do not attempt to write these fields.

## Acceptance criteria

- [ ] Agents cannot accidentally invent authoritative run or method identity
- [ ] All harness-owned fields are reproducible from sealed inputs
- [ ] A scientifically complete payload can be converted into a valid canonical
      envelope without a model call
- [ ] No transformation adds a scientific claim, assumption, result, citation,
      or provenance assertion
- [ ] Task briefs show payload examples, not full envelopes
- [ ] All existing tests pass

## Files touched

| File | Change |
| --- | --- |
| `src/model_forge/harness/envelope.py` | New: canonical envelope builder |
| `src/model_forge/harness/role_execution.py` | Use envelope builder after agent exit |
| `src/model_forge/harness/task_briefs.py` | Payload-focused examples |
| `src/model_forge/application/default_instructions.py` | Updated instructions |
| `resources/instructions/**/*.md` | Updated role instructions |
| `architecture/schemas/` | Optional: payload schema documents |
| `tests/` | Envelope construction tests |

## Dependencies

- HV-1 (raw preservation -- the envelope builder reads the raw payload)
- HV-2 (classified findings -- payload errors get correctable class)

## Risks

- **Instruction change risk**: changing what agents are told to write may
  initially produce different output shapes. Mitigate by running in
  development mode and comparing outputs.
- **Payload schema drift**: the payload schema must stay in sync with the full
  schema. Mitigate by deriving payload fields from the full schema
  programmatically rather than maintaining a separate schema.
- **Transition period**: outputs written before HV-4 contain agent-authored
  identity fields; outputs written after do not. Validators must accept the
  harness-populated value in both cases (the harness overwrites or fills, so
  validation always sees harness-owned values). Old sealed records are not
  rewritten.

## Revision 2 changelog (2026-08-12, coder review)

- A1: rescoped the package. The original draft's "canonical envelope" read as
  a new document structure wrapping the payload, which would be a contract
  change (ADR, new schemas, rework of all finding codes and tests) with a
  blast radius the plan did not acknowledge. Revision 2 scopes HV-4 as
  build-time population of harness-owned fields within the EXISTING schema
  shapes; the envelope sketch is now explicitly a logical ownership view.
- A2 (HV-4.1): payload subsets are derived programmatically from the full
  schemas, not maintained as parallel documents.
- A3 (HV-4.2): renamed and re-specified as `populate_harness_fields`
  returning a complete document in the existing schema shape; added the rule
  that artifact digests bind stored bytes.
- A4: added the transition-period risk (pre/post-HV-4 output shapes).
