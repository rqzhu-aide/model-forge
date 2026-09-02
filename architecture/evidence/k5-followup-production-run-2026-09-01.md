# K-5 Follow-Up Production Run: P2 Full Catalog FAILED, Correctable (2026-09-01)

Controlled production exercise of the post-audit-fix build (harness audit
2026-08-31 fix program, packages P-A through P-I landed; HEAD `bdf5610`,
suite 1388 green per the program log). Recipe followed:
`k5-production-re-run-2026-08-21.md`. Predecessor era:
`k5-production-re-run-2026-08-23.md`.

## Precondition check

- Fix program: P-I marked DONE (`plan/harness-audit-2026-08-31-fix-program.md`;
  fix commit `ba713a4`, tests 1373 -> 1388, gates green). HEAD `bdf5610` is
  the mark-DONE doc commit on top of `ba713a4`; no code delta.
- Tree: clean. One untracked `.tmp_readmes/` directory (unrelated README
  scrape) was parked to `/tmp` before the exercise, not deleted.
- Port :8765 was held by a stale `model-forge serve` (pid 478416, pre-dating
  the exercise); killed before serving.

## Setup deviations from the recipe (environment drift, recorded)

1. **Role profile override inverted.** The recipe's
   `MODEL_FORGE_DATA_ANALYST_PROFILE=data_scientist` now FAILS BOOT:
   `bootstrap._verify_hermes_profiles` raised
   `ValueError: Hermes profiles not found on disk: data_analyst
   (data_scientist)`. The `data_scientist` profile no longer exists; a
   configured `data_analyst` profile now does (glm-5.3-flash via z.ai,
   own auth.json). The server was started WITHOUT the override
   (`MODEL_FORGE_EXECUTOR_KIND=local_hermes .venv/bin/model-forge serve`).
   Role profiles in play: research_lead (kimi-k3), theorist, data_analyst
   (glm-5.3-flash). The model-forge skill's production-exercise reference
   was updated to match.
2. **Project/run-store era changed.** The run store was reset around
   2026-08-24: the recipe's project `...b2d9f388...` and its instruction
   chain (run `...9789b57d`) are gone from the live DB. Current project:
   `project.entangled_langevin_particle_acceleration.71e5a01fab594a1c8329766bb6fd1d66`.
3. **Instruction text.** The last published full-catalog run in the live
   store (`...98e86f9b`, 2026-08-25) is a one-off user-directed selection
   pass (605 chars) whose preconditions are stale (it pins a four-record
   catalog and a selection that P3-P5 have since consumed). Used instead
   the standard catalog-building instruction (1064 chars) from the last
   published catalog-building run `...8fd97448` (2026-08-25), the direct
   analogue of the old chain text. Same mode (`p2.full_catalog`), same
   `current_only` policy, default current inputs (5: project_brief,
   literature_synthesis, literature_library, literature_coverage,
   current_catalog), mode-scoped phase-view descriptor, fresh
   Idempotency-Key.
4. Backup before exercise: `~/.model-forge-backups/20260901-225450`
   (149 MB).
5. There is no `/api/v1/health` route (404); readiness was verified via
   `GET /api/v1/projects` (200).

## Run

- `run.p2.p2-full-catalog.9c2c4093d1a74d98a21357e2383b6bc2`, launched
  2026-09-01 23:01:15 CDT (04:01:15Z) via `POST /runs` (201), phase
  contract 2.5.0.

## Run outcome: FAILED at stage 3, all findings correctable

Terminal state `failed` at 06:39:00Z (01:39 CDT), wall time 2 h 37 m 45 s
(launch to terminal event). Event timeline (UTC):

| Time (UTC) | Event |
|---|---|
| 04:01:15 | created -> preparing -> prepared -> running |
| 05:04:44 | stage 1 `p2.independent_proposals` succeeded (63.5 min) |
| 06:16:33 | stage 2 `p2.cross_review` succeeded (71.8 min) |
| 06:39:00 | stage 3 `p2.lead_reconciliation` FAILED (22.5 min) |
| 06:39:00 | run.failed: "A declared role group failed. No scientific role was retried." |

