# Roles and Files

## Purpose

This folder answers three practical questions:

1. What kinds of files and records exist in Method Hub?
2. In each phase, which role reads and writes each type?
3. For each role, what does it read and write across the five phases?

This is a researcher-facing guide derived from the normative Method Hub
architecture. It does not replace the executable phase contracts or persisted
schemas.

## Source of truth

Use the sources in this order:

1. [`architecture/contracts/phases/P1.json`](../architecture/contracts/phases/P1.json)
   through [`P5.json`](../architecture/contracts/phases/P5.json) define exact
   modes, stage order, role read sets, role outputs, and publication bindings.
2. [`architecture/phases/`](../architecture/phases/) explains the scientific
   purpose and assessment boundary of each phase.
3. [`architecture/02-run-harness.md`](../architecture/02-run-harness.md),
   [`03-storage-and-authority.md`](../architecture/03-storage-and-authority.md),
   and [`08-role-context-and-communication.md`](../architecture/08-role-context-and-communication.md)
   define execution, storage authority, context isolation, and handoff rules.

If this guide disagrees with an executable phase contract, implementation stops
until the guide or contract is corrected. Code must not infer a different rule
from a familiar filename or an older project layout.

## Guide map

- [File types](file-types.md) distinguishes research material, structured
  records, compact decision views, run-control records, and formal authority.
- [By phase](by-phase.md) gives the exact role order, reads, writes, and formal
  publication effects for Phases 1 through 5.
- [By role](by-role.md) gives the inverse view for the research lead, theorist,
  data analyst, and outside reviewer.

The phase and role views use the same contract IDs. They were cross-checked as
inverses: every role-stage write in one view appears under the same role and
phase in the other view.

## Rules shared by every phase

1. The user decides whether to run or rerun a phase. The user also chooses the
   mode, method when applicable, instructions, optional context, and selected
   history. No result launches another phase automatically.
2. Current formal records are the default scientific basis. Earlier run
   workspaces are excluded unless the user explicitly selects them.
3. A role writes only inside its assigned run-local role root. No role writes
   directly to `records/`, `generations/`, the current index, or another role's
   directory.
4. Parallel roles start from the same frozen group basis and cannot read one
   another's current-stage outputs.
5. A later stage reads an earlier role output only after the harness has sealed a
   successful `RoleInvocationClosure`, verified the output schema and digest,
   and accepted the artifact into a harness-owned location.
6. The manifest is a recipe. The realized execution chain is
   `PreparedRoleContext` to `RoleInvocationStart` to role outputs to
   `RoleInvocationClosure` to `RunSubmission`.
7. Validation and publication occur only after the complete required closure
   chain exists. The harness then atomically creates formal generations,
   authority events, derived projections, and a `PublicationReceipt`.
8. Primary artifact, structured record, and compact decision view describe
   information depth. They do not indicate whether an object is formal, current,
   aligned, supported, or ready for another phase.

## Naming

The current architecture uses these role IDs:

- `research_lead`
- `theorist`
- `data_analyst`
- `outside_reviewer`

The older names `data_scientist` and `paper_reviewer` are retired.

## Two different prepared contexts

Every role invocation has an infrastructure `PreparedRoleContext` that records
the exact material supplied to that role. Phase 5 review-revision additionally
has a scientific prepared input named `p5.review_packet`. The outside reviewer
can read only that packet.

## Handoff terminology

`handoff_required: true` closes a stage gate. It means every invocation in the
stage must close successfully and every declared output must be accepted before
the next stage or submission. It does not imply that the role writes a
`Handoff` object unless the stage's declared outputs include one.

The Phase 1 output `p1.phase2_handoff` remains immutable run provenance. Phase 2
uses the promoted Phase 1 library, synthesis, and coverage records as its formal
basis, not a file selected from the latest Phase 1 run folder.
