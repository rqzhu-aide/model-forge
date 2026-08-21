# E-1: P2 Structured Lead Evaluation - Implementation Program

Status: ACTIVE (2026-08-21). Contract authority: ADR-017 (Accepted).

Tez directive (2026-08-21): restructure P2 evaluation - stage 1 proposes
without the lead; stage 2 reviewers file structured per-method
evaluations keyed by contracted stable_id; stage 3 lead adjudicates and
seals 1-10 scores on three axes (theoretical validity + identifiability,
literature positioning + novelty [lead-only], empirical testability +
computational efficiency) into each method record; the catalog row card
displays the scores. Stage-1 proposer context always encourages unique
literature positioning and high novelty.

## Package plan (dependency order)

### E-1a - Contract (architecture only)

- P2.json: stage-1 roles [theorist, data_analyst]; remove
  p2.lead_proposal output; stage-1 objective gains the novelty
  encouragement (renders into task briefs, ADR-013); stage-2 review
  outputs gain the structured evaluation requirement; stage-3 outputs
  gain the per-method evaluation block; validation_rules updated
  (score range 1-10, justification required, issue refs resolve,
  evaluation required for every method in the change set under the new
  contract version).
- phase-2.md: sections 5 (role order), 6 (run-local outputs), 7
  (machine validation), 8 (assessment boundary) rewritten to match.
- schemas/method.schema.json: optional `evaluation` block (three axes,
  score 1-10 + justification + issue_refs + adjudicated_at +
  review_basis_ids).
- schemas/review-report.schema.json: `method_evaluations` array
  (stable_id + axis assessment + issue refs) and issues keyed by
  stable_id.
- traceability.json + validate_package.py rules + stage-role
  instruction docs + contract fixtures.
- Gate: validator exit 0.

### E-1b - Backend

- Contract/schema loading for the new blocks; MethodRow assembly
  exposes `evaluation`; removal of p2.lead_proposal from registries,
  task-brief skeletons, and any stage-composition consumers; fixtures
  updated (P2 runs in tests lose the lead stage-1 role).
- Gate: pytest suite green (1204 baseline; expect fixture churn).

### E-1c - Web display

- MethodRow type gains `evaluation`; method row card renders a
  three-chip score strip (score + tone); justifications and issue links
  in the details disclosure; methods without evaluation render
  "Not yet evaluated" (all 9 current catalog entries).
- Gate: vitest green (140 baseline).

### E-1d - Production exercise

- One controlled P2 full-catalog run under the new contract
  (local_hermes executor, same safety recipe as K-5: backup, serve,
  mode-scoped descriptor, fresh idempotency key, monitor). Verify:
  stage 1 runs with two proposers, reviews carry structured
  evaluations, scores seal into method records, the row card displays
  them.
- Evidence doc under architecture/evidence/.

## Notes

- The 46-issue vocabulary observed on 2026-08-21 (validity 16,
  computation 13, empirical_testability 6, scope 6, ...) maps onto the
  three axes as: validity+identifiability -> axis 1; empirical
  testability + research_attention -> axis 3 (testability half);
  computation + reproducibility + scope -> axis 3 (efficiency half);
  literature/novelty concerns -> axis 2 (lead adjudication).
- Pre-change method records keep no evaluation block; no migration.
