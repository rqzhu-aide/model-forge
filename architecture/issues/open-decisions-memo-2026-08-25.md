# Open Decisions Memo (2026-08-25)

Status: for Tez. Each item needs a decision; none blocks the running fresh
cycle. Recommendations are the coder's, prepared for audit.

Audit 2026-08-28 status line: D-1, D-7, and D-9 are decided and landed.
D-2 is CLOSED (stale premise - the code already implements its option (a);
see the item). D-3 is DECIDED (activate_method sealed transaction landed
2026-08-28). D-4 is DECIDED (FP closure sweep, commit 4a761f1). FP-7 is
CLOSED. Still waiting on Tez: D-5 (hidden vs dimmed context options). D-6
and D-8 remain open by design/partially mitigated as documented in their
items.

## D-1. P0-2: P5 contract presence model (context-selection issues) - RESOLVED

DECIDED by Tez 2026-08-26: the mode boundary is not a schema problem to be
patched with a third presence value; the phase should be situation-driven
like a researcher.  Tez's instruction: "given these materials, write the
draft if it is not established yet, and revise the draft if there is
already a preliminary version."

Landed (P5 contract 2.3.0 -> 2.4.0):
- `p5.current_manuscript` is now `required_on_rerun` (the P3 pattern):
  absent on the first manuscript run, required on reruns for the same
  stable method lineage.  Assembly reruns now SEE the established draft
  instead of an absent stub.
- New input `p5.review_target_manuscript` (`required_in_modes:
  [p5.review_revision]`) keeps the review-revision machine gate; the
  parallel review role_reads and the review packet source it.
- Assembly mode directive + stage-role assignment rewritten
  situation-driven: absent marker -> write the first manuscript; current
  draft -> continue and polish it, preserving supported claims.  Review
  findings remain review-revision-only.
- Review-revision stays a separate mode (the independent review panel is
  a real quality gate); only the input semantics unified.
- Researcher-supplied material enters through the seed channel, revised
  2026-08-28 (ADR-019 superseding ADR-018, scenario S31): the run command
  carries `seed_inputs` mapped to declared supplementary slots
  (`pN.researcher_material`), the seed freezes with researcher_seed
  provenance, and seeds are additive only - a seed can never replace a
  required published input, so a finished foreign manuscript cannot enter
  at P5.  A researcher's own paper enters at P1 as supplementary material
  and the pipeline builds around it; pure paper-auditing of an external
  draft is out of scope.

History: the original D-1 analysis (options a/b/c, recommendation b)
superseded by Tez's direction.

## D-2. K-1 D5: revalidate unreachable for REJECTED runs - CLOSED (stale premise)

Audit 2026-08-28: the premise below is refuted by the code. Correction
eligibility already includes `rejected` (service.py:2299 and :3022), and
`_correction_target_closure` implements exactly option (a): for REJECTED runs
it targets the newest SUCCEEDED closure covering the requested scope
(service.py:2870-2890). This has been in the code since before this memo
(commit 90f84f1, 2026-08-23). Retained below as the historical record; no
decision is needed.

The correction command path targets the newest FAILED closure; a REJECTED
run (submission rejected at the gate) has no failed closure, so revalidate
cannot be authorized even when the rejection findings are correctable.
The K-1 plan left D5 open "for the method owner".

Options:
- (a) Extend the target-closure rule: for REJECTED runs, target the newest
  SUCCEEDED closure covering the requested scope (the code comment at
  service.py:2132 already sketches this).
- (b) Leave as-is; a rejected run is recovered by launching a fresh run.

Recommendation: (b). A rejection means the submission itself was not
publishable; re-running with corrected instructions is the honest path,
and the fresh-cycle evidence shows re-runs are cheap (~35-75 min).

## D-3. User activation of proposed methods costs a full P2 run - DECIDED 2026-08-28

DECIDED by Tez 2026-08-28: option (a) landed. `activate_method` is a sealed
user control transaction (proposed -> active) through the same atomic
method+catalog command path as retire/reactivate; the Phase 2 method table
offers Activate for proposed methods. No Phase 2 rerun is required. Original
analysis retained below.

