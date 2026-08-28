# Harness Validation and Output Recovery Plan

Status: Proposed

Prepared: 2026-08-12

Scope: Model Forge trusted-local Hermes execution, role output validation,
scientific validation, run status, recovery, and researcher-facing diagnostics.

Related architecture:

- [ADR-012: Trusted local Hermes execution](../../design/decisions/ADR-012-trusted-local-hermes-execution.md)
- [ADR-013: Layered prompts and phase-specific output contracts](../../design/decisions/ADR-013-layered-prompts-and-phase-specific-output-contracts.md)
- [S05: Failed or cancelled run preserves current state](../../design/scenarios/S05-failed-run.md)
- [Instruction, output-integrity, and UI fix plan](../../archive/instruction-output-integrity-fix-plan.md)

## 1. Goal

Keep the publication boundary strict while preventing completed scientific work
from being mislabeled as an execution failure because its output package needs a
correctable structural or reporting change.

The completed design should satisfy all of the following:

1. A Hermes process failure, output-conformance problem, integrity rejection,
   scientific outcome, and publication conflict are distinct conditions.
2. Formal project state changes only after all blocking checks pass.
3. Correctable output problems preserve the completed work and offer the
   smallest user-controlled recovery action.
4. Model Forge never silently reruns scientific work or invents scientific
   content.
5. The researcher can inspect every relevant output, validation finding, and
   mechanical transformation before deciding what to run next.
6. Negative, inconclusive, contradictory, or open research results remain valid
   outcomes when they are represented honestly.

This plan does not propose making provenance, method identity, artifact
integrity, or atomic publication checks permissive.

## 2. Current problem

The current lifecycle conflates successful execution with output conformance:

1. Hermes exits successfully and may have completed the assigned research.
2. Model Forge applies one mechanical repair pass to the workspace output.
3. Any remaining schema error changes the role closure to `FAILED`.
4. The stage fails, followed by the entire phase run.
5. The Web UI reports `Execution failed` even when the actual problem is a
   missing field, an output-envelope mismatch, or another correctable contract
   issue.

The same binary behavior appears at final submission. Validation supports
`ERROR`, `WARNING`, and `INFORMATION`, but every finding factory in the
codebase hardcodes `ERROR`; the `WARNING` and `INFORMATION` severities have
zero uses. A sparse metadata field and a wrong method digest can therefore
have the same operational consequence.

There are also two validation paths. Canonical phase runs validate against the
resolved phase and mode, while the supervised-run adapter currently constructs
a validation context without the true mode. Because scientific validators do
contain mode-specific logic, these two paths can reach different decisions for
the same output.

Finally, the existing repair pass edits the workspace output before an
immutable raw snapshot is guaranteed. It may remove unexpected fields and add
nested timestamp fields without following their schema paths. This can both
lose useful content and create new validation errors.

## 3. Design principles

### 3.1 Publication remains fail-closed

Invalid or ambiguous material must not become a formal current record. Method
Hub continues to require exact project, run, phase, method, producer, frozen
basis, artifact, and digest bindings.

### 3.2 Execution and acceptance are different facts

`Hermes completed its command` is an operational fact. `The output satisfies
the publication contract` is a separate validation fact. Neither should
overwrite the other.

### 3.3 User control applies to scientific work

No failed or incomplete phase launches another scientific invocation by
itself. A deterministic format normalization may be part of the already
authorized run if it is fully disclosed and cannot alter scientific meaning.
Any model-based or scientifically substantive correction requires an explicit
user action.

### 3.4 Preserve before transforming

The original workspace and output bytes must be sealed before repair,
normalization, or adaptation. Every derived candidate must identify its source
and record an exact transformation report.

### 3.5 The harness owns harness facts

Agents should not be responsible for reproducing information already known by
Model Forge. The harness should populate or compute run identity, role identity,
method identity, frozen-basis identity, timestamps, generation identifiers,
artifact locations, and digests.

### 3.6 Scientific uncertainty is not an operational error

An honestly labeled null result, failed proof attempt, counterexample,
inapplicable diagnostic, or unresolved question may be scientifically useful.
Validation should prevent unsupported positive claims, not require artificial
positive content.

## 4. Target lifecycle model

Represent a run using four independent axes. A single user-facing summary may
be derived from them, but the underlying facts must remain separate.

