# Harness Audit 2026-08-16: Missing Components and Residual Misalignments

Status: findings only (no code changes, no new tests)
Author: coder profile
Basis: current tree at `60b1fcc` (post ISS-1..ISS-9), production DB at
`~/.method-hub/method-hub.sqlite3`, the trusted-local execution program plan,
and the instruction-output-integrity fix plan. Every finding carries
file:line evidence verified against this tree.

Suite state at audit time: backend 1071 green, vitest 120/120 green,
`validate_package.py` exit 0.

## NEW findings (first reported here)

### NA-1 (P1): restart completion watcher validates and promotes against an empty, unverified manifest

`application/service.py:462-495` (`_run_post_exit_validation`, landed in the
Researcher Trust package `ac3232a`) hand-builds
`SealedRun(manifest={})` and passes it to `validate_run_outputs`.
`output_validation._resolve_seal` (output_validation.py:226-227) trusts a
passed `SealedRun` as-is; only the string form goes through
`assembler._reconstruct`, which is the digest-verified path.

Consequences, both verified against the check implementations:

1. With real outputs present: `_declared_outputs({})` returns empty
   (output_validation.py:335-337), so every file under `outputs/` is an
   "undeclared file" and `_check_inventory` fails (line 585). A run that
   succeeded across a server restart is recorded validation-FAILED and its
   memory promotion is blocked - a false negative on exactly the runs the
   watcher exists to rescue.
2. With an EMPTY `outputs/` directory: no declared outputs and no inventory
   entries, so inventory passes, schema/identity/phase checks have nothing
   to check, and the verdict can be a vacuous PASS - after which
   `promote_run_state` (called on pass, service.py:486-490) promotes memory
   state for a run that produced nothing. The memory-policy gate inside
   promotion reads the same empty manifest, so its policy lookup is equally
   ungrounded.
3. Either way the WP-E1 tamper-evidence rule (manifest digest verification
   before judgment) is bypassed on this path.

Fix (small): pass the invocation id string to `validate_run_outputs`
(digest-verified reconstruction), and reconstruct the sealed run via
`assembler._reconstruct(record)` for the promotion call. The watcher already
holds `invocation_id`. This needs a regression test: sealed run + closed
succeeded launch + real declared outputs, driven through
`_run_post_exit_validation`, asserting a PASS verdict and a recorded report.

### NA-2 (P3): the restart watcher misclassifies pre-restart cancellations

`_watch_reconciled_run` (service.py:432-436) maps every non-succeeded
terminal result to `failed`. The F1b cancel classification depends on the
`cancel_requested` callback, which is documented as "never persisted"
(run_launcher.py:399-402), and the executor never returns CANCELLED. A run
cancelled shortly before a server restart is therefore re-labeled `failed`
by the watcher. Record-accuracy issue only (no validation/promotion runs on
non-succeeded), but the closure history becomes wrong exactly when
operators investigate restarts.

## Known open items re-verified against the current tree

### K-1 (P1): the correction lane is display-only - no invocation path exists

HV-5 shipped the full correction machinery: run states
`correction_authorized` / `correcting` / `correction_exhausted`
(domain/runs.py:34-37, transitions at :84), projection and recovery routing
(run_views.py:216, 304, 360-365), the policy classification that feeds it
(domain/validation.py, ISS-6 reclass), the correction module itself
(application/correction.py: `revalidate`, `normalize`,
`build_correction_instruction`, `check_correction_bounds`), API action
types `revalidate_run` / `normalize_run_outputs` /
`request_output_correction` (api/models.py:40-52, mirrored in
web/src/api/types.ts:40), and UI messaging on the run page
(web/src/pages/RunPage.tsx:194-215 tells the user outputs "require
correction" and shows a "smallest correction" hint).

But there is NO way to invoke any of it: the router exposes only
start/cancel for runs (api/router.py POST routes at :265, :351, :387,
:476), no service method calls into `correction.py` (zero imports outside
the module itself), and the CLI has no correction command. A user whose
run lands in `needs_output_correction` is told what is wrong and given no
action to fix it. With ISS-6 routing the dominant failure class
(`schema.*`: 78+33+17+... findings in production) into
`needs_output_correction`, this is now the largest functional gap in the
recovery story: the diagnosis is wired end-to-end, the treatment is not.

Missing component: a correction command path (API endpoint(s) accepting the
output-correction command, service entrypoints calling
`correction.revalidate`/`normalize`/`build_correction_instruction`,
correction-bounded re-execution, and the UI actions to drive them).

### K-2 (P1, decision needed): two-lane output policy divergence persists

The formal lane repairs before validation
(`role_execution.py:1467` calls `_apply_disclosed_mechanical_repairs`,
disclosed via transformation records); the supervised WP-E1 lane validates
raw bytes with zero repair calls (`application/output_validation.py` has no
repair reference). FP-2.5 in the instruction-output-integrity fix plan
records the decision as unresolved: converge (both raw, or repairs
disclosed in both) or document the deliberate difference. The ISS-1..3
work widened the formal lane's repair surface (envelope population + ID
sanitization), which makes the divergence larger today than when FP-2.5
was written.

### K-3 (P2): stale redaction regex in the kanban executor

`executors/hermes.py:89` still uses `sk-[a-zA-Z0-9]{20,}`, which misses
`sk-` keys containing dashes or underscores (`sk-proj-...`).
`executors/local_hermes.py:77` carries the fixed `[a-zA-Z0-9_-]` class.
One-line alignment; flagged since WP-E0.

