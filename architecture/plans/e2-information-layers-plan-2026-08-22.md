# E-2 Program: Information Layers Made Real (2026-08-22)

Status: E-2a (ee16531: pointer stamping, compact-view schema, P1/P3
contracts 2.1.0, work_summaries, validation policy 1.10.0) and E-2b
(c648a0d: layer-aware materialization + compact-first briefs) LANDED.
E-2c LANDED 2026-08-22: P1 run run.p1.p1-literature-update.19ff3cc0 and
P2 run run.p2.p2-full-catalog.48c8b90b both published; the sealed
synthesis record carries a compact_decision_view whose sha256
(b41c5b13...) resolves to hash-verified artifact-store bytes plus 72
work_summaries entries, and every P2 role received
inputs/compact/p2.literature_synthesis.md (2.75 KB) alongside the full
records (compact-first, drill-down preserved). Residual: primary_artifact
representation pointers remain agent-declared and do not resolve to
artifact-store bytes; closing that is the E-2d follow-up package.
Contract authority: architecture/03-storage-and-authority.md section 2
(three information layers). Evidence base:
architecture/evidence/storage-memory-review-2026-08-22.md (incl. addendum).

## Problem

The three-layer design (primary_artifact / structured_record /
compact_decision_view) is specified and plumbed but hollow:

1. Every compact_decision_view in the store is a placeholder. Root cause:
   agents author `representations[].artifact` pointers but cannot compute
   sha256 of their own files, so they invent synthetic hashes (observed:
   1111..., 9999..., aaaa... in sealed records, including from a REAL P1
   run). The harness explicitly leaves representation pointers untouched
   (role_execution.py:_fix_self_referential_hashes case 3).
2. Input materialization ignores layers: roles always receive the full
   primary artifact (133 KiB literature library into every P2 role).
3. Per-literature-work contribution paragraphs do not exist structurally.

## Tez rulings (2026-08-22, approved)

1. The same role that produces the primary artifact also writes the
   compact view, as an extra declared output sealed in the same run.
   No separate summarizer role.
2. Downstream roles receive the compact view FIRST plus the full record
   materialized for drill-down; briefs instruct compact-first reading.
3. Per-work one-paragraph contributions live in the P1 synthesis record
   as a structured work_summaries array.

## Design

### Representation stamping (the core mechanism)

Agents declare compact pointers with `uri: "output://<filename>"` and no
hash. At closure (extend _fix_self_referential_hashes), the harness
resolves the sibling output file in the role workspace, computes the real
sha256, and stamps artifact_id + sha256. Validation then requires real
pointers for compact_decision_view entries (rejects synthetic hashes and
pointers to nonexistent siblings), so placeholders can never seal again.

### Compact view outputs

- P1 (contract 2.1.0): new declared output `p1.synthesis_compact`
  (markdown; decision-oriented: what the literature establishes, what is
  missing, what P2 should try), written by p1.lead_synthesis. Attached to
  the synthesis record's representations as compact_decision_view via the
  stamping mechanism.
- P3: same pattern for the theory record (1-2 page technical summary).
- P2 methods: the two-line summary field (contract 2.2.0 writing rules)
  already serves as the method compact tier; no new output.

### Per-work summaries

scientific-record.schema.json gains optional `work_summaries[]`:
{source_id, key_contribution (one paragraph), relevance_to_question}.
P1 lead instructions require one entry per cited work.

### Layer-aware materialization (E-2b)

When a resolved basis input record carries a compact_decision_view with
real bytes in the artifact store, materialize it as
`inputs/compact/<contract_input_id>.md` alongside the full record at
`inputs/<sha256>` (addressing unchanged). Briefs name the compact path
and instruct compact-first reading. Placeholder/dev pointers are ignored
(dev loop unaffected).

## Packages

- E-2a: stamping mechanism + validation + P1/P3 contract outputs +
  work_summaries schema + instructions + fixtures/tests.
- E-2b: layer-aware materialization + brief wording + tests.
- E-2c: production exercise: real P1 run (real compact views), then a P2
  run consuming them; measure per-role input bytes before/after.

## Acceptance

- Real sealed records carry compact_decision_view pointers whose sha256
  resolve to real artifact-store bytes.
- P2 stage-1 briefs list compact views; materialized bytes per role drop
  measurably vs the E-1d baseline (192 KiB stage-1).
- Synthesis records carry work_summaries for every cited source.
- All gates green; validator exit 0.