Discovered 2026-08-24: P3/P4 require the selected method lifecycle =
active, and the only path from proposed to active is a P2 publication
(view_models.py:189: "A proposed method must be activated by a Phase 2
research publication"). Selecting a method after a catalog run therefore
costs a full extra P2 run (~35-40 min) whose only content change is one
lifecycle flag.

Options:
- (a) Add an authenticated user control transaction "activate method"
  (proposed -> active), sealed like the lifecycle command, with the audit
  trail. This makes the select-to-advance moment a first-class user
  authority act (consistent with retire/reactivate being user acts).
- (b) Keep the P2-publication-only path (status quo).

Recommendation: (a). The current path burns a full multi-role run to
record one bit of user intent; the activation IS a user decision by
design, so a direct sealed transaction is the honest shape. Small package:
lifecycle transition extension + command path + UI action + tests.

## D-4. FP-8: parallel-stage isolation (design) - DECIDED 2026-08-28

DECIDED in the instruction-output-integrity closure record
(archive/instruction-output-integrity-fix-plan.md, "FP-8 decisions";
commit 4a761f1): designed-deferred, matching the recommendation below.

Should P1 discovery and P5 parallel reviews get harness-enforced read
scoping instead of instruction-only isolation? This is a contract plus
harness change and needs its own plan if yes.

Recommendation: defer. Instruction-only isolation has produced no observed
cross-contamination finding in any production run to date (46 archived +
fresh cycle). Revisit if a contamination finding ever surfaces.

## D-5. P1-3: hidden vs dimmed unavailable context options (product)

Context options hidden by mode are currently invisible
(`_HIDDEN_BY_MODE`); the alternative is to show them dimmed with a reason.

Recommendation: keep hidden. A dimmed-but-unselectable option invites the
question "why can't I select this" on every page; the phase view already
documents the mode's basis.

## D-6. K-7: reviewer-memory boundary (open by design)

Documented as deliberately open; no action proposed. Noted here so the
audit trail shows it was considered in this sweep.

## D-7. Long synchronous commands orphan on client disconnect (C-3) - RESOLVED

DECIDED by Tez 2026-08-26: detached background-task corrections (option a)
plus reconciliation (option b's safety net).  Landed in this package:

- Lane B corrections now run as detached asyncio tasks (the same pattern
  as run launches): the command seal + correcting transition stay
  synchronous (command errors still reach the caller), then the response
  returns immediately and the worker settles the run asynchronously.
  A client disconnect can no longer cancel an invocation mid-flight.
- Repeat requests while a worker is in flight return current state without
  double-firing (in-flight task registry per run).
- Startup reconciliation marks runs left in `correcting` whose newest
  correction command never closed (`run.correction_interrupted` event;
  HV-5.8 respected - no auto-advance; the lane bound is never spent
  because attempt rows are written only at closure).

IMPORTANT CORRECTION to the C-3 autopsy below: store forensics on run
cddfc1fb (2026-08-26 re-examination) show the "orphaned" correction was
nothing of the kind - it ran 29 minutes and closed FAILED honestly
(closure + attempt rows both timestamped 03:06:35Z, one finding); the run
then sat in `correcting` per D6 awaiting the next command, and the
CORRECTION_EXHAUSTED refusal was the bounded-lane rule working as
designed.  The disconnect-cancellation causal claim is REFUTED for that
instance: attempt rows are written at closure, so a true mid-flight kill
cannot spend a lane.  The detachment above still removes the real residual
hazards (long-held HTTP connections, illegible in-flight state).

Historical record of the original observation follows.

Observed 2026-08-26 in production: Lane B corrections ran SYNCHRONOUSLY
inside the HTTP request handler (`await execute_targeted_correction` in
`request_output_correction`, ~30-60+ min for a role re-invocation). When
the issuing client disconnects (a 30s client timeout did this), the ASGI
server cancels the handler mid-invocation: the run is left in
`correcting` with no live worker, no outcome events, and - because HV-5.6
bounds count the recorded attempt conservatively (recorded at invocation
start, pass or fail) - the single scientific attempt is SPENT without
ever running. The only recovery is a full phase rerun.

Options:
- (a) Run corrections as detached background tasks: seal the command,
  return 202 immediately, execute via the launcher; the UI polls state
  (it already does). The restart-reconciliation machinery then also
  covers corrections.
- (b) Keep synchronous execution but document that clients must hold the
  connection, and add reconciliation for orphaned `correcting` runs
  (no live invocation + no outcome -> re-open the lane).
- (c) Both.

Recommendation: (a) - it matches how runs themselves launch (the run
start command returns at launch, not at completion) and reuses the
existing reconciliation. (b)'s reconciliation half is worth doing
regardless as a safety net.

Addendum (2026-08-26, second exercise on run e32ca610): the request
returned 200 within seconds while the invocation + closure ran in the
background - so the handler is NOT purely synchronous; the orphan
mechanism in attempt 1 needs the Phase-1 replay loop to pin down (per
the diagnosing-bugs discipline: the disconnect-cancellation causal claim
remains UNVERIFIED by reproduction). Also confirmed D6 semantics live:
a failed correction closure with one lane's bound remaining leaves the
run in `correcting` BY DESIGN (no transition event) - the recovery is
the other lane or a fresh command, not a wedge. The packaging lane then
recovered the run.

## D-8. Harness-owned envelope fields are only stamped AT SEAL (F-3)

`content_sha256`, `created_at`, `schema_version` sit in the harness-owned
set (envelope.py) and are recomputed/overwritten at sealing - but
validation runs on the raw agent output and still REQUIRES them. The
agent must therefore author bootstrap values for fields it cannot
compute correctly by construction (a self-referential digest). F-1b/F-1c
added the population tier for `record_type` only; the same treatment was
never extended to the envelope trio. Production cost: the P4 correction
invocation (run e32ca610) wrote the right scientific content with the
wrong envelope shape and burned the scientific attempt on
`schema.required` findings for exactly these fields.

Recommendation: extend the F-1 population machinery so harness-owned
fields are populated BEFORE validation (compute content_sha256 over the
agent content, set created_at, const-populate schema_version), making
validation check science, not plumbing. Schema/contract version impact:
population is harness-side; no contract text changes required if the
schemas already declare these fields harness-owned - verify per schema
before implementation.

## D-9. Rejection detail is not persisted; closure-vs-submission validation asymmetry

Observed 2026-08-26 (P5 run d93f5891 rejected, submission.validation_failed):

1. RESOLVED 2026-08-26 (commit f9c3e69): the full findings were persisted
   all along (`_reject` writes `closure_findings`; `run_views.py:391`
   surfaces them); the gap was per-finding detail in the API projection and
   any UI rendering.  `FindingGroupView.items` now carries each finding
   (code, message, object_id, json_pointer; capped 100/group) and the run
   page renders an expandable per-finding list.
2. The same `_validate_p5` claim-linkage rule produced 0 findings at role
   closure but 25 at submission over the same sealed outputs (verified by
   local replay of the real validator against the sealed artifacts).
   MECHANISM VERIFIED 2026-08-26: role closures run structural validation
   only (`validate_role_outputs`); `validate_phase_scientific` is called
   exactly twice - at submission (`submission_validation.py:198`) and in
   the legacy launch path (`output_validation.py:830`).  No skip bug at
   closure: scientific validation simply never runs there.  DESIGN
   QUESTION for Tez: run phase-level scientific validation when a phase's
   final stage closes (catches claim-level defects before submission, at
   the cost of one validator pass per phase), or keep submission as the
   first scientific checkpoint by design.

   DECIDED by Tez 2026-08-26: NO closure-time validator.  Instead the lead
   role performs the scientific check as part of its review - the system
   should behave like a research team, where the team lead verifies
   claim-evidence linkage before anything leaves the team, and the outside
   reviewer (submission gate; ideally a different model provider) stays a
   REAL independent audit, not the first checkpoint.  Landed: P4 contract
   2.3.0 -> 2.4.0 and P5 2.2.0 -> 2.3.0 (lead stage objectives now carry
   the in-house scientific check), matching prose in phase-4.md/phase-5.md,
   the research_lead soul states the duty, and the example digest cascade
   (command/manifest/role starts/closures/submission/journal/receipt/audit
   chain) re-rooted.
3. ADJACENT FIX LANDED 2026-08-26: the legacy launch-path phase-consistency
   check silently `_skip`ped when declared+parsed outputs could not bind to
   sealed inventory entries (`output_validation.py:824`); it now fails
   loud, since that condition means the seal or inventory is structurally
   suspect.  Legitimate skips (no validator for the phase; no phase-prefixed
   outputs at all) remain skips.

## FP-7 status (frontend small repairs) - CLOSED 2026-08-28

All FP-7 items landed and verified in the instruction-output-integrity
closure sweep (commits fac1b2c, 4a761f1; closure record in
archive/instruction-output-integrity-fix-plan.md). Original note: being
handled in this sweep as code items where the intent is unambiguous
(validation-report link, size badge, fetch routing, retired-panel cleanup).
FP-7.4 (per-option deselection) is folded into D-4/D-5 and stays with the
design decision.

## SK: skill attachment configuration (decided 2026-08-26)

DECIDED by Tez: team members carry configurable skill sets at phase
granularity at minimum, with a skill selector UI on each member
configuration page.  Folded into the active plan
[skill-selector-and-role-skill-configuration-2026-08-26.md](../archive/skill-selector-and-role-skill-configuration-2026-08-26.md)
(packages SK-1 through SK-5).  Per-stage and per-run overrides are
deferred and recorded in that plan.  Related landed groundwork: custom
skills made real (9831988); the lead in-house scientific check (926aa53);
P5 situation-driven manuscript handling (c31ed46).
