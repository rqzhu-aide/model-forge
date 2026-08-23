# ADR-013: Layered prompts and phase-specific output contracts

## Status

Accepted, 2026-08-11.

## Context

Model Forge previously selected one instruction template through a fallback
chain. A stage-role template could replace the mode directive, and a resolved
default could replace researcher-authored direction. General scientific-record
and review-issue schemas also could not express the distinct obligations of a
theory, empirical protocol, manuscript package, open review finding, or outside
review report.

This matters because Phase 2 through Phase 5 modes assign different scientific
jobs. Phase 4 preliminary and comprehensive are scopes of investigation, not
chronological stages. A parallel reviewer reports a finding about a frozen
manuscript, while only the revision lead may create a dispositioned issue.

## Invariants that must remain true

- The sealed phase, mode, selected method identity, inputs, role, output
  contract, parallel-isolation rule, and execution boundary are immutable.
- Researcher-authored direction reaches the role verbatim and has highest
  scientific priority within the sealed boundary. It cannot change the mode,
  method scope, or declared outputs.
- A stage-role assignment narrows one role's work. It does not replace the mode
  directive or expand scope.
- Reviewers assess one immutable manuscript basis and same-group reviewers do
  not inspect one another's findings.
- Formal publication still requires schema, identity, provenance, phase, and
  publication validation.
- Structural and semantic validation cannot prove scientific truth.

## Options considered

### Option A: One fallback-selected prompt and general schemas

This is smaller, but applicable directions can hide one another and specialized
research obligations remain only in prose.

### Option B: Layered prompts with general schemas

This preserves all directions, but theory, protocol, manuscript, and review
outputs remain too weakly distinguished for structural validation.

### Option C: Layered prompts and dedicated output schemas

This makes prompt precedence explicit, preserves distinct P2 through P5 modes,
treats Phase 4 modes as scopes, and binds specialized outputs to appropriate
structural contracts. This option is selected.

## Decision

### 1. Compose separate prompt layers

Each role task brief composes these applicable layers in order:

1. the immutable instruction boundary derived from the sealed run;
2. the mode directive;
3. the stage-role assignment, when one exists;
4. researcher direction, when the researcher supplied non-default text.

No scientific layer silently replaces another. Mode and stage-role templates
receive the frozen `phase_id`, `mode_id`, `mode_slug`, `stage_id`, and `role`.
Researcher direction remains verbatim and has highest scientific priority
subject to the immutable boundary.

### 2. Keep P2 through P5 modes distinct

| Phase | Modes | Required distinction |
|---|---|---|
| P2 | `p2.full_catalog`, `p2.focused_method`, `p2.researcher_proposal` | Full catalog may change multiple catalog entries. Focused method reassesses exactly one stable method. Researcher proposal evaluates the supplied method without inventing alternatives. |
| P3 | `p3.theory_establishment`, `p3.theory_revision` | Establishment constructs a complete scoped theory account. Revision compares the exact current theory statement by statement and may repair, weaken, narrow, condition, or retract claims. |
| P4 | `p4.preliminary`, `p4.comprehensive` | Preliminary performs a small set of decisive feasibility and diagnostic checks. Comprehensive performs a self-contained, prespecified full evaluation. |
| P5 | `p5.assembly`, `p5.review_revision` | Assembly creates the first integrated manuscript without inventing review history. Review-revision freezes a manuscript, obtains isolated findings, records lead dispositions, and creates a revised candidate. |

Mode-specific wording must not imply work belonging to another mode.

### 3. Treat P4 modes as scope, not chronology

Comprehensive mode does not require a prior preliminary run, prior preliminary
evidence, or a separate prior-implementation input. It may be the first P4 run
for an exact method identity. When an exact current implementation exists on a
rerun, it may be reused only after recorded verification; otherwise it is
replaced. Both modes finalize a claim-linked protocol before inspecting
outcomes and append deviations without rewriting prespecified fields.

### 4. Bind specialized outputs to dedicated schemas

The catalog adds five Draft 2020-12 schemas:

| Schema | Contract boundary |
|---|---|
| `theory-record.schema.json` | Complete P3 theory with a primary artifact, assumptions, statement-level status and support, dependencies, empirical implications, limitations, and revision provenance. |
| `empirical-protocol.schema.json` | Prespecified P4 protocol with claim-to-test links, estimand, data or simulation unit, baselines, tuning budget, uncertainty, multiplicity, stopping, leakage checks, thresholds, and append-only deviations. |
| `manuscript-package.schema.json` | P5 package pointing to the readable manuscript and classifying material claims by P1 through P4 support. |
| `review-finding.schema.json` | One open reviewer finding about a frozen manuscript, without lead disposition fields. |
| `review-report.schema.json` | One outside-review report with scope, missing materials, assessment, strengths, prioritized open findings, novelty-search boundary, and evidence that could change the assessment. |

The catalog therefore contains 42 schemas. Existing immutable generations are
not rewritten. Newly prepared runs use the schema bindings frozen into their
phase contract and manifest.

### 5. Separate reviewer findings from lead dispositions

Specialist reviewers emit open `review-finding` objects. The outside reviewer
emits one `review-report` containing open findings. Reviewers cannot mark a
finding fixed, partially fixed, deferred, or rejected, and cannot add a lead
disposition reason or revision location.

The P5 revision lead converts every finding into the existing `review-issue`
ledger, preserving issue identity, reviewer, basis, location, consequence, and
requested resolution. The lead records a final disposition and reason. Fixed
or partially fixed issues cite exact revision locations. A disposition records
the lead's action; it does not prove that the concern is resolved.

### 6. Use neutral structural examples

Examples embedded in task briefs are structural templates, not candidate
scientific content. Identity-bearing values, including IDs, digests, and
timestamps, are replaced with `<...>` placeholders. Roles must supply run-real
values while preserving the demonstrated shape.

### 7. Preserve the validation boundary

Schemas may require fields, enumerations, relationships, and conditional
structure. Semantic validators may check identity, provenance, mode
consistency, review conversion, claim-support references, protocol
completeness, and publication obligations.

These checks establish contract conformance only. They do not establish a
theorem's truth, an interpretation's validity, a protocol's scientific
adequacy, a contribution's novelty, or a review judgment's correctness.
Negative, contradictory, incomplete, or unresolved scientific conclusions
remain valid outputs when recorded honestly within the contract.

## Consequences

### Benefits

- Task briefs preserve all applicable direction and expose its precedence.
- P2 through P5 roles cannot silently drift into another run mode.
- P4 comprehensive work is available based on scope rather than run order.
- Missing specialized structure becomes visible before publication.
- Reviewer independence and lead accountability are represented separately.

### Costs and risks

- Templates and tests must cover each mode-sensitive stage-role combination.
- Newly prepared runs must produce richer records and readable artifacts.
- Dedicated schemas still require expert scientific judgment.
- Narrative scenarios and generated role/file guides require separate updates.

## Contract changes

- P3 theory outputs use `theory-record.schema.json`.
- P4 protocol output uses `empirical-protocol.schema.json`, without a required
  preliminary chronology.
- P5 manuscript and reviewer outputs use `manuscript-package.schema.json`,
  `review-finding.schema.json`, and `review-report.schema.json`; the lead still
  produces `review-issue.schema.json`.
- P2 through P5 templates state exact mode scope.
- Task rendering composes mode, stage-role, and researcher layers.

## Schema changes

- Add the five schemas listed above.
- Increase the schema-catalog count from 37 to 42.
- Do not migrate or rewrite prior immutable records.

## Scenario changes

Executable acceptance coverage is provided by
[`test_instruction_template_inventory.py`](../../tests/test_instruction_template_inventory.py),
[`test_harness_outputs.py`](../../tests/test_harness_outputs.py),
[`test_p3_p4_research_contracts.py`](../../tests/test_p3_p4_research_contracts.py),
and
[`test_p5_research_contract.py`](../../tests/test_p5_research_contract.py).
Narrative scenario and generated role/file guide updates remain open in the
[Instruction, Output-Integrity, and UI Fix Plan](../plans/instruction-output-integrity-fix-plan.md).
