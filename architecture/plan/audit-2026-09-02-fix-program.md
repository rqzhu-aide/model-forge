# Fix Program: Model Forge Audit 2026-09-02

Status: COMPLETE 2026-09-02. One package, one commit, in the order below.
Source of truth for findings: [../archive/completed/audit-2026-09-02.md](../archive/completed/audit-2026-09-02.md)
(F1-F21 with file:line evidence, all independently verified).

Approved by Tez 2026-09-02 with the coder's recommendations:

- F1: fix BOTH halves - an in-process wake-up watcher AND output-based
  post-exit success detection. Either half alone leaves a hole.
- F6: seal the run as properly cancelled with a diagnostic note when an
  intent has no acknowledgement (the cancel command was already durably
  accepted; wedging contradicts Section 11.1).
- F8: distinguish prior-attempt leftovers by content digest, not mtime.

## Execution rules

- Work on the tree at ~/product/model-forge, venv `.venv`.
- Implement via delegate_task subagents with self-contained briefs (see the
  model-forge skill's subagent-dispatch-playbook); the coordinator validates
  every claimed fix against the code before committing. Stray-write sweep
  after every subagent package.
- Gates before EVERY commit: `.venv/bin/python -m pytest tests -q` exit 0
  and `.venv/bin/python architecture/tools/validate_package.py` exit 0.
  No em/en dashes and no trailing whitespace in any file under
  `architecture/`. UI packages additionally: vitest, `tsc --noEmit`,
  rebuilt dist.
- Every fix ships with a regression test that fails on the pre-fix code.
- Commit message convention: `Audit-2026-09-02 Pkg <letter>: <summary>`
  listing the F-numbers fixed.
- After each commit, mark the package DONE here with the commit SHA and
  the test count delta.
- If a package uncovers a contradiction with the audit's analysis, stop
  and record it in the audit doc instead of improvising.

## Packages

### P-A: Restart recovery completion (F1) -- DONE

DONE 2026-09-02: commit 3a53fe7. Tests 1398 -> 1405 (+7; 6 fail pre-fix,
the 7th pins the missing-output honest-failure path by design). Gates:
pytest exit 0, validate_package.py exit 0 (both re-run by the
coordinator). Implementation as pinned: `RoleExecutionPending` carries
`external_execution_id`; `_recover_completed_execution` performs
output-based post-restart success detection on FAILED + exit_code None;
the coordinator spawns a per-execution pending watcher
(`pending_poll_seconds`, default 5.0) that re-schedules the run when
reconcile turns terminal. Drift note: the correction-path pending raise
(`execute_correction` :1735) intentionally still raises without an
external id - correction states are never auto-advanced; P-D owns that
lane.

1. In-process wake-up. When `_execute` catches `RoleExecutionPending`,
   spawn a bounded watcher task that polls `executor.reconcile` for the
   pending external execution (interval mirroring the supervised lane's
   5 s) and calls `_schedule(run_id)` when reconcile returns a terminal
   result. The exception must carry the external execution id (extend
   `RoleExecutionPending` with an optional attribute, populated at the
   `role_execution.py:1606` raise site). Watchers self-remove on terminal
   result, terminal run state, or shutdown; the per-run asyncio lock keeps
   the scheduled pass serialized with any other advancement.
2. Output-based post-exit success detection. When reconcile returns
   FAILED with `exit_code None` from the restart-blind path ("process
   not found"), the harness checks the role workspace for the declared
   expected outputs before accepting the failure: all declared outputs
   present -> construct a SUCCEEDED result (exit_code None, diagnostic
   noting the post-restart recovery) and let `_validate_and_close` judge
   the bytes; anything missing -> keep FAILED. Implemented in
   `RoleLifecycleService` (the invocation and workspace are in scope
   there; the executor stays process-focused).

Regression tests must drive the real executor boundary where the pre-fix
code fails: real subprocess that exits while "restarted" (fresh executor
instance), outputs written -> closure sealed succeeded, not
executor.role_failed; and a watcher test where reconcile turning terminal
re-schedules the run without a manual `coordinator.run()` call (the gap
in `test_restart_with_in_flight_role_recovers`).

### P-B: Infrastructure-error containment (F3, F4) -- DONE

DONE 2026-09-02: commit 568bdfb. Tests 1405 -> 1409 (+4 net: 1 rename,
4 new; all 5 touched tests proven to fail pre-fix). Gates: pytest exit 0,
validate_package.py exit 0 (both re-run by the coordinator).
Implementation: heartbeat bookkeeping (append + cancellation read) is
best-effort with warning logs inside `RepositoryExecutionObserver` - the
local_hermes tree-kill finally can no longer trigger on a transient DB
error (F3); all close-path repository/artifact writes (both close paths,
`_seal_output`, `_seal_authored_snapshot`, both correction attempt-record
sites, and the two `correction_execution.py` revalidation closures) now
surface generic failures as `RoleExecutionInfrastructureError` with
conflicts untouched (F4); the parallel gather prefers Pending/
Infrastructure over generic errors. Drift recorded: the two P-A
output-recovery tests and the watcher test moved their interruption point
from heartbeat to close-path `record_artifact` (forced by the F3
semantics change; F1 intent preserved).

### P-C: Cancellation integrity (F5, F6, F22) -- DONE

DONE 2026-09-02: commit fdf3e20. Tests 1409 -> 1412 (+3, all proven to
fail pre-fix). Gates: pytest exit 0, validate_package.py exit 0 (both
re-run by the coordinator). Implementation as pinned: cancel CAS race now
raises CONTROL_HEAD_STALE carrying the sealed command id (F5);
settle_cancellation seals a cancelled closure with a crash-window
diagnostic for intent-without-ack (F6); Lane A correction bookkeeping
failures surface as an honest CommandRejected via
`_correction_bookkeeping_failed` (F22). Drift recorded: F22 reuses
CONTROL_HEAD_STALE (no infrastructure code exists in the registry and
api/errors.py was out of scope) - a dedicated code is a candidate future
improvement; the message text is honest about the sealed state.

- F5: `service.py` cancel path raises `CONTROL_HEAD_STALE` on
  `compare_and_swap_failed` (mirror the correction path at `:2571-2585`);
  keep swallowing only `already_applied`/`cancellation_fenced`. Retry
  with a fresh basis then works despite the sealed idempotency key.
- F6: `settle_cancellation` seals a `cancelled` closure with a diagnostic
  when an intent has no durable acknowledgement (approved decision),
  instead of raising into the swallowing handler; the run completes
  `cancelled`. Regression: intent-without-ack + cancel -> run reaches
  `cancelled`, no wedge across a simulated restart.
- F22 (added during P-B validation, same sealed-key-loss class as F5):
  the Lane A correction command path (`service.py:2742-2773`) seals the
  correction command, then a transient failure in
  `record_revalidation_closure`/`record_normalize_closure` (now correctly
  `RoleExecutionInfrastructureError` post-P-B) propagates with no
  upstream handler, so a client retry with the same idempotency key
  early-returns without re-applying. Fix: surface the failure as a proper
  command error that tells the researcher to issue a fresh correction
  command (the run stays `correcting`; D-7 re-issue is the designed
  recovery), never a silent sealed-and-lost acceptance.

### P-D: Correction replay attempt protection (F7) -- DONE

DONE 2026-09-02: commit 839b228. Tests 1412 -> 1415 (+3; two fail
pre-fix, the third guards the guard by design). Gates: pytest exit 0,
validate_package.py exit 0 (both re-run by the coordinator).
Implementation verbatim per pin: the correction reconcile branch now
applies `_recover_completed_execution` to the correction workspace on
FAILED + exit_code None (outputs present -> judged by validation, attempt
spent on the validation outcome only), and raises
`RoleExecutionInfrastructureError` without spending the bounded attempt
when no outputs exist (propagation traced: `_drive_lane_b` logs, no CAS,
no attempt row, run stays in the correction lane for D-7 re-issue).
Noted for future audit: the generic executor-exception path in
`execute_correction` also builds FAILED/exit_code None and still spends
the attempt (distinguishable from a vanished process; same shape as F7).

On a reconcile-FAILED during a correction replay where the process
vanished post-restart (exit_code None, restart-blind diagnostic), apply
P-A's output inspection to the correction workspace before spending the
attempt: outputs present -> validate them (attempt spent only on the
validation outcome); outputs absent -> classify interrupted, no spend.
Depends on P-A.

### P-E: Companion-artifact adapt path (F8) -- DONE (deleted)

Tez DECIDED 2026-09-02: option (b), delete the decorative path.
DONE 2026-09-02: commit 1cb1333. Tests 1420 -> 1415 (-5, exactly the
deleted adapt-path tests; per-test dispositions in the commit - each
deleted test's real subject either died with the machinery or has a
named production-path equivalent). Deleted `LinkedArtifact`,
`AdaptedOutput`, the `OutputAdapter` Protocol, `DefaultOutputAdapter`
and the R31 mtime companion scan from `output_adapters.py` (170 -> 53
lines), plus the import/instantiation/discarded call in
`role_execution.py`. `preserve_raw_output` kept byte-identical (it is
production-live since P-J). Gates: pytest exit 0, validate_package.py
exit 0 (both re-run by the coordinator).

BLOCKED 2026-09-02 (contradiction rule): pre-implementation verification
found the `adapt()` result is discarded at its only production call site
(`role_execution.py:2937`) and `AdaptedOutput`/`linked_artifacts` have no
production consumers - the companion scan is decorative machinery, so the
F8 mtime defect has zero production effect. Awaiting Tez's decision:
(a) wire linked artifacts into the sealed closure (designed feature,
contract work), (b) delete the decorative adapt path (coder's
recommendation, per the retired-code rule), or (c) fix the mtime rule
anyway. The original pin (digest-based exclusion, approved) applies
verbatim if (a) or (c) is chosen:

Original pin (kept for the chosen resolution):
`harness/output_adapters.py:106-109`: replace the mtime rule with
digest-based prior-attempt exclusion (approved decision): a same-stem
sibling is skipped only when its digest appears in the prior closure's
linked artifacts; otherwise it is linked and the recorded digest speaks
for itself. Regression: companion written BEFORE the JSON is linked;
genuine stale leftover (digest matches prior closure) is still skipped.

### P-F: Phase-view query keeps previous data (F2) -- DONE

DONE 2026-09-02: commit c50cf88. Vitest 183 -> 185 (+2, both proven to
fail pre-fix); tsc 0, build ok, validate_package.py exit 0 (all re-run by
the coordinator). Implementation: `placeholderData: keepPreviousData` on
the mode/method-keyed phase query; an aria-live busy note wired to
`isFetching`; the rerun prefill is withheld while `isPlaceholderData` so
RunForm's apply effect cannot stamp from the stale view (real hazard
found in the required placeholder-window audit; the other effects were
verified safe). Incident recorded: the program cron fired mid-package and
its session ran P-F concurrently; the two subagents collided twice, the
first converged a merged tree, and the coordinator verified the merged
result end-to-end (diff, all four gates). Cron paused for the remainder
of the foreground-driven program.

`PhasePage.tsx`: `placeholderData: keepPreviousData` (TanStack v5) on the
phase query so a mode/method switch renders the stale view with a busy
hint instead of unmounting the form. Vitest: form field content survives
a mode switch (the pre-fix wipe).

### P-G: CSS token repair (F9, F10) -- DONE

DONE 2026-09-02: commit 417d6d9. Vitest 185 -> 190 (+5; the static
token-resolution contract test, 3 of its assertions proven to fail
pre-fix); tsc 0, build ok, validator exit 0 (all re-run by the
coordinator). All 11 dead references repointed (--bg/--border/
--border-light/--soft -> --surface-soft/--line), `.run-logs__pre` now
reads ~15:1 light / ~13:1 dark, `--canvas-strong` deleted. The new
contract test (`styles-tokens.test.ts`, node:fs read - Vite `?raw`
imports return empty under vitest, a vacated-contract trap the package
caught and guarded) also exact-match-locks 13 pre-existing fallback-
carrying legacy token references; repointing those is recorded as a
follow-up (P-I takes the one visible defect, `.tl-dot`'s white border in
dark theme).

Define `--surface-raised` and `--border-subtle` per theme (fixing the
light-theme run-log contrast, F9); repoint the dead `var(--border)` /
`var(--bg)` references to `--line` / `--line-strong` / `--surface-soft`
as appropriate (`styles.css:2971, 1223, 2808, 3145, 3153, 3103, 3201,
3222, 2880`); delete the unused `--canvas-strong` (`:7`, `:61`).
WCAG-verify the new pairs (>= 4.5:1 for text-bearing surfaces).

### P-H: Rerun-flow UI repairs (F11, F12, F21) -- DONE

DONE 2026-09-02: commit b5ebb3b. Vitest 190 -> 195 (+5; four proven to
fail pre-fix, the fifth guards the prefill no-persist contract by
design); tsc 0, build ok, validator exit 0. Implemented directly by the
coordinator after two subagent attempts died on provider API timeouts
before making any edits (tree verified clean both times). Landed
behavior: navigation resets the explicit-mode override so a rerun
link's frozen basis wins again (F11); the prefill is passed only when
the frozen mode is still offered, with an honest "no longer offered"
note otherwise (F12); the placeholder window is guarded by a
`rerunReady` flag instead of prop withholding, so the apply-once marker
survives placeholder windows and the prefill can never re-stamp over
user edits (P-F interaction); same-value `applyExternal` no longer
strands the draft skip flag (F21).

- F11: reset `userModeOverride` in the phase/project/searchParams effect
  (`PhasePage.tsx:35-40`).
- F12: pass `rerunPrefill` to RunForm only when `rerunModeApplicable`;
  otherwise render a distinct "this basis is no longer offered" note.
- F21: `useLocalDraft.applyExternal` skips setting `skipPersist` when
  `next === value`.
- Vitest per fix (mode re-wins after navigation; no banner when mode
  retired; same-value external apply does not strand the next edit).

### P-I: UI states hygiene (F19, F20) -- DONE

DONE 2026-09-02: commit 6e6d7b3. Vitest 195 -> 201 (+6; four fail
pre-fix, two guards pass by design); tsc 0, build ok, validator exit 0
(all re-run by the coordinator). Landed: overview decision briefs show
"Decision brief is unavailable" on query failure instead of vanishing
silently (F19, with a new ProjectOverviewPage test file - none existed);
`.phase-chip` and `.tl-dot` are covered by the reduced-motion block, the
hover scale neutralized WITHOUT dropping the centering translate (the
coordinator's pin said `transform: none`, which would have un-centered
the dot - the subagent's correction is right); `.tl-dot`'s border
repointed to `var(--surface)` and the token contract test's `--bg`
allowlist entry removed (P-G follow-up).

- F19: overview decision briefs render an inline error state when the
  P1/P2 phase-view query fails (`ProjectOverviewPage.tsx:374-383`,
  consumed at `:428`/`:442`).
- F20: add `.phase-chip` and `.tl-dot` transitions to the
  reduced-motion block (`styles.css:2812`, `:2987`, block at `:4033`).

### P-J: Backend hygiene (F13, F14, F15, F18) -- DONE

DONE 2026-09-02: commit 57067e1. Tests 1415 -> 1420 (+5, all proven to
fail pre-fix); pytest exit 0, validate_package.py exit 0 (both re-run by
the coordinator). Landed: both `_recover_frozen_contract` copies now
skip corrupted artifact rows with a warning instead of aborting recovery
(F13); `_fix_record` re-runs handoff stamping after the content recompute
in a bounded loop - and the package surfaced a real circularity:
`content_sha256` and `handoff_artifact.sha256` cover each other, so a
hypothetical hybrid record could never be idempotent; verified no
contracted record type carries both, documented in code and test (F14);
executor-failed corrections now preserve raw output bytes exactly like
the validated-failure path (F15 - R4 only avoided clobbering, it never
preserved); `validate_materialization` is now genuinely side-effect-free
via a `persist=False` path - the dry-run's writes were redundant because
`publish` re-runs the materialization itself (F18).

- F13: `_recover_frozen_contract` (both copies) skips unreadable/corrupt
  `phase_contract_frozen` rows instead of aborting the loop.
- F14: `_fix_record` recomputes `handoff_artifact.sha256` after the
  `content_sha256` recompute (or iterates to fixpoint), closing the
  one-field-over stale-digest class.
- F15: correction FAILED branch preserves raw bytes like the base path
  (`preserve_raw_output` + `raw_seal_sha256`).
- F18: `validate_materialization` computes bundle digests without
  persisting (artifact id derivable from the digest), restoring the
  no-writes docstring contract; or amend the docstring if persistence
  proves load-bearing (record which in the commit).

### P-K: Dead code and latent pointer guard (F16, F17) -- DONE

DONE 2026-09-02: commit 027af75. Tests net 1420 -> 1420 (-6 dead + 5
migrated guards + 1 F17 regression); pytest exit 0, validate_package.py
exit 0 (both re-run by the coordinator). Deleted `prepare_candidate_output`/
`CandidateOutput` (envelope.py) and `_is_placeholder_hash` plus its dead
supporting constants (role_execution.py); the six tests that exercised the
dead path were migrated to the production close lane (five guard tests,
one deleted as a true duplicate - per-test dispositions in the commit).
F17 guard sits at `normalize_closure_outputs`, the single choke point for
all persisted normalize mutation (preview path deliberately unguarded -
read-only, seals nothing); a normalize-lane output carrying an `output://`
pointer at a co-closure sibling now raises before any write.

- F16: delete `prepare_candidate_output`/`CandidateOutput`
  (`envelope.py:517-630`) and `_is_placeholder_hash`
  (`role_execution.py:664-673`); migrate the pinning tests to the live
  path.
- F17: fail loud when the normalize lane meets stamped `output://`
  pointers at co-closure outputs (guard in
  `apply_normalize_transformations`), so the latent staleness class can
  never seal silently; document the limitation in the audit doc.

## Closure

After the last package: re-run the full gate set, append the closure note
to `architecture/audit-2026-09-02.md` (per-package commits, decided-no-
change items, suite state), move the audit doc to
`archive/completed/`, and update the directory READMEs.