| Axis | Recommended values | Meaning |
| --- | --- | --- |
| Agent execution | `not_started`, `running`, `completed`, `failed`, `cancelled` | Whether Hermes and its tools completed operationally |
| Output conformance | `not_checked`, `passed`, `correction_required`, `integrity_rejected` | Whether the produced packet can enter formal validation and publication |
| Publication | `not_attempted`, `published`, `withheld`, `conflicted` | Whether canonical project state changed |
| Scientific outcome | phase-specific controlled values | Supported, negative, inconclusive, contradictory, open, or not applicable |

For Version 1, add a recoverable run condition named
`needs_output_correction`, or an equivalent projection derived from the axes.
It must mean:

- the assigned Hermes process completed;
- produced work has been preserved;
- formal publication did not occur;
- one or more blocking findings are correctable without changing run authority;
- the next action remains under researcher control.

Reserve `failed` for executor, tool, timeout, process-control, or infrastructure
failure. Reserve `rejected` for material that cannot be trusted under the
sealed authority, identity, provenance, or integrity rules. Preserve
`conflicted` for an atomic-publication head conflict.

Do not rewrite old immutable closures. A role correction creates a new attempt
record linked to the original closure.

## 5. Validation policy

Create an explicit registry for every validation code. Do not infer policy from
the text of its message.

The registry must be total in effect. Some codes are composed dynamically at
runtime (schema-error paths, JSON parse failures) and cannot be enumerated in
advance, so the registry defines a default policy: an unregistered code blocks
publication. No code may become non-blocking by omission. Finding factories
consult the registry at emission time, and a registry-completeness test
asserts that every literal finding code in the source is registered, so a
typo or a newly added code fails loudly instead of silently inheriting a
default.

Each registry entry should include:

- stable finding code;
- validation layer;
- default severity;
- whether it blocks publication;
- applicable phases and modes;
- correction class;
- responsible role or harness component;
- whether deterministic repair is allowed;
- whether a model call is required;
- whether researcher override is allowed;
- concise rationale and user-facing guidance.

Use the following classes.

### 5.1 Operational failure

Examples include a nonzero process exit, timeout, process-tree termination
failure, unreadable workspace caused by infrastructure, or executor exception.

Effect: execution fails. Preserve all available work. Do not publish.

### 5.2 Integrity blocker

Examples include:

- unsafe paths or symlinks;
- wrong project, run, phase, producer, or selected method;
- frozen-basis or authority mismatch;
- false or contradictory provenance;
- artifact-byte or digest mismatch;
- unresolved identity collision that makes records ambiguous;
- unauthorized method or lifecycle mutation;
- stale atomic-publication head.

Effect: publication is rejected or conflicted. These checks are never silently
repaired and cannot be overridden in Version 1.

### 5.3 Correctable contract error

Examples include:

- malformed JSON when the original scientific artifact is preserved;
- missing or incorrectly shaped envelope fields;
- missing harness-known identifiers, timestamps, pointers, or hashes;
- enum spelling or identifier-format errors;
- undeclared fields;
- repairable local cross-reference errors;
- missing required reporting metadata;
- a required output file omitted despite a successful process exit.

Effect: publication is withheld and the run enters
`needs_output_correction`. The work is not called an execution failure.

### 5.4 Scientific claim blocker

Examples include:

- a theorem labeled established without a proof or valid proof location;
- an empirical claim labeled supported without linked evidence;
- evidence claimed to use the exact current method when its method identity
  differs;
- a manuscript assertion whose stated support does not exist.

Effect: publication is withheld. The user may request a targeted scientific
correction or ask the role to downgrade the claim to open, unsupported,
inconclusive, or contradicted. The harness must not make that judgment itself.

### 5.5 Scientific attention

Examples include a justified empty category, open proof obligation, limitation,
nonexact evidence excluded from current-method synthesis, incomplete optional
diagnostic, or a reproducibility limitation stated honestly.

Effect: retain a visible warning or attention item. Publish automatically under
the authority of the original user-launched run when no blocking finding
remains. Do not add a separate approval step.

### 5.6 Information

Examples include optional presentation improvements and nonblocking notices.

Effect: record and display without blocking work or publication.

## 6. Proposed records and commands

Define these concepts in architecture schemas before runtime code depends on
them. HV-0 owns authoring these schemas (work item HV-0.6); no runtime code in
HV-1 or later may depend on a record type whose schema has not landed.

### 6.1 ValidationAttempt

An immutable record containing:

- attempt ID and ordinal;
- run, stage, role, output, contract, schema, phase, and mode identity;
- input and candidate-output digests;
- validator and policy versions;
- complete structured findings;
- overall conformance decision;
- start and completion timestamps;
- link to the previous attempt, if any.

Each finding should include the code, class, severity, blocking flag, JSON
pointer or artifact location, expected and observed form when safe, responsible
actor, correction guidance, and applicable policy entry.

### 6.2 OutputTransformationRecord

An immutable record for every mechanical transformation containing:

- source and result digests;
- allowlisted transformation code;
- affected paths;
- before and after values when they are safe and bounded;
- harness version;
- confirmation that no primary scientific artifact changed.

### 6.3 RoleAttempt

Extend invocation identity with an attempt ordinal or attempt ID. A new attempt
must never mutate or replace the prior closure. It records which previous
output it is correcting.

A correction attempt pins the original run's frozen basis content: input
generations and digests, method identity, and role profile versions. The
reviewed-basis drift check for a correction compares that pinned basis content,
not the current authority head. If other work has published since the original
run, the correction still seals against its original basis, and the conflict is
resolved by the existing atomic publication check at promotion time, which may
yield `conflicted`. A correction never re-reviews context and never widens
scope; a researcher who wants the current basis launches a rerun instead.

### 6.4 OutputCorrectionCommand

A user command that identifies:

- the exact run, role closure, validation attempt, and expected lifecycle head;
- whether the request is revalidation, deterministic normalization, packaging
  correction, or scientific correction;
- the permitted output scope;
- any user-authored instruction added for the correction.

The command must not authorize a different method, phase scope, or context
basis. A change to those items remains a new phase run or rerun.

## 7. Implementation work packages

### HV-0: Freeze the architecture and failure baseline

Goal: establish the policy and evidence before changing acceptance behavior.

Work:

1. Inventory every existing validation code and map it provisionally to the
   classes in Section 5.
2. Collect representative real Hermes outputs, especially completed work that
   was rejected for structural reasons. Remove private research content when
   necessary while preserving the failure shape.
3. Record baseline counts by phase, mode, role, validator code, and outcome.
4. Add an ADR for the independent lifecycle axes, correction authority, and
   validation policy registry.
5. Revise S05 so that it distinguishes executor failure from completed work
   requiring output correction.
6. Add scenarios for deterministic normalization, user-requested correction,
   revalidation, integrity rejection, and warning-only publication.

Acceptance:

- every current finding code appears exactly once in the inventory;
- the ADR states which actions require new user authority;
- scenarios preserve the current formal record on every nonpublished path;
- no validation threshold is relaxed in this package.

### HV-1: Preserve raw work and unify validation context

Goal: remove information loss and inconsistent decisions before adding
recovery.

Work:

1. Seal the original role workspace and output inventory before applying any
   repair.
2. Run repair and validation against a derived candidate workspace.
3. Record all mechanical transformations with before and after digests.
4. Replace global name-based timestamp injection with schema-path-aware
   traversal. Do not synthesize scientific timestamps or provenance.
5. Do not silently delete unknown scientific fields. Preserve them in the raw
   snapshot and either map them through an explicit extension mechanism or
   report a correctable finding.
6. Consolidate canonical and supervised validation around one
   `ValidationContext` containing the exact contract, phase, mode, method,
   frozen basis, role, and output bindings.
7. Remove the supervised path's empty-mode shim.

Acceptance:

- the original output digest is recoverable for every executor and validation
  outcome;
- identical bytes and context receive the same decision in both execution
  surfaces;
- repair cannot inject a field outside its schema path;
- every repair is visible in a structured record.

### HV-2: Introduce the validation policy registry

Goal: distinguish unsafe material from correctable or advisory findings.

Work:

1. Implement the registry described in Section 5.
2. Make structural, submission, and scientific validators emit classified
   findings rather than forcing every finding to `ERROR`.
3. Compute the overall decision from explicit `blocks_publication` policy, not
   from the mere presence of any finding.
4. Keep all existing integrity checks blocking.
5. Make policy mode-aware where scientific scope differs, especially P3
   establishment versus revision and P4 preliminary versus comprehensive.
6. Version the policy and bind its version into each ValidationAttempt.

Acceptance:

- changing message wording cannot change acceptance behavior;
- all hard identity, provenance, digest, path, and publication checks still
  block;
- warning-only negative or inconclusive outputs can pass publication;
- tests exercise at least one finding in every policy class.

