# Architecture Implementation Plans

Active implementation work. A plan does not change an invariant, schema,
phase contract, or acceptance scenario by itself - update the corresponding
specification or decision record before code relies on such a change.

## Active plans

None as of 2026-09-02.

## Recently completed (retained here for their pin documents)

- [audit-2026-09-02-fix-program.md](audit-2026-09-02-fix-program.md) -
  fix program for the 2026-09-02 full audit (F1-F22), packages P-A
  through P-K. COMPLETE 2026-09-02: every package landed with regression
  tests proven against pre-fix code; P-E (F8) was blocked when the
  companion-artifact adapt pipeline proved decorative and awaits Tez's
  delete-vs-wire-up decision. The audit doc is archived at
  [../archive/completed/audit-2026-09-02.md](../archive/completed/audit-2026-09-02.md).
- [harness-audit-2026-08-31-fix-program.md](harness-audit-2026-08-31-fix-program.md) -
  fix program for the 2026-08-31 harness audit (R1-R37), packages P-A
  through P-K. COMPLETE 2026-09-02; all packages landed or explicitly
  decided-no-change (R17, R37). The per-package implementation pins
  (`harness-audit-2026-08-31-p*-pins.md`) remain in this directory because
  the archived audit doc and its closure note link to them here.

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
