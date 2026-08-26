# Evidence: F-1 generation identity + fresh-cycle P1 + correction-lane boundary (2026-08-24)

Scope: the rename-era production exercise (clean-slate restart of the
entangled-Langevin project), three findings, and their resolution status.
Build under test: `bc181e6` (F-1), contract versions P1 2.2.0 / P2 2.3.0 /
P3 2.2.0 / P4 2.1.0 / P5 2.1.0, validation policy 1.12.0.

## 1. Legacy format migration (rename fallout, resolved)

The method-hub -> model-forge rename (90f84f1) changed the prepared-recipe
format marker, which made every pre-rename sealed recipe unloadable:
`PreparedRunRecipe.load` rejects `method-hub.prepared-run-recipe`. The
correction lane 500'd on any pre-rename failed run.

Resolution (Tez directive: no legacy-name aliases, migrate the data):
all 46 sealed recipes rewritten in place (format marker + bundled-skill
source tags), digests recomputed with the repository canonicalization,
run rows repointed. The DB enforces manifest immutability with triggers, so
this was a guarded one-time migration: triggers dropped, migrated, restored
verbatim; every recipe re-verified through the repository's own loader;
`PRAGMA integrity_check` ok. Ledger + pre-migration payloads archived at
`~/.model-forge-backups/migration-20260823-legacy-format/`. Historical
digest-bound records (closures, intents, submissions, receipts, generations)
keep their original format strings by design; nothing format-checks them on
load. The clean-slate reset (below) retired the question entirely: the new
store only ever contains model-forge.* records.

## 2. Correction-lane boundary mapped empirically (finding C-2)

Failed run `run.p1.p1-literature-update.bf5acb79cfa344d58d334308d4937116`
(pre-rename store): `p1.lead_synthesis` sealed 4 of 5 declared outputs, then
failed validation on the 5th (`schema.uniqueItems`, duplicated
`affected_basis_ids` in the unsealed `p1.synthesis_candidate`).

All three lanes were exercised against this failure:

- normalize preview: 0 of 3 findings fixable (no transformation creates a
  missing output).
- scientific: rejected `MF-74` (CORRECTION_SCOPE_INVALID). The scope gate
  admits only the closure's SEALED outputs when any exist, so the output that
  actually failed can never be named; the blast-radius check would also block
  its recreation (no never-sealed-creation skip on the scientific path).
- revalidate: mechanically correct post-migration, honestly re-failed with
  `output.required_missing` x3 (the partial-seal closure cannot bind its
  unsealed required outputs).

Conclusion: a partial-seal failure whose bad bytes live in the unsealed
output is unrecoverable by design today. The K5-3 plan-declared scope applies
only to zero-seal closures. Fix package (planned, not started): failed
closures get plan-declared scope regardless of seal count, plus a
never-sealed-creation skip in the scientific blast-radius path.

## 3. F-1: candidates carry no generation identity (resolved, verified in production)

Root cause: `generation_id` was schema-required in candidate outputs but is
harness-owned, and the harness never populated it (`run_facts.generation_id`
is always empty at closure). Agents masked the hole for weeks by inventing
sequential ids (`generation.p1.lit_update.026` ...) which validated and were
sealed as if real; the publisher's real digest-bound ids are derived at
promotion, so candidate-carried ids were always fiction. On a fresh library
the agent had no sequence to continue and omitted the field: 66 x
`schema.required`, operational_failure, run dead. Every fresh P1 would fail.

Fix (plan: architecture/plans/f1-candidate-generation-identity-plan-2026-08-23.md):
`generation_id` relaxed from `required` in method, literature-source,
scientific-record, and theory-record schemas (theory-record extension proved
load-bearing by the e2e suite); closure strips agent-supplied
generation_id/generation_number; contract bumps as listed above; 20 new
tests; suite 1254 green; validator exit 0. Commit `bc181e6`.

Production verification on the fresh store: run
`run.p1.p1-literature-update.7e0c9a54dcac438aa207c04675430337` published
(57 min, zero findings, 4 succeeded closures). Sealed candidates carry no
generation identity (73 source records, compact view, handoff, 11 attention
items all clean); the only `generation_id` values present are basis citations
to the project brief's generation, which is correct.

## 4. E-2d pointer retirement verified on the fresh store

All sealed record representations on the fresh generations resolve:
`artifact://sha256/<digest>` URIs hash-verify byte-for-byte against the
artifact store, and artifact ids match the pinned derivation exactly
(`deterministic_id("artifact", project_id, run_id, "<output_id>.as_authored",
digest)`; verified for `p1.synthesis_candidate`).

## 5. Fresh-cycle P2 (2026-08-24): member cap honored, E-2e verified, E-2f hardened

First P2 full-catalog attempt (`run.p2.p2-full-catalog.4a71023d...`) failed at
lead reconciliation: the agent wrote `identity: null` on all 4 method records,
and the E-2e case-5 stamping discriminator (identity-is-dict) silently skipped
canonical_artifact stamping, so the agent's CORRECT `input://<filename>`
declarations reached validation: 20 findings (schema.required identity,
schema.required artifact_id, schema.pattern uri), all correctly classified
correctable_contract_error/packaging. Partial seal (2 of the closure's outputs
sealed before the failure) made the run uncorrectable under the C-2 trap -
second production hit.