### K-4 (P2): the default `disabled` executor accepts formal run commands that never execute

With `executor_kind == "disabled"` (the default, settings.py:24),
bootstrap leaves `run_launcher=None` (bootstrap.py:60, 104-110) and
`start_run` creates the run in state `created` with no launch
(service.py:1225-1228). `execution_available=False` is surfaced in views,
but the command is still accepted and the run then sits in `created`
forever with no terminal reason. The stop-ship posture makes this
configuration the production default, so every formal-lane start in a
default deployment produces a zombie run. Options: reject start_run
commands when `execution_available` is false, or add an explicit
terminal "not executed" state.

### K-5 (P2): zero post-fix production exercise

The newest production closure is 2026-08-10; the entire HV program
(`63dca62`, 2026-08-15) and all ISS fixes (2026-08-16) are validated only
by the suite, probes, and fixtures. Production failure signatures the fixes
target (brief-obedient agents failing on harness-owned fields; schema.*
findings misrouted) have never been re-exercised by a real agent run. A
controlled re-run of a known-failing phase (for example a P2 full-catalog
run, the mode with the most production failures) through the repaired
formal lane is the cheapest strong evidence that ISS-1..7 moved the
failure rate.

### K-6 (P3): cosmetic transformation labeling

`_classify_transformations` still classifies by the old key-name heuristic,
so schema-derived ID sanitizations (ISS-7) and reference rewrites record as
generic `value_rewrite` instead of `id_sanitization`. Transformation
records stay complete; only the labels lag. Reported by the ISS-7/8
subagent, confirmed during this audit.

### K-7 (open, documented): reviewer-memory boundary

`10-open-implementation-gaps.md` keeps this open by design: sealing the
outside reviewer's packet does not prove empty memory; full closed-packet
review needs an ephemeral-session attestation or verified memory reset.

## Program-level remaining components

From the trusted-local execution program (the controlling plan):

1. **WP-I** (the only remaining work package): phase-specific output
   adapters with real Hermes fixtures, then the controlled five-phase pilot
   through the local path. Depends on WP-D/E/F (all complete); WP-H gate
   (complete) covers publishable runs.
2. **Correction command path** (K-1) - not a WP item; needs its own
   package.
3. **Instruction-integrity fix plan remainders**: FP-1.3 integration tests
   (the layered instruction mechanism is implemented and verified in this
   audit at run_coordinator.py:506-544 + task_briefs.py:703-746, but the
   empty/placeholder and missing-template integration cases are untested);
   FP-2 convergence decision (= K-2); FP-5 narrative acceptance scenarios;
   FP-6.1-6.3 small backend repairs; FP-7 frontend repairs; FP-8 design
   decisions (parallel-stage isolation, context-card granularity) awaiting
   Tez.

## Suggested order

NA-1 fix (small, includes its regression test) -> K-1 correction command
path (the largest missing component) -> K-5 controlled re-run (evidence
that the repair lane now converges real agent output) -> K-2 decision ->
K-3/K-4/K-6 small alignments -> WP-I.

## Fix log

### 2026-08-18 audit status update (coder; no code changes)

Verified against the tree at `74b243f` (suite 1122 green, vitest 120/120,
validator exit 0):

- **K-1: IN PROGRESS, P1-P3b landed.** The correction lane is no longer
  display-only: error codes (`ad3e2a6`), attempt-aware submission read and
  Lane A re-entry with the D4 family-first fix (`c1cf087`),
  `request_output_correction` service + `revalidate_run` descriptor
  (`b91fe9e`), and the `POST /projects/{id}/runs/{run_id}/corrections`
  endpoint (`74b243f`). Remaining K-1 work (normalize/preview, Lane B, UI)
  is sequenced as P4-P6 in
  [k1-remaining-implementation-plan-2026-08-17.md](k1-remaining-implementation-plan-2026-08-17.md).
- **K-3: FIXED** (`c79b02d`): kanban executor `sk-` redaction regex aligned
  with local_hermes; regression test added.
- **K-4: CLOSED as already-fixed** (`e4a98d9`, live probe 2026-08-17): the
  `executor.unavailable` gate rejects `start_run` when no executor is
  configured; no zombie run is created. The zombie-run claim above was
  stale.
- **K-6: FIXED** (`57529d4`): transformation classification uses the exact
  rename map; schema-derived sanitizations label as `id_sanitization`.
- **Still open**: NA-2 (tracked as P7 in the K-1 plan), K-2 (needs Tez
  decision), K-5 (production re-exercise after P1-P6 land), K-7 (open by
  design).

### 2026-08-16: NA-1 FIXED (commit c243fe5, subagent package, validator-verified)

`_run_post_exit_validation` no longer hand-builds `SealedRun(manifest={})`:
validation goes through the invocation-id string form and promotion through
`assembler._reconstruct(record)`, both digest-verified. The existing
best-effort try/except already wraps the whole body, so a tampered or
missing manifest is logged and skipped (no watcher crash). Two regression
tests in `tests/test_supervised_run_logs.py` (`TestPostExitValidation`):
real declared outputs + closed succeeded launch records a PASS verdict
(verified to record "fail" on pre-fix code), and a deleted manifest records
no pass and does not raise. Validator re-ran the acceptance chain
independently: suite 1073 green (1071 + 2), `validate_package.py` exit 0,
commit scope exactly the two intended files. NA-2 (cancel-vs-failed
relabeling across restart) remains open: a correct fix needs persisted
cancel intent, which is a design decision, not a mechanical repair.
