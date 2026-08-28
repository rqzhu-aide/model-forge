# ADR-019: Seeds Are Additive Supplementary Material, Never Replacements

Status: Accepted (2026-08-28; Tez directive 2026-08-28)
Supersedes: ADR-018
References: S31 (researcher supplementary material)

## Context

ADR-018 let a researcher seed stand in for any declared contract input,
including required published inputs such as `p5.current_manuscript`. Tez
reviewed the shipped semantics and rejected them: a researcher who holds a
finished paper must enter it at Phase 1, where the pipeline builds the
literature research, references, and computational work around it.
Parachuting a foreign draft into P5 skips everything that makes the
manuscript verifiable - that is pure paper-auditing work, and it belongs
elsewhere, not in this system.

The legitimate need is narrower: a researcher working inside an existing,
already-started project holds additional material - for example their own
partial code at Phase 4 - and wants the phase to utilize or revise it so
the implementation is easier. That material is supplementary context, not
a replacement for the pipeline's published state.

## Decision

The seed channel becomes additive-only.

- **Supplementary slots.** Each phase contract declares optional
  `supplementary_inputs` (initially one per phase: `pN.researcher_material`,
  record type `researcher_material`). These slots resolve exclusively from
  the run command's seed channel; they never resolve from the record store.
- **Required inputs are untouchable.** A seed naming a required input
  fails preparation with `input.seed_replaces_published_input`. Required
  inputs always resolve from published current records. A seed naming
  nothing declared still fails with `input.unknown_seed`.
- **No rerun semantics.** A seeded supplementary slot is not a published
  record: it does not count for rerun detection and cannot turn a first
  run into a continuation.
- **Provenance and reproducibility unchanged.** Seeds still live inside
  the sealed command's content digest, are content-addressed at
  preparation, and freeze with `origin: "researcher_seed"`; the audit
  trail always distinguishes researcher material from published state.
- **Stale-basis guard needs no exemption.** Because a seed never occupies
  a reviewed required input, the generation-drift guard compares published
  inputs only; the ADR-018 exemption branch is removed as dead code.

Consequences for entry points: a researcher's own paper enters as seeded
supplementary material to P1, and the pipeline builds the literature
basis, method, theory, and empirical record around it. There is no door
that lands a finished foreign manuscript in P5.

## Consequences

- The phase-contract schema gains `supplementary_inputs` with
  `record_type` fixed to `researcher_material`; the common record-type
  enum gains `researcher_material`. All five contracts bump a minor
  version (P1 2.3.0 to 2.4.0; P2-P5 2.4.0 to 2.5.0).
- The stale-basis generation guard no longer special-cases seeds; the
  ADR-018 production run (`run.p5.p5-assembly.ba0dd8a366b44d2bb17ce049b5f4a30e`,
  cancelled before execution) remains historical evidence of the
  superseded semantics only.
- The UI exposes the seed channel as the run form's "Supplementary
  material" section (copy-in for small material, external link for
  large), and the run page marks seeded basis entries with a researcher
  material provenance badge.
- A seed remains authoritative for its run only and never becomes a
  current record by itself; publication still flows through the normal
  gates.