### HV-3: Separate lifecycle status and expose complete diagnostics

Goal: make the user-facing state scientifically and operationally accurate.

Work:

1. Add the independent execution, conformance, publication, and scientific
   outcome projections.
2. Stop converting a successful Hermes exit into an execution failure when
   validation fails.
3. Add `needs_output_correction`, or the equivalent derived status, to the
   canonical run projection.
4. Expose complete validation attempts, role closures, bounded diagnostics,
   output inventories, raw snapshots, and valid partial artifacts through the
   ordinary phase-run API.
5. Replace the four-message summary with a complete grouped finding view.
6. Keep the supervised-run area as an advanced diagnostic surface, or merge it
   into the canonical run detail. Do not require the researcher to understand
   two inconsistent run models.

Recommended run-page wording:

> Hermes completed the assigned work. Formal publication was withheld because
> 3 output checks require correction. Your current project record was not
> changed.

Acceptance:

- a completed but nonconforming role never displays `Execution failed`;
- the researcher can locate every blocking field and preserved artifact;
- project overview does not count validation rejection as executor failure;
- the UI states whether formal project state changed;
- the run page offers no recovery control whose backing machinery does not yet
  exist (correction actions arrive with HV-5; HV-3 ships accurate status and
  complete findings only).

### HV-4: Move mechanical record construction into the harness

Goal: reduce avoidable agent formatting errors without weakening validation.

Work:

1. Define a smaller role-authored scientific payload for each output type.
2. Build the canonical system envelope from sealed run facts.
3. Compute method-definition and artifact digests from canonical content rather
   than asking agents to copy them.
4. Populate harness-owned identity, basis, producer, generation, timestamp, and
   pointer fields deterministically.
5. Provide a workspace command or library function that builds and validates a
   candidate output before the role exits.
6. Include concise, complete, mode-correct examples in the task brief, but keep
   the schema and validator as the source of truth.

Acceptance:

- agents cannot accidentally invent authoritative run or method identity;
- all harness-owned fields are reproducible from sealed inputs;
- a scientifically complete payload can be converted into a valid canonical
  envelope without a model call;
- no transformation adds a scientific claim, assumption, result, citation, or
  provenance assertion.

### HV-5: Add bounded, user-controlled recovery

Goal: correct the smallest affected output without repeating completed
scientific work.

Provide three distinct actions.

#### Revalidate unchanged output

Use when validator code, schema policy, or a transient dependency changed. It
makes no model call and records a new ValidationAttempt against unchanged bytes.

#### Apply deterministic normalization

Use only for allowlisted representation changes. Show or record the exact diff.
The normalization may run as part of the original launch authority because it
does not constitute new scientific work. It must never alter a primary research
artifact or semantic claim.

#### Request targeted correction

The user explicitly authorizes the affected role to correct specified output.
The correction attempt receives:

- the same frozen inputs and method identity;
- the previous raw and candidate outputs;
- the complete structured validation report;
- a scope limited to the named outputs;
- an instruction distinguishing packaging correction from scientific
  correction.

Default to at most one packaging correction attempt and one user-authorized
scientific correction attempt. Make the bounds configurable later only with a
separate decision. Never repeat completed upstream roles automatically.

For a parallel role group, preserve the common frozen basis and rerun only the
nonconforming role after user authorization. Start the downstream lead stage
only after every required parallel closure conforms.

Re-entry into the submission gate follows explicit mechanics (detailed in
HV-5.1): the original submission record is immutable and never rewritten; each
correction that passes validation creates a new submission attempt record; and
publication binds the latest passing attempt through the existing atomic
publication check.

Acceptance:

- every correction attempt has a unique immutable identity;
- restart reconciliation never relaunches a correction automatically;
- packaging correction cannot change primary scientific artifact digests;
- scientific correction cannot expand phase scope or change the selected
  method;
- exhaustion results in `completed, correction still required`, not a false
  execution failure.

### HV-6: Calibrate phase schemas for scientific applicability

Goal: accept valid research structures without encouraging artificial filler.

Perform this package only after HV-0 provides real failure evidence. Treat each
phase as a separate reviewed change.

#### P1

- represent search, researcher-supplied, imported-library, and citation-chain
  source origins;
- require truthful provenance appropriate to the origin rather than a search
  record for every source.

#### P2

- allow justified empty or not-applicable assumptions, literature, and
  limitation categories where scientifically appropriate;
