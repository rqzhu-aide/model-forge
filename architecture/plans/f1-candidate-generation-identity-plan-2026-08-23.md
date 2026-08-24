# F-1 Plan: candidates carry no generation identity (2026-08-23)

Status: PLANNED (Tez approved 2026-08-23 as finding C-4a, fresh-cycle blocker).
Context: the fresh-slate P1 run (`run.p1.p1-literature-update.5b162e18769e4180a70ef76ba76cb41b`,
2026-08-23) FAILED at `p1.lead_synthesis` with 66 × `schema.required` on
harness-owned `generation_id` (64 `p1.source_changes` items +
`p1.synthesis_candidate` + `p1.coverage_candidate`), correctly classified
`operational_failure` by the ADR-015 rule. Root cause verified in code:
`_sealed_run_facts` (harness/role_execution.py ~line 2396) NEVER sets
`generation_id`, so `populate_harness_fields` (harness/envelope.py ~line 361,
fills only when truthy) never fires. The field has been required since the
initial commit; every prior run passed only because AGENTS invented
sequential ids (`generation.p1.lit_update.026`..., confirmed in the sealed
Aug-22 outputs) - fabricated provenance in a harness-owned field, the same
class as E-2c/E-2e. A fresh library gives the agent no sequence to continue,
so the latent hole became a hard blocker.

## Verified facts (probed 2026-08-23)

1. Real generation ids are derived AT PROMOTION by `_generation_id`
   (harness/publication.py:1152) from project+run+binding+slot+record_type+
   document_sha256+artifact_id, over the final sealed bytes. The publisher
   stores documents AS-IS (`document=item`, ~line 965) and never rewrites
   them, so a candidate-carried generation_id can never become true.
2. NOTHING downstream reads a candidate's `generation_id`: the literature
   index reducer keys items by `identifiers` then `source_id`/`record_id`
   (harness/index_reducers.py:221-235 `_literature_key`); P1 publication
   bindings carry no `item_key_pointer`; current-slot mapping uses the
   publisher-derived envelope id.
3. Three schemas require `generation_id` today:
   `literature-source.schema.json`, `scientific-record.schema.json`,
   `method.schema.json` (all also harness-own it in envelope.py's
   `_HARNESS_OWNED_BY_SCHEMA`). `generation_number` is harness-owned
   (scientific-record) but required nowhere.
4. No instruction file under resources/instructions/ mentions
   `generation_id` (agents invent it from schema pressure alone).
5. Contract versions are per-phase (phases.json + phases/P<N>.json carry
   matching `contract_version` fields; see E-1f commit b9046ef for the bump
   mechanics). P1 is 2.1.0, P2 is 2.2.0.
6. Golden/example fixtures (architecture/examples/*.example.json and
   tests/fixtures/golden/*) CARRY generation_id and stay schema-valid after
   relaxation (property kept, only `required` drops) - but the strip rule
   (P2 below) will REMOVE the field from dev-executor closure outputs in
   e2e tests, so expect honest golden/digest fallout in the suite.

## Design pins

- **P1 (schema relaxation).** Remove `generation_id` from `required` in
  every architecture/schemas/*.schema.json that both requires it and
  validates closure-time candidate outputs (the three above; grep to
  confirm the complete set). KEEP the property definition; extend its
  description with: "Assigned by the publisher at promotion; candidates
  must not carry it (the harness strips it at closure)."
- **P2 (strip rule).** In `populate_harness_fields` (harness/envelope.py),
  for `generation_id` and `generation_number` when they are harness-owned
  for the schema: if the run-facts value is empty, DELETE any agent-supplied
  value from the candidate (in place of the current silent pass-through);
  if non-empty, overwrite as today. Agents can no longer seal fabricated
  generation identity of any shape.
- **P3 (contract bumps).** Bump `contract_version` one minor step in
  phases.json and phases/P<N>.json for every phase whose output schemas
  changed (P1 2.1.0 -> 2.2.0; P2 2.2.0 -> 2.3.0; P3/P4/P5 only if their
  outputs validate against a relaxed schema - verify via the phase files'
  output schema references, not guesswork). Follow b9046ef's exact bump
  shape.
- **P4 (tests).** New tests covering: (a) a source-changes/synthesis/
  coverage candidate WITHOUT generation_id passes closure validation (the
  fresh-library regression from today's run); (b) an agent-supplied
  generation_id is STRIPPED before sealing (fabrication channel closed);
  (c) publisher derivation unchanged (existing tests). Fix golden/e2e
  fallout honestly per the standard rules - the expected class is dev
  closure outputs losing the field, shifting sealed digests in e2e tests.
- **P5 (docs).** Add one paragraph to architecture/03-publication-trust.md
  (or the doc that defines record identity) stating: generation identity is
  assigned at promotion from digest-bound inputs; candidates never carry it.
  Update architecture/plans/README.md (F-1 entry; remove the E-2e probe's
  dependence note if any). ASCII hyphens only.

## Out of scope

- Historical sealed records keep their agent-invented generation ids
  (immutable archive; the old store is archived under
  ~/.model-forge-backups/pre-clean-slate-20260823-213642 anyway).
- No publisher changes (derivation already correct).
- No alias/compat acceptance of legacy names anywhere.
- A systematic audit of OTHER harness-owned fields for population coverage
  (generation_number has the identical never-truthy condition) is a
  RECOMMENDED follow-up, not this package.

## Acceptance

One sentence: a fresh-library P1 closure validates without generation_id
anywhere in candidate outputs, and an agent that writes one has it stripped
before sealing; suite + validator green.

## Verify

- Suite: `.venv/bin/python -m pytest tests/ -q` (baseline 1234 passed at
  456a9f1) plus the new tests; validator:
  `.venv/bin/python architecture/tools/validate_package.py` exit 0.
- Production proof (after landing): rerun the fresh P1 (same instruction)
  to publish, then probe the sealed synthesis record (E-2d retirement probe
  rides along).
