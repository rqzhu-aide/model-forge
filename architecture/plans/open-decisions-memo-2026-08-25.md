# Open Decisions Memo (2026-08-25)

Status: for Tez. Each item needs a decision; none blocks the running fresh
cycle. Recommendations are the coder's, prepared for audit.

## D-1. P0-2: P5 contract presence model (context-selection issues)

The P5 contract cannot express "required in one mode, optional in another":
`presence: required_in_modes` is the only conditional form and the schema
forbids combining it with an optional base. Effect: in P5 assembly mode the
prior manuscript slot is invisible (`p5.current_manuscript` is
required_in_modes=[p5.review_revision] only), so a first assembly run has
no manuscript input by design.

Options:
- (a) Add a presence form `optional_in_modes` / `required_except_modes`
  (schema change, needs an ADR).
- (b) Keep the current model; accept that assembly always starts from the
  P4 outputs (a prior manuscript enters only via review_revision).
- (c) Split P5 into two modes with separate presence declarations.

Recommendation: (b) for now - the first P5 run is unaffected, and the
review-revision loop is the only path that needs the prior manuscript.
Revisit when a second manuscript version is needed. If (a) is preferred,
this is a small schema + ADR package.

## D-2. K-1 D5: revalidate unreachable for REJECTED runs

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

## D-3. User activation of proposed methods costs a full P2 run

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

## D-4. FP-8: parallel-stage isolation (design)

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

## D-7. Long synchronous commands orphan on client disconnect (C-3)

Observed 2026-08-26 in production: Lane B corrections run SYNCHRONOUSLY
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

## FP-7 status (frontend small repairs)

Being handled in this sweep as code items where the intent is unambiguous
(validation-report link, size badge, fetch routing, retired-panel cleanup).
FP-7.4 (per-option deselection) is folded into D-4/D-5 and stays with the
design decision.