- keep exact mathematical identity and method-lineage requirements strict;
- retain a method-class-specific definition rather than forcing one universal
  representation.

#### P3

- permit proof-only, definition-focused, impossibility, counterexample, and
  unsuccessful exploratory outcomes;
- recognize a proof contained in the primary theory manuscript rather than
  requiring a duplicate artifact;
- permit explicit not-applicable categories and structured novel theoretical
  objects;
- continue blocking claims labeled established without an identifiable proof.

#### P4

- define separate preliminary and comprehensive requirement profiles;
- make baselines, tuning, multiplicity, stopping rules, leakage checks, and
  reproducibility items conditional on study type;
- retain evidence for an older or nonexact method version, but mark it
  inapplicable and exclude it from current-method support;
- derive prespecification order from harness events rather than agent-authored
  timestamps.

#### P5

- map manuscript sections to scientific functions instead of fixed literal
  headings;
- permit a justified absence of claims from a phase;
- distinguish self-contained definitions and assumptions from claims that need
  external evidential support;
- allow an outside reviewer to report no strengths when that is the reviewer's
  honest judgment.

Acceptance:

- each schema change has an ADR or amendment when it changes an accepted
  contract;
- every newly allowed structure has a positive example and semantic test;
- every retained integrity boundary has a negative test;
- no phase requires fabricated `not applicable` prose merely to satisfy
  `minItems`.

### HV-7: Pilot, measure, and harden

Goal: demonstrate fewer false rejections without weakening formal integrity.

Build a calibration corpus containing:

- valid but structurally diverse Hermes outputs;
- sparse, negative, inconclusive, contradictory, and not-applicable outcomes;
- scientifically complete work with repairable packaging defects;
- wrong method identity, wrong basis, false provenance, and digest mismatch;
- unsafe paths and malformed artifacts;
- publication conflicts;
- anonymized examples of real false rejections.

Run the new policy in shadow mode first. Record both the current decision and
the proposed decision without changing publication. Review disagreements by
phase and validator code.

Track:

- first-pass conformance rate;
- correction success rate;
- agent-completed but nonconforming rate;
- hard integrity rejection rate by code;
- confirmed false rejection rate;
- complete phase reruns avoided;
- median time from output completion to publication.

Acceptance:

- repairable representation defects recover without repeating scientific work;
- wrong identity, basis, provenance, or digest never publishes;
- warning-only negative and inconclusive outcomes publish and remain visible;
- restart, cancellation, and conflict tests preserve immutable evidence;
- the full backend, architecture, API, and frontend acceptance suites pass.

## 8. Researcher-facing controls

The ordinary phase-run page should provide these controls only when applicable:

| Action | Model call | Changes scientific content | User action required |
| --- | --- | --- | --- |
| Inspect or download run packet | No | No | No additional authorization |
| Revalidate unchanged output | No | No | Explicit click |
| Apply deterministic normalization | No | No | Covered by launch authority, with visible record |
| Request packaging correction | Yes | No intended scientific change | Explicit click |
| Request scientific correction | Yes | Yes, within frozen scope | Explicit click and optional instruction |
| Start full phase rerun | Yes | Yes | Existing run or rerun control |

Do not introduce a generic post-run `Approve` button. If the user launched the
run and all blocking checks pass, publication proceeds under that launch
authority. The researcher decides whether to launch a correction or rerun only
when further scientific work is needed.

## 9. Required acceptance matrix

At minimum, end-to-end tests must cover:

1. Hermes process failure with preserved partial work and no publication.
2. Hermes success plus malformed JSON, producing output correction rather than
   execution failure.
3. Hermes success plus a missing harness-owned field, repaired and disclosed.
4. Hermes success plus a correctable scientific cross-reference error.
5. Unsupported theorem labeled established, blocked pending user-controlled
   correction or downgrade.
6. Honest failed proof or inconclusive empirical result, published with the
   correct scientific outcome.
7. P4 preliminary output that omits comprehensive-only protocol elements.
8. Evidence for a previous method version, preserved but excluded from current
   synthesis.
9. Wrong method identity or frozen basis, strictly rejected.
10. Unsafe path or digest mismatch, strictly rejected.
11. Atomic publication conflict, preserving both the attempt and current state.
12. Revalidation after a validator-policy change, with unchanged output digest.
13. User-authorized targeted correction, with all attempts retained.
14. Restart during correction, with no automatic relaunch.