Closures and findings per role (from `role_execution_closures`):

| Stage | Role | Closed (UTC) | Status | Outputs sealed | Findings |
|---|---|---|---|---|---|
| independent_proposals | theorist | 04:19:04 | succeeded | 1 (theory_proposal) | 0 |
| independent_proposals | data_analyst | 05:04:44 | succeeded | 1 (empirical_proposal) | 0 |
| cross_review | theorist | 05:30:48 | succeeded | 1 (theory_review) | 0 |
| cross_review | data_analyst | 06:16:33 | succeeded | 1 (empirical_review) | 0 |
| lead_reconciliation | research_lead | 06:39:00 | FAILED | 2 (attention_items, decision) | 4 |

The failing output `p2.method_changes` was NOT sealed; the two valid
stage-3 outputs were sealed inside the FAILED closure. Findings (all
`finding_class=correctable_contract_error`, `correction_class=packaging`,
`blocks_publication=true`):

1. `schema.required`: 'lineage' is a required property, at `/0`.
2. `schema.required`: 'artifact_id' is a required property, at
   `/0/mathematical_definition/canonical_artifact`.
3. `schema.required`: 'sha256' is a required property, same pointer.
4. `schema.pattern`: uri
   `input://inputs/1214a10bbb978463b8db2f2c31ede380907e4a42c2f1a20cca59afaa066e27`
   does not match `^(artifact|generation|run)://[^\s]+$`.

Notable detail: the invalid uri digest is a 62-character truncation of the
stage-1 theorist proposal artifact sha256
(`f11214a10bbb...` -> `1214a10bbb...`, leading `f1` dropped), wrapped in
the non-contract `input://` scheme. The agent invented a pointer instead
of referencing the sealed artifact.

## Correction lane: NOT entered

Zero `run_validation_attempts`, zero submission rows for this run. The
run detail offers `available_recovery_controls`: revalidate, normalize,
packaging, scientific. Lane entry is operator-authorized post-failure,
not automatic: the 2026-08-26 P4 precedent (`...cddfc1fb`) shows
`failed` at 02:26:42Z, then `correction_authorized` at 02:37:11Z via an
explicit correction command. Per the exercise protocol (poll to terminal,
do not interrupt), no correction was authorized in this session, so the
rebuilt correction lane (fix program P-C: R3, R4, R7, R13, R22) still has
no production exercise. **Recommended follow-up:** authorize the
`packaging` correction on THIS run (it remains parked in `failed` with
live recovery controls and four packaging-class findings) as the lane's
first production exercise.

## Assessment

- **Failure signature: NOT new.** This is the known historical class:
  lead_reconciliation output failing schema validation on `lineage` and
  on an agent-invented `canonical_artifact` pointer, the same residual
  recorded in `k5-production-re-run-2026-08-23.md` ("P2 method-record
  canonical_artifact pointer hashes are agent-invented (dangling)").
  Agent-side contract violation, not a harness defect.
- **Harness behavior on the post-fix build is correct and improved:**
  findings are classified (`correctable_contract_error` / `packaging`)
  rather than unclassified as in the 22 historical failures; valid
  stage-3 outputs sealed while the invalid one did not; the run failed
  cleanly with operator recovery controls offered; no harness errors in
  the server log across the full run.
- **Wall time** (158 min vs the 35-75 min recipe estimate, vs 102 min on
  2026-08-23): growth is agent work, not harness overhead. Contributing
  factors: data_analyst now runs glm-5.3-flash (profile change above)
  and the catalog/literature inputs keep growing. Stage walls 63.5 /
  71.8 / 22.5 min; per-role spread is large (theorist closed stage 1 in
  18 min, data_analyst took 63.5 min).
- **No new harness-side failure signatures observed** (fix-program step 7
  not triggered; no file:line defect evidence to record).

## Housekeeping

- Exercise server stopped after the terminal state; port :8765 free;
  default posture (executor=disabled) restored.
- Backup retained at `~/.model-forge-backups/20260901-225450`.
- The failed run is left in place with its recovery controls live for
  the recommended correction-lane follow-up.