E-2f fix (commit `c6970c6`, planner-direct): the stamping discriminator now
keys on mathematical_definition.canonical_artifact alone, and the lead
instruction states explicitly that identity is agent-authored. One regression
test; suite 1255 green; validator exit 0.

Re-run `run.p2.p2-full-catalog.8fd97448064d4fcf98af8348a496797a` published
(33 min, zero findings, 5 succeeded closures). Verified on sealed state:

- Member cap honored: 4 methods (ANEL, SCLE theory-sourced; DGEL, RBEL
  empirically sourced) = exactly 2 per member.
- E-2e production verification: every method record's canonical_artifact was
  stamped to `artifact://sha256/<digest>` + a REAL artifact registry row
  (lookup path fired, no deterministic fallback). The two stamped digests
  re-hash exactly to the stage-1 sealed proposal bytes (theorist
  a02a5645..., data_analyst d8157d8c...). The E-2 arc (E-2a..E-2f) is now
  fully production-verified.

## 6. Fresh-cycle P3 (2026-08-25): F-1b/F-1c fixes, theory established on ANEL

First P3 attempt (`run.p3...7af5a339`) failed operational at the theorist
stage: `p3.theory_candidate` (theory-record schema) requires the
harness-owned `record_type`, but the per-output population only consulted
the publication-binding map, which names no per-stage candidate outputs.
Second attempt (`run.p3...01badda9`) passed the theorist stage and failed
the same way one stage later on `p3.analyst_audit` (scientific-record
schema: record_type is an enum ref, no const, no binding). A full
five-phase sweep found exactly three outputs in this hole class
(`p3.analyst_audit`, `p4.analyst_synthesis`, `p4.theory_audit`).

Fixes landed planner-direct:

- **F-1b** (`9ef9e7a`): schema-`const` fallback derives record_type
  mechanically when no binding names the output (theory-record ->
  "theory_record"). Agent-authored record_type is now always overwritten.
- **F-1c** (`b960790`): contract-declared record_type on the three
  scientific-record candidates (values reuse the historically established
  `review_issue_ledger` / `empirical_synthesis`); population tier order is
  binding -> contract -> schema const; the phase-contract meta-schema
  formally admits the optional field. P3 2.3.0, P4 2.2.0; example cascade
  re-rooted; suite 1258 green; validator exit 0.

Third attempt (`run.p3.p3-theory-establishment.b78248ac...`) **published in
75 minutes with zero findings across all three stages**:

- `p3.theory_candidate` sealed with `record_type=theory_record` (F-1b tier
  fired in production).
- `p3.analyst_audit` sealed with `record_type=review_issue_ledger` (F-1c
  tier fired in production).
- No candidate carries generation identity (F-1 strip holds).
- Two fresh generations (theory record + phase decision) with digest-bound
  publisher-derived ids.

Scientific outcome: the ANEL theory record carries 21 established
statements, including `thm.anel.marginal_exactness` (every marginal is
exactly a ULA chain), `cor.anel.no_mixing_acceleration` (ANEL does not
accelerate mixing; gains live in estimator variance, not exploration),
`thm.anel.mirror_lock` (symmetric targets lock antithetic pairs), and
`thm.anel.quadratic_zero_variance` (zero-variance pair means for linear
functionals on Gaussian targets), plus 11 empirical implications and 10
limitations - a clean, falsifiable target for P4.

F-2 watch confirmed in production: the phase-decision candidate carries an
agent-invented sequential `generation.decision.p3.anel...1` (decision-record
generation_id is still agent-authored, not harness-owned).

## 8. P4 preliminary empirical (2026-08-26): correction-lane recovery arc

Run `run.p4.p4-preliminary.e32ca610c19c44ddaaa8f4722c6efde5`, published
19:20 UTC (receipt revision 6). Arc: analyst closure FAILED (iteration
limit hit at the final write step; protocol sealed, three outputs
unproduced) -> scientific correction (resume-from-prior-work; the agent
finished in ~4 minutes from its sealed protocol + artifacts) closed
FAILED on envelope plumbing: evidence.json was written as a bare array
and all three outputs lacked the harness-owned envelope fields
(schema_version, created_at, content_sha256) - validation requires them
but stamping happens only at seal (filed as D-8/F-3) -> packaging
correction (harness-generated instruction from findings) PASSED in
~4 minutes -> pipeline resumed (K5-4 edge) -> theorist and lead stages
clean -> submitted -> published.

Production-first evidence for the correction taxonomy: both Lane B lanes
exercised on real failures, D6 correcting-state semantics confirmed live,
HV-5.6 bounded-attempt accounting confirmed (spent lanes stay spent;
a correction closure that never executed still spends its attempt - see
D-7 for the orphaned first attempt on the earlier P4 run).