Each case must assert the backend state, Web UI wording, available controls,
complete findings, preserved artifacts, and whether formal project state
changed.

## 10. Migration and compatibility

1. Do not rewrite historical run records or closures.
2. Derive the best available lifecycle axes for legacy runs. If a legacy
   `FAILED` closure contains `output.structural_validation_failed`, display it
   as `Legacy run: execution completed, validation failed` without changing the
   immutable record.
3. Version all new validation, transformation, and correction records.
4. Keep old API fields during a deprecation interval while adding structured
   findings and lifecycle projections.
5. Roll out by phase after shadow comparison. P3 and P4 are the best first
   scientific pilots because their outputs currently combine complex content
   with the strictest structured requirements.

## 11. Suggested delivery order

Use the following order:

1. HV-0: architecture decision, rule inventory, scenarios, and real failure
   baseline.
2. HV-1: raw preservation, repair safety, and validation-path convergence.
3. HV-2: finding policy and severity classification.
4. HV-3: lifecycle semantics, API diagnostics, and UI wording.
5. HV-4: harness-owned envelope construction.
6. HV-5: bounded user-controlled correction.
7. HV-6: phase-by-phase scientific schema calibration.
8. HV-7: shadow comparison, pilots, and operational hardening.

The first implementation block should be HV-0 and HV-1. It fixes the current
mode-context defect and prevents output loss while collecting the evidence
needed to calibrate strictness. Do not implement automatic or model-based
correction before raw preservation and complete validation reports exist.

## 12. Likely code and specification areas

This is an orientation map, not permission to edit every listed file in one
change.

- `src/model_forge/harness/role_execution.py`: raw snapshot, candidate repair,
  role-attempt identity, and conformance closure.
- `src/model_forge/harness/outputs.py`: structural findings and classification.
- `src/model_forge/harness/submission_validation.py`: consolidated validation
  decision.
- `src/model_forge/harness/scientific_validators.py`: classified and mode-aware
  scientific findings.
- `src/model_forge/application/output_validation.py`: remove the empty-mode
  supervised adapter.
- `src/model_forge/application/run_coordinator.py`: lifecycle projection,
  complete reports, and correction commands.
- `src/model_forge/domain/runs.py`: recoverable conformance state and allowed
  transitions.
- `src/model_forge/domain/validation.py`: policy class and structured finding
  fields.
- `src/model_forge/api/models.py` and run views: complete validation and artifact
  projections.
- `web/src/pages/RunPage.tsx` and status components: accurate status,
  diagnostics, and recovery controls.
- `architecture/contracts`, `architecture/schemas`, `architecture/scenarios`,
  and `architecture/decisions`: controlling specifications before runtime
  changes.

## 13. Completion criterion

This program is complete when a researcher can distinguish, inspect, and
recover from a correctable output problem without rerunning completed science,
while Model Forge still proves that no result with the wrong method, basis,
producer, provenance, artifact bytes, or publication authority can become
formal project state.

## Revision 2 changelog (2026-08-12, coder review)

Amendments applied after a full verification pass against commit `53efd01`.
Detail and evidence: [harness-validation-review-2026-08-12.md](harness-validation-review-2026-08-12.md).

- A1 (Section 2): corrected "nearly every issue" to "every issue"; verified
  that all finding factories hardcode `ERROR` and `WARNING`/`INFORMATION`
  have zero uses repo-wide.
- A2 (Section 5): added the registry totality rule. Dynamically composed codes
  are unbounded, so unregistered codes default to blocking, factories consult
  the registry at emission time, and a completeness test catches unregistered
  literal codes.
- A3 (Section 6): assigned schema authorship for ValidationAttempt,
  OutputTransformationRecord, RoleAttempt, and OutputCorrectionCommand to
  HV-0 (new work item HV-0.6). Previously no package owned them despite the
  schema-first rule.
- A4 (Section 6.3): resolved the conflict between "inherits the exact frozen
  run basis" and reviewed-basis drift sealing. A correction pins the original
  basis content; drift checks compare content, not the authority head;
  concurrent publication is handled by the existing atomic publication check.
- A5 (Section 7, HV-3): added the acceptance rule that the UI never offers a
  recovery control whose machinery does not exist yet (HV-3 ships before
  HV-5).
- A6 (Section 7, HV-5): added the submission re-entry principle. The base
  submission row is immutable and unique per run
  (`storage/migrations.py:219-233`), so corrections produce new submission
  attempt records and publication binds the latest passing attempt.
