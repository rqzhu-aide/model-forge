# ADR-017: P2 Structured Lead Evaluation - Three-Axis Method Scores

Status: Accepted (2026-08-21, Tez design directive; parameters ruled 2026-08-21)
Supersedes: part of ADR-013-era P2 role order (stage-1 lead proposal removed)

## Context

The P2 catalog run evaluates candidate methods, but the evaluation is
sealed as prose (decision headline, rationales) plus reviewer issues whose
category vocabulary is free text and whose method attribution is naming
convention inside issue ids. The 2026-08-21 UI audit and the follow-up
redesign surfaced the consequence: the method catalog rows cannot show
decision-relevant evaluation, because none exists in a structured,
attributed, adjudicated form.

Tez directive (2026-08-21): restructure the P2 evaluation flow and seal
per-method scores.

## Decision

### D1. Stage 1 proposes without the lead

`p2.independent_proposals` roles become `theorist` + `data_analyst` only.
The `p2.lead_proposal` output is removed. The research lead no longer
authors proposals; the lead's only P2 act is reconciliation and
adjudication in stage 3. Authorship and judgment no longer concentrate in
one role.

### D2. Stage 2 reviewers evaluate inside their competency axes

The cross-review report schema gains a structured per-method evaluation
block keyed by the CONTRACTED method stable_id (ending attribution by
naming convention):

- theorist evaluates axis T (theoretical validity + identifiability)
- data_analyst evaluates axis E (empirical testability + computational
  efficiency)
- both may raise issues on any axis; issues carry the method stable_id

### D3. The lead adjudicates and seals the official three-axis scores

Stage 3 (`p2.lead_reconciliation`) writes, for every method in the
catalog change set, an `evaluation` block sealed INTO the method record
(so it versions with the catalog entry and the UI reads it directly):

```
evaluation: {
  theoretical_validity:      { score: 1-10, justification, issue_refs },
  literature_positioning:    { score: 1-10, justification, issue_refs },
  empirical_feasibility:     { score: 1-10, justification, issue_refs },
  adjudicated_at, review_basis_ids
}
```

Score scale (Tez ruling 2026-08-21): integers 1-10 per axis, with a
required justification per axis.

The three axes (Tez's split):
1. theoretical validity + identifiability
2. literature positioning + novelty (LEAD-ONLY, Tez ruling 2026-08-21:
   no structured reviewer assessment on this axis; reviewers may only
   raise issues. The lead synthesizes from the frozen literature basis)
3. empirical testability + computational efficiency

The lead owns all three final scores. Reviewer evaluations remain sealed
in the review reports as the visible input to adjudication.

### D3a. Proposer guidance on novelty (Tez ruling 2026-08-21)

The stage-1 task context sent to theorist and data_analyst always
encourages proposals with unique literature positioning and high
novelty. This renders through the stage objective / task-brief layer
(ADR-013): the stage-1 objective text carries the encouragement so every
generated proposal brief includes it.

### D4. Display

The method catalog row (web) gains a compact three-chip score strip
(score + tone per axis); justifications and linked issues stay in the
method details disclosure. Methods without an evaluation block (all
pre-change catalog entries) render "Not yet evaluated".

## Consequences

- Contract: P2.json role_stages/run_local_outputs/validation_rules,
  phase-2.md sections 5-8, method.schema.json (evaluation block),
  review-report.schema.json (per-method evaluations + method-keyed
  issues), traceability + validator rules, stage-role instructions.
- Backend: MethodRow view assembly exposes the evaluation block.
- Web: MethodRow type, MethodTable/MethodSelector score strip, tests.
- Migration: none destructive; evaluation is additive and optional until
  the first post-change P2 run populates it. Validation requires the
  block only for runs produced under the new contract version.
- Focused-method and researcher-proposal modes: stage 1 evaluates the
  in-scope method(s) under the same two roles; scores seal per method
  in the change set as above.

## Resolved parameters (Tez rulings, 2026-08-21)

1. Score scale: integers 1-10 per axis, justification required.
2. Literature positioning + novelty is lead-only; theorist/data_analyst
   raise issues but file no structured assessment on that axis. Stage-1
   proposer context always encourages unique literature positioning and
   high novelty (D3a).
