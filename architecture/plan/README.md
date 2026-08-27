# Architecture Implementation Plans

Active implementation work. A plan does not change an invariant, schema,
phase contract, or acceptance scenario by itself - update the corresponding
specification or decision record before code relies on such a change.

## Active plans

- [Skill Selector and Role Skill Configuration](skill-selector-and-role-skill-configuration-2026-08-26.md) -
  per-phase skill assignment for team members with a selector UI on each
  member configuration page (Tez direction 2026-08-26). Packages SK-1
  through SK-5; per-stage and per-run overrides deferred.
- [Instruction, Output-Integrity, and UI Fix Plan](instruction-output-integrity-fix-plan.md) -
  packages FP-1 through FP-8. FP-2 SATISFIED (2026-08-25); FP-3 and FP-4
  complete; FP-1, FP-5, FP-6 partially complete; FP-7 (small frontend
  repairs) and FP-8 (design decisions) remain open. Predates the WP
  program; a closure review against the current build is due before any
  further package is dispatched from it.

## Supporting documents

- Decisions that bind this work:
  [ADR-012](../design/decisions/ADR-012-trusted-local-hermes-execution.md),
  [ADR-013](../design/decisions/ADR-013-layered-prompts-and-phase-specific-output-contracts.md),
  [ADR-014](../design/decisions/ADR-014-independent-lifecycle-axes-and-validation-policy.md).
- Undecided questions live in [../issues/](../issues/README.md), not here.
- Completed plans and closed programs retire to
  [../archive/](../archive/README.md). The Trusted Local Execution Program
  (WP-A through WP-I) is fully CLOSED as of 2026-08-26; new work starts as
  new plans in this directory.

## Rules

- One package, one commit, explicit paths; backend suite and
  `tools/validate_package.py` green before every commit.
- UI packages additionally require vitest, `tsc --noEmit`, and a rebuilt
  dist before commit.
- Evidence for a completed gate lands in `../evidence/` and is cited from
  the plan's closure note.
