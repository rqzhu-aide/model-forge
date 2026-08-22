# E-1d: Production Exercise Under Contract 2.1.0 (2026-08-21)

First controlled P2 run under ADR-017 (structured lead evaluation).
Project: entangled Langevin particle acceleration (same controlled
instruction, `current_only`, five default inputs as the K-5 re-run, for
comparability). Backup: ~/.method-hub-backups/20260821-185755 (61 MB).

## Run facts

- Run: `run.p2.p2-full-catalog.a20a05553cdf41339eac49e7713b965d`
- Contract: P2 version 2.1.0 (first run under the scoring contract)
- Launched ~18:59 CDT, published ~20:04 CDT (~65 min wall; stage 3
  reconciliation was the long pole, consistent with the added
  adjudication work)
- Publication: clean - 0 validation findings, 0 correction-lane attempts
- Change set: 2 new methods (ASN-EL, SNEL), catalog now 11 methods

## Verified (the ADR-017 checklist)

1. Stage composition: stage 1 executed exactly two proposers
   (01-theorist, 01-data_analyst; no research_lead). PASS
2. Lead adjudication sealed: both change-set method records carry a
   complete evaluation block (three axes, integer scores 1-10,
   substantive justifications - e.g. "T1 (marginal exactness) is PROVED
   and independently reproduced...", review_basis_ids naming the actual
   proposal/review handoffs). PASS
   - ASN-EL: validity 7, novelty 6, feasibility 8
   - SNEL: validity 7, novelty 6, feasibility 7
3. Enforcement stayed silent on conformant content: the new
   p2.method_evaluation_* / p2.review_axis_violation checks fired zero
   findings. PASS
4. UI: the catalog row cards show real score chips with tone bands
   (screenshot: e1d-catalog-real-scores.png); the 9 pre-change methods
   correctly render "Not yet evaluated" (e1c-not-yet-evaluated.png). PASS

## Findings exposed by the exercise (honest gaps)

### G1. Reviewer structured evaluations are NOT produced (E-1a mistarget)

Stage-2 review outputs (p2.theory_review, p2.empirical_review) are
declared with `architecture/schemas/handoff.schema.json` (kind: audit),
NOT review-report.schema.json. E-1a's EDIT 4 added `method_evaluations`
to review-report.schema.json, which P2 stage 2 does not use, so the
reviewer task briefs never surface the field and the agents produced
none (verified: 0 method_evaluations in both review handoffs).

The reviewers still delivered substantive unstructured reviews (12 + 12
unresolved_issues with category/severity; the theorist numerically
verified a disputed closed form before flagging it), and the lead's
sealed justifications visibly draw on them. But the contracted
structured reviewer signal is absent.

Proposed fix (E-1e, small): add optional `method_evaluations` to
handoff.schema.json (audit kind), add optional `stable_id` to the
handoff unresolved_issues item shape, update the two stage-2 instruction
templates to require per-method evaluations on the owned axis, and add a
blocking P2 validator rule requiring the field's presence on review
outputs (the existing p2.review_axis_violation check then has teeth).

### G2. E-1b assembly shipped unwired (caught by live probe)

_method_evaluation() was added but never passed to the MethodRow
constructor; the API returned evaluation=None for scored methods.
No test covered the wiring. Fixed in 3fee8f6 with an end-to-end
list_methods test (test_list_methods_surfaces_sealed_evaluation).
Lesson recorded: helper-level tests do not prove assembly wiring; every
new view field needs one end-to-end projection test.

## Gates after the fixup

- pytest: 1206 passed (1205 + 1 wiring test)
- validator: exit 0
- vitest: 148 passed (E-1c)
