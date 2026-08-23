# K-5 Evidence Gate Re-Run: P2 Full Catalog PUBLISHED (2026-08-23)

Controlled production re-run of the P2 `p2.full_catalog` mode on the
current tree (`1f0b240`), per the plans-README completion order
(refreshed 2026-08-22, `ba2ec89`): the K-1 plan is COMPLETE and this
re-run is the evidence gate over the E-1 (structured lead evaluation,
ADR-017) and E-2a..d (information layers, primary-pointer stamping)
work landed since the 2026-08-21 K-5 closure.

Predecessors: `k5-production-re-exercise-2026-08-20.md` (exposed
K5-1..4), `k5-production-re-run-2026-08-21.md` (K-5 closure, tree at
`5a287cc`), `e1d-run-2026-08-21/` (first ADR-017 run), and the E-2c
exercise (2026-08-22, tree at `ed85b55`).

## Setup (same safety recipe as the prior K-5 exercises)

- Pre-flight: suite 1222 passed, validator clean (5 phase contracts,
  47 schemas) at `1f0b240`; no stale `:8765` listener.
- Backup before exercise: `~/.method-hub-backups/20260823-094232`
  (103 MB).
- Server: `METHOD_HUB_EXECUTOR_KIND=local_hermes
  METHOD_HUB_DATA_ANALYST_PROFILE=data_scientist method-hub serve`
  (loopback :8765), booted fresh from the tree at `1f0b240`.
- Project: `project.entangled_langevin_particle_acceleration.b2d9f388...`.
- Controlled input: the SAME 903-character instruction text as the
  `...9789b57d` run and both prior K-5 exercises (verified
  byte-identical from the run store), `current_only`, the five default
  current inputs (project_brief, literature_synthesis,
  literature_library, literature_coverage, current_catalog),
  mode-scoped phase view descriptor, fresh Idempotency-Key.
- Run: `run.p2.p2-full-catalog.e13a6b3761684126af5729794be9262e`,
  launched 2026-08-23 09:44:22 CDT via `POST /runs` (201).

## Run outcome: PUBLISHED

Terminal state `published` at 11:26:50 CDT, ~102.5 minutes wall time.
Event timeline (CDT):

| Time | Event |
|---|---|
| 09:44:22 | created -> preparing -> prepared -> running |
| 10:16:30 | stage 1 `p2.independent_proposals` succeeded (2 roles, ~32 min) |
| 11:12:24 | stage 2 `p2.cross_review` succeeded (2 roles, ~56 min) |
| 11:26:50 | stage 3 `p2.lead_reconciliation` succeeded (1 role, ~14.5 min) |
| 11:26:50 | submitted -> validating -> promoting -> published (atomic) |

All five stage-role closures sealed SUCCEEDED with ZERO findings each
(stage 1 has two proposers and no lead since ADR-017, matching the
E-1d shape):

| Stage | Role | Outputs | Findings |
|---|---|---|---|
| independent_proposals | theorist | 1 | 0 |
| independent_proposals | data_analyst | 1 | 0 |
| cross_review | theorist | 1 | 0 |
| cross_review | data_analyst | 1 | 0 |
| lead_reconciliation | research_lead | 3 | 0 |

Publication receipt `receipt.7b786ec64201d8c664cbea10e06f43...`,
committed 2026-08-23T16:26:50Z. The run has ZERO validation-attempt
rows: the correction lane was never entered because nothing failed.
The method catalog grew 12 -> 14 active methods.

## E-1/E-2 behaviors verified live (the gate's purpose)

- **E-1 structured evaluation seals (ADR-017).** Both change-set
  method records carry complete adjudicated three-axis evaluations
  with justifications, issue_refs, and 3 review_basis_ids each:
  SGEL `method.entangled_shared_gradient_langevin` = validity 4 /
  feasibility 5 / positioning 5; AREL
  `method.array_rqmc_entangled_langevin` = 5 / 6 / 6.
- **E-2b compact-first materialization.** Every role workspace
  received `inputs/compact/p2.literature_synthesis.md` (2,750 B)
  alongside the full records: stage-1 roles 5 full inputs (~405 KiB),
  stage-2 roles 7 (~445 KiB), stage-3 lead 9 (~517 KiB).
- **E-2 artifact integrity.** All 14 sealed artifacts for the run
  (9 contract outputs incl. sidecars, 5 role-closure documents, run
  recipe, publisher transform) re-hash to their recorded sha256.
- **Delimited-LaTeX convention (`1f0b240`).** The two new method
  records carry 66 and 43 `$...$`-delimited math spans in their
  canonical definitions and summaries; a small number of bare commands
  remain in prose (2 and 5 occurrences) - minor compliance residue,
  not a validation failure.
- **Correction lane.** Not entered (nothing failed) - the desired
  outcome, consistent with the 2026-08-21 closure.

## New residual finding: P2 canonical_artifact pointers dangle

Same failure class as the E-2c residual gap (primary_artifact
pointers, fixed by E-2d for P1/P3), but in a field E-2d did not
cover: the P2 method record's
`mathematical_definition.canonical_artifact`:

- SGEL: `artifact://theory_proposal/p2/theory-proposal.json` claims
  sha256 `7b17e46c...` - present NOWHERE in the artifact store or
  artifacts table; the sealed `p2.theory_proposal` output for this
  run is `63f8e7ae...` (27,693 B).
- AREL: `generation://p2_independent_proposals/generation.method.
  array_rqmc_entangled_langevin.p2.001` claims `ff076ea6...` - the
  target generation exists but its content_sha256 is `d3c6ff99...`.

Policy 1.11.0 validates primary-pointer layers at the
coverage/theory/analyst (P1/P3) call sites only; no P2 call site
validates canonical_artifact, so validation passed. The record content
itself is safe (records are content-addressed in formal_generations;
the role outputs are independently sealed), but the declared pointer
hashes are agent-invented. Candidate fix: extend the E-2d
stamping/validation mechanism to the P2 canonical_artifact field.

## Timing note

~102.5 min wall vs ~34 min (2026-08-21, pre-ADR-017) and ~65 min
(E-1d). Stage 2 cross-review accounts for the growth (~56 min): the
reviewers now produce structured evaluations over a 12-method catalog
with compact-first inputs. No stage stalled; timings are agent work,
not harness overhead.

## Housekeeping

- The exercise server was stopped afterwards; the default posture
  (executor=disabled) is restored.
- The K-5 evidence gate is satisfied for the E-1/E-2 build. The
  canonical_artifact residual is tracked as a candidate E-2 follow-up
  (same shape as the retired E-2c gap).
