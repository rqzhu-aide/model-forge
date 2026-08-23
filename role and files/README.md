# Roles and Files

## Purpose

This folder answers three practical questions:

1. What scientific files and records exist in Model Forge?
2. In each phase, which role reads and writes each type?
3. For each role, what does it read and write across the five phases?

This is a researcher-facing guide derived from the normative architecture. It
does not replace the executable phase contracts or schemas.

## Source of truth

Use the sources in this order:

1. [`architecture/contracts/phases/P1.json`](../architecture/contracts/phases/P1.json)
   through [`P5.json`](../architecture/contracts/phases/P5.json) define exact
   modes, stage order, role read sets, outputs, and publication bindings.
2. [`architecture/schemas/`](../architecture/schemas/) defines each output's
   scientific structure.
3. [`architecture/phases/`](../architecture/phases/) explains each phase's
   scientific purpose and assessment boundary.
4. [`architecture/02-run-harness.md`](../architecture/02-run-harness.md),
   [`03-storage-and-authority.md`](../architecture/03-storage-and-authority.md),
   and [`08-role-context-and-communication.md`](../architecture/08-role-context-and-communication.md)
   define execution, authority, context isolation, and handoff rules.

If this guide disagrees with a split phase contract, the contract is
authoritative and the documentation must be corrected.

## Guide map

- [File types](file-types.md) distinguishes primary artifacts, structured
  records, compact decisions, run-control records, and formal authority.
- [By phase](by-phase.md) gives exact modes, role order, reads, writes, and
  publication effects for Phases 1 through 5.
- [By role](by-role.md) gives the inverse view for the research lead,
  theorist, data analyst, and outside reviewer.

The phase and role views use the same contract IDs. Every role-stage write in
one view must appear under the same role and phase in the other view.

## Dedicated research records

The current contracts use dedicated schemas where a generic scientific record
would hide an important research boundary:

- Phase 3 uses `TheoryRecord` for `p3.theory_candidate` and
  `p3.complete_theory`. It includes a readable primary theory artifact,
  statement IDs, assumptions, quantifiers, regimes, status, proof support or
  open obligations, dependencies, empirical implications, and revision history.
- Phase 4 uses `EmpiricalProtocol` for `p4.protocol`. It fixes claim-to-test
  links, the estimand, data or simulation unit, baselines, tuning budget,
  metrics, uncertainty, multiplicity, stopping, leakage checks, thresholds,
  and deviations before results are interpreted.
- Phase 5 uses `ManuscriptPackage` for `p5.manuscript_candidate`.
- Phase 5 specialist audits contain `ReviewFinding` items. The outside reviewer
  writes a `ReviewReport`. Only the revision lead converts all open findings
  into dispositioned `ReviewIssue` records.

These types define scientific content. Run-local versus formal authority still
comes only from validation and publication.

## Rules shared by every phase

1. The user decides whether to run or rerun a phase and chooses its mode,
   instructions, method when applicable, optional context, and selected history.
   No result launches another phase automatically.
2. Current formal records are the default scientific basis. Historical records
   are excluded unless the user explicitly selects them.
3. A role writes only inside its assigned run-local role root. It never writes
   directly to formal records, generations, indexes, or another role's folder.
4. Parallel roles start from the same frozen group basis and cannot read one
   another's current-stage outputs.
5. A later stage reads an earlier output only after the harness seals a
   successful role closure, verifies schema and digest, and accepts the artifact.
6. Validation and publication begin only after the complete required closure
   chain exists. Formal generations and the publication receipt commit atomically.
7. Primary artifact, structured record, and compact decision view describe
   information depth. They do not imply formal status, currency, alignment, or
   scientific support.

## Naming

The current role IDs are:

- `research_lead`
- `theorist`
- `data_analyst`
- `outside_reviewer`

The older names `data_scientist` and `paper_reviewer` are retired.

## Two different prepared contexts

Every role invocation has an infrastructure `PreparedRoleContext` recording
the exact material supplied to it. Phase 5 review-revision additionally has a
scientific prepared input named `p5.review_packet`. The outside reviewer reads
only that packet as project-specific context.

## Handoff terminology

`handoff_required: true` closes a stage gate. Every invocation in that stage
must close successfully and every declared output must be accepted before the
next stage or submission. It does not imply a `Handoff` output unless the
contract declares one.

The Phase 1 output `p1.phase2_handoff` remains immutable run provenance. Phase 2
uses the promoted Phase 1 library, synthesis, and coverage records as its formal
basis, not a file selected from the latest Phase 1 run folder.
