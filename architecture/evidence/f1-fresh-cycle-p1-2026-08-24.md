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

## 5. Open follow-ups

- decision-record.schema.json still requires an agent-authored
  `generation_id` (not harness-owned): the sealed phase-decision candidate
  on the fresh run carries the invented value `generation.p1.decision.001`
  while the envelope carries the real derived id. Same anti-pattern, small;
  recommend an F-2 follow-up (relax + strip) at the next contract window.
- C-2 correction-scope package (section 2).
- The fresh cycle continues: P2 full-catalog run
  `run.p2.p2-full-catalog.4a71023db19d40d8a91b3b8b3a163f6e` launched
  2026-08-24 17:39 with a per-member proposal cap (at most 2 methods per
  member) in the instruction, per Tez.
