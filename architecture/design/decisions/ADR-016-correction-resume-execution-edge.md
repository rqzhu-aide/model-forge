# ADR-016: Correction Resume-Execution Edge for Mid-Pipeline Failures

## Status

Accepted (2026-08-20, Tez; K5-4 from the K-5 production re-exercise fix
round, evidence:
`architecture/evidence/k5-production-re-exercise-2026-08-20.md` addendum)

## Context

The K-5 controlled production run (P2 full catalog) failed at stage 1 of 3
(`p2.independent_proposals`); stages 2 and 3 never executed and hold no
closures. After the K5-1..K5-3 fixes landed, a passed correction on such a
run still could not re-enter the pipeline: `seal_correction_submission`
requires every stage role to hold a SUCCEEDED closure through the
family-aware read, so a mid-pipeline correction raised
`SubmissionAssemblyError` AFTER the bounded correction attempt was spent.
The run was left in `correcting` with no legal exit, and HV-5.8 forbids
auto-advancing correction states.

Two further facts shape the decision:

- `RoleLifecycleService.execute_or_reconcile` recovered only the BASE
  closure (base-identity `_load_closure`), so even a forced resume would
  re-fail the corrected role on its stale failed base closure. The
  family-aware `load_existing` (D4, ADR-014 lane) existed but was not
  consulted on the execution path.
- The restart-reconciliation machinery
  (`execute_or_reconcile_stage` -> `execute_or_reconcile`) already continues
  a partially closed pipeline: roles holding a succeeded closure reconcile
  without re-invocation, and roles without closures execute fresh.

## Alternatives

(a) **Resume-execution edge.** After a passed correction on an incomplete
closure chain, transition `correcting -> running` and hand off to the run
launcher; the coordinator reconciles the corrected and completed stages
through the family-aware read and executes the remaining stages.

(b) **Refuse mid-pipeline corrections up front.** Honest, but it makes the
correction lane useless for the dominant production failure class (the K-5
shape), forcing a full phase rerun for a single failed role output.

## Decision

Adopt (a).

1. **State machine.** `CORRECTING` gains a `RUNNING` edge
   (`domain/runs.py`; documented in `02-run-harness.md` sections 2.3 and 3).
2. **Family-aware reconciliation.** `execute_or_reconcile` reads through
   `load_existing` (correction family first, base fallback). Correction-free
   runs walk zero correction attempts and fall back to the identical
   base-closure read, so their behavior is unchanged.
3. **Branch at the correction pass tail.** A harness-pure probe
   (`incomplete_correction_chain`) lists the stage roles lacking a
   SUCCEEDED closure through the family-aware read. An empty result takes
   the existing submission path (`correcting -> submitted`). A non-empty
   result CASes `correcting -> running` with a `run.execution_resumed`
   event, clearing the stale failure fields (`terminal_reason`,
   `closure_findings`) from the run payload, then hands off to the run
   launcher.
4. **Straggler failures converge.** A role that failed but was not covered
   by the correction still holds a failed base closure; on resume the stage
   fails again through the normal orchestration path, the run returns to
   `failed` WITH the closure findings propagated (K5-2), and the correction
   lane can be re-entered for that role. The first correction's closure
   persists and supersedes, so no corrected work is repeated or lost.

## Invariants that must remain true

- A correction never creates a formal generation, authority event, or
  current-index change by itself; only the normal
  `submitted -> validating -> promoting` path publishes. The resumed run
  reaches submission only through the complete-chain seal.
- Sealed closures are never edited in place; the failed base closure
  remains on record and is superseded, never rewritten.
- HV-5.8 stands: the coordinator never auto-advances
  `correction_authorized` or `correcting`. The resume CAS is the explicit
  consequence of a sealed, authorized correction command, not a restart
  relaunch.
- Correction-free runs reconcile exactly as before (the family walk finds
  no correction attempts and falls back to the base closure).
- A resumed run never re-invokes a role that holds a succeeded base or
  correction closure.

## Consequences

- The correction lane covers the dominant production failure class end to
  end: a role output fails validation mid-pipeline, the closure seals
  nothing, the bounded correction repairs it, and the pipeline continues.
- A resumed run is indistinguishable from any `running` run for restart
  reconciliation: a server crash after the resume CAS resumes the pipeline
  normally, which is now the intended semantics.
- Scenario S26 gains the mid-pipeline resume expectation.
- The K-5 controlled re-run is unblocked.
