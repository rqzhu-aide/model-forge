# K-5 Production Re-Run: P2 Full Catalog PUBLISHED (2026-08-21)

Controlled re-run of the P2 `p2.full_catalog` mode after the K5-1..K5-4
fix round (ADR-015, ADR-016; commits b334f86, 87427ec, e3470ae, c6183ea,
4a592bd), per the K-5 execution plan in
`architecture/plans/k1-remaining-implementation-plan-2026-08-17.md`.
Predecessor: `k5-production-re-exercise-2026-08-20.md` (the run that
exposed K5-1..4).

## Setup (identical to the 2026-08-20 exercise)

- Backup before exercise: `~/.model-forge-backups/20260821-074407` (56 MB).
- Server: `MODEL_FORGE_EXECUTOR_KIND=local_hermes
  MODEL_FORGE_DATA_ANALYST_PROFILE=data_scientist model-forge serve`
  (loopback :8765), started fresh from the tree at `5a287cc` (a stale
  Aug-20 server process still bound to :8765 was stopped first; it held
  pre-fix code in memory).
- Project: `project.entangled_langevin_particle_acceleration.b2d9f388...`
  (27 historical full-catalog runs: 22 failed, 5 published; plus the
  2026-08-20 controlled failure).
- Controlled input: the SAME instruction text as the last published
  full-catalog run (`...9789b57d`), `current_only`, the five default
  current inputs (unchanged since the prior exercise), mode-scoped phase
  view descriptor, fresh Idempotency-Key.
- Run: `run.p2.p2-full-catalog.fb8d6b2b22ea4126bc6ab9b2939fae64`,
  launched 2026-08-21 07:50:14 CDT via `POST /runs` (201).

## Run outcome: PUBLISHED

Terminal state `published` at 08:24:11 CDT, ~34 minutes wall time. Event
timeline (CDT):

| Time | Event |
|---|---|
| 07:50:14 | created -> preparing -> prepared -> running |
| 08:02:28 | stage 1 `p2.independent_proposals` succeeded (3 roles, ~12 min) |
| 08:14:07 | stage 2 `p2.cross_review` succeeded (2 roles, ~12 min) |
| 08:24:11 | stage 3 `p2.lead_reconciliation` succeeded (1 role, ~10 min) |
| 08:24:11 | submitted -> validating -> promoting -> published (atomic) |

All six stage-role closures sealed SUCCEEDED with ZERO findings each:

| Stage | Role | Outputs | Findings |
|---|---|---|---|
| independent_proposals | research_lead | 1 | 0 |
| independent_proposals | theorist | 1 | 0 |
| independent_proposals | data_analyst | 1 | 0 |
| cross_review | theorist | 1 | 0 |
| cross_review | data_analyst | 1 | 0 |
| lead_reconciliation | research_lead | 3 | 0 |

Publication receipt `receipt.1864f6c20dda88a09485de0b871c...`: atomic
commit, authority sequence 132 -> 152, current revision 9 -> 10,
committed 2026-08-21T13:24:11Z. The run has ZERO validation-attempt rows:
the correction lane was never entered because nothing failed.

## What this evidences

- **K5-1 (ADR-015) resolved in production.** The stage-1 theorist handoff
  (a broadcast into the two-role cross_review stage) failed
  `schema.required` on `to_role` deterministically in the 2026-08-20 run.
  Under the broadcast-optional contract the same stage passed with zero
  findings. The stage-1 wall (~40 min to failure on 2026-08-20) is gone.
- **The historical failure signature is gone.** All 22 historical
  full-catalog failures were `output.structural_validation_failed` at
  `lead_reconciliation` (research_lead) with unclassified schema.*
  findings. The lead reconciliation closure sealed 3 outputs, 0 findings.
- **Baseline shift:** the full-catalog mode goes from 22 failed / 5
  published (historical, pre-repair) and 0/1 (controlled, 2026-08-20) to
  a clean 1/1 publish on the repaired build (suite 1204 green, validator
  0 at `5a287cc`).
- **The correction lane was not exercised** (nothing failed), so the
  K5-4 resume edge has test-suite evidence (mid-pipeline E2E in
  `tests/test_correction_resume.py`) but no production exercise yet. That
  is the desired outcome for this run, not a gap in the evidence: the
  lane exists for failures, and this run produced none.

## Housekeeping

- The exercise server was stopped afterwards; the default posture
  (executor=disabled) is restored.
- K-5 is CLOSED. K-7 (reviewer-memory boundary) stays open by design.