Empirical results (sealed evidence record, 6 entries, all SUPPORTED at
prespecified thresholds, 200 replicates per arm, exact gradient-cost
parity B = N x T verified by instrumented counters):

- Marginal exactness: shared-noise trajectory difference 0.0 bitwise;
  ESS-per-gradient ratios ANEL/ULA in [0.997, 1.008] (95% CIs across
  four targets) - no mixing/exploration acceleration, as theorized.
- Asymmetric double well: stationary within-pair correlation
  rho_* = -0.8820 (CI [-0.8829, -0.8812]); time-averaged pooled
  variance ratio R_time = 0.1499 (CI [0.1135, 0.1977]).
- Gaussian targets: pooled linear-functional estimator near-exact
  zero-variance, R_term ~ 1e-31.
- Mirror-locked symmetric target: even-functional (x^2) variance ratio
  R_time = 1.8577 (CI [1.4085, 2.4201] contains the predicted 2).
- Mirror lock exact: max |pair sum| = 0.0 over all steps, pairs,
  replicates; within-pair correlation exactly -1.
- Cost parity exact: 48,000 / 64,000 / 320,000 / 160,000 gradient
  evaluations per replicate on G1/G2/A1/S1, both arms; wall-clock
  within +/-4%.

## 9. P5 assembly (2026-08-26): rejection -> correction -> publish

Run `run.p5.p5-assembly.d93f58913040492ba7da9a72f28b4b0c`, published
19:55 UTC (receipt revision 7). The assembly lead sealed all 8 outputs
with zero closure findings, but the SUBMISSION gate rejected the run:
claims in p5.claim_traceability without supporting/counterevidence ids.
The terminal message displayed only the first four findings as generic
text (findings[:4] join) and the persisted validation_report carried
only status+summary (filed as D-9). A local replay of the real
validator over the sealed artifacts (run-store forensics) identified 25
unlinked claims: theorems without theory-record links, empirical claims
without evidence-record links, definitions without the method-record
link. A scientific correction (scope: claim_traceability +
manuscript_candidate) re-invoked the assembly lead with a linkage-only
instruction; the correction passed, the run re-submitted automatically,
and submission validation passed. First production correction exercised
on a REJECTED run.

Cycle summary: P1 -> P2 (catalog + selection) -> P3 -> P4 -> P5 all
published on one continuous authority chain (revisions 1..7), every
phase mode through the local_hermes path - the five-phase pilot required
by the trusted-local-execution program (WP-I) is complete.

## 10. Backlog sweep (2026-08-25): F-2, E-1e, C-2, FP-7

Authorized by Tez as a broader autonomous sweep ("fix all remaining
issues and unfinished plan"), executed planner-direct with per-package
gates (suite + validator green before each commit):

- **F-2** (`eacf55c`): decision-record `generation_id`/
  `generation_number` are harness-owned; relaxed from required; strip
  rule covers them; all five phase contracts bumped (P1 2.3.0, P2 2.4.0,
  P3 2.4.0, P4 2.3.0, P5 2.2.0). Motivated by the P3 production
  observation (`generation.decision.p3.anel...1` agent-invented). The
  publisher already ignores candidate values (the published decision
  generation was digest-bound), so no downstream reader changes.
- **E-1e** (`43433cb`): stage-2 reviewer structured evaluations -
  optional `method_evaluations` on the handoff schema (axis optional;
  stage validators own axis enforcement), `stable_id` on unresolved
  issues, blocking rule `p2.review_evaluations_missing`
  (correctable/packaging), both cross-review instruction templates
  require the field, dev-executor example updated.
- **C-2** (`255fd47`): the partial-seal correction trap closed. The
  scope gate now admits sealed UNION plan-declared outputs for FAILED
  closures (succeeded closures keep sealed-only; K5-3 zero-seal path
  unchanged). The Lane B blast-radius verifier's K5-3 branch already
  treats wholesale creation of an output without sealed source bytes as
  the correction itself, so the union is sufficient - no lane changes.
  Plan doc: `plans/c2-partial-seal-correction-scope-plan-2026-08-25.md`.
  Note: the gate's `_plan_from_recipe` pins the frozen contract digest,
  so pre-bump failed runs (e.g. fresh P2 `4a71023d`) stay uncorrectable
  by design; the fix applies to failures on current contracts.
- **FP-7** (`d6d2445`): artifact fetches routed through the web API
  client (`requestText` + `api.getArtifactContent`); items 1-3 verified
  already resolved in-tree. vitest 157 green, tsc clean.

Registry reconciliation (`25ae525`): E-2e probe, F-1 production proof,
E-1e, C-2 marked landed; FP-2 marked SATISFIED (HV disclosed repairs +
K-2 sign-off); NA-2/P7 marked resolved (`894203a`); K-2 resolved; P0-3
folded into FP-2. Open decision memo for Tez:
`plans/open-decisions-memo-2026-08-25.md` (P0-2 presence model, K-1 D5,
user-activation transaction, FP-8 isolation, P1-3 hide-vs-dim, K-7).
